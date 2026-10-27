"""Синтез карты без LLM: внутренние напряжения и сквозные темы.

Каждый текст корпуса размечен полюсами осей синтеза, к которым он тянет (payload.axes: [{axis, pole, s 1–3}]);
оси и пороги — параметры доктрины (synthesis_*). Для показанных в отчёте положений считается доля веса карты
на каждом полюсе: Σ заметность·s / Σ заметность всех положений с текстом (положения «фон поколения» — с пониженным
весом). Доля сравнивается с распределением по популяции случайных карт (stats.synthesis, scripts.synthesis_calibrate),
как скоры синастрии — с нулевой моделью.

  напряжение   — оба полюса оси сильнее, чем у synthesis_tension_pct% карт, или самая заметная пара текстов, прямо
                 тянущих в разные стороны (s ≥ 2), сильнее, чем у synthesis_pair_pct% карт (противоречие, которое
                 читатель увидит в соседних карточках); у каждой стороны есть отчётливое положение: synth:tension:<ось>.
                 Пороги — процентили по популяции, поэтому каждая ось срабатывает одинаково часто;
  сквозная тема — полюс сильнее, чем у synthesis_theme_pct% карт, противоположный не сильнее
                 synthesis_theme_opposite_pct%, и полюс подтверждают ≥ synthesis_min_theme_items НЕЗАВИСИМЫХ
                 свидетельств (правило свидетельств: положения об одной и той же планете — одно свидетельство,
                 как Сатурн в 1-м доме и Сатурн на Асценденте): карточка synth:theme:<ось>:<полюс>.
Текст, который сам описывает спор двух полюсов одной оси, в счёт этой оси не идёт: он уже синтез.
"""
from __future__ import annotations

from bisect import bisect_left
from fnmatch import fnmatchcase

from .doctrine import Doctrine
from .i18n import tr
from .rules import describe


def axes_of(d: Doctrine) -> list[dict]:
    return d.params.get("synthesis_axes", [])


def _texts(modules: list[dict], d: Doctrine):
    """(вес, заголовок, текст, карточка) для каждого показанного положения с текстом, включая собранные в группу.
    Закреплённые положения (Солнце, Луна, Асцендент — report_pinned) в традиции главные, а по PageRank знака
    их заметность бывает низкой, поэтому их вес не ниже synthesis_pinned_floor_pct-го процентиля весов отчёта."""
    p = d.params
    bg, bgw = p.get("report_background_module"), float(p.get("synthesis_background_weight", 1.0))
    pinned = list(p.get("report_pinned") or [])
    rows = []
    for m in modules:
        if m.get("code") == p.get("synthesis_module"):
            continue
        k = bgw if m.get("code") == bg else 1.0
        for it in m["items"]:
            if it.get("text"):
                rows.append((k, float(it.get("own_salience", it.get("salience", 0))), it["key"], it["title"], it["text"], it))
            for g in it.get("group") or []:      # пометка оси — на самом положении внутри группы, а не на её заголовке
                if g.get("text"):
                    rows.append((k, float(g.get("salience", 0)), g.get("key", ""), g["title"], g["text"], g))
    sal = sorted(r[1] for r in rows)
    floor = sal[min(len(sal) - 1, int(len(sal) * float(p.get("synthesis_pinned_floor_pct", 0)) / 100))] if sal else 0.0
    for k, w, key, title, text, card in rows:
        if any(fnmatchcase(key, pat) for pat in pinned):
            w = max(w, floor)
        yield k * w, title, text, card, key


def bodies_of(key: str, card: dict, chart: dict | None, d: Doctrine) -> frozenset:
    """о каких планетах (точках) положение: по ним свидетельства считаются независимыми или нет.
    Углы карты (Асцендент, MC) сами по себе свидетельства не сливают: знак Асцендента и планета на Асценденте —
    в традиции разные свидетельства, а Сатурн в 1-м доме и Сатурн на Асценденте — одно (тот же Сатурн)."""
    kind, *p = key.split(":")
    angles = {b.code for b in d.bodies if b.kind == "angle"}
    bs: set = set()
    if kind in ("sign", "house", "dignity", "final"):
        bs = {p[0]}
    elif kind == "aspect":
        bs = {p[0], p[2]}
    elif kind in ("reception", "dominant"):
        bs = {p[0], p[1]}
    elif kind == "ruler" and chart and p[0] in chart.get("houses", {}):
        r = d.primary_ruler(chart["houses"][p[0]]["sign"])
        bs = {r} if r else set()
    elif kind == "rule":
        bs = set(card.get("bodies") or [])
    planets = bs - angles
    return frozenset(planets or bs or {key})


def testimonies(items: list) -> list[list]:
    """свидетельства, сгруппированные в независимые: положения, у которых есть общая планета, — одно свидетельство"""
    groups: list[tuple[set, list]] = []
    for it in items:
        bs = set(it[4])
        hit = [g for g in groups if g[0] & bs]
        merged = (bs.union(*(g[0] for g in hit)), [x for g in hit for x in g[1]] + [it])
        groups = [g for g in groups if g not in hit] + [merged]
    return [sorted(g[1], key=lambda x: -x[0]) for g in groups]


def contributions(modules: list[dict], d: Doctrine, chart: dict | None = None) -> tuple[dict, float]:
    """{(ось, полюс): [(вклад, s, заголовок, карточка, планеты)]}, общий вес карты"""
    out: dict[tuple, list] = {}
    total = 0.0
    for w, title, text, card, key in _texts(modules, d):
        total += w
        tags = [t for t in text.get("axes") or [] if isinstance(t, dict)]
        both = {t["axis"] for t in tags if sum(1 for u in tags if u["axis"] == t["axis"]) > 1}
        for t in tags:
            if t["axis"] in both:
                continue
            out.setdefault((t["axis"], t["pole"]), []).append((w * int(t["s"]), int(t["s"]), title, card,
                                                                 bodies_of(key, card, chart, d)))
    return out, total


def _pair(contrib: dict, total: float, axis: str, poles: list[str]) -> float:
    """сила самой заметной пары противоречащих текстов: меньший из двух самых весомых отчётливых (s ≥ 2) вкладов сторон"""
    tops = [max((c[0] for c in contrib.get((axis, p), []) if c[1] >= 2), default=0.0) for p in poles]
    return min(tops) / total if total else 0.0


def shares(modules: list[dict], d: Doctrine) -> dict[str, dict[str, float]]:
    """доли полюсов и, под ключом "pair", сила самой заметной пары противоречащих текстов по оси"""
    contrib, total = contributions(modules, d)
    out = {}
    for ax in axes_of(d):
        poles = [pl["code"] for pl in ax["poles"]]
        out[ax["code"]] = {p: (sum(c[0] for c in contrib.get((ax["code"], p), [])) / total if total else 0.0) for p in poles}
        out[ax["code"]]["pair"] = _pair(contrib, total, ax["code"], poles)
    return out


def percentile(value: float, quantiles: list[float]) -> float:
    """место доли среди карт популяции, 0–100 (quantiles — 101 точка распределения)"""
    if not quantiles:
        return 0.0
    if value <= quantiles[0]:
        return 0.0
    return min(100.0, float(bisect_left(quantiles, value)) * 100.0 / (len(quantiles) - 1))


def synthesize(modules: list[dict], d: Doctrine, calibration: dict, content: dict, locale: str = "ru",
               chart: dict | None = None) -> list[dict]:
    """карточки синтеза для отчёта; положения, на которые они опираются, получают пометку оси"""
    p = d.params
    q = (calibration or {}).get("axes")
    if not q or not axes_of(d):
        return []
    contrib, total = contributions(modules, d, chart)
    if not total:
        return []
    t_ten, t_theme = float(p.get("synthesis_tension_pct", 70)), float(p.get("synthesis_theme_pct", 90))
    t_opp = float(p.get("synthesis_theme_opposite_pct", 50))
    t_pair = float(p.get("synthesis_pair_pct", 101))
    min_side, min_theme = int(p.get("synthesis_min_side_items", 1)), int(p.get("synthesis_min_theme_items", 3))
    per_side = int(p.get("synthesis_detail_per_side", 3))
    tensions, themes = [], []
    for ax in axes_of(d):
        a, b = (pl["code"] for pl in ax["poles"])
        side = {c: sorted(contrib.get((ax["code"], c), []), key=lambda x: -x[0]) for c in (a, b)}
        pct = {c: percentile(sum(x[0] for x in side[c]) / total, q.get(ax["code"], {}).get(c, [])) for c in (a, b)}
        strong = {c: sum(1 for x in side[c] if x[1] >= 2) for c in (a, b)}
        # напряжение: оба полюса сильны по карте в целом — или два заметных текста прямо тянут в разные стороны
        pair = percentile(_pair(contrib, total, ax["code"], [a, b]), q.get(ax["code"], {}).get("pair", []))
        if min(strong.values()) >= min_side and (min(pct.values()) >= t_ten or pair >= t_pair):
            tensions.append((max(min(pct.values()), pair), ax, side, None))
        for c, o in ((a, b), (b, a)):
            # сквозная тема — правило свидетельств: не меньше min_theme НЕЗАВИСИМЫХ свидетельств (разные планеты)
            if pct[c] >= t_theme and pct[o] <= t_opp and len(testimonies(side[c])) >= min_theme:
                themes.append((pct[c], ax, side, c))
    tensions.sort(key=lambda x: -x[0])
    themes.sort(key=lambda x: -x[0])
    chosen = tensions[:int(p.get("synthesis_max_tensions", 3))] + themes[:int(p.get("synthesis_max_themes", 2))]
    cards = []
    for score, ax, side, pole in chosen:
        lab = {pl["code"]: pl["label"].get(locale, pl["code"]) for pl in ax["poles"]}
        key = f"synth:tension:{ax['code']}" if pole is None else f"synth:theme:{ax['code']}:{pole}"
        names = lambda c: list(dict.fromkeys(x[2] for x in side[c]))[:per_side]
        if pole is None:
            detail = " · ".join(f"{lab[c].capitalize()}: " + ", ".join(names(c)) for c in lab)
            mark = f"↔ {ax['label'].get(locale, ax['code'])}"
            marked = [x[3] for c in lab for x in side[c][:per_side]]
        else:
            reps = [g[0] for g in sorted(testimonies(side[pole]), key=lambda g: -g[0][0])][:per_side]   # по одному от свидетельства
            detail = tr(d, locale, "synth_evidence", list=", ".join(x[2] for x in reps))
            mark = tr(d, locale, "synth_theme_mark", pole=lab[pole])
            marked = [x[3] for x in reps]
        for it in {id(c): c for c in marked}.values():
            if mark not in it.setdefault("tags", []):
                it["tags"].append(mark)
        cards.append({"key": key, "module": p.get("synthesis_module"), "salience": round(score, 1),
                      "title": describe(key, d, locale), "text": content.get(key), "detail": detail, "main": True})
    return cards
