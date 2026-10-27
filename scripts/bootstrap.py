"""Первичная настройка: доктрина -> индексы -> калибровка (-> гео).
python -m scripts.bootstrap [--geonames]"""
import subprocess
import sys

steps = [
    [sys.executable, "-m", "scripts.load_doctrine", "doctrine/classic_modern_v1.yaml"],
    [sys.executable, "-m", "scripts.calibrate"],
]
if "--geonames" in sys.argv:
    steps.append([sys.executable, "-m", "scripts.load_geonames", "--download"])
for s in steps:
    print("+", " ".join(s[2:]), flush=True)
    subprocess.run(s, check=True)
