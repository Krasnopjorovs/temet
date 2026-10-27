"""Импорт текстов (JSON-массивы) как черновиков; одобрение — отдельной командой.
python -m scripts.import_content outputs/*.json --source "qwen3.8-27b" [--locale en]
python -m scripts.import_content --approve 'sign:VENUS:%' [--locale en]   # одобрить по маске (SQL LIKE)
Новая версия уже одобренного текста становится его правкой (draft_payload): страница показывает одобренный текст,
а правку — только с галочкой «черновики»; одобрение переносит правку на место текста.
"""
import argparse
import json
import os
import re

from psycopg.types.json import Jsonb

from astro import store
from astro.rules import key_space
from astro.service import Runtime


def parse(path):
    raw = open(path, encoding="utf-8").read()
    m = re.search(r"\[.*\]", raw, re.S)
    return json.loads(m.group(0) if m else raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--source", default="local-llm")
    ap.add_argument("--approve")
    ap.add_argument("--locale", help="язык текстов (по умолчанию ru); для --approve — только этот язык")
    a = ap.parse_args()
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        if a.approve:
            with conn.cursor() as cur:
                cur.execute("update content set payload=coalesce(draft_payload, payload), draft_payload=null, "
                            "status='approved', updated_at=now() where doctrine_id=%s and key like %s "
                            "and (status='draft' or draft_payload is not null) and (%s::text is null or locale=%s)",
                            (rt.doctrine_id, a.approve, a.locale, a.locale))
                print(f"approved {cur.rowcount}")
            conn.commit()
            return
        valid = set(key_space(rt.d))
        ok = bad = rev = svc = 0
        visible = lambda p: {k: v for k, v in (p or {}).items() if not k.startswith("_")}
        with conn.cursor() as cur:
            for path in a.files:
                for item in parse(path):
                    key = item.pop("key", None)
                    if key not in valid:
                        bad += 1
                        continue
                    # у одобренного текста изменились только служебные поля (_sig — подписи смысла): читатель
                    # ничего нового не увидит, поэтому это не правка на одобрение, а обновление на месте
                    cur.execute("select status, payload from content where doctrine_id=%s and key=%s and locale=%s",
                                (rt.doctrine_id, key, a.locale or "ru"))
                    old = cur.fetchone()
                    if old and old["status"] == "approved" and visible(old["payload"]) == visible(item):
                        cur.execute("update content set payload=%s, draft_payload=null, updated_at=now() "
                                    "where doctrine_id=%s and key=%s and locale=%s",
                                    (Jsonb(item), rt.doctrine_id, key, a.locale or "ru"))
                        svc += 1
                        ok += 1
                        continue
                    cur.execute(
                        """insert into content (doctrine_id, key, locale, payload, status, source)
                           values (%s,%s,%s,%s,'draft',%s)
                           on conflict (doctrine_id, key, locale) do update set
                             payload = case when content.status = 'approved' then content.payload else excluded.payload end,
                             draft_payload = case when content.status = 'approved' and content.payload is distinct from excluded.payload
                                                  then excluded.payload else null end,
                             source = excluded.source, updated_at = now()
                           returning (xmax <> 0) as existed, status, draft_payload is not null as revision""",
                        (rt.doctrine_id, key, a.locale or "ru", Jsonb(item), a.source))
                    r = cur.fetchone()
                    rev += bool(r["revision"])
                    ok += 1
        conn.commit()
    print(f"imported {ok} texts ({rev} of them as revisions of approved texts, which stay live until approved; "
          f"{svc} approved texts got only service-field updates), skipped {bad} unknown keys")


if __name__ == "__main__":
    main()
