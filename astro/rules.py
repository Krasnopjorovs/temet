"""Факты карты, DSL составных правил и сборка отчёта.

Атомарные факты (ключи) порождаются из карты автоматически:
  sign:BODY:SIGN · house:BODY:H · aspect:B1:ASP:B2 · dignity:BODY:KIND ·
  ruler:H:in:H2 (управитель дома H в доме H2) · channel_top:N · final:BODY · reception:B1:B2
У каждого факта есть заметность (salience) из PageRank/силы аспекта/угловатости —
отчёт ранжирует факты, а не вываливает всё подряд.

Составные правила — нечёткие предикаты (сила 0..1), хранятся в БД как JSON:
  all (min) · any (max) · not · in_sign · in_house · aspect · dignity · dominant ·
  channel · stellium · spectrum.  Ссылки на тела: "VENUS", {"ruler_of_house": 2},
  {"dispositor": <ref>}.  Одинаковый concept выводится один раз.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from itertools import combinations

from .doctrine import Doctrine
from .forecast import describe_forecast_key, forecast_keys
from .i18n import fmt


class NeedsTime(Exception):
    pass


# ------------------------------------------------------------------ refs
def resolve_ref(ref, chart: dict, d: Doctrine) -> str | None:
    if isinstance(ref, str):
        return ref
    if "ruler_of_house" in ref:
        if not chart["meta"]["time_known"]:
            raise NeedsTime()
        sign = chart["houses"][str(ref["ruler_of_house"])]["sign"]
        return d.primary_ruler(sign)
    if "dispositor" in ref:
        body = resolve_ref(ref["dispositor"], chart, d)
        return chart["bodies"][body]["dispositor"]
    raise ValueError(f"unknown ref {ref}")


def _body(chart, code):
    e = chart["bodies"].get(code)
    if e is None or not e["shown"]:
        raise NeedsTime()
    return e


# ------------------------------------------------------------------ predicates
def evaluate(cond: dict, chart: dict, d: Doctrine) -> tuple[float, set[str]]:
    """-> (сила 0..1, тела, на которых держится срабатывание)."""
    (op, arg), = cond.items()
    if op == "all":
        res = [evaluate(c, chart, d) for c in arg]
        return min(s for s, _ in res), set().union(*(b for _, b in res))
    if op == "any":
        res = []
        for c in arg:
            try:
                res.append(evaluate(c, chart, d))
            except NeedsTime:
                continue
        if not res:
            raise NeedsTime()
        return max(res, key=lambda r: r[0])
    if op == "not":
        s, b = evaluate(arg, chart, d)
        return 1.0 - s, b
    if op == "in_sign":
        body = resolve_ref(arg["body"], chart, d)
        return float(_body(chart, body)["sign"] in arg["signs"]), {body}
    if op == "in_house":
        if not chart["meta"]["time_known"]:
            raise NeedsTime()
        body = resolve_ref(arg["body"], chart, d)
        return float(_body(chart, body).get("house") in arg["houses"]), {body}
    if op == "aspect":
        a = resolve_ref(arg["a"], chart, d)
        b = resolve_ref(arg["b"], chart, d)
        _body(chart, a), _body(chart, b)
        best = 0.0
        for x in chart["aspects"]:
            if {x["a"], x["b"]} == {a, b} and x["aspect"] in arg.get("kinds", [x["aspect"]]):
                best = max(best, x["strength"])
        return (best if best >= arg.get("min", 0.0) else 0.0), {a, b}
    if op == "dignity":
        body = resolve_ref(arg["body"], chart, d)
        return float(_body(chart, body).get("dignity", {}).get("kind") in arg["kinds"]), {body}
    if op == "dominant":
        body = resolve_ref(arg["body"], chart, d)
        return float(body in chart["dominance"]["order"][: int(arg.get("top", 3))]), {body}
    if op == "channel":
        body = resolve_ref(arg["of"], chart, d)
        row = d.channels.get(body)
        return float(row is not None and int(row["channel"]) == int(arg["eq"])), {body}
    if op == "stellium":
        st = [s for s in chart["stellia"] if s["by"] == arg.get("by", "sign")]
        return float(bool(st)), set().union(*(set(s["bodies"]) for s in st))
    if op == "spectrum":
        return float(chart["spectrum"][str(arg["h"])]["amp"] >= arg["min"]), set()
    raise ValueError(f"unknown predicate {op}")


def match_rules(chart: dict, d: Doctrine) -> tuple[list[dict], list[str]]:
    """Заметность правила в тех же единицах, что у атомарных фактов (масса PageRank):
    приоритет × сила × суммарный вес тел, на которых правило сработало."""
    pr = chart["dominance"]["pagerank"]
    avg = 1.0 / max(len(pr), 1)
    hits, unresolved = [], []
    for r in d.rules:
        try:
            s, bodies = evaluate(r["condition"], chart, d)
        except NeedsTime:
            unresolved.append(r["key"])
            continue
        if s > 0:
            mass = sum(pr.get(b, 0.0) for b in bodies) or avg
            hits.append({"key": f"rule:{r['key']}", "module": r["module"], "concept": r["concept"],
                         "salience": round(r["priority"] * s * mass, 5), "strength": round(s, 4),
                         "bodies": sorted(bodies, key=lambda c: d.body_index.get(c, 99)),
                         "covers": list(r.get("covers") or [])})
    hits.sort(key=lambda h: -h["salience"])
    seen, out = set(), []
    for h in hits:
        if h["concept"] in seen:
            continue
        seen.add(h["concept"])
        out.append(h)
    return out, unresolved


# ------------------------------------------------------------------ atomic facts
def _module_for(d: Doctrine, body: str | None, house: int | None, kind: str | None = None) -> str:
    for m in d.modules:
        if kind and kind in (m.get("kinds") or []):
            return m["code"]
    # «планета в доме» — это про сферу жизни: сначала дом, потом тело (Уран во 2-м — про деньги, а не про мышление);
    # кроме модулей, где тело важнее дома (узлы, Лилит, Хирон — всегда «Карма»)
    first = set(d.params.get("report_body_first") or [])
    if kind == "house" and body and any(body in m["bodies"] for m in d.modules if m["code"] in first):
        return next(m["code"] for m in d.modules if m["code"] in first and body in m["bodies"])
    order = (("houses", house), ("bodies", body)) if kind == "house" else (("bodies", body), ("houses", house))
    for field, val in order:
        for m in d.modules:
            if val and val in m[field]:
                return m["code"]
    return d.modules[-1]["code"]


def atomic_facts(chart: dict, d: Doctrine) -> list[dict]:
    pr = chart["dominance"]["pagerank"]
    hcw = d.params["house_class_weight"]
    facts = []

    def add(key, body, house, sal, **extra):
        mod = _module_for(d, body, house, key.split(":", 1)[0])
        facts.append({"key": key, "module": mod, "salience": round(sal, 5), **extra})

    # --- темы всей карты: ведущая пара планет и перекосы стихий/крестов
    planets = [b.code for b in d.bodies if b.kind == "planet" and b.code in pr]
    top = sorted(planets, key=lambda c: -pr[c])[:2]
    if len(top) == 2:
        x, y = sorted(top, key=lambda c: d.body_index[c])
        add(f"dominant:{x}:{y}", None, None, pr[x] + pr[y])
    bal, th = chart["balance"], d.params["balance"]
    for group, shares in (("element", bal["elements"]), ("modality", bal["modalities"])):
        even = 1.0 / len(shares)
        for name, share in shares.items():
            if share >= th["high"]:
                add(f"{group}:high:{name}", None, None, share - even)
            elif share <= th["low"]:
                add(f"{group}:low:{name}", None, None, even - share)

    for b in d.bodies:
        e = chart["bodies"][b.code]
        if not e["shown"]:
            continue
        base = pr.get(b.code, b.weight / 10)
        add(f"sign:{b.code}:{e['sign']}", b.code, e.get("house"), base)
        if "house" in e:
            add(f"house:{b.code}:{e['house']}", b.code, e["house"], base * hcw[d.house_class(e["house"])])
        if "dignity" in e:
            add(f"dignity:{b.code}:{e['dignity']['kind']}", b.code, e.get("house"),
                base * abs(e["dignity"]["score"]) / 5)
    for a in chart["aspects"]:
        b1, b2 = sorted((a["a"], a["b"]), key=lambda c: d.body_index[c])
        sal = a["strength"] * d.aspect_by_code[a["aspect"]].weight * (pr.get(b1, .02) * pr.get(b2, .02)) ** .5
        add(f"aspect:{b1}:{a['aspect']}:{b2}", b1, None, sal * 2, uncertain=a["uncertain"])
    if chart["meta"]["time_known"]:
        for h in range(1, 13):
            ruler = d.primary_ruler(chart["houses"][str(h)]["sign"])
            if ruler and "house" in chart["bodies"][ruler]:
                h2 = chart["bodies"][ruler]["house"]
                add(f"ruler:{h}:in:{h2}", None, h, pr.get(ruler, 0.02) * hcw[d.house_class(h)])
    for k, ch in enumerate(chart["dominance"]["channels_order"][:3]):
        add(f"channel_top:{ch}", None, None, chart["dominance"]["channels"][ch] * (1 - 0.2 * k))
    for body in chart["dispositors"]["final"]:
        add(f"final:{body}", body, None, pr.get(body, 0.02) * 1.5)
    for b1, b2 in chart["dispositors"]["receptions"]:
        x, y = sorted((b1, b2), key=lambda c: d.body_index[c])
        add(f"reception:{x}:{y}", x, None, (pr.get(x, .02) + pr.get(y, .02)))
    facts.sort(key=lambda f: -f["salience"])
    return facts


FORECAST_KINDS = {"tr", "trh", "moon", "lun", "ecl", "retro", "pm", "pmh", "pms"}


def key_space(d: Doctrine) -> list[str]:
    """Полное множество ключей контента, которое может породить доктрина."""
    keys = []
    signs = [s["code"] for s in d.signs]
    planets = [b for b in d.bodies if b.kind == "planet"]
    keys += [f"dominant:{x.code}:{y.code}" for x, y in combinations(planets, 2)]
    for group, field in (("element", "element"), ("modality", "modality")):
        names = sorted({s[field] for s in d.signs})
        keys += [f"{group}:{lvl}:{n}" for lvl in ("high", "low") for n in names]
    excl = {frozenset(x) for x in d.params.get("aspect_exclude_pairs", [])}
    for b in d.bodies:
        keys += [f"sign:{b.code}:{s}" for s in signs]
        if b.kind != "angle":
            keys += [f"house:{b.code}:{h}" for h in range(1, 13)]
    keys += sorted({f"dignity:{b}:{kind}" for (b, _), (kind, _) in d.dignities.items()})
    for b1, b2 in combinations(d.bodies, 2):
        if frozenset((b1.code, b2.code)) in excl:
            continue
        keys += [f"aspect:{b1.code}:{a.code}:{b2.code}" for a in d.aspects]
    keys += [f"ruler:{h}:in:{h2}" for h in range(1, 13) for h2 in range(1, 13)]
    chans = sorted({int(r["channel"]) for r in d.channels.values()})
    keys += [f"channel_top:{c}" for c in chans]
    rulers = sorted({b for rows in d.rulers.values() for b, _, _ in rows}, key=lambda c: d.body_index[c])
    keys += [f"final:{b}" for b in rulers]
    keys += [f"reception:{x}:{y}" for x, y in combinations(rulers, 2)]
    keys += [f"rule:{r['key']}" for r in d.rules]
    keys += synthesis_keys(d)
    keys += forecast_keys(d)
    return keys


def synthesis_keys(d: Doctrine) -> list[str]:
    """тексты синтеза: напряжение по каждой оси и сквозная тема по каждому полюсу"""
    keys = []
    for ax in d.params.get("synthesis_axes", []):
        keys.append(f"synth:tension:{ax['code']}")
        keys += [f"synth:theme:{ax['code']}:{p['code']}" for p in ax["poles"]]
    return keys


def describe(key: str, d: Doctrine, locale: str = "ru") -> str:
    tpl = d.params.get("fact_templates", {}).get(locale, {})
    kind, *parts = key.split(":")
    if kind in FORECAST_KINDS:
        return describe_forecast_key(key, d, locale) or key
    bl = lambda c: d.body(c).label.get(locale, c)
    sl = lambda c: d.sign_by_code[c]["label"].get(locale, c)
    al = lambda c: d.aspect_by_code[c].label.get(locale, c)
    args: dict = {}
    if kind == "sign":
        args = {"body": bl(parts[0]), "sign": sl(parts[1])}
    elif kind == "house":
        args = {"body": bl(parts[0]), "house": parts[1]}
    elif kind == "aspect":
        args = {"a": bl(parts[0]), "aspect": al(parts[1]), "b": bl(parts[2])}
    elif kind == "dignity":
        args = {"body": bl(parts[0]),
                "kind": d.params.get("dignity_labels", {}).get(locale, {}).get(parts[1], parts[1])}
    elif kind == "ruler":
        args = {"h": parts[0], "h2": parts[2]}
    elif kind == "channel_top":
        args = {"n": parts[0]}
    elif kind == "final":
        args = {"body": bl(parts[0])}
    elif kind == "reception":
        args = {"a": bl(parts[0]), "b": bl(parts[1])}
    elif kind == "dominant":
        args = {"a": bl(parts[0]), "b": bl(parts[1])}
    elif kind in ("element", "modality"):
        p = d.params
        args = {"level": p.get("level_labels", {}).get(locale, {}).get(parts[0], parts[0]),
                "name": p.get(f"{kind}_labels", {}).get(locale, {}).get(parts[1], parts[1])}
    elif kind == "synth":
        ax = next((a for a in d.params.get("synthesis_axes", []) if a["code"] == parts[1]), None)
        if ax is None:
            return key
        pl = {p["code"]: p["label"].get(locale, p["code"]) for p in ax["poles"]}
        kind = f"synth_{parts[0]}"
        args = {"axis": ax["label"].get(locale, ax["code"]), "pole": pl.get(parts[2], "") if len(parts) > 2 else ""}
    elif kind == "rule":
        rule = next((r for r in d.rules if r["key"] == parts[0]), None)
        if rule and rule.get("label", {}).get(locale):
            return rule["label"][locale]
        args = {"key": parts[0]}
    t = tpl.get(kind)
    return fmt(t, locale, **args) if t else key


# ------------------------------------------------------------------ report
def assemble_report(chart: dict, d: Doctrine, content: dict[str, dict], locale: str = "ru") -> dict:
    rules, unresolved = match_rules(chart, d)
    covered = [pat for r in rules for pat in r["covers"]]
    facts = [f for f in atomic_facts(chart, d) if not any(fnmatchcase(f["key"], p) for p in covered)]
    limit = int(d.params["report_facts_per_module"])
    modules = []
    gaps = []
    for m in d.modules:
        items = [x for x in rules if x["module"] == m["code"]] + \
                [x for x in facts if x["module"] == m["code"]]
        items.sort(key=lambda x: -x["salience"])
        items = items[:limit]
        for it in items:
            it["title"] = describe(it["key"], d, locale)
            c = content.get(it["key"])
            if c:
                it["text"] = c
            else:
                gaps.append(it["key"])
        modules.append({"code": m["code"], "label": m["label"].get(locale, m["code"]), "items": items})
    return {
        "doctrine": d.code,
        "modules": modules,
        "content_gaps": gaps,
        "unresolved_rules_need_time": unresolved,
        "channels_verified": all(r["verified"] for r in d.channels.values()),
    }
