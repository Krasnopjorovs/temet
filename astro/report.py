"""Сборка отчёта для читателя (без LLM): порядок, главное и второстепенное, один сигнал — одна карточка,
повторы между карточками убираются по заранее посчитанным подписям смысла.

Всё управляется параметрами доктрины:
  report_display_order      — порядок модулей на странице (назначение фактов модулям не меняется);
  report_main_per_module    — сколько карточек модуля показывать развёрнутыми, остальное — «ещё»;
  report_background_module  — куда собрать положения «фон поколения» (одним свёрнутым блоком в конце);
  report_dedupe_jaccard     — порог похожести пунктов (доля общих значимых лемм), выше — пункт не повторяется;
  report_pinned             — маски ключей, которые всегда идут первыми и развёрнутыми (Солнце, Луна, Асцендент);
  report_hide_unverified_channels — не показывать каналы, пока соответствия в доктрине не сверены;
  report_group_rulers_min   — управители, стоящие в одном доме (≥ N), собираются в одну карточку этого дома;
  synthesis_*               — карточки синтеза: напряжения и сквозные темы карты (astro/synthesis.py).
У правила `presents: covered` вместо общего текста показывается текст поглощённого им факта этой карты
(«управитель 2-го в 12-м», а не «в 8-м или 12-м»).
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from .brief import scope_info
from .i18n import join, tr
from .doctrine import Doctrine
from .rules import atomic_facts, describe
from .synthesis import synthesize



def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def _merge_dignities(items: list[dict], d: Doctrine, chart: dict, locale: str) -> list[dict]:
    """достоинство планеты — пометка на карточке «планета в знаке», а не отдельная карточка"""
    by_key = {it["key"]: it for it in items}
    lab = d.params.get("dignity_labels", {}).get(locale, {})
    out = []
    for it in items:
        kind, *p = it["key"].split(":")
        if kind == "dignity" and p[0] in chart["bodies"]:
            host = by_key.get(f"sign:{p[0]}:{chart['bodies'][p[0]]['sign']}")
            if host is not None:
                host.setdefault("tags", []).append(lab.get(p[1], p[1]))
                if not host.get("text") and it.get("text"):
                    host["text"] = it["text"]
                continue
        out.append(it)
    return out


def _rule_detail(it: dict, d: Doctrine, chart: dict, locale: str) -> None:
    """правило с вариантами называет вариант этой карты: на каких телах и в каких домах сработало"""
    if not it["key"].startswith("rule:") or not it.get("bodies"):
        return
    sl = {s["code"]: s["label"].get(locale, s["code"]) for s in d.signs}
    rule = next((r for r in d.rules if f"rule:{r['key']}" == it["key"]), None)
    if rule and "'stellium'" in repr(rule["condition"]):
        by = "sign" if "'house'" not in repr(rule["condition"]) else "house"
        groups = [st for st in chart.get("stellia", []) if st["by"] == by]
        it["detail"] = " · ".join(
            f"{sl.get(st['key'], st['key']) if by == 'sign' else tr(d, locale, 'house_n', n=int(st['key']))}: "
            + ", ".join(d.body(b).label.get(locale, b) for b in st["bodies"]) for st in groups)
        return
    parts = []
    for b in it["bodies"]:
        e = chart["bodies"].get(b, {})
        where = sl.get(e.get("sign"), "")
        if e.get("house"):
            where += ", " + tr(d, locale, "house_n", n=int(e["house"]))
        parts.append(f"{d.body(b).label.get(locale, b)} — {where}")
    it["detail"] = "; ".join(parts)


def _present_covered(modules, d: Doctrine, chart: dict, content: dict, locale: str) -> None:
    """правило с `presents: covered` показывает текст своего варианта — поглощённого атомарного факта"""
    facts = atomic_facts(chart, d)
    for m in modules:
        for it in m["items"]:
            rule = next((r for r in d.rules if f"rule:{r['key']}" == it["key"]), None)
            if not rule or rule.get("presents") != "covered":
                continue
            for f in facts:      # факты уже по убыванию заметности
                if any(fnmatchcase(f["key"], pat) for pat in rule.get("covers") or []) and content.get(f["key"]):
                    it["key"], it["title"], it["text"] = f["key"], describe(f["key"], d, locale), content[f["key"]]
                    it.pop("bodies", None)
                    break


def _group_rulers(modules, d: Doctrine, locale: str, min_n: int) -> None:
    """несколько управителей в одном доме — одна карточка этого дома, остальные внутри неё"""
    by_target: dict[int, list] = {}
    for m in modules:
        for it in m["items"]:
            k = it["key"].split(":")
            if k[0] == "ruler" and it.get("text"):
                by_target.setdefault(int(k[3]), []).append((m, it))
    for h2, lst in by_target.items():
        if len(lst) < min_n:
            continue
        lst.sort(key=lambda x: -x[1].get("salience", 0))
        lead_m, lead = lst[0]
        houses = sorted(int(it["key"].split(":")[1]) for _, it in lst)
        names = join([tr(d, locale, "ruler_of_n", n=h) for h in houses], d, locale)
        lead["group_title"] = tr(d, locale, "rulers_meet", h=h2, names=names)
        lead["group"] = [{"key": it["key"], "title": it["title"], "text": it["text"], "salience": it.get("salience", 0),
                          **({"tags": it["tags"]} if it.get("tags") else {})}
                         for _, it in sorted(lst[1:], key=lambda x: int(x[1]["key"].split(":")[1]))]
        lead["own_salience"] = lead.get("salience", 0)
        lead["salience"] = sum(it.get("salience", 0) for _, it in lst)
        for m, it in lst:
            m["items"].remove(it)
        target = next((m for m in modules for mm in d.modules if mm["code"] == m["code"] and h2 in mm["houses"]), lead_m)
        target["items"].insert(0, lead)


def _dup(u: dict, pool: list[dict], thr: float) -> bool:
    """повтор: много общих значимых лемм; два общих оборота; общий оборот из двух значимых слов;
    общий оборот плюс ещё одно общее нечастое слово вне его («расскажите тому, кому доверяете» + «рассказать»)"""
    for v in pool:
        common = set(u["w"]) & set(v["w"])
        if len(common) >= 3 and len(common) / len(set(u["w"]) | set(v["w"])) >= thr:
            return True
        shared = set(u["t"]) & set(v["t"])
        if len(shared) >= 2 or set(u["t2"]) & set(v["t2"]):
            return True
        if shared and (set(u.get("r", ())) & set(v.get("r", ()))) - {w for g in shared for w in g.split()}:
            return True
    return False


def _dedupe(modules: list[dict], thr: float) -> int:
    """убирает пункты in_life и поля strength/shadow/action, повторяющие уже показанные выше в этом отчёте"""
    seen: dict[str, list] = {"in_life": [], "strength": [], "shadow": [], "action": []}
    removed = 0
    ordered = [it for m in modules for it in m["items"] if it.get("main")] + \
              [it for m in modules for it in m["items"] if not it.get("main")]   # сначала всё развёрнутое
    texts = [t for it in ordered for t in [it.get("text")] + [g.get("text") for g in it.get("group") or []]]
    for t in texts:
        sig = (t or {}).get("_sig")
        if not sig or not isinstance(sig.get("action"), dict):
            continue
        keep = []
        for bullet, u in zip(t.get("in_life") or [], sig.get("in_life") or []):
            if _dup(u, seen["in_life"], thr):
                removed += 1
                continue
            keep.append(bullet)
            seen["in_life"].append(u)
        if t.get("in_life") and len(keep) < len(t["in_life"]):
            t["in_life"] = keep
        for f in ("strength", "shadow", "action"):
            u = sig.get(f)
            if not u or not u["w"]:
                continue
            pool = seen["strength"] + seen["shadow"] if f in ("strength", "shadow") else seen[f]
            if _dup(u, pool, thr):
                t[f] = None
                removed += 1
            else:
                seen[f].append(u)
    return removed


def finalize(rep: dict, chart: dict, d: Doctrine, stats: dict, locale: str = "ru", content: dict | None = None,
             synthesis: bool = True) -> dict:
    p = d.params
    main_n = int(p.get("report_main_per_module", 5))
    bg_code = p.get("report_background_module")
    thr = float(p.get("report_dedupe_jaccard", 0.45))
    modules = rep["modules"]
    pinned = list(p.get("report_pinned") or [])
    if p.get("report_hide_unverified_channels") and not all(r.get("verified") for r in d.channels.values()):
        chan_rules = {f"rule:{r['key']}" for r in d.rules if "'channel'" in repr(r["condition"])}
        for m in modules:
            m["items"] = [it for it in m["items"]
                          if not it["key"].startswith("channel_top:") and it["key"] not in chan_rules]
        rep["content_gaps"] = [k for k in rep.get("content_gaps", [])
                               if not k.startswith("channel_top:") and k not in chan_rules]
    _present_covered(modules, d, chart, content or {}, locale)
    if int(p.get("report_group_rulers_min", 0)) >= 2:
        _group_rulers(modules, d, locale, int(p["report_group_rulers_min"]))
    background = []
    for m in modules:
        items = _merge_dignities(m["items"], d, chart, locale)
        kept = []
        for it in items:
            _rule_detail(it, d, chart, locale)
            sc = scope_info(it["key"], chart, d, stats, locale)
            if sc:
                it["scope"] = sc[1]
            if bg_code and sc and sc[0] == "generation":
                background.append(it)
            else:
                kept.append(it)
        pin = lambda it: next((i for i, pat in enumerate(pinned) if fnmatchcase(it["key"], pat)), None)
        # закреплённые — первыми; без текста — в конец; дальше по заметности (порядок assemble_report)
        kept.sort(key=lambda it: (pin(it) is None, pin(it) or 0, not it.get("text")))
        for i, it in enumerate(kept):
            it["main"] = bool(it.get("text")) and (i < main_n or pin(it) is not None)
        m["items"] = kept
    if bg_code and background:
        lab = next((x.get("label", {}) for x in p.get("report_extra_modules", []) if x.get("code") == bg_code), {})
        for it in background:
            it["main"] = False
        modules.append({"code": bg_code, "label": lab.get(locale) or lab.get("ru") or bg_code, "items": background, "background": True})
    syn_code = p.get("synthesis_module")
    if synthesis and syn_code:
        cards = synthesize(modules, d, stats.get("synthesis") or {}, content or {}, locale, chart)
        if cards:
            lab = next((x.get("label", {}) for x in p.get("report_extra_modules", []) if x.get("code") == syn_code), {})
            modules.append({"code": syn_code, "label": lab.get(locale) or lab.get("ru") or syn_code, "items": cards, "synthesis": True})
    order = p.get("report_display_order") or []
    rank = {c: i for i, c in enumerate(order)}
    modules.sort(key=lambda m: rank.get(m["code"], len(rank)))
    rep["deduped"] = _dedupe(modules, thr)
    for m in modules:
        for it in m["items"]:
            if it.get("text"):
                it["text"] = {k: v for k, v in it["text"].items() if k != "_sig"}
            for g in it.get("group") or []:
                g["text"] = {k: v for k, v in g["text"].items() if k != "_sig"}
    return rep
