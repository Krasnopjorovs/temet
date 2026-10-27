"""Выгрузить недостающий контент как файлы-промпты для локальной модели (через web UI).
Каждый файл = промпт доктрины (роль + принципы + формат) + ключи с брифами (astro.brief).
Ответ модели сохраняете как .json рядом и импортируете scripts.import_content.

python -m scripts.export_content_prompts --module karma --batch 40 --out prompts/
"""
import argparse
import os

from astro import store
from astro.brief import authoring_prompt, brief, load_stats
from astro.rules import _module_for, key_space
from astro.service import Runtime

PROMPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "doctrine", "prompts", "content.ru.txt")


def module_of_key(key, d):
    kind, *p = key.split(":")
    if kind in ("sign", "house", "dignity", "final"):
        return _module_for(d, p[0], int(p[1]) if kind == "house" else None)
    if kind in ("aspect", "reception"):
        return _module_for(d, p[0], None)
    if kind == "ruler":
        return _module_for(d, None, int(p[0]))
    if kind == "rule":
        return next((r["module"] for r in d.rules if r["key"] == p[0]), "")
    return _module_for(d, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module")
    ap.add_argument("--kind", help="sign|house|aspect|dignity|ruler|channel_top|final|reception|rule")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--out", default="prompts")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        have = store.content_keys(conn, rt.doctrine_id)
    keys = [k for k in key_space(rt.d) if k not in have]
    stats = load_stats(rt.d)
    header = (authoring_prompt(PROMPT, d=rt.d)
              + "\n\nПоложения (ключ :: название :: бриф — посчитанные факты, не трактовка):\n")
    if a.kind:
        keys = [k for k in keys if k.split(":")[0] == a.kind]
    if a.module:
        keys = [k for k in keys if module_of_key(k, rt.d) == a.module]
    files = 0
    for i in range(0, len(keys), a.batch):
        chunk = keys[i:i + a.batch]
        path = os.path.join(a.out, f"{rt.d.code}_{a.module or 'all'}_{a.kind or 'all'}_{i // a.batch:04d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "".join(f"- {brief(k, rt.d, stats)}\n" for k in chunk))
        files += 1
    print(f"{len(keys)} missing keys -> {files} prompt files in {a.out}/")


if __name__ == "__main__":
    main()
