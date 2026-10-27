"""Собрать переведённый корпус для импорта: текстовые поля — из перевода, остальное (action_kind, axes …) — из исходника,
подписи смысла (_sig) — заново по корпусу этого языка (для снятия повторов в отчёте).

python -m scripts.build_translation out/*.json --source content/forecast_v1.json --out content/forecast_v1.en.json
затем: python -m scripts.import_content content/forecast_v1.en.json --locale en --source "<кто перевёл>"
"""
import argparse
import json

from scripts.content_signatures import sign
from scripts.gate_translation import TEXT, load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--source", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--common", type=float, default=0.04)
    a = ap.parse_args()
    src, tr = load(a.source), load(a.files)
    items, missing = [], []
    for k, s in src.items():
        if k not in tr:
            missing.append(k)
            continue
        meta = {f: v for f, v in s.items() if f not in TEXT and f not in ("in_life", "_sig", "_seq")}
        items.append({**meta, **{f: tr[k][f] for f in TEXT if tr[k].get(f)}, "in_life": tr[k]["in_life"]})
    items, n = sign(items, a.common)
    json.dump(items, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    extra = sorted(set(tr) - set(src))
    print(f"{len(items)} texts -> {a.out} ({n} common words); not translated: {len(missing)}; unknown keys: {len(extra)}")
    if missing:
        print("  missing:", ", ".join(missing[:20]) + (" …" if len(missing) > 20 else ""))


if __name__ == "__main__":
    main()
