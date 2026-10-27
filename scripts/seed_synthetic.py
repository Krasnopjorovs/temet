"""Синтетические профили (synthetic=true) для нагрузочных тестов и проверки recall.
В выдачу реальным людям они не попадают (фильтр по умолчанию).
python -m scripts.seed_synthetic --n 5000"""
import argparse
import os
import time

import numpy as np

from astro import store
from astro.service import Runtime, synthetic_inputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=12345)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        modes = list(rt.d.modes)
        t = time.time()
        for i, inp in enumerate(synthetic_inputs(rt.d, a.n, seed=a.seed)):
            pick = [m for m in modes if rng.random() < 0.6] or [modes[0]]
            rt.create_profile(conn, f"synthetic-{a.seed}-{i}", inp, pick, synthetic=True)
        print(f"{a.n} synthetic profiles in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
