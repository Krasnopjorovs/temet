"""Повторы между полями текстов, которые встречаются в одном отчёте: та же проверка, что убирает повторы из отчёта
(astro.report._dup по подписям смысла), но заранее — чтобы переписанное поле не повторяло поля-соседи.

python -m scripts.dup_check out/*.json --base content/claude_v13.json --pairs pairs.json
pairs.json: {"<ключ>|<поле>": [["<ключ соседа>", "<поле соседа>"], …]} — с какими полями поле встречалось и совпадало.
"""
import argparse
import json
import sys
from collections import Counter

from astro.doctrine import load_yaml
from astro.report import _dup
from scripts.content_signatures import FIELDS, _content, unit
from scripts.corpus_checks import lemmas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--base", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--common", type=float, default=0.04)
    a = ap.parse_args()
    thr = float(load_yaml(a.doctrine).params.get("report_dedupe_jaccard", 0.45))
    base = {it["key"]: it for it in json.load(open(a.base, encoding="utf-8"))}
    focus = {}
    for p in a.files:
        for it in json.load(open(p, encoding="utf-8")):
            focus[it["key"]] = {**focus.get(it["key"], {}), **it}
    merged = {k: {**v, **focus.get(k, {})} for k, v in base.items()}
    df = Counter()
    for it in merged.values():
        s = set()
        for x in [*it.get("in_life", []), *(it.get(f, "") or "" for f in FIELDS)]:
            s |= set(_content(lemmas(x)))
        df.update(s)
    common = {w for w, c in df.items() if c / len(merged) > a.common}
    pairs = json.load(open(a.pairs, encoding="utf-8"))
    bad = 0
    for k, it in focus.items():
        for f in FIELDS:
            if f not in it or f"{k}|{f}" not in pairs:
                continue
            u = unit(it[f], common)
            for k2, f2 in pairs[f"{k}|{f}"]:
                other = merged.get(k2, {}).get(f2)
                if other and _dup(u, [unit(other, common)], thr):
                    bad += 1
                    print(f"  REPEAT {k} [{f}] ~ {k2} [{f2}]: «{other[:90]}»")
    print(f"checked {len(focus)} texts · repeats {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
