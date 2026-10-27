"""Сколько полей прячет снятие повторов в отчётах: N случайных карт, корпус текстов из файла.

python -m scripts.dedupe_scan --content content/claude_v14.json [--locale ru] [--charts 300] [--out scan.json]
Печатает среднее число спрятанных полей на отчёт и самые частые; --out — пары «поле ~ поле выше», из них собирается
pairs.json для scripts.dup_check.
"""
import argparse
import collections
import json
import statistics

import astro.report as R
from astro.brief import load_stats
from astro.chart import build_chart
from astro.doctrine import load_yaml
from astro.rules import assemble_report, atomic_facts, match_rules, synthesis_keys
from astro.service import synthetic_inputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--locale", default="ru")
    ap.add_argument("--charts", type=int, default=300)
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--out")
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    st = load_stats(d)
    content = {it["key"]: {k: v for k, v in it.items() if k != "key"} for it in json.load(open(a.content, encoding="utf-8"))}
    hits, pair, per = collections.Counter(), collections.Counter(), []

    def logging_dedupe(modules, thr):
        seen = {"strength": [], "shadow": [], "action": []}
        n = 0
        ordered = [it for m in modules for it in m["items"] if it.get("main")] + \
                  [it for m in modules for it in m["items"] if not it.get("main")]
        for it in ordered:
            for t, key in [(it.get("text"), it["key"])] + [(g.get("text"), g["key"]) for g in it.get("group") or []]:
                sig = (t or {}).get("_sig")
                if not sig:
                    continue
                for f in ("strength", "shadow", "action"):
                    u = sig.get(f)
                    if not u or not u["w"]:
                        continue
                    pool = seen["strength"] + seen["shadow"] if f in ("strength", "shadow") else seen[f]
                    hit = next((src for v, src in pool if R._dup(u, [v], thr)), None)
                    if hit:
                        hits[(key, f)] += 1
                        pair[((key, f), hit)] += 1
                        n += 1
                    else:
                        seen[f].append((u, (key, f)))
        per.append(n)
        return 0
    R._dedupe = logging_dedupe
    for inp in synthetic_inputs(d, a.charts, seed=3):
        c = build_chart(inp, d)
        keys = [f["key"] for f in atomic_facts(c, d)] + [r["key"] for r in match_rules(c, d)[0]] + synthesis_keys(d)
        cont = {k: json.loads(json.dumps(content[k])) for k in keys if k in content}
        R.finalize(assemble_report(c, d, cont), c, d, st, a.locale, cont)
    print(f"charts {len(per)} · fields hidden per report: mean {statistics.mean(per):.2f}, median {statistics.median(per)}"
          f" · distinct fields ever hidden: {len(hits)}")
    for (k, f), n in hits.most_common(15):
        print(f"  {n:4d} {k} {f}")
    if a.out:
        json.dump({"hits": [[k, f, n] for (k, f), n in hits.most_common()],
                   "pairs": [[x[0], x[1], y[0], y[1], n] for (x, y), n in pair.most_common()]},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
