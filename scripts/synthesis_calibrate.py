"""Калибровка синтеза: распределение долей полюсов осей по популяции случайных карт.

Для каждой карты собирается тот же отчёт, что видит клиент (assemble_report + finalize без синтеза), и считаются доли
веса на полюсах (astro.synthesis.shares). Квантили 0..100 по каждому полюсу пишутся в
doctrine/stats/<код>.synthesis.json — отчёт читает их вместе со stats. Вторая, независимая выборка показывает,
как часто срабатывают напряжения и сквозные темы при порогах из доктрины.

Тексты (с разметкой axes) берутся из JSON-файла корпуса; после смены разметки калибровку нужно пересчитать.
python -m scripts.synthesis_calibrate content/claude_vN.json [--n 3000] [--check 1000]
"""
import argparse
import json
import os
import random
from collections import Counter

import numpy as np

from astro.brief import load_stats
from astro.chart import build_chart
from astro.doctrine import load_yaml
from astro.ephemeris import BirthInput
from astro.report import finalize
from astro.rules import assemble_report, synthesis_keys
from astro.synthesis import axes_of, shares, synthesize


def charts(d, n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        y = rng.randint(1920, 2030)
        yield build_chart(BirthInput(f"{y}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                                     f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}", "UTC",
                                     rng.uniform(-45, 62), rng.uniform(-180, 180)), d)


def report(chart, d, stats, content):
    return finalize(assemble_report(chart, d, content), chart, d, stats, content=content, synthesis=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content")
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--check", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=23)
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    stats = load_stats(d)
    stats.pop("synthesis", None)
    content = {it["key"]: {k: v for k, v in it.items() if k != "key"} for it in json.load(open(a.content, encoding="utf-8"))}
    acc = {(ax["code"], p): [] for ax in axes_of(d) for p in [x["code"] for x in ax["poles"]] + ["pair"]}
    for c in charts(d, a.n, a.seed):
        for ax, poles in shares(report(c, d, stats, content)["modules"], d).items():
            for pole, v in poles.items():
                acc[(ax, pole)].append(v)
    cal = {"population": a.n, "axes": {}}
    for (ax, pole), vals in acc.items():
        cal["axes"].setdefault(ax, {})[pole] = [round(float(x), 6) for x in np.percentile(vals, range(101))]
    out = os.path.join(os.path.dirname(a.doctrine), "stats", f"{d.code}.synthesis.json")
    json.dump(cal, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{out}: {len(acc)} poles from {a.n} charts")
    # проверка частоты срабатывания на независимой выборке
    fired, per = Counter(), []
    have = {k for k in synthesis_keys(d)}
    for c in charts(d, a.check, a.seed + 1):
        rep = report(c, d, stats, content)
        cards = synthesize(rep["modules"], d, cal, {k: content.get(k) for k in have}, chart=c)
        per.append(len(cards))
        fired.update(x["key"] for x in cards)
    print(f"cards per chart: mean {np.mean(per):.2f}, none {sum(1 for x in per if not x) / len(per):.0%}, "
          f"distribution {sorted(Counter(per).items())}")
    for k, v in fired.most_common():
        print(f"  {k:40s} {v / a.check:6.1%}")


if __name__ == "__main__":
    main()
