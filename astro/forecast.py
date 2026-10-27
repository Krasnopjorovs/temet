"""Прогноз по натальной карте на окно времени (неделя, месяц) — без LLM, только расчёт и ключи текстов.

Техники (всё настраивается в доктрине, params.forecast):
  tr   — транзит планеты к натальной точке: эпизод «вход в орбис — точные касания — выход»; попятные петли
         одного аспекта сливаются в один эпизод; разворот планеты на точке усиливает тему;
         «обещание карты» — те же две планеты связаны аспектом и в натальной карте (любым: тип назван в ответе);
  trh  — транзит планеты по натальному дому (с датами входа и выхода, петли на границе домов учтены);
  moon — Луна по домам (для недели);
  lun / ecl — новолуния, полнолуния и затмения: дом и натальные точки рядом;
  retro — попятный период Меркурия, Венеры, Марса в доме карты;
  pm / pmh / pms — прогрессивная Луна (вторичные прогрессии, день за год): аспекты, дом, знак.
Вес события = вес планеты × вес натальной точки (её PageRank в карте) × класс аспекта × точность в окне × усилители.
Тема, которую задевают ≥ 2 разные техники (медленный транзит, прогрессия, лунация, затмение), подтверждена.
Погрешность даты от неточного времени рождения = неопределённость натальной точки / скорость планеты.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import swisseph as swe

from .chart import house_of
from .doctrine import Doctrine
from .i18n import DEFAULT, fmt, join, lab
from .ephemeris import _calc, _ensure_thread_init

J1970 = 2440587.5
MINUTE = 1.0 / 1440.0


def w180(x):
    return (x + 180.0) % 360.0 - 180.0


def jd_of(dt: datetime) -> float:
    return J1970 + dt.astimezone(timezone.utc).timestamp() / 86400.0


def dt_of(jd: float, tz) -> datetime:
    return datetime.fromtimestamp((jd - J1970) * 86400.0, tz=timezone.utc).astimezone(tz)


def bisect(f, a: float, b: float, tol: float = MINUTE) -> float:
    """корень f на [a, b] при разных знаках на концах"""
    fa = f(a)
    for _ in range(64):
        if b - a < tol:
            break
        m = (a + b) / 2.0
        fm = f(m)
        if (fm > 0) == (fa > 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2.0


def window(period: str, start: date, tz) -> tuple[datetime, datetime]:
    """неделя — 7 дней с даты начала; месяц — календарный месяц, в котором лежит дата"""
    if period == "week":
        a = datetime(start.year, start.month, start.day, tzinfo=tz)
        return a, a + timedelta(days=7)
    if period == "month":
        a = datetime(start.year, start.month, 1, tzinfo=tz)
        b = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=tz)
        return a, b
    raise ValueError(f"unknown period {period}")


class Sky:
    def __init__(self, d: Doctrine):
        _ensure_thread_init()
        self.se = {b.code: int(b.source["se"]) for b in d.bodies if "se" in b.source}
        self.allow = bool(d.params.get("allow_moshier", False))
        self._series: dict = {}

    def pos(self, body: str, jd: float) -> tuple[float, float]:
        return _calc(jd, self.se[body], self.allow)

    def lon(self, body: str, jd: float) -> float:
        return self.pos(body, jd)[0]

    def series(self, body: str, jd0: float, jd1: float, step: float):
        key = (body, jd0, jd1, step)
        if key not in self._series:
            t = np.arange(jd0, jd1 + step / 2, step)
            lon, spd = np.empty_like(t), np.empty_like(t)
            for i, x in enumerate(t):
                lon[i], spd[i] = self.pos(body, x)
            self._series[key] = (t, lon, spd)
        return self._series[key]


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _episodes(t, g, orb, gap, fn, w0, w1):
    """эпизоды |g| ≤ orb, пересекающие окно [w0, w1]; проходы ближе gap сливаются; границы и точные касания —
    бисекцией по fn (знаковое отклонение от точного аспекта, градусы)"""
    n = len(t)
    runs = _runs(np.abs(g) <= orb)
    if not runs:
        return []
    groups = [[runs[0]]]
    for r in runs[1:]:
        if t[r[0]] - t[groups[-1][-1][1]] < gap:
            groups[-1].append(r)
        else:
            groups.append([r])
    out = []
    for grp in groups:
        i0, i1 = grp[0][0], grp[-1][1]
        lo = t[max(i0 - 1, 0)]
        hi = t[min(i1 + 1, n - 1)]
        if hi < w0 or lo > w1:
            continue
        edge = lambda x: abs(fn(x)) - orb
        start = None if i0 == 0 else bisect(edge, t[i0 - 1], t[i0])
        end = None if i1 == n - 1 else bisect(edge, t[i1], t[i1 + 1])
        exacts = []
        for a, b in grp:
            for k in range(max(a - 1, 0), min(b, n - 2) + 1):
                if np.sign(g[k]) != np.sign(g[k + 1]) and abs(g[k]) < 90 and abs(g[k + 1]) < 90:
                    exacts.append(bisect(fn, t[k], t[k + 1]))
        exacts = sorted(set(round(x, 6) for x in exacts))
        sel = slice(i0, i1 + 1)
        out.append({"start": start, "end": end, "t0": t[i0], "t1": t[i1], "exacts": exacts, "passes": len(grp),
                    "speed": float(np.median(np.abs(np.diff(np.unwrap(np.radians(g[max(i0 - 1, 0):i1 + 2])))))) /
                    float(t[1] - t[0]) * 180 / math.pi if i1 > i0 else None, "_sel": sel})
    return out


def _peak_dev(ep, fn, t, g, w0, w1) -> float:
    """наименьшее отклонение от точного аспекта внутри окна"""
    if any(w0 <= x <= w1 for x in ep["exacts"]):
        return 0.0
    a = max(w0, ep["start"] if ep["start"] is not None else t[0])
    b = min(w1, ep["end"] if ep["end"] is not None else t[-1])
    if a > b:
        return float("inf")
    inside = [abs(g[i]) for i in range(len(t)) if a < t[i] < b]
    return min([abs(fn(a)), abs(fn(b))] + inside)


def _stations(sky: Sky, body: str, t, spd) -> list[dict]:
    out = []
    for k in range(len(t) - 1):
        if (spd[k] > 0) != (spd[k + 1] > 0):
            x = bisect(lambda j: sky.pos(body, j)[1], t[k], t[k + 1])
            out.append({"jd": x, "lon": sky.lon(body, x), "dir": "R" if spd[k] > 0 else "D"})
    return out


def _house_runs(t, lon, cusps, step_fn, w0, w1, gap):
    """присутствие планеты в домах: сырые отрезки (для окна) и эпизоды с петлями (для дат «с … по …»)"""
    hs = np.array([house_of(float(x), cusps) for x in lon])
    segs = []
    i, n = 0, len(t)
    while i < n:
        j = i
        while j + 1 < n and hs[j + 1] == hs[i]:
            j += 1
        h = int(hs[i])
        a = None if i == 0 else bisect(lambda x: 1.0 if house_of(step_fn(x), cusps) == h else -1.0, t[i - 1], t[i])
        b = None if j == n - 1 else bisect(lambda x: 1.0 if house_of(step_fn(x), cusps) == h else -1.0, t[j], t[j + 1])
        segs.append({"house": h, "start": a, "end": b, "t0": t[i], "t1": t[j]})
        i = j + 1
    merged: dict[int, list[dict]] = {}
    for s in segs:
        lst = merged.setdefault(s["house"], [])
        if lst and lst[-1]["end"] is not None and s["start"] is not None and s["start"] - lst[-1]["end"] < gap:
            lst[-1]["end"], lst[-1]["t1"] = s["end"], s["t1"]
        else:
            lst.append(dict(s))
    present = []
    for s in segs:
        a = s["start"] if s["start"] is not None else t[0]
        b = s["end"] if s["end"] is not None else t[-1]
        ov = min(b, w1) - max(a, w0)
        if ov > 0:
            ep = next(e for e in merged[s["house"]]
                      if (e["start"] is None or e["start"] <= a + 1e-9) and (e["end"] is None or e["end"] >= b - 1e-9))
            present.append({"house": s["house"], "overlap": ov, "seg": s, "episode": ep})
    by_h: dict[int, dict] = {}
    for p in present:
        q = by_h.get(p["house"])
        if q:
            q["overlap"] += p["overlap"]
            q["ingress"] = q["ingress"] or p["seg"]["start"]
        else:
            by_h[p["house"]] = {**p, "ingress": p["seg"]["start"]}
    return list(by_h.values())


class Forecaster:
    def __init__(self, d: Doctrine, calibration: dict | None = None):
        self.d = d
        self.p = d.params["forecast"]
        self.cal = calibration or {}

    # ------------------------------------------------------------------ helpers
    def _cls(self, aspect: str) -> str:
        return next(c for c, lst in self.p["aspect_classes"].items() if aspect in lst)

    def _kernel(self, dev: float, orb: float) -> float:
        return math.exp(math.log(float(self.p["orb_floor"])) * (dev / orb) ** 2) if dev <= orb else 0.0

    def _natal_weights(self, chart: dict) -> dict[str, float]:
        pr = chart["dominance"]["pagerank"]
        pts = [n for n in self.p["natal_points"] if chart["bodies"].get(n, {}).get("shown") and n in pr]
        mean = sum(pr[n] for n in pts) / max(1, len(pts))
        return {n: pr[n] / mean for n in pts}

    def _promise(self, chart: dict, a: str, b: str) -> tuple[float, str | None]:
        """натальный аспект между теми же планетами: (сила, код аспекта) — тип может отличаться от транзитного"""
        if a == b:
            return 0.0, None
        best = max((x for x in chart["aspects"] if {x["a"], x["b"]} == {a, b}), key=lambda x: x["strength"], default=None)
        if not best or best["strength"] < float(self.p.get("promise_min_strength", 0.0)):
            return 0.0, None
        return best["strength"], best["aspect"]

    # ------------------------------------------------------------------ main
    def compute(self, chart: dict, period: str, start: date, tz_name: str, locale: str = DEFAULT) -> dict:
        p, d = self.p, self.d
        tz = ZoneInfo(tz_name)
        a_dt, b_dt = window(period, start, tz)
        w0, w1 = jd_of(a_dt), jd_of(b_dt)
        wlen = w1 - w0
        sky = Sky(d)
        known = chart["meta"]["time_known"]
        cusps = chart.get("cusps") if known else None
        wn = self._natal_weights(chart)
        hcw = d.params["house_class_weight"]
        hmean = sum(hcw[d.house_class(h)] for h in range(1, 13)) / 12.0
        aspects = {a.code: a.angle_deg for a in d.aspects if any(a.code in v for v in p["aspect_classes"].values())}
        unc_asc = chart["bodies"].get("ASC", {}).get("w_deg", 0.0) if known else 0.0
        items: list[dict] = []
        stations_all: dict[str, list[dict]] = {}

        def approx(item, unc_days, dur):
            item["date_uncertainty_days"] = round(unc_days, 1) if unc_days >= 0.5 else 0
            ratio = unc_days / max(dur, 1.0)
            if ratio > float(p["drop_uncertainty_ratio"]):
                return False
            if ratio > float(p["max_date_uncertainty_ratio"]):
                item["approx"] = True
                item["score"] *= float(p["approx_penalty"])
            return True

        # --------------------------------------------------------- транзиты к натальным точкам
        for T in p["transiting"]:
            slow = T in p["slow"]
            hz = float(p["horizon_days"]["slow" if slow else "fast"])
            step = float(p["scan_step_days"][T])
            t, lon, spd = sky.series(T, w0 - hz, w1 + hz, step)
            st = _stations(sky, T, t, spd) if T not in ("SUN",) else []
            stations_all[T] = st
            orb = float(p["orb"][T])
            gap = float(p["episode_gap_days"]["slow" if slow else "fast"])
            for N, wN in wn.items():
                nlon = chart["bodies"][N]["lon"]
                for acode, ang in aspects.items():
                    targets = {round((nlon + ang) % 360, 9), round((nlon - ang) % 360, 9)}
                    for lam in targets:
                        g = w180(lon - lam)
                        fn = lambda x, lam=lam, T=T: w180(sky.lon(T, x) - lam)
                        for ep in _episodes(t, g, orb, gap, fn, w0, w1):
                            dev = _peak_dev(ep, fn, t, g, w0, w1)
                            if dev > orb:
                                continue
                            cls = self._cls(acode)
                            strength = self._kernel(dev, orb)
                            station = next((s for s in st if abs(w180(s["lon"] - lam)) <= float(p["station_orb"])
                                            and (ep["start"] is None or s["jd"] >= ep["start"] - 1)
                                            and (ep["end"] is None or s["jd"] <= ep["end"] + 1)), None)
                            promise, promise_aspect = self._promise(chart, T, N)
                            score = float(p["body_weight"][T]) * wN * float(p["class_weight"][cls]) * strength
                            score *= (1 + float(p["promise_boost"]) * promise)
                            if station:
                                score *= float(p["station_boost"])
                            it = {"kind": "tr", "key": f"tr:{T}:{cls}:{N}", "body": T, "point": N, "aspect": acode,
                                  "cls": cls, "slow": slow, "start": ep["start"], "end": ep["end"],
                                  "exacts": ep["exacts"], "passes": ep["passes"], "strength": round(strength, 3),
                                  "promise": round(promise, 3), "promise_aspect": promise_aspect,
                                  "station": station, "score": score}
                            if N in ("ASC", "MC") or chart["bodies"][N].get("w_deg", 0) > 0:
                                v = ep["speed"] or abs(float(np.median(spd[ep["_sel"]]))) or 1e-3
                                dur = ((ep["end"] or t[-1]) - (ep["start"] or t[0]))
                                if not approx(it, chart["bodies"][N].get("w_deg", 0.0) / max(v, 1e-3), dur):
                                    continue
                            items.append(it)

        # --------------------------------------------------------- дома
        if cusps:
            gap_slow = float(p["episode_gap_days"]["slow"])
            for T in p["house_transits"]:
                slow = T in p["slow"]
                hz = float(p["horizon_days"]["slow" if slow else "fast"])
                t, lon, spd = sky.series(T, w0 - hz, w1 + hz, float(p["scan_step_days"][T]))
                for pr in _house_runs(t, lon, cusps, lambda x, T=T: sky.lon(T, x), w0, w1,
                                      gap_slow if slow else float(p["episode_gap_days"]["fast"])):
                    h, ep = pr["house"], pr["episode"]
                    frac = min(1.0, pr["overlap"] / wlen)
                    score = float(p["house_weight"][T]) * hcw[d.house_class(h)] / hmean * frac
                    it = {"kind": "trh", "key": f"trh:{T}:{h}", "body": T, "house": h, "slow": slow,
                          "start": ep["start"], "end": ep["end"], "ingress": pr["ingress"],
                          "presence": round(frac, 3), "score": score}
                    v = abs(float(np.median(spd))) or 1e-3
                    dur = ((ep["end"] or t[-1]) - (ep["start"] or t[0]))
                    if approx(it, unc_asc / v, dur):
                        items.append(it)
            if period in p["moon_days_for"]:
                t, lon, _ = sky.series("MOON", w0 - 1, w1 + 1, float(p["scan_step_days"]["MOON"]))
                hs = [house_of(float(x), cusps) for x in lon]
                i = 0
                while i < len(t):
                    j = i
                    while j + 1 < len(t) and hs[j + 1] == hs[i]:
                        j += 1
                    h = hs[i]
                    f = lambda x, h=h: 1.0 if house_of(sky.lon("MOON", x), cusps) == h else -1.0
                    a = t[i] if i == 0 else bisect(f, t[i - 1], t[i])
                    b = t[j] if j == len(t) - 1 else bisect(f, t[j], t[j + 1])
                    if b > w0 and a < w1:
                        items.append({"kind": "moon", "key": f"moon:{h}", "house": h, "start": a, "end": b,
                                      "score": 0.0})
                    i = j + 1

        # --------------------------------------------------------- лунации и затмения
        t, _, _ = sky.series("MOON", w0 - 1, w1 + 1, 0.25)
        for phase, shift in (("NEW", 0.0), ("FULL", 180.0)):
            fn = lambda x, s=shift: w180(sky.lon("MOON", x) - sky.lon("SUN", x) - s)
            g = np.array([fn(x) for x in t])
            for k in range(len(t) - 1):
                if np.sign(g[k]) == np.sign(g[k + 1]) or abs(g[k]) > 90 or abs(g[k + 1]) > 90:
                    continue
                x = bisect(fn, t[k], t[k + 1])
                if not (w0 <= x < w1):
                    continue
                mlon = sky.lon("MOON", x)
                ecl = self._eclipse(x, phase)
                contacts = []
                for N, wN in wn.items():
                    for pl in ([mlon] if phase == "NEW" else [mlon, (mlon + 180) % 360]):
                        dv = abs(w180(pl - chart["bodies"][N]["lon"]))
                        if dv <= float(p["lunation_orb"]) and N not in [c["point"] for c in contacts]:
                            contacts.append({"point": N, "dev": round(dv, 2), "w": wN})
                base = float(p["eclipse_weight"][ecl] if ecl else p["lunation_weight"][phase])
                score = base * (1 + float(p["lunation_contact_boost"]) * sum(c["w"] for c in contacts))
                h = house_of(mlon, cusps) if cusps else None
                kind = "ecl" if ecl else "lun"
                key = (f"ecl:{ecl}:{h}" if ecl else f"lun:{phase}:{h}") if h else None
                items.append({"kind": kind, "key": key, "phase": phase, "eclipse": ecl, "house": h, "lon": mlon,
                              "start": x, "end": x, "exacts": [x], "contacts": contacts, "score": score})

        # --------------------------------------------------------- попятные периоды
        for T in p["retro_watch"]:
            st = stations_all.get(T, [])
            for k, s in enumerate(st):
                if s["dir"] != "R":
                    continue
                e = next((x for x in st[k + 1:] if x["dir"] == "D"), None)
                a, b = s["jd"], (e["jd"] if e else None)
                if (b is not None and b < w0) or a > w1:
                    continue
                mid = (max(a, w0) + min(b if b is not None else w1, w1)) / 2
                h = house_of(sky.lon(T, mid), cusps) if cusps else None
                frac = (min(b if b is not None else w1, w1) - max(a, w0)) / wlen
                items.append({"kind": "retro", "key": f"retro:{T}:{h}" if h else None, "body": T, "house": h,
                              "start": a, "end": b, "station_r": s, "station_d": e,
                              "score": float(p["retro_weight"][T]) * min(1.0, frac)})

        # --------------------------------------------------------- прогрессивная Луна
        if known:
            pm = p["progressed_moon"]
            jb, Y = float(chart["meta"]["jd_ut"]), float(p["tropical_year_days"])
            plon = lambda x: sky.lon("MOON", jb + (x - jb) / Y)
            t = np.arange(w0 - 400, w1 + 400, 5.0)
            lon = np.array([plon(x) for x in t])
            unc_pm = chart["bodies"]["MOON"].get("w_deg", 0.0)
            for N, wN in wn.items():
                nlon = chart["bodies"][N]["lon"]
                for acode, ang in aspects.items():
                    for lam in {round((nlon + ang) % 360, 9), round((nlon - ang) % 360, 9)}:
                        g = w180(lon - lam)
                        fn = lambda x, lam=lam: w180(plon(x) - lam)
                        for ep in _episodes(t, g, float(pm["orb"]), 0.0, fn, w0, w1):
                            dev = _peak_dev(ep, fn, t, g, w0, w1)
                            if dev > float(pm["orb"]):
                                continue
                            cls = self._cls(acode)
                            s_ = self._kernel(dev, float(pm["orb"]))
                            it = {"kind": "pm", "key": f"pm:{cls}:{N}", "point": N, "aspect": acode, "cls": cls,
                                  "start": ep["start"], "end": ep["end"], "exacts": ep["exacts"],
                                  "strength": round(s_, 3),
                                  "score": float(pm["weight"]) * wN * float(p["class_weight"][cls]) * s_}
                            v = 13.2 / Y
                            if approx(it, (unc_pm + chart["bodies"][N].get("w_deg", 0.0)) / v,
                                      (ep["end"] or t[-1]) - (ep["start"] or t[0])):
                                items.append(it)
            mid = (w0 + w1) / 2
            ml = plon(mid)
            h = house_of(ml, cusps)
            sign = d.sign_by_idx[int(ml // 30) % 12]["code"]
            hs = np.array([house_of(float(x), cusps) for x in lon])
            ss = np.array([int(x // 30) % 12 for x in lon])
            k = int(np.searchsorted(t, mid))
            span = lambda arr, val: (next((t[i + 1] for i in range(k - 1, -1, -1) if arr[i] != val), None),
                                     next((t[i] for i in range(k, len(t)) if arr[i] != val), None))
            a, b = span(hs, h)
            items.append({"kind": "pmh", "key": f"pmh:{h}", "house": h, "start": a, "end": b,
                          "score": float(pm["house_weight"]) * hcw[d.house_class(h)] / hmean})
            a, b = span(ss, int(ml // 30) % 12)
            items.append({"kind": "pms", "key": f"pms:{sign}", "sign": sign, "start": a, "end": b,
                          "score": float(pm["sign_weight"])})

        self._clusters(items, chart, wn)
        self._confirm(items)
        res = self._shape(items, chart, period, a_dt, b_dt, w0, w1, tz, locale)
        mid = (w0 + w1) / 2           # небо в середине окна — для внешнего круга
        res["sky"] = {"at": dt_of(mid, tz).isoformat(timespec="minutes"), "bodies": {}}
        for T in ["MOON", *p["transiting"]]:
            lon_, spd_ = sky.pos(T, mid)
            res["sky"]["bodies"][T] = {"lon": round(lon_, 4), "shown": True, "retro": spd_ < 0}
        return res

    # ------------------------------------------------------------------ связки
    def _clusters(self, items: list[dict], chart: dict, wn: dict) -> None:
        """натальные точки в тесном соединении — одна связка: транзит одной планеты одним аспектом проходит их подряд,
        и эти события помечаются друг другом (тема дней складывается вместе, а не спорит по тону)"""
        lim = float(self.p.get("cluster_min_strength", 1.1))
        parent = {n: n for n in wn}
        find = lambda x: x if parent[x] == x else find(parent[x])
        for a in chart["aspects"]:
            if a["aspect"] == "CONJ" and a["strength"] >= lim and a["a"] in parent and a["b"] in parent:
                parent[find(a["a"])] = find(a["b"])
        groups: dict[tuple, list[dict]] = {}
        for it in items:
            if it["kind"] == "tr":
                groups.setdefault((it["body"], it["aspect"], find(it["point"])), []).append(it)
        for lst in groups.values():
            pts = {it["point"] for it in lst}
            if len(pts) < 2:
                continue
            for it in lst:
                a = it["start"] if it["start"] is not None else -1e9
                b = it["end"] if it["end"] is not None else 1e9
                near = sorted({o["point"] for o in lst if o["point"] != it["point"] and
                               (o["start"] if o["start"] is not None else -1e9) <= b + 3 and
                               (o["end"] if o["end"] is not None else 1e9) >= a - 3},
                              key=lambda c: self.d.body_index[c])
                if near:
                    it["cluster"] = near

    # ------------------------------------------------------------------ затмения
    def _eclipse(self, jd: float, phase: str) -> str | None:
        if phase == "NEW":
            ret, tret = swe.sol_eclipse_when_glob(jd - 1.0, swe.FLG_SWIEPH, 0, False)
            return "SOLAR" if abs(tret[0] - jd) < 1.0 else None
        ret, tret = swe.lun_eclipse_when(jd - 1.0, swe.FLG_SWIEPH, 0, False)
        if abs(tret[0] - jd) >= 1.0:
            return None
        if self.p.get("eclipse_lunar_min") == "partial" and not ret & (swe.ECL_TOTAL | swe.ECL_PARTIAL):
            return None
        return "LUNAR"

    # ------------------------------------------------------------------ подтверждение
    def _confirm(self, items: list[dict]) -> None:
        tech_ok = set(self.p["confirm_techniques"])
        themes: dict[tuple, list[tuple[str, dict]]] = {}

        def touch(theme, tech, it):
            if tech in tech_ok:
                themes.setdefault(theme, []).append((tech, it))

        for it in items:
            k = it["kind"]
            if k == "tr" and it["slow"]:
                touch(("pt", it["point"]), "slow", it)
            elif k == "trh" and it["slow"]:
                touch(("h", it["house"]), "slow", it)
            elif k == "pm":
                touch(("pt", it["point"]), "progressed", it)
            elif k == "pmh":
                touch(("h", it["house"]), "progressed", it)
            elif k in ("lun", "ecl"):
                tech = "eclipse" if k == "ecl" else "lunation"
                if it.get("house"):
                    touch(("h", it["house"]), tech, it)
                for c in it["contacts"]:
                    touch(("pt", c["point"]), tech, it)
        for theme, lst in themes.items():
            if len({tech for tech, _ in lst}) < 2:
                continue
            for _, it in lst:
                others = [o for _, o in lst if o is not it]
                it.setdefault("confirmed", [])
                it["confirmed"] += [o.get("key") for o in others if o.get("key") not in it["confirmed"]]
                if not it.get("_boosted"):
                    it["score"] *= float(self.p["confirm_boost"])
                    it["_boosted"] = True

    # ------------------------------------------------------------------ форма ответа
    def _shape(self, items, chart, period, a_dt, b_dt, w0, w1, tz, locale=DEFAULT) -> dict:
        p = self.p
        wlen = w1 - w0
        main, timeline, background, moon = [], [], [], []
        for it in items:
            it.pop("_boosted", None)
            if it["kind"] == "moon":
                moon.append(it)
                continue
            peak = any(w0 <= x < w1 for x in it.get("exacts") or []) or \
                (it.get("station") and w0 <= it["station"]["jd"] < w1) or \
                (it.get("ingress") is not None and w0 <= it["ingress"] < w1) or \
                (it["kind"] == "retro" and (w0 <= it["start"] < w1 or (it["end"] is not None and w0 <= it["end"] < w1)))
            a = it["start"] if it.get("start") is not None else w0 - 1e4
            b = it["end"] if it.get("end") is not None else w1 + 1e4
            it["peak_in_window"] = bool(peak)
            if not peak and (b - a) > float(p["background_ratio"]) * wlen:
                background.append(it)
            else:
                timeline.append(it)
        timeline.sort(key=lambda x: -x["score"])
        n_main = int(p["main_count"][period])
        # главное — события с пиком внутри окна (точное касание, разворот, вход в дом); остальные — только если пиков мало
        main = ([it for it in timeline if it.get("key") and it["peak_in_window"]] +
                [it for it in timeline if it.get("key") and not it["peak_in_window"]])[:n_main]
        for it in main:
            it["main"] = True
        timeline.sort(key=lambda x: (x["exacts"][0] if x.get("exacts") else (x.get("start") or w0)))
        background.sort(key=lambda x: -x["score"])
        moon.sort(key=lambda x: x["start"])
        raw = sum(it["score"] for it in items if it["kind"] != "moon")
        q = self.cal.get(period)
        pct = None
        if q:
            pct = round(100.0 * float(np.searchsorted(np.array(q), raw)) / len(q), 1)
        fmt = lambda jd: None if jd is None else dt_of(jd, tz).isoformat(timespec="minutes")

        def out(it):
            o = {k: v for k, v in it.items() if k not in ("_sel",)}
            for f in ("start", "end", "ingress"):
                if f in o:
                    o[f] = fmt(o[f])
            if "exacts" in o:
                o["exacts"] = [fmt(x) for x in o["exacts"]]
            for f in ("station", "station_r", "station_d"):
                if o.get(f):
                    o[f] = {**o[f], "jd": fmt(o[f]["jd"]), "lon": round(o[f]["lon"], 3)}
            if "lon" in o and isinstance(o["lon"], float):
                o["lon"] = round(o["lon"], 3)
            o["score"] = round(o["score"], 4)
            o["title"] = self.title(it, locale)
            o["short"] = self.short(o["title"], locale)
            tp = self._tp(locale)
            note = tp.get("notes", {}).get(it["kind"])
            if it.get("cluster"):
                others = it["cluster"]
                verb = tp.get("cluster_verb") or [""]
                note = ((note + " ") if note else "") + tp["cluster"].format(
                    ins=self._case(it["point"], 1, locale), verb=verb[min(len(others), len(verb)) - 1],
                    others=join([self._bl(c, locale) for c in others], self.d, locale), t=self._bl(it["body"], locale))
            if note:
                o["note"] = note
            return o

        return {"period": period, "window": {"start": a_dt.isoformat(), "end": b_dt.isoformat(), "tz": str(tz)},
                "time_known": chart["meta"]["time_known"], "intensity": {"raw": round(float(raw), 4), "pct": pct,
                                                                         "label": self.intensity_label(pct, locale)},
                "main": [out(x) for x in main], "timeline": [out(x) for x in timeline],
                "background": [out(x) for x in background], "moon": [out(x) for x in moon]}

    def intensity_label(self, pct, locale="ru"):
        if pct is None:
            return None
        lab = None
        il = self.p["intensity_labels"]
        for lo, text in il.get(locale) or il[DEFAULT]:
            if pct >= lo:
                lab = text
        return lab

    # ------------------------------------------------------------------ подписи
    def _tp(self, locale):
        return _templates(self.p, locale)

    def _bl(self, c, locale):
        return lab(self.d.body(c).label, locale, c)

    def _case(self, c, i, locale):
        return _case(self.d, self.p, c, i, locale)

    def short(self, title: str, locale: str = "ru") -> str:
        """подпись строки ленты: полный заголовок без «вашей карты» (замены — params.forecast.templates.<язык>.short)"""
        for a, b in self._tp(locale).get("short") or []:
            title = title.replace(a, b)
        return title

    def title(self, it: dict, locale: str = "ru") -> str:
        tp = self._tp(locale)
        F = lambda tpl_, **kw: fmt(tpl_, locale, **kw)
        k = it["kind"]
        if k in ("tr", "pm"):
            phrase = tp["aspect"][it["aspect"]].format(dat=self._case(it["point"], 0, locale), ins=self._case(it["point"], 1, locale))
            return tp[k].format(t=self._bl(it["body"], locale) if k == "tr" else "", phrase=phrase).strip()
        if k == "trh":
            return F(tp["trh"], t=self._bl(it["body"], locale), h=it["house"])
        if k == "moon":
            return F(tp["moon"], h=it["house"])
        if k in ("lun", "ecl"):
            name = tp["lun"][it["phase"]] if k == "lun" else tp["ecl"][it["eclipse"]]
            s = F(tp["in_house"], name=name, h=it["house"]) if it.get("house") else name
            if it["contacts"]:
                s += ", " + tp["contact"].format(ins=join([self._case(c["point"], 1, locale) for c in it["contacts"]], self.d, locale))
            return s
        if k == "retro":
            return F(tp["retro"], t=self._bl(it["body"], locale), h=it["house"]) if it.get("house") else self._bl(it["body"], locale)
        if k == "pmh":
            return F(tp["pmh"], h=it["house"])
        if k == "pms":
            return tp["pms"].format(sign=lab(self.d.sign_by_code[it["sign"]]["label"], locale, it["sign"]))
        return it.get("key") or k


def forecast_keys(d: Doctrine) -> list[str]:
    """пространство ключей текстов прогноза"""
    p = d.params.get("forecast")
    if not p:
        return []
    keys = []
    for T in p["transiting"]:
        for cls in p["aspect_classes"]:
            keys += [f"tr:{T}:{cls}:{N}" for N in p["natal_points"]]
    for T in p["house_transits"]:
        keys += [f"trh:{T}:{h}" for h in range(1, 13)]
    keys += [f"moon:{h}" for h in range(1, 13)]
    keys += [f"lun:{ph}:{h}" for ph in p["lunation_weight"] for h in range(1, 13)]
    keys += [f"ecl:{e}:{h}" for e in p["eclipse_weight"] for h in range(1, 13)]
    keys += [f"retro:{T}:{h}" for T in p["retro_watch"] for h in range(1, 13)]
    for cls in p["aspect_classes"]:
        keys += [f"pm:{cls}:{N}" for N in p["natal_points"]]
    keys += [f"pmh:{h}" for h in range(1, 13)]
    keys += [f"pms:{s['code']}" for s in d.signs]
    return keys


def describe_forecast_key(key: str, d: Doctrine, locale: str = "ru") -> str | None:
    """заголовок ключа для авторов текстов (класс аспекта, без конкретной даты)"""
    p = d.params.get("forecast")
    if not p:
        return None
    tp = _templates(p, locale)
    cs = lambda c, i: _case(d, p, c, i, locale)
    bl = lambda c: lab(d.body(c).label, locale, c)
    F = lambda tpl_, **kw: fmt(tpl_, locale, **kw)
    kind, *parts = key.split(":")
    if kind == "tr":
        T, cls, N = parts
        return tp["tr_key"].format(gen=cs(T, 2), cls=tp["class"][cls], dat=cs(N, 0))
    if kind == "pm":
        cls, N = parts
        return tp["pm_key"].format(cls=tp["class"][cls], dat=cs(N, 0))
    if kind == "trh":
        return F(tp["trh"], t=bl(parts[0]), h=parts[1])
    if kind == "moon":
        return F(tp["moon"], h=parts[0])
    if kind in ("lun", "ecl"):
        return F(tp["in_house"], name=tp[kind][parts[0]], h=parts[1])
    if kind == "retro":
        return F(tp["retro"], t=bl(parts[0]), h=parts[1])
    if kind == "pmh":
        return F(tp["pmh"], h=parts[0])
    if kind == "pms":
        return tp["pms"].format(sign=lab(d.sign_by_code[parts[0]]["label"], locale, parts[0]))
    return None


def _templates(p: dict, locale: str) -> dict:
    t = p["templates"]
    return {**t[DEFAULT], **t.get(locale, {})}


def _case(d: Doctrine, p: dict, code: str, i: int, locale: str) -> str:
    """падеж подписи точки (дательный, творительный, родительный); у языка без падежей — сама подпись"""
    forms = (p.get("cases") or {}).get(locale, {}).get(code)
    return forms[i] if forms else lab(d.body(code).label, locale, code)
