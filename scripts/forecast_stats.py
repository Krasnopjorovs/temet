"""Факты для авторов текстов прогноза: сколько обычно длится влияние и как часто повторяется.

Для каждой транзитной планеты и класса аспекта — по случайным натальным точкам и 200 годам эфемерид:
длительность эпизода (вход в орбис — выход, попятные петли слиты, как в прогнозе) и промежуток до следующего
эпизода того же класса к той же точке. Для домов — сколько планета идёт по дому средней ширины (30°) и как часто
возвращается. Для прогрессивной Луны — длительность аспекта и пребывания в доме/знаке.
Результат дописывается в doctrine/stats/<код>.forecast.json (ключ "episodes"); калибровка насыщенности не трогается.

python -m scripts.forecast_stats
"""
from __future__ import annotations

import json
import os
import random

import numpy as np

from astro.doctrine import load_yaml
from astro.forecast import Sky, _runs, w180


def episodes(t, g, orb, gap):
    runs = _runs(np.abs(g) <= orb)
    out = []
    for a, b in runs:
        if out and t[a] - out[-1][1] < gap:
            out[-1][1], out[-1][3] = t[b], b
        else:
            out.append([t[a], t[b], a, b])
    return [(x[0], x[1]) for x in out if x[2] > 0 and x[3] < len(t) - 1]   # обрезанные краем выборки — не в счёт


def main():
    d = load_yaml("doctrine/classic_modern_v1.yaml")
    p = d.params["forecast"]
    sky = Sky(d)
    rng = random.Random(5)
    jd0, jd1 = 2415020.5, 2488070.5                  # 1900–2100
    angles = {a.code: a.angle_deg for a in d.aspects}
    contacts = {cls: sum(1 if angles[c] in (0, 180) else 2 for c in codes) for cls, codes in p["aspect_classes"].items()}
    res: dict = {"tr": {}, "trh": {}, "retro": {}}
    for T in p["transiting"]:
        slow = T in p["slow"]
        step = max(float(p["scan_step_days"][T]), 0.5)
        t, lon, spd = sky.series(T, jd0, jd1, step)
        period = 360.0 / (float(np.unwrap(np.radians(lon))[-1] - np.radians(lon[0])) * 180 / np.pi / (t[-1] - t[0]))
        gap = 400.0 if slow else float(p["episode_gap_days"]["fast"])   # все петли одного прохода — одна тема
        for cls, codes in p["aspect_classes"].items():
            durs = []
            for _ in range(40):
                n = rng.uniform(0, 360)
                for c in codes:
                    for lam in {(n + angles[c]) % 360, (n - angles[c]) % 360}:
                        durs += [b - a for a, b in episodes(t, w180(lon - lam), float(p["orb"][T]), gap)]
            res["tr"][f"{T}:{cls}"] = {"days": round(float(np.median(durs)), 1),
                                       "days_p90": round(float(np.quantile(durs, .9)), 1),
                                       "every_days": round(period / contacts[cls], 1)}
        if T in p["house_transits"]:
            res["trh"][T] = {"days": round(period * 30 / 360, 1), "every_days": round(period, 1)}
        if T in p["retro_watch"]:
            st = np.where(np.diff(np.sign(spd)) != 0)[0]
            ts = t[st]
            dirs = np.sign(spd[st + 1])
            r = [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if dirs[i] < 0]
            starts = [ts[i] for i in range(len(ts)) if dirs[i] < 0]
            res["retro"][T] = {"days": round(float(np.median(r)), 1), "every_days": round(float(np.median(np.diff(starts))), 1)}
    v = 13.18 / 365.25                               # прогрессивная Луна: ~13.2° в год
    pm = p["progressed_moon"]
    res["pm"] = {"days": round(2 * float(pm["orb"]) / v, 1), "house_days": round(30 / v, 1), "sign_days": round(30 / v, 1)}
    res["moon"] = {"days": 2.5, "every_days": 27.3}
    res["lun"] = {"every_days": 365.25}
    path = os.path.join("doctrine", "stats", f"{d.code}.forecast.json")
    data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    data["episodes"] = res
    json.dump(data, open(path, "w", encoding="utf-8"))
    for k, v_ in res["tr"].items():
        print(k, v_)
    print(res["trh"], res["retro"], res["pm"])


if __name__ == "__main__":
    main()
