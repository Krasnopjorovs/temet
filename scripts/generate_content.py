"""Офлайн-генерация текстов отчёта на локальной модели (OpenAI-совместимый llama-server).

Безопасно для долгих прогонов: каждая партия сразу пишется в свой файл в --out и
импортируется в БД как ЧЕРНОВИК (в обычный отчёт не попадает до одобрения).
Повторный запуск продолжает с места остановки: уже готовые ключи пропускаются.
Черновики помечены версией промпта: поменяли doctrine/prompts/content.ru.txt — старые
черновики перегенерируются; одобренные тексты не трогаются никогда.
Партия с неразборчивым ответом сохраняется как .err.txt и не теряется.

python -m scripts.generate_content --url http://localhost:8080 --out content_out
python -m scripts.generate_content --match 'dominant:SATURN:PLUTO,element:*,modality:*'   # проба
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatchcase

from psycopg.types.json import Jsonb

from astro import store
from astro.rules import key_space
from astro.brief import authoring_prompt, brief, load_stats
from astro.service import Runtime

DEFAULT_PROMPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "doctrine", "prompts", "content.ru.txt")
SYSTEM = ""   # загружается из файла промпта (роль и принципы — данные, не код)


KIND_ORDER = ["dominant", "element", "modality", "rule", "sign", "house", "ruler",
              "dignity", "final", "reception", "channel_top", "aspect"]


def strip_reasoning(text: str) -> str:
    """llama-server с --reasoning-format none отдаёт размышления прямо в content."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def parse_items(text: str, wanted: list[str]) -> list[dict]:
    body = strip_reasoning(text)
    body = re.sub(r"^```(?:json)?|```$", "", body.strip(), flags=re.M).strip()
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end < start:
        raise ValueError("no JSON array in response")
    items = json.loads(body[start:end + 1])
    ok = set(wanted)
    out = [i for i in items if isinstance(i, dict) and i.get("key") in ok and i.get("body")]
    if not out:
        raise ValueError("JSON parsed but no valid items")
    return out


def call(url: str, model: str | None, user: str, max_tokens: int, temperature: float, timeout: int) -> str:
    payload = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    if model:
        payload["model"] = model
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("LLM_URL", "http://localhost:8080"))
    ap.add_argument("--model")
    ap.add_argument("--out", default="content_out")
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="файл с ролью и принципами")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--kinds", help="через запятую; по умолчанию все в порядке важности")
    ap.add_argument("--limit", type=int, help="не больше N ключей за запуск (проба)")
    ap.add_argument("--match", help="маски ключей через запятую, напр. 'dominant:SATURN:PLUTO,element:*'")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--temperature", type=float, default=0.5)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--source", default="local-llm")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    global SYSTEM
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        rows = store.content_rows(conn, rt.doctrine_id)
    SYSTEM = authoring_prompt(a.prompt, d=rt.d)
    phash = hashlib.sha256(SYSTEM.encode()).hexdigest()[:8]
    source = f"{a.source}|prompt:{phash}"
    stats = load_stats(rt.d)
    kinds = a.kinds.split(",") if a.kinds else KIND_ORDER
    # пропускаем одобренное (никогда не трогаем), черновики текущей версии промпта и чужие
    # черновики (другой источник, например тексты от другого автора); перегенерируются только
    # свои черновики старых версий промпта
    own = f"{a.source}|"
    skip = {k for k, (st, src) in rows.items()
            if st != "draft" or src == source or not (src or "").startswith(own)}
    todo = sorted((k for k in key_space(rt.d) if k.split(":", 1)[0] in kinds and k not in skip),
                  key=lambda k: (kinds.index(k.split(":", 1)[0]), k))
    if a.match:
        pats = [p.strip() for p in a.match.split(",") if p.strip()]
        todo = [k for k in todo if any(fnmatchcase(k, p) for p in pats)]
    if a.limit:
        todo = todo[:a.limit]
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    print(f"{len(todo)} keys to write in {len(batches)} batches -> {a.url} (concurrency {a.concurrency}, "
          f"prompt {phash})", flush=True)
    if not batches:
        return

    def run(idx: int, keys: list[str]):
        name = f"{rt.d.code}_{keys[0].split(':', 1)[0]}_{int(time.time())}_{idx:04d}"
        user = ("Положения (ключ :: название :: бриф — посчитанные факты, не трактовка):\n"
                + "".join(f"- {brief(k, rt.d, stats)}\n" for k in keys))
        t = time.time()
        raw = ""
        for attempt in (1, 2):
            try:
                raw = call(a.url, a.model, user, a.max_tokens, a.temperature if attempt == 1 else 0.2, a.timeout)
                items = parse_items(raw, keys)
                break
            except Exception as e:
                err = e
        else:
            with open(os.path.join(a.out, name + ".err.txt"), "w", encoding="utf-8") as f:
                f.write(f"{err}\n\n{user}\n\n---\n{raw}")
            return idx, 0, len(keys), time.time() - t, str(err)
        with open(os.path.join(a.out, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        with store.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
            for it in items:
                key = it.pop("key")
                cur.execute(
                    """insert into content (doctrine_id, key, payload, status, source)
                       values (%s,%s,%s,'draft',%s)
                       on conflict (doctrine_id, key, locale) do update
                         set payload=excluded.payload, source=excluded.source, updated_at=now()
                         where content.status = 'draft' and content.source like %s""",
                    (rt.doctrine_id, key, Jsonb(it), source, own + "%"))
            conn.commit()
        return idx, len(items), len(keys), time.time() - t, ""

    t0, done = time.time(), 0
    with ThreadPoolExecutor(a.concurrency) as ex:
        futs = [ex.submit(run, i, b) for i, b in enumerate(batches)]
        for n, f in enumerate(as_completed(futs), 1):
            idx, ok, total, dt, err = f.result()
            done += ok
            eta = (time.time() - t0) / n * (len(batches) - n)
            status = f"ERROR {err}" if err else f"{ok}/{total} ok"
            print(f"[{n}/{len(batches)}] batch {idx}: {status} in {dt:.0f}s · total {done}/{len(todo)} · "
                  f"ETA {eta / 60:.0f} min", flush=True)
    print(f"finished: {done}/{len(todo)} drafts written in {(time.time() - t0) / 60:.1f} min", flush=True)
    sys.exit(0 if done else 1)


if __name__ == "__main__":
    main()
