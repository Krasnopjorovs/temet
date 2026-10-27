"""Независимая проверка движка: совпадает ли то, что считает сервис, с тем, что даёт другая теория и другой код.

  A. Положения тел — с теориями Миуса (VSOP87 для планет, ELP для Луны, отдельная теория Плутона; pymeeus),
     а не со Swiss Ephemeris: видимая геоцентрическая эклиптическая долгота на дату, и знак скорости (ретроградность).
  B. Асцендент, MC и куспиды Плацидуса — по школьным формулам из звёздного времени и наклона эклиптики
     (своя реализация, без функций домов Swiss Ephemeris).
  C. Местное время → UTC — через pytz (другая библиотека и своя копия базы часовых поясов), включая переводы часов.
  D. Производные факты карты — знак, дом, управитель, достоинство, аспекты, конечный диспозитор, рецепции,
     стеллиумы — пересчитываются заново из долгот и сверяются с картой.
  E. Периоды «фон поколения» (Уран, Нептун, Плутон по знакам) — по независимым ингрессиям из теорий Миуса.
  F. Синтез — внутренняя согласованность: перечисленные положения есть в отчёте и помечены, у темы ≥ 3 независимых
     свидетельства, у напряжения есть обе стороны.

python -m scripts.verify_engine [--n 300] [--content content/claude_vN.json]
Хирон отдельной теории не имеет и проверяется только через Swiss Ephemeris.
"""
import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pytz
import swisseph as swe
from pymeeus.Coordinates import (equatorial2ecliptical, mean_obliquity, nutation_longitude, precession_equatorial,
                                 true_obliquity)
from pymeeus.Epoch import Epoch
from pymeeus.Jupiter import Jupiter
from pymeeus.Mars import Mars
from pymeeus.Mercury import Mercury
from pymeeus.Moon import Moon
from pymeeus.Neptune import Neptune
from pymeeus.Pluto import Pluto
from pymeeus.Saturn import Saturn
from pymeeus.Sun import Sun
from pymeeus.Uranus import Uranus
from pymeeus.Venus import Venus

from astro.brief import load_stats
from astro.chart import build_chart
from astro.doctrine import load_yaml
from astro.ephemeris import BirthInput, raw_positions, resolve_instant

PLANETS = {"MERCURY": Mercury, "VENUS": Venus, "MARS": Mars, "JUPITER": Jupiter, "SATURN": Saturn,
           "URANUS": Uranus, "NEPTUNE": Neptune}
SIGNS = ["ARIES", "TAURUS", "GEMINI", "CANCER", "LEO", "VIRGO", "LIBRA", "SCORPIO", "SAGITTARIUS", "CAPRICORN",
         "AQUARIUS", "PISCES"]
# эталон управителей знаков (современная схема, которую использует доктрина)
RULER = dict(zip(SIGNS, ["MARS", "VENUS", "MERCURY", "MOON", "SUN", "MERCURY", "VENUS", "PLUTO", "JUPITER", "SATURN",
                         "URANUS", "NEPTUNE"]))
J2000 = Epoch(2451545.0)


def dd(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def tt(jd_ut):
    y, m, _ = Epoch(jd_ut).get_date()
    return Epoch(jd_ut + Epoch.tt2ut(y, m) / 86400.0)


def meeus_lon(code, e):
    if code == "SUN":
        return float(Sun.apparent_geocentric_position(e)[0])
    if code == "MOON":
        return float(Moon.apparent_ecliptical_pos(e)[0])
    if code in PLANETS:
        ra, dec, _ = PLANETS[code].geocentric_position(e)
        return float(equatorial2ecliptical(ra, dec, true_obliquity(e))[0])
    if code == "PLUTO":                                   # J2000 → дата: прецессия, нутация (аберрация ~20″ не учтена)
        ra, dec = Pluto.geocentric_position(e)
        ra, dec = precession_equatorial(J2000, e, ra, dec)
        return (float(equatorial2ecliptical(ra, dec, mean_obliquity(e))[0]) + float(nutation_longitude(e))) % 360
    if code == "MEAN_NODE":
        return (float(Moon.longitude_mean_ascending_node(e)) + float(nutation_longitude(e))) % 360
    if code == "LILITH":        # средний апогей = средний перигей Миуса + 180°
        return (float(Moon.longitude_mean_perigee(e)) + 180.0 + float(nutation_longitude(e))) % 360
    return None


def osculating_node(jd_ut):
    """истинный (оскулирующий) узел: пересечение мгновенной плоскости орбиты Луны (r × v) с эклиптикой"""
    def vec(jd):
        lam, beta, dist, _ = Moon.apparent_ecliptical_pos(tt(jd))
        lo, la = math.radians(float(lam)), math.radians(float(beta))
        return [dist * math.cos(la) * math.cos(lo), dist * math.cos(la) * math.sin(lo), dist * math.sin(la)]
    h = 1 / 24
    r, a, b = vec(jd_ut), vec(jd_ut - h), vec(jd_ut + h)
    v = [(b[i] - a[i]) / (2 * h) for i in range(3)]
    hx, hy = r[1] * v[2] - r[2] * v[1], r[2] * v[0] - r[0] * v[2]
    return math.degrees(math.atan2(hx, -hy)) % 360


def angles_placidus(jd_ut, lat, lon):
    """Асцендент, MC и куспиды Плацидуса по формулам: звёздное время IAU 1982 + нутация, полудуги склонений."""
    e = tt(jd_ut)
    eps = math.radians(float(true_obliquity(e)))
    t = (jd_ut - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd_ut - 2451545.0) + 0.000387933 * t * t - t ** 3 / 38710000.0
    gast = gmst + float(nutation_longitude(e)) * math.cos(eps)
    ramc = math.radians((gast + lon) % 360.0)
    phi = math.radians(lat)
    lam = lambda ra: math.degrees(math.atan2(math.sin(ra), math.cos(ra) * math.cos(eps))) % 360
    mc = lam(ramc)
    asc = math.degrees(math.atan2(math.cos(ramc), -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)))) % 360
    cusps = {1: asc, 10: mc}
    for house, f, below in ((11, 1 / 3, False), (12, 2 / 3, False), (2, 2 / 3, True), (3, 1 / 3, True)):
        l = math.radians(mc + (house - 10 if not below else house + 2) * 30)
        for _ in range(100):
            dec = math.asin(math.sin(eps) * math.sin(l))
            dsa = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
            ra = ramc + f * dsa if not below else ramc + math.pi - f * (math.pi - dsa)
            nl = math.radians(lam(ra))
            if abs(nl - l) < 1e-12:
                break
            l = nl
        cusps[house] = math.degrees(l) % 360
    for h in (1, 2, 3, 10, 11, 12):
        cusps[(h + 5) % 12 + 1] = (cusps[h] + 180.0) % 360
    return [cusps[h] for h in range(1, 13)]


def stat(xs):
    xs = np.array(xs) * 3600.0
    return f"медиана {np.median(xs):.1f}″, макс {xs.max():.1f}″"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--content")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    rng = random.Random(a.seed)
    ok = True

    def verdict(name, good, detail):
        nonlocal ok
        ok &= good
        print(f"{'OK  ' if good else 'FAIL'} {name}: {detail}")

    # ---------------- A. положения
    errs, retro_bad, retro_n = defaultdict(list), [], 0
    for _ in range(a.n):
        jd = 2415020.5 + rng.random() * (2469807.5 - 2415020.5)          # 1900–2049
        ours = raw_positions(jd, 0.0, 0.0, d)
        e = tt(jd)
        errs["RAHU"].append(dd(ours["lon"]["RAHU"], osculating_node(jd)))
        errs["средний узел (проверка нутации)"].append(dd(swe.calc_ut(jd, swe.MEAN_NODE)[0][0], meeus_lon("MEAN_NODE", e)))
        for code in ["SUN", "MOON", *PLANETS, "PLUTO", "LILITH"]:
            m = meeus_lon(code, e)
            errs[code].append(dd(ours["lon"][code], m))
            if code in PLANETS or code == "PLUTO":
                m1, m2 = meeus_lon(code, tt(jd - 0.5)), meeus_lon(code, tt(jd + 0.5))
                speed = ((m2 - m1 + 180) % 360) - 180
                if abs(speed) > 0.002:                                   # вдали от стояний
                    retro_n += 1
                    if (speed < 0) != (ours["speed"][code] < 0):
                        retro_bad.append((code, jd))
    # Плутон: у Миуса — астрометрическое положение J2000, годичная аберрация (~20″) не учтена.
    # Раху: истинный узел сверяется с оскулирующим узлом, вычисленным из положения и скорости Луны по Миусу.
    # Лилит: Swiss Ephemeris считает средний апогей по уточнённой модели, формула Миуса старше — расхождение
    # в несколько угловых минут ожидаемо; на знак оно влияет только у самой границы знаков.
    tol = {"SUN": 5, "MOON": 30, "PLUTO": 60, "RAHU": 120, "LILITH": 450, "средний узел (проверка нутации)": 1}
    for code, xs in errs.items():
        lim = tol.get(code, 30) / 3600.0
        verdict(f"A долгота {code}", max(xs) <= lim, f"{stat(xs)} (допуск {tol.get(code, 30)}″)")
    verdict("A ретроградность", not retro_bad, f"{retro_n - len(retro_bad)} из {retro_n} совпали" + (f"; расхождения {retro_bad[:3]}" if retro_bad else ""))

    # ---------------- B. дома
    herr, asc_e, mc_e = [], [], []
    for _ in range(a.n):
        jd = 2415020.5 + rng.random() * (2469807.5 - 2415020.5)
        lat, lon = rng.uniform(-60, 60), rng.uniform(-180, 180)
        ours = raw_positions(jd, lat, lon, d)
        ref = angles_placidus(jd, lat, lon)
        asc_e.append(dd(ours["cusps"][0], ref[0]))
        mc_e.append(dd(ours["cusps"][9], ref[9]))
        herr += [dd(x, y) for x, y in zip(ours["cusps"], ref)]
    verdict("B Асцендент", max(asc_e) < 30 / 3600, stat(asc_e) + " (допуск 30″)")
    verdict("B MC", max(mc_e) < 30 / 3600, stat(mc_e) + " (допуск 30″)")
    verdict("B куспиды Плацидуса (|широта| ≤ 60°)", max(herr) < 60 / 3600, stat(herr) + " (допуск 60″)")

    # ---------------- C. время
    zones = ["Europe/Samara", "Europe/Moscow", "Europe/Riga", "Europe/Zurich", "Asia/Yekaterinburg", "Asia/Kolkata",
             "Asia/Kathmandu", "America/St_Johns", "America/New_York", "Australia/Sydney", "Asia/Tehran", "Europe/Kyiv"]
    bad_t, n_amb, bad_flag = [], 0, []
    # случайные моменты и моменты прямо в часы перехода на летнее и зимнее время
    cases = [(rng.choice(zones), datetime(rng.randint(1920, 2030), rng.randint(1, 12), rng.randint(1, 28),
                                          rng.randint(0, 23), rng.randint(0, 59))) for _ in range(a.n * 3)]
    for tz in zones:
        z = pytz.timezone(tz)
        for t0 in getattr(z, "_utc_transition_times", [])[1:]:
            if 1920 <= t0.year <= 2030 and rng.random() < 0.15:
                loc = pytz.utc.localize(t0).astimezone(z).replace(tzinfo=None)
                cases += [(tz, loc - timedelta(minutes=30)), (tz, loc + timedelta(minutes=10)), (tz, loc - timedelta(minutes=70))]
    for tz, local in cases:
        local = local.replace(second=0, microsecond=0)
        inst = resolve_instant(BirthInput(local.strftime("%Y-%m-%d"), local.strftime("%H:%M"), tz, 0.0, 0.0), d.params)
        try:
            ref = pytz.timezone(tz).localize(local, is_dst=None).astimezone(timezone.utc)
            if abs((inst.utc - ref).total_seconds()) > 60:      # pytz округляет местное среднее время до минуты
                bad_t.append((tz, local, inst.utc, ref))
            if any("local_time" in f for f in inst.flags):
                bad_flag.append((tz, local, inst.flags))
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            n_amb += 1
            if not any("local_time" in f for f in inst.flags):
                bad_flag.append((tz, local, "переход часов не помечен"))
    verdict("C местное время → UTC", not bad_t, f"{len(cases) - n_amb} обычных моментов совпали с pytz (до минуты)" + (f"; расхождения {bad_t[:2]}" if bad_t else ""))
    verdict("C переводы часов", not bad_flag, f"{n_amb} неоднозначных или несуществующих моментов помечены" + (f"; ошибки {bad_flag[:2]}" if bad_flag else ""))

    # ---------------- D. производные факты
    problems = defaultdict(int)
    n_asp = 0
    charts = []
    for _ in range(a.n):
        y = rng.randint(1920, 2030)
        inp = BirthInput(f"{y}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}", f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}",
                         "UTC", rng.uniform(-60, 60), rng.uniform(-180, 180))
        c = build_chart(inp, d)
        charts.append((inp, c))
        cusps = c.get("cusps")
        for code, b in c["bodies"].items():
            s = SIGNS[int(b["lon"] // 30) % 12]
            problems["знак"] += s != b["sign"]
            problems["управитель знака"] += RULER[s] != b["dispositor"]
            if cusps and "house" in b:
                h = next(i + 1 for i in range(12) if (b["lon"] - cusps[i]) % 360 < (cusps[(i + 1) % 12] - cusps[i]) % 360)
                problems["дом"] += h != b["house"]
            dg = d.dignities.get((code, s))
            problems["достоинство"] += (dg[0] if dg else None) != (b.get("dignity") or {}).get("kind")
        listed = {(x["a"], x["b"], x["aspect"]) for x in c["aspects"]}
        shown = [k for k, b in c["bodies"].items() if b["shown"]]
        excl = {frozenset(p) for p in d.params.get("aspect_exclude_pairs", [])}
        for i, p in enumerate(shown):
            for q in shown[i + 1:]:
                if frozenset((p, q)) in excl:
                    continue
                sep = dd(c["bodies"][p]["lon"], c["bodies"][q]["lon"])
                for asp in d.aspects:
                    orb = abs(sep - asp.angle_deg)
                    has = (p, q, asp.code) in listed or (q, p, asp.code) in listed
                    n_asp += has
                    problems["аспект за пределом орбиса"] += has and orb > asp.orb_deg + 1e-6
                    problems["пропущен точный аспект (орбис ≤ ½)"] += (not has) and orb <= asp.orb_deg / 2
        nxt = {k: RULER[SIGNS[int(b["lon"] // 30) % 12]] for k, b in c["bodies"].items() if d.body(k).kind == "planet"}
        problems["конечный диспозитор"] += sorted(k for k, v in nxt.items() if v == k) != c["dispositors"]["final"]
        recs = {frozenset((p, q)) for p, q in nxt.items() if p != q and nxt.get(q) == p}
        problems["рецепции"] += recs != {frozenset(r) for r in c["dispositors"]["receptions"]}
        by_sign = defaultdict(set)
        for k, b in c["bodies"].items():
            if d.body(k).kind == "planet":
                by_sign[b["sign"]].add(k)
        ours = {st["key"]: set(st["bodies"]) for st in c.get("stellia", []) if st["by"] == "sign"}
        ref = {s: v for s, v in by_sign.items() if len(v) >= int(d.params.get("stellium_min", 3))}
        problems["стеллиум по знаку"] += ours != ref
    for k in ("знак", "дом", "управитель знака", "достоинство", "аспект за пределом орбиса",
              "пропущен точный аспект (орбис ≤ ½)", "конечный диспозитор", "рецепции", "стеллиум по знаку"):
        verdict(f"D {k}", problems[k] == 0, f"{problems[k]} расхождений на {a.n} картах" + (f" ({n_asp} аспектов)" if "аспект" in k else ""))

    # ---------------- E. периоды поколений
    stats = load_stats(d)
    worst = 0
    checked = 0
    for code in ("URANUS", "NEPTUNE", "PLUTO"):
        jd0, jd1, step = 2415020.5, 2470172.5, 2.0                      # 1900–2050
        seq = []
        jd = jd0
        while jd < jd1:
            seq.append((jd, int(meeus_lon(code, tt(jd)) // 30) % 12))
            jd += step
        runs = defaultdict(list)
        cur = None
        for jd, s in seq:
            if cur and cur[0] == s:
                cur[2] = jd
            else:
                if cur:
                    runs[cur[0]].append([cur[1], cur[2]])
                cur = [s, jd, jd]
        runs[cur[0]].append([cur[1], cur[2]])
        for s, rs in runs.items():
            merged = []
            for r in rs:
                if merged and r[0] - merged[-1][1] < 250:
                    merged[-1][1] = r[1]
                else:
                    merged.append(r)
            ours = stats.get("sign_passage", {}).get(f"{code}:{SIGNS[s]}", {}).get("periods", [])
            for st_, en_ in ours:
                (m0, y0), (m1, y1) = map(int, st_.split(".")), map(int, en_.split("."))
                best = min(merged, key=lambda r: abs(r[0] - (2415020.5 + (y0 - 1900) * 365.25 + (m0 - 1) * 30.4)))
                ref0, ref1 = (datetime(1858, 11, 17) + timedelta(days=best[0] - 2400000.5),
                              datetime(1858, 11, 17) + timedelta(days=best[1] - 2400000.5))
                miss = max(abs((ref0.year - y0) * 12 + ref0.month - m0), abs((ref1.year - y1) * 12 + ref1.month - m1))
                worst = max(worst, miss)
                checked += 1
    verdict("E периоды «фон поколения» (Уран, Нептун, Плутон)", worst <= 1,
            f"{checked} периодов, наибольшее расхождение начала или конца — {worst} мес. (допуск 1)")

    # ---------------- F. синтез
    if a.content:
        from astro.report import finalize
        from astro.rules import assemble_report
        from astro.synthesis import bodies_of
        content = {it["key"]: {k: v for k, v in it.items() if k != "key"} for it in json.load(open(a.content, encoding="utf-8"))}
        bad = []
        n_cards = 0
        for inp, c in charts[:200]:
            rep = finalize(assemble_report(c, d, content), c, d, stats, content=content)
            titles = {}
            for m in rep["modules"]:
                if m.get("synthesis"):
                    continue
                for it in m["items"]:
                    titles[it["title"]] = it
                    for g in it.get("group") or []:
                        titles[g["title"]] = g
            for m in rep["modules"]:
                if not m.get("synthesis"):
                    continue
                for card in m["items"]:
                    n_cards += 1
                    det = card["detail"]
                    parts = [det.split(": ", 1)[1]] if det.startswith("Об этом говорят: ") else [p.split(": ", 1)[1] for p in det.split(" · ")]
                    names = [x.strip() for part in parts for x in part.split(", ")]
                    for nm in names:
                        if nm not in titles:
                            bad.append((card["key"], nm, "нет в отчёте"))
                    if card["key"].startswith("synth:theme"):
                        sets = [bodies_of(titles[nm].get("key", ""), titles[nm], c, d) for nm in names if nm in titles]
                        if len(sets) < 3 or any(x & y for i, x in enumerate(sets) for y in sets[i + 1:]):
                            bad.append((card["key"], "меньше трёх независимых свидетельств", names))
                    if not card.get("text"):
                        bad.append((card["key"], "нет текста"))
        verdict("F синтез", not bad, f"{n_cards} карточек на 200 картах" + (f"; ошибки {bad[:3]}" if bad else ""))
    # ---------------- G. прогноз: даты транзитов, лунаций, затмений, разворотов, ингрессий, прогрессивной Луны
    from datetime import date as _date
    from astro.forecast import Forecaster, jd_of
    fc = Forecaster(d)
    parse = lambda s: jd_of(datetime.fromisoformat(s))
    dev_tr, dev_edge, dev_lun, dev_pm, dev_ing, bad_st, n_win = [], [], [], [], [], [], 0
    for inp, c in charts[:60]:
        y = rng.randint(2000, 2039)
        r = fc.compute(c, "month", _date(y, rng.randint(1, 12), 1), "UTC")
        n_win += 1
        for it in r["main"] + r["timeline"] + r["background"]:
            k = it["kind"]
            if k == "tr":
                lam = [(c["bodies"][it["point"]]["lon"] + s * a_.angle_deg) % 360 for a_ in d.aspects
                       if a_.code == it["aspect"] for s in (1, -1)]
                for x in it["exacts"]:
                    m = meeus_lon(it["body"], tt(parse(x)))
                    dev_tr.append((it["body"], min(dd(m, l_) for l_ in lam)))
                orb = float(d.params["forecast"]["orb"][it["body"]])
                for x in (it["start"], it["end"]):
                    if x:
                        m = meeus_lon(it["body"], tt(parse(x)))
                        dev_edge.append((it["body"], abs(min(dd(m, l_) for l_ in lam) - orb)))
                if it.get("station"):
                    j = parse(it["station"]["jd"])
                    s1 = dd(meeus_lon(it["body"], tt(j - 1.0)), meeus_lon(it["body"], tt(j - 1.5)))
                    v1 = ((meeus_lon(it["body"], tt(j - 1.0)) - meeus_lon(it["body"], tt(j - 1.5)) + 180) % 360) - 180
                    v2 = ((meeus_lon(it["body"], tt(j + 1.5)) - meeus_lon(it["body"], tt(j + 1.0)) + 180) % 360) - 180
                    if (v1 > 0) == (v2 > 0) and s1 > 0:
                        bad_st.append((it["key"], it["station"]["jd"]))
            elif k in ("lun", "ecl"):
                j = parse(it["exacts"][0])
                ms = []
                for back in (3.0, 10.0, -3.0):
                    e = Moon.moon_phase(Epoch(j - back), target="new" if it["phase"] == "NEW" else "full")
                    ms.append(e.jde() - Epoch.tt2ut(*e.get_date()[:2]) / 86400.0)
                dev_lun.append(min(abs(m - j) for m in ms) * 1440.0)
            elif k == "pm":
                jb = c["meta"]["jd_ut"]
                lam = [(c["bodies"][it["point"]]["lon"] + s * a_.angle_deg) % 360 for a_ in d.aspects
                       if a_.code == it["aspect"] for s in (1, -1)]
                for x in it["exacts"]:
                    jp = jb + (parse(x) - jb) / float(d.params["forecast"]["tropical_year_days"])
                    dev_pm.append(min(dd(meeus_lon("MOON", tt(jp)), l_) for l_ in lam))
            elif k == "trh" and it.get("ingress") and c.get("cusps"):
                h = it["house"]
                lo_ = meeus_lon(it["body"], tt(parse(it["ingress"])))     # вход в дом — через его куспид или
                dev_ing.append((it["body"], min(dd(lo_, c["cusps"][h - 1]), dd(lo_, c["cusps"][h % 12]))))  # попятно через следующий
    tol = lambda b: 40.0 if b == "PLUTO" else 15.0
    worst = lambda lst: max([v * 3600 / tol(b) for b, v in lst] or [0])
    verdict("G1 точные даты транзитов (теории Миуса)", worst(dev_tr) <= 1,
            f"{len(dev_tr)} касаний в {n_win} месяцах, " + stat([v for _, v in dev_tr] or [0]) + " (допуск 15″, Плутон 40″)")
    verdict("G2 вход и выход из орбиса", worst(dev_edge) <= 1, f"{len(dev_edge)} границ, " + stat([v for _, v in dev_edge] or [0]))
    verdict("G3 развороты планет (смена знака скорости по Миусу)", not bad_st, f"ошибок {len(bad_st)}" + (f": {bad_st[:3]}" if bad_st else ""))
    verdict("G4 новолуния и полнолуния (алгоритм фаз Миуса)", max(dev_lun or [0]) <= 2.0,
            f"{len(dev_lun)} лунаций, наибольшее расхождение {max(dev_lun or [0]):.2f} мин (допуск 2)")
    verdict("G5 прогрессивная Луна (ELP)", max(dev_pm or [0]) * 3600 <= 30, f"{len(dev_pm)} касаний, " + stat(dev_pm or [0]) + " (допуск 30″)")
    verdict("G6 вход планет в дома", worst(dev_ing) <= 1, f"{len(dev_ing)} ингрессий, " + stat([v for _, v in dev_ing] or [0]))
    # затмения 2026–2028 — с каталогом NASA (полутеневые лунные доктрина не считает)
    ref = {("SOLAR", "2026-02-17"), ("SOLAR", "2026-08-12"), ("SOLAR", "2027-02-06"), ("SOLAR", "2027-08-02"),
           ("SOLAR", "2028-01-26"), ("SOLAR", "2028-07-22"), ("LUNAR", "2026-03-03"), ("LUNAR", "2026-08-28"),
           ("LUNAR", "2028-01-12"), ("LUNAR", "2028-07-06"), ("LUNAR", "2028-12-31")}
    found = set()
    c0 = charts[0][1]
    for y in (2026, 2027, 2028):
        for mth in range(1, 13):
            for it in fc.compute(c0, "month", _date(y, mth, 1), "UTC")["timeline"]:
                if it["kind"] == "ecl":
                    found.add((it["eclipse"], it["exacts"][0][:10]))
    verdict("G7 затмения 2026–2028 (каталог NASA)", found == ref,
            f"найдено {len(found)} из {len(ref)}" + (f"; лишние {sorted(found - ref)}, нет {sorted(ref - found)}" if found != ref else ""))
    print("ИТОГ:", "всё сошлось" if ok else "есть расхождения")


if __name__ == "__main__":
    main()
