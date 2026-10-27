"""Факты для брифов контента — считаются из эфемерид и доктрины, без ручных таблиц.

  sign_passage   — сколько тело проходит знак (с возвратами; typical — среднее, взвешенное длиной прохода,
                   т. е. сколько длится проход вокруг дня рождения) и, для медленных, периоды 1920–2030;
  aspect_episode — сколько аспект держится в орбисе (с петлями ретроградности) и как часто повторяется;
  freq           — доля карт случайной популяции, где ключ встречается;
  rule_bodies    — на каких телах держатся срабатывания правил (доля срабатываний);
  birth_years    — 5–95-й перцентили года рождения у карт с ключом;
  together       — ключи, которые стоят в том же отчёте в ≥ 60% случаев, с долей (рецепция и знак, достоинство и знак);
  variants       — какие варианты составного ключа реально встречаются (знаки, дома) и с какой долей.

python -m scripts.content_stats [--n 4000] [--out doctrine/stats/<code>.json]
"""
import argparse
import json
import os
import random
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import swisseph as swe

from astro.chart import build_chart
from astro.doctrine import load_yaml
from astro.ephemeris import BirthInput, _ensure_thread_init
from astro.rules import atomic_facts, match_rules

Y0, Y1 = 1920, 2031          # окно популяции и перечисляемых периодов
E0, E1 = 1880, 2071          # окно эфемерид шире, чтобы края периодов были настоящими
MERGE_GAP_DAYS = 250      # возвраты при ретроградности склеиваются в один проход/эпизод
SLOW_LIST_DAYS = 300      # периоды перечисляются для тел, которые идут по знаку дольше ~10 месяцев (даты в пометке отчёта)


def longitudes(d, jds):
    _ensure_thread_init()
    out = {}
    for b in d.bodies:
        if "se" in b.source:
            out[b.code] = np.array([swe.calc_ut(j, int(b.source["se"]), swe.FLG_SWIEPH)[0][0] for j in jds])
    for b in d.bodies:
        if "offset_of" in b.source:
            out[b.code] = (out[b.source["offset_of"]] + float(b.source["deg"])) % 360
    return out


def runs(mask, step, merge_gap):
    """непрерывные участки True (в днях), с объединением разрывов короче merge_gap"""
    idx = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
    seg = list(zip(idx[::2], idx[1::2]))
    merged = []
    for a, b in seg:
        if merged and (a - merged[-1][1]) * step < merge_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def ymd(jd):
    y, m, _, _ = swe.revjul(jd)
    return f"{m:02d}.{y}"


def ephem_stats(d):
    signs = [s["code"] for s in d.signs]
    day = np.arange(swe.julday(E0, 1, 1), swe.julday(E1, 1, 1), 1.0)
    w0, w1 = swe.julday(Y0, 1, 1), swe.julday(Y1, 1, 1)
    inside = lambda a, b, jd: jd[min(b, len(jd) - 1)] >= w0 and jd[a] < w1
    fine = np.arange(swe.julday(2000, 1, 1), swe.julday(2004, 1, 1), 1 / 12)   # шаг 2 ч для Луны
    L, Lf = longitudes(d, day), longitudes(d, fine)
    fast = {c for c in L if np.median(np.abs(np.diff(np.unwrap(np.radians(L[c]))))) > np.radians(5)}  # Луна
    passage, episode = {}, {}
    for c in L:
        lon, jd, step = (Lf[c], fine, 1 / 12) if c in fast else (L[c], day, 1.0)
        sidx = (lon // 30).astype(int)
        for k, s in enumerate(signs):
            rs = runs(sidx == k, step, MERGE_GAP_DAYS if c not in fast else 0)
            if not rs:
                continue
            lens = [(b - a) * step for a, b in rs]
            ln = np.array(lens)
            rec = {"typical_days": round(float((ln ** 2).sum() / ln.sum()), 1), "median_days": round(float(np.median(ln)), 1)}
            if np.median(lens) >= SLOW_LIST_DAYS:
                rec["periods"] = [[ymd(jd[a]), ymd(jd[min(b, len(jd) - 1)])] for a, b in rs
                                  if inside(a, b, jd) and a > 0 and b < len(jd)]
            passage[f"{c}:{s}"] = rec
    excl = {frozenset(x) for x in d.params.get("aspect_exclude_pairs", [])}
    codes = [b.code for b in d.bodies if b.code in L]
    for a, b in combinations(codes, 2):
        if frozenset((a, b)) in excl:
            continue
        use_fine = a in fast or b in fast
        la, lb, step = (Lf[a], Lf[b], 1 / 12) if use_fine else (L[a], L[b], 1.0)
        span = (len(la) * step)
        phase = (la - lb) % 360
        bounded = np.abs(((phase + 180) % 360) - 180).max() < 90   # Меркурий/Венера у Солнца: колебание, не петли
        for asp in d.aspects:
            lens, starts, long_eps = [], [], []
            for target in sorted({asp.angle_deg % 360, (360 - asp.angle_deg) % 360}):
                dev = np.abs(((phase - target + 180) % 360) - 180)
                raw = runs(dev <= asp.orb_deg, step, 0)
                ep = []
                for x, y in raw:   # петля ретроградности: между проходами отклонение не уходит дальше 2.5 орбиса
                    if ep and not use_fine and not bounded and (x - ep[-1][1]) * step <= 600 and dev[ep[-1][1]:x].max() <= 2.5 * asp.orb_deg:
                        ep[-1][1] = y
                    else:
                        ep.append([x, y])
                lens += [(y - x) * step for x, y in ep]
                starts += [x * step for x, _ in ep]
                if not use_fine:
                    long_eps += [(x, y) for x, y in ep if (y - x) >= 365 and inside(x, y, day) and x > 0 and y < len(day)]
            if not lens:
                continue
            st = np.sort(np.array(starts))
            ln = np.array(lens)
            episode[f"{a}:{asp.code}:{b}"] = {          # типичная длительность для родившегося в аспекте:
                "typical_days": round(float((ln ** 2).sum() / ln.sum()), 2),   # среднее, взвешенное длиной
                "median_days": round(float(np.median(ln)), 2),
                "recur_days": round(float(np.median(np.diff(st))), 1) if len(st) > 2 else round(span, 0)}
            if long_eps and float((ln ** 2).sum() / ln.sum()) >= 365:
                episode[f"{a}:{asp.code}:{b}"]["periods"] = [[ymd(day[x]), ymd(day[y - 1])] for x, y in sorted(long_eps)]
    return passage, episode


def population(d, n, seed):
    rng = random.Random(seed)
    freq, rule_b, rule_n = Counter(), defaultdict(Counter), Counter()
    years, pair, variants = defaultdict(list), Counter(), defaultdict(Counter)
    for _ in range(n):
        y = rng.randint(Y0, Y1 - 1)
        c = build_chart(BirthInput(f"{y}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                                   f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}", "UTC",
                                   rng.uniform(-45, 62), rng.uniform(-180, 180)), d)
        B = c["bodies"]
        keys = {f["key"] for f in atomic_facts(c, d)}
        hits, _ = match_rules(c, d)
        for h in hits:
            keys.add(h["key"])
            rule_n[h["key"]] += 1
            rule_b[h["key"]].update(set(h.get("bodies", [])))
            hs = sorted({B[b]["house"] for b in h.get("bodies", []) if "house" in B[b]})
            variants[h["key"]]["дом " + "/".join(map(str, hs)) if hs else "—"] += 1
        for k in keys:
            kind, *p = k.split(":")
            if kind == "dignity":
                variants[k][B[p[0]]["sign"]] += 1
            elif kind == "reception":
                variants[k][f"{B[p[0]]['sign']}|{B[p[1]]['sign']}"] += 1
            years[k].append(y)
        ks = sorted(keys)
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                pair[(a, b)] += 1
        freq.update(keys)
    together = defaultdict(dict)       # ключи, которые часто (≥ 60%) или всегда (≥ 90%) стоят в том же отчёте
    for (a, b), m in pair.items():
        if m >= 20:
            if m / freq[a] >= 0.6:
                together[a][b] = round(m / freq[a], 2)
            if m / freq[b] >= 0.6:
                together[b][a] = round(m / freq[b], 2)
    yr = {k: [int(np.percentile(v, 5)), int(np.percentile(v, 95))] for k, v in years.items() if len(v) >= 10}
    var = {k: {x: round(m / sum(cnt.values()), 3) for x, m in cnt.most_common()} for k, cnt in variants.items()}
    return ({k: round(v / n, 4) for k, v in freq.items()},
            {k: {b: round(v / rule_n[k], 3) for b, v in cnt.most_common()} for k, cnt in rule_b.items()},
            yr, {k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in together.items()}, var)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out")
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    out = a.out or os.path.join(os.path.dirname(a.doctrine), "stats", f"{d.code}.json")
    passage, episode = ephem_stats(d)
    freq, rule_bodies, birth_years, together, variants = population(d, a.n, a.seed)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"doctrine": d.code, "years": [Y0, Y1 - 1], "population": a.n, "sign_passage": passage,
               "aspect_episode": episode, "freq": freq, "rule_bodies": rule_bodies,
               "birth_years": birth_years, "together": together, "variants": variants},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
    print(f"{out}: passages {len(passage)}, aspect episodes {len(episode)}, keys seen {len(freq)}")


if __name__ == "__main__":
    main()
