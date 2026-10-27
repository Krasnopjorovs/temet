"""Калибровка насыщенности прогноза: распределение суммарного веса событий окна (неделя, месяц)
по случайным картам и случайным датам. Результат — doctrine/stats/<код>.forecast.json (квантили по периодам),
сервис переводит вес окна в перцентиль и слова из params.forecast.intensity_labels.

python -m scripts.forecast_calibrate [--doctrine doctrine/classic_modern_v1.yaml] [--workers 2]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import date
from multiprocessing import Pool

import numpy as np

from astro.chart import build_chart
from astro.doctrine import load_yaml
from astro.forecast import Forecaster
from astro.service import synthetic_inputs

_D = None


def _init(path):
    global _D
    _D = load_yaml(path)


def _one(job):
    inp, windows = job
    c = build_chart(inp, _D)
    fc = Forecaster(_D)
    out = []
    for period, start in windows:
        out.append((period, fc.compute(c, period, start, "UTC")["intensity"]["raw"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    cal = d.params["forecast"]["calibration"]
    rng = random.Random(cal["seed"])
    y0, y1 = cal["year_range"]
    jobs = []
    for inp in synthetic_inputs(d, int(cal["charts"]), seed=int(cal["seed"])):
        wins = []
        for _ in range(int(cal["windows_per_chart"])):
            day = date(rng.randint(y0, y1), rng.randint(1, 12), rng.randint(1, 28))
            wins += [("week", day), ("month", day)]
        jobs.append((inp, wins))
    vals: dict[str, list[float]] = {"week": [], "month": []}
    with Pool(a.workers, initializer=_init, initargs=(a.doctrine,)) as pool:
        for n, res in enumerate(pool.imap_unordered(_one, jobs, chunksize=4), 1):
            for period, raw in res:
                vals[period].append(raw)
            if n % 50 == 0:
                print(f"{n}/{len(jobs)} карт", flush=True)
    q = int(d.params["calibration"]["quantiles"])
    out = {p: [round(float(x), 5) for x in np.quantile(np.array(v), np.linspace(0, 1, q))] for p, v in vals.items()}
    path = os.path.join("doctrine", "stats", f"{d.code}.forecast.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    for p, v in vals.items():
        v = np.array(v)
        print(f"{p}: n={len(v)} медиана {np.median(v):.2f}, 30% {np.quantile(v, .3):.2f}, 70% {np.quantile(v, .7):.2f}, "
              f"90% {np.quantile(v, .9):.2f}")
    print("->", path)


if __name__ == "__main__":
    main()
