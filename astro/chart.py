"""Натальная карта как вычисленная структура: положения, дома, достоинства,
аспекты (то же ядро, что в синастрии), граф диспозиторов + PageRank доминант,
гармонический спектр. Все параметры — из доктрины."""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from .doctrine import Doctrine
from .ephemeris import BirthInput, julday, raw_positions, resolve_instant, sample_uncertainty
from .kernels import aspect_strength


def house_of(lon: float, cusps: list[float]) -> int:
    for i in range(12):
        a, b = cusps[i], cusps[(i + 1) % 12]
        if (a <= b and a <= lon < b) or (a > b and (lon >= a or lon < b)):
            return i + 1
    raise ValueError("house_of: cusps do not cover the circle")


def build_chart(inp: BirthInput, d: Doctrine) -> dict:
    p = d.params
    inst = resolve_instant(inp, p)
    jd = julday(inst.utc)
    raw = raw_positions(jd, inp.lat, inp.lon, d)
    w = sample_uncertainty(inst, inp, d)
    known = inst.time_known
    cusps = raw["cusps"]

    bodies = {}
    for b in d.bodies:
        lon = raw["lon"][b.code]
        sidx = int(lon // 30) % 12
        sign = d.sign_by_idx[sidx]
        shown = known or not b.needs_time
        entry = {
            "lon": round(lon, 6), "sign": sign["code"], "sign_idx": sidx,
            "deg_in_sign": round(lon % 30, 4), "w_rad": round(w[b.code], 6),
            "w_deg": round(math.degrees(w[b.code]), 3), "shown": shown,
        }
        spd = raw["speed"][b.code]
        if not math.isnan(spd):
            entry["speed"] = round(spd, 6)
            entry["retro"] = spd < 0
        if known and b.kind != "angle":
            entry["house"] = house_of(lon, cusps)
        dig = d.dignities.get((b.code, sign["code"]))
        if dig:
            entry["dignity"] = {"kind": dig[0], "score": dig[1]}
        entry["dispositor"] = d.primary_ruler(sign["code"])
        bodies[b.code] = entry

    chart = {
        "doctrine": d.code,
        "meta": {
            "input": {"date": inp.date, "time": inp.time, "tz": inp.tz, "lat": inp.lat, "lon": inp.lon,
                      "place": inp.place_label, "uncertainty_min": inst.half_window_min},
            "utc": inst.utc.isoformat(), "jd_ut": jd, "utc_offset_h": inst.offset_hours,
            "time_known": known, "house_system": raw["house_system"],
            "flags": inst.flags + raw["flags"],
        },
        "bodies": bodies,
    }
    if known:
        chart["cusps"] = [round(c, 6) for c in cusps]
        chart["houses"] = {}
        for i, c in enumerate(cusps, start=1):
            sc = d.sign_by_idx[int(c // 30) % 12]["code"]
            chart["houses"][str(i)] = {"cusp": round(c, 4), "sign": sc,
                                       "rulers": [r[0] for r in d.rulers.get(sc, [])]}
    chart["aspects"] = natal_aspects(chart, d)
    chart["dispositors"] = dispositor_structure(chart, d)
    chart["dominance"] = dominance(chart, d)
    chart["balance"] = balance(chart, d)
    chart["spectrum"] = spectrum(chart, d)
    chart["stellia"] = stellia(chart, d)
    return chart


def natal_aspects(chart: dict, d: Doctrine) -> list[dict]:
    p = d.params
    excl = {frozenset(x) for x in p.get("aspect_exclude_pairs", [])}
    shown = [b for b in d.bodies if chart["bodies"][b.code]["shown"]]
    out = []
    for b1, b2 in combinations(shown, 2):
        if frozenset((b1.code, b2.code)) in excl:
            continue
        e1, e2 = chart["bodies"][b1.code], chart["bodies"][b2.code]
        delta = math.radians(e1["lon"] - e2["lon"])
        for a in d.aspects:
            s = float(aspect_strength(delta, a.angle_deg, a.orb_deg, p["kernel_shape"], p["orb_floor"]))
            if s >= p["natal_min_strength"]:
                sep = abs((e1["lon"] - e2["lon"] + 180) % 360 - 180)
                orb = abs(sep - a.angle_deg)
                out.append({"a": b1.code, "b": b2.code, "aspect": a.code, "orb": round(orb, 3),
                            "strength": round(s, 4),
                            "uncertain": max(e1["w_deg"], e2["w_deg"]) > a.orb_deg / 2})
    out.sort(key=lambda x: -x["strength"])
    return out


def dispositor_structure(chart: dict, d: Doctrine) -> dict:
    """Функциональный граф «тело -> управитель знака»: конечные диспозиторы,
    взаимные рецепции, циклы и цепочки до аттрактора."""
    nxt = {k: v["dispositor"] for k, v in chart["bodies"].items()
           if v["dispositor"] and d.body(k).kind == "planet"}
    finals = sorted(k for k, v in nxt.items() if v == k)
    cycles, seen = [], set()
    for start in nxt:
        path, node = [], start
        while node in nxt and node not in path:
            path.append(node)
            node = nxt[node]
        if node in path:
            cyc = path[path.index(node):]
            key = frozenset(cyc)
            if len(cyc) > 1 and key not in seen:
                seen.add(key)
                cycles.append(cyc)
    chains = {}
    for start in nxt:
        path, node = [start], nxt[start]
        while node in nxt and node not in path:
            path.append(node)
            node = nxt[node]
        chains[start] = path
    receptions = [c for c in cycles if len(c) == 2]
    return {"final": finals, "receptions": receptions, "cycles": cycles, "chains": chains}


def dominance(chart: dict, d: Doctrine) -> dict:
    """Персонализированный PageRank по графу: знак->управитель, дом->управитель дома,
    аспекты (взвешены силой). Телепортация ∝ вес тела × угловатость × достоинство."""
    pr = d.params["pagerank"]
    hcw = d.params["house_class_weight"]
    nodes = [b.code for b in d.bodies if chart["bodies"][b.code]["shown"]]
    idx = {c: i for i, c in enumerate(nodes)}
    n = len(nodes)
    adj = np.zeros((n, n))
    houses = chart.get("houses", {})
    for c in nodes:
        e = chart["bodies"][c]
        for ruler, _, rw in d.rulers.get(e["sign"], []):
            if ruler in idx:
                adj[idx[c], idx[ruler]] += pr["edge_sign_ruler"] * rw
        if "house" in e:
            for ruler, _, rw in d.rulers.get(houses[str(e["house"])]["sign"], []):
                if ruler in idx:
                    adj[idx[c], idx[ruler]] += pr["edge_house_ruler"] * rw
    for a in chart["aspects"]:
        if a["a"] in idx and a["b"] in idx:
            wgt = pr["edge_aspect"] * a["strength"] * d.aspect_by_code[a["aspect"]].weight
            adj[idx[a["a"]], idx[a["b"]]] += wgt
            adj[idx[a["b"]], idx[a["a"]]] += wgt
    tele = np.zeros(n)
    for c in nodes:
        e = chart["bodies"][c]
        ang = hcw[d.house_class(e["house"])] if "house" in e else 1.0
        dig = e.get("dignity", {}).get("score", 0.0)
        tele[idx[c]] = d.body(c).weight * ang * max(0.05, 1.0 + pr["dignity_coef"] * dig)
    tele /= tele.sum()
    rows = adj.sum(1, keepdims=True)
    T = np.where(rows > 0, adj / np.where(rows > 0, rows, 1), tele[None, :])
    r = tele.copy()
    for _ in range(int(pr["iters"])):
        r_new = (1 - pr["alpha"]) * tele + pr["alpha"] * (T.T @ r)
        if np.abs(r_new - r).sum() < 1e-12:
            r = r_new
            break
        r = r_new
    r /= r.sum()
    ranks = {c: round(float(r[idx[c]]), 5) for c in nodes}
    order = sorted(ranks, key=lambda k: -ranks[k])
    ch = {}
    for body, row in d.channels.items():
        if body in ranks:
            ch[int(row["channel"])] = ch.get(int(row["channel"]), 0.0) + ranks[body]
    tot = sum(ch.values()) or 1.0
    ch = {k: round(v / tot, 5) for k, v in sorted(ch.items())}
    return {"pagerank": ranks, "order": order, "channels": ch,
            "channels_order": sorted(ch, key=lambda k: -ch[k])}


def balance(chart: dict, d: Doctrine) -> dict:
    """Доли «массы» карты (PageRank) по стихиям и крестам — взвешено важностью, а не счётом планет."""
    pr = chart["dominance"]["pagerank"]
    el = {s["element"]: 0.0 for s in d.signs}
    mo = {s["modality"]: 0.0 for s in d.signs}
    for code, w in pr.items():
        s = d.sign_by_code[chart["bodies"][code]["sign"]]
        el[s["element"]] += w
        mo[s["modality"]] += w
    tot = sum(pr.values()) or 1.0
    return {"elements": {k: round(v / tot, 4) for k, v in el.items()},
            "modalities": {k: round(v / tot, 4) for k, v in mo.items()}}


def spectrum(chart: dict, d: Doctrine) -> dict:
    """Z_h = Σ w e^{ihθ}/Σw по планетам: |Z_1| — скученность (стеллиумы),
    |Z_3| — тригональная, |Z_4| — квадратурная когерентность карты."""
    ws, th = [], []
    for b in d.bodies:
        if b.kind == "planet":
            ws.append(b.weight)
            th.append(math.radians(chart["bodies"][b.code]["lon"]))
    ws, th = np.array(ws), np.array(th)
    out = {}
    for h in range(1, 13):
        z = (ws * np.exp(1j * h * th)).sum() / ws.sum()
        out[str(h)] = {"amp": round(float(abs(z)), 4),
                       "focus_deg": round(float((math.degrees(np.angle(z)) / h) % (360 / h)), 2)}
    return out


def stellia(chart: dict, d: Doctrine) -> list[dict]:
    m = int(d.params["stellium_min"])
    out = []
    for by in ("sign", "house"):
        groups: dict = {}
        for b in d.bodies:
            e = chart["bodies"][b.code]
            if b.kind == "planet" and by in e:
                groups.setdefault(e[by], []).append(b.code)
        out += [{"by": by, "key": k, "bodies": v} for k, v in groups.items() if len(v) >= m]
    return out
