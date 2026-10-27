"""Калибровка против нулевой модели: распределение сырых скоров по всем парам
популяции -> таблица квантилей. Перцентиль 97 = «выше 97% случайных пар».

python -m scripts.calibrate                 # синтетическая популяция из параметров доктрины
python -m scripts.calibrate --profiles      # реальные (не синтетические) профили, если их >= 300
"""
import argparse
import os
import time

import numpy as np

from astro import store
from astro.chart import build_chart
from astro.service import Runtime, synthetic_inputs
from astro.synastry import quantile_table


def vectors_from_profiles(conn, rt):
    dc = rt.d.code
    with conn.cursor() as cur:
        cur.execute("select id from profile where not synthetic and doctrine_id=%s", (rt.doctrine_id,))
        ids = [r["id"] for r in cur.fetchall()]
    kinds = [f"{dc}:x"] + [f"{dc}:q:{m}" for m in rt.d.modes] + [f"{dc}:qd:{x}" for x in rt.syn.dims]
    v = store.get_vectors(conn, ids, kinds)
    return {k.split(":", 1)[1]: np.stack([v[(i, k)] for i in ids]) for k in kinds}, len(ids)


def vectors_synthetic(rt):
    n = int(rt.d.params["calibration"]["synthetic_charts"])
    t = time.time()
    acc: dict[str, list] = {}
    for inp in synthetic_inputs(rt.d, n):
        for k, v in rt.syn.vectors(build_chart(inp, rt.d)).items():
            acc.setdefault(k, []).append(v)
    print(f"{n} synthetic charts in {time.time() - t:.1f}s")
    return {k: np.stack(v) for k, v in acc.items()}, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", action="store_true")
    a = ap.parse_args()
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        if a.profiles:
            V, n = vectors_from_profiles(conn, rt)
            if n < 300:
                raise SystemExit(f"only {n} real profiles; need >= 300, use synthetic")
            pop = "profiles"
        else:
            V, n = vectors_synthetic(rt)
            pop = "synthetic"
        X = V["x"]
        mask = ~np.eye(n, dtype=bool)
        K = int(rt.d.params["calibration"]["quantiles"])
        keys = [(m, f"q:{m}") for m in rt.d.modes] + [(dim, f"qd:{dim}") for dim in rt.syn.dims]
        for key, vk in keys:
            S = V[vk] @ X.T                       # S[a, b] = U(a <- b) для всех пар сразу
            vals = S[mask]
            q = quantile_table(vals, K)
            store.write_calibration(conn, rt.doctrine_id, key, q, int(vals.size), pop, rt.syn.fingerprint)
            print(f"{key:10} pairs={vals.size:>9}  p50={q[K // 2]:+.4f}  p90={q[int(.9 * (K - 1))]:+.4f}  "
                  f"p99={q[int(.99 * (K - 1))]:+.4f}")


if __name__ == "__main__":
    main()
