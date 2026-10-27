"""Бриф к ключу контента: что это за положение и посчитанные факты о нём (эфемериды, популяция, доктрина).

Бриф — данные, а не трактовка: автор текста (человек или модель) получает определение из доктрины,
насколько положение личное или общее для ровесников, как часто встречается, при каких вариантах
срабатывает составное правило. Таблицы считает scripts.content_stats.
"""
from __future__ import annotations

import json
import os

from .doctrine import Doctrine
from .rules import describe


def load_stats(d: Doctrine, path: str | None = None) -> dict:
    """факты из эфемерид и выборки карт; рядом — калибровка синтеза (<код>.synthesis.json), если она есть"""
    path = path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "doctrine", "stats", f"{d.code}.json")
    try:
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
    except FileNotFoundError:
        stats = {}
    for part in ("synthesis", "forecast"):          # калибровки синтеза и насыщенности прогноза
        extra = path[:-len(".json")] + f".{part}.json"
        if os.path.exists(extra):
            with open(extra, encoding="utf-8") as f:
                stats[part] = json.load(f)
    return stats


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    return one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many


def duration(days: float) -> str:
    if days < 2:
        h = max(1, round(days * 24))
        return f"около {h} {_plural(h, 'часа', 'часов', 'часов')}" if h < 36 else "около полутора суток"
    if days < 14:
        n = round(days)
        return f"около {n} {_plural(n, 'дня', 'дней', 'дней')}"
    if days < 60:
        n = round(days / 7)
        return f"около {n} {_plural(n, 'недели', 'недель', 'недель')}"
    if days < 548:
        n = round(days / 30.4)
        return f"около {n} {_plural(n, 'месяца', 'месяцев', 'месяцев')}"
    n = round(days / 365.25)
    return f"около {n} {_plural(n, 'года', 'лет', 'лет')}"


def every(days: float) -> str:
    """«раз в 3 месяца», «раз в год», «раз в 10 лет»"""
    if days < 45:
        return "каждый месяц"
    if days < 330:
        n = round(days / 30.4)
        return "раз в месяц" if n == 1 else f"раз в {n} {_plural(n, 'месяц', 'месяца', 'месяцев')}"
    n = round(days / 365.25)
    return "раз в год" if n <= 1 else f"раз в {n} {_plural(n, 'год', 'года', 'лет')}"


def scope(days: float) -> str:
    """насколько положение личное — для автора; в отчёте это показывает отдельная пометка (scope_note)"""
    if days < 60:
        return "индивидуальное положение"
    if days < 365:
        return "общее для родившихся в один сезон — отчёт помечает это сам, в тексте не упоминай"
    return "фон поколения — отчёт помечает это сам с годами, в тексте не упоминай поколение и годы"


def _share(x: float | None) -> str:
    if x is None:
        return ""
    if x < 0.01:
        return f"встречается редко (примерно в одной карте из {round(1 / x) if x > 0 else 1000})"
    return f"встречается примерно в {round(100 * x)}% карт"


def _ref(ref, d: Doctrine) -> str:
    if isinstance(ref, str):
        return d.body(ref).label.get("ru", ref)
    if "ruler_of_house" in ref:
        return f"управитель {ref['ruler_of_house']}-го дома"
    if "dispositor" in ref:
        return f"диспозитор ({_ref(ref['dispositor'], d)})"
    return str(ref)


def _or(xs) -> str:
    xs = [str(x) for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " или " + xs[-1]


def render_condition(c: dict, d: Doctrine) -> tuple[str, bool]:
    """условие правила словами; второй элемент — есть ли у условия несколько вариантов"""
    (op, arg), = c.items()
    if op in ("all", "any"):
        parts = [render_condition(x, d) for x in arg]
        txt = (" и " if op == "all" else "; либо ").join(p for p, _ in parts)
        return (f"({txt})" if op == "any" else txt), op == "any" or any(m for _, m in parts)
    if op == "not":
        t, m = render_condition(arg, d)
        return f"не ({t})", m
    if op == "in_house":
        hs = arg["houses"]
        return f"{_ref(arg['body'], d)} в {_or(f'{h}-м' for h in hs)} доме", len(hs) > 1 or not isinstance(arg["body"], str)
    if op == "in_sign":
        ss = [d.sign_by_code[s]["label"]["ru"] for s in arg["signs"]]
        return f"{_ref(arg['body'], d)} в знаке {_or(ss)}", len(ss) > 1
    if op == "aspect":
        ks = [d.aspect_by_code[k].label["ru"].lower() for k in arg.get("kinds", [a.code for a in d.aspects])]
        return f"{_ref(arg['a'], d)} и {_ref(arg['b'], d)}: {_or(ks)}", len(ks) > 1
    if op == "dignity":
        lab = d.params.get("dignity_labels", {}).get("ru", {})
        return f"{_ref(arg['body'], d)}: {_or(lab.get(k, k) for k in arg['kinds'])}", len(arg["kinds"]) > 1
    if op == "dominant":
        return f"{_ref(arg['body'], d)} среди {arg.get('top', 3)} самых весомых тел карты", False
    if op == "stellium":
        planets = [b.label["ru"] for b in d.bodies if b.kind == "planet"]
        by = "знаке" if arg.get("by", "sign") == "sign" else "доме"
        return (f"не меньше {d.params['stellium_min']} планет в одном {by} (любые из: {', '.join(planets)})", True)
    if op == "channel":
        return f"канал {_ref(arg['of'], d)} = {arg['eq']}", False
    if op == "spectrum":
        return f"выражена гармоника {arg['h']}", False
    return op, False


FORECAST_KINDS = ("tr", "trh", "moon", "lun", "ecl", "retro", "pm", "pmh", "pms")


def forecast_text_long(key: str, d: Doctrine) -> bool:
    """полный текст (медленные влияния, затмения, прогрессии) или короткий (быстрые, Луна, лунации, попятные)"""
    fp = d.params.get("forecast") or {}
    kind, *p = key.split(":")
    return kind in fp.get("long_text_kinds", []) or (kind in ("tr", "trh") and p[0] in fp.get("slow", []))


def forecast_brief(key: str, d: Doctrine, stats: dict) -> str:
    fp = d.params["forecast"]
    ep = (stats.get("forecast") or {}).get("episodes", {})
    hl = {h["num"]: h["label"]["ru"] for h in d.houses}
    gen = lambda c: fp["cases"]["ru"][c][2]
    kind, *a = key.split(":")
    out = ["формат: " + ("полный" if forecast_text_long(key, d) else "короткий")]
    speed = lambda T: ("медленная планета: тема месяцев, иногда больше года" if T in fp["slow"]
                       else "быстрая планета: фон нескольких дней, такие тексты читатель встречает часто")
    if kind in ("tr", "pm"):
        cls, N = (a[1], a[2]) if kind == "tr" else (a[0], a[1])
        names = [d.aspect_by_code[c].label["ru"].lower() for c in fp["aspect_classes"][cls]]
        if len(names) > 1:
            out.append(f"текст общий для аспектов «{' и '.join(names)}» — конкретный аспект не называй")
        if N in ("ASC", "MC"):
            out.append("точка карты, которая зависит от часа рождения")
    if kind == "tr":
        T, cls, N = a
        out.append(speed(T))
        e = ep.get("tr", {}).get(f"{T}:{cls}")
        if e:
            s = f"обычно длится {duration(e['days'])}"
            if e["days_p90"] > 1.5 * e["days"]:
                s += f", с попятными петлями до {duration(e['days_p90']).replace('около ', '')}"
            out.append(s + f"; к одной точке карты повторяется примерно {every(e['every_days'])}")
        if T == N and cls == "CONJ":
            out.append(f"возвращение {gen(T)}: планета приходит на то место, где стояла в момент рождения")
    elif kind == "trh":
        T, h = a
        out.append(f"дом {h} — {hl[int(h)]}")
        out.append(speed(T))
        e = ep.get("trh", {}).get(T)
        if e:
            out.append(f"идёт по дому средней ширины {duration(e['days'])}, снова приходит в него {every(e['every_days'])}")
    elif kind == "moon":
        out.append(f"дом {a[0]} — {hl[int(a[0])]}")
        out.append("Луна проходит дом за два-три дня и возвращается в него каждый месяц: самый частый и самый короткий текст прогноза")
    elif kind == "lun":
        out.append(f"дом {a[1]} — {hl[int(a[1])]}")
        out.append("новолуние — начало лунного цикла: время начинать и намечать" if a[0] == "NEW"
                   else "полнолуние — вершина лунного цикла: итог, ясность, эмоции на пике")
        out.append("в этом доме случается раз в год")
    elif kind == "ecl":
        out.append(f"дом {a[1]} — {hl[int(a[1])]}")
        out.append("солнечное затмение — усиленное новолуние: поворот и начало новой главы, отзывается несколько месяцев"
                   if a[0] == "SOLAR" else
                   "лунное затмение — усиленное полнолуние: завершение и отпускание, отзывается несколько месяцев")
        out.append("в одном доме бывает раз в несколько лет")
    elif kind == "retro":
        T, h = a
        e = ep.get("retro", {}).get(T)
        out.append(f"дом {h} — {hl[int(h)]}")
        if e:
            out.append(f"попятное движение {gen(T)} длится {duration(e['days'])} и бывает {every(e['every_days'])}; "
                       "в традиции — время пересмотра, возврата к начатому и доработки")
    elif kind == "pm":
        out.append("вторичная прогрессия (день жизни после рождения — за год): описывает внутреннее созревание, а не внешний фон")
        e = ep.get("pm")
        if e:
            out.append(f"аспект прогрессивной Луны держится {duration(e['days'])}")
    elif kind in ("pmh", "pms"):
        out.append("вторичная прогрессия: внутренняя тема нескольких лет, а не внешний фон")
        if kind == "pmh":
            out.append(f"дом {a[0]} — {hl[int(a[0])]}")
        e = ep.get("pm")
        if e:
            out.append(f"прогрессивная Луна идёт по дому или знаку {duration(e['house_days'])}")
    return f"{key} :: {describe(key, d)} :: " + "; ".join(out)


def brief(key: str, d: Doctrine, stats: dict) -> str:
    kind, *p = key.split(":")
    if kind in FORECAST_KINDS:
        return forecast_brief(key, d, stats)
    bl = lambda c: d.body(c).label.get("ru", c)
    hl = {h["num"]: h["label"]["ru"] for h in d.houses}
    freq = stats.get("freq", {}).get(key)
    out: list[str] = []
    if kind == "sign":
        b = d.body(p[0])
        if b.kind in ("node", "point"):
            out.append(f"расчётная точка: {bl(p[0])}")
        if b.kind == "angle":
            out.append("зависит от часа и места рождения — индивидуально")
        else:
            ps = stats.get("sign_passage", {}).get(f"{p[0]}:{p[1]}")
            if ps:
                out.append(f"{bl(p[0])} идёт по этому знаку {duration(ps.get('typical_days', ps['median_days']))}: "
                           f"{scope(ps.get('typical_days', ps['median_days']))}")

    elif kind == "house":
        out.append(f"дом {p[1]} — {hl[int(p[1])]}; дом зависит от часа и места рождения — индивидуально")
    elif kind == "synth":
        ax = next(a for a in d.params["synthesis_axes"] if a["code"] == p[1])
        poles = {x["code"]: x for x in ax["poles"]}
        pd = lambda x: f"«{x['label']['ru']}» ({x['desc']})"
        if p[0] == "tension":
            out.append(f"карточка синтеза «{ax['label']['ru']}» (в традиции: {ax['anchor']}) — внутреннее напряжение: "
                       f"в карте сильны обе склонности — {pd(ax['poles'][0])} и {pd(ax['poles'][1])}; "
                       "отчёт сам перечисляет положения на каждой стороне; служебные слова брифа (ось, полюс) читателю не называй")
        else:
            other = next(x for c, x in poles.items() if c != p[2])
            out.append(f"карточка синтеза «{ax['label']['ru']}» (в традиции: {ax['anchor']}) — сквозная тема: "
                       f"склонность {pd(poles[p[2]])} подтверждают несколько положений карты, а противоположная — "
                       f"«{other['label']['ru']}» — выражена слабо; отчёт сам перечисляет эти положения; "
                       "служебные слова брифа (ось, полюс) читателю не называй")
    elif kind == "aspect":
        a = d.aspect_by_code[p[1]]
        out.append(f"{a.label['ru'].lower()} ({a.angle_deg:g}°), орбис до {a.orb_deg:g}°")
        if d.body(p[0]).kind == "angle" or d.body(p[2]).kind == "angle":
            out.append("связан с углом карты — зависит от часа рождения, индивидуально")
        else:
            ep = stats.get("aspect_episode", {}).get(f"{p[0]}:{p[1]}:{p[2]}")
            if ep:
                t = ep.get("typical_days", ep["median_days"])
                out.append(f"в орбисе держится {duration(t)}: {scope(t)}")


        pts = [bl(x) for x in (p[0], p[2]) if d.body(x).kind in ("node", "point")]
        if pts:
            out.append("расчётная точка: " + ", ".join(pts))
    elif kind == "dignity":
        lab = d.params.get("dignity_labels", {}).get("ru", {}).get(p[1], p[1])
        signs = [d.sign_by_code[s]["label"]["ru"] for (b, s), (k, _) in d.dignities.items() if b == p[0] and k == p[1]]
        out.append(f"{lab}: {bl(p[0])} в знаке {_or(signs)}")
        ds = [stats.get("sign_passage", {}).get(f"{p[0]}:{s}") for (b, s), (k, _) in d.dignities.items()
              if b == p[0] and k == p[1]]
        ds = [x.get("typical_days", x["median_days"]) for x in ds if x]
        if ds and d.body(p[0]).kind != "angle":
            out.append(f"{bl(p[0])} идёт по такому знаку {duration(max(ds))}: {scope(max(ds))}")
    elif kind == "ruler":
        out.append(f"планета, управляющая знаком на куспиде дома {p[0]} ({hl[int(p[0])]}), стоит в доме {p[2]} "
                   f"({hl[int(p[2])]}); зависит от часа рождения")
    elif kind == "reception":
        own = lambda b: [d.sign_by_code[s]["label"]["ru"] for s, rows in d.rulers.items() if any(x == b for x, _, _ in rows)]
        out.append(f"{bl(p[0])} стоит в знаке, которым управляет {bl(p[1])}, а {bl(p[1])} — в знаке, которым управляет "
                   f"{bl(p[0])} (знаки под управлением {bl(p[0])}: {_or(own(p[0]))}; {bl(p[1])}: {_or(own(p[1]))})")
    elif kind == "final":
        out.append(f"все цепочки «планета → управитель её знака» сходятся на одном теле — {bl(p[0])}; оно стоит в своём знаке")
    elif kind == "dominant":
        out.append(f"{bl(p[0])} и {bl(p[1])} — две самые весомые планеты этой карты (по связям управлений и аспектов)")
    elif kind in ("element", "modality"):
        th = d.params["balance"]
        side = f"не меньше {round(100 * th['high'])}%" if p[0] == "high" else f"не больше {round(100 * th['low'])}%"
        out.append(f"на {('стихию' if kind == 'element' else 'крест')} приходится {side} веса планет карты")
    elif kind == "rule":
        r = next(x for x in d.rules if x["key"] == p[0])
        cond, multi = render_condition(r["condition"], d)
        out.append(f"срабатывает, когда: {cond}")
        if multi:
            out.append("у условия несколько вариантов — текст должен быть верен для каждого и не выдавать один вариант за данность")
        rb = stats.get("rule_bodies", {}).get(key)
        if rb and len(rb) > 2:
            top = sorted(rb.items(), key=lambda kv: -kv[1])[:6]
            out.append("по выборке карт держится на: " + ", ".join(f"{bl(b)} {round(100 * v)}%" for b, v in top))
    elif kind == "channel_top":
        out.append("канал по методологии доктрины (не сверен с первоисточником)")
    sl = lambda c: d.sign_by_code[c]["label"]["ru"]
    var = stats.get("variants", {}).get(key) or {}
    tog = stats.get("together", {}).get(key) or {}
    tog = tog if isinstance(tog, dict) else {k: 1.0 for k in tog}
    fq = stats.get("freq", {})
    lift = lambda k, v: v / fq[k] if fq.get(k) else 99.0          # «рядом» — только если чаще, чем в среднем
    tog = {k: v for k, v in tog.items() if not k.startswith("channel_top:") and lift(k, v) >= 1.5}
    near = [k for k, v in tog.items() if v >= 0.9]
    often = [k for k, v in tog.items() if 0.6 <= v < 0.9]
    by_variant: list[str] = []
    if kind == "dignity" and var:
        out.append("варианты по выборке: " + ", ".join(f"{bl(p[0])} в знаке {sl(x)} {round(100 * v)}%" for x, v in var.items()))
        by_variant += [f"sign:{p[0]}:{x}" for x in var]
    elif kind == "reception" and var:
        pairs = [(x.split("|"), v) for x, v in var.items()]
        out.append("реально встречается: " + "; ".join(f"{bl(p[0])} в знаке {sl(a)} и {bl(p[1])} в знаке {sl(b)} {round(100 * v)}%"
                                                       for (a, b), v in pairs))
        by_variant += [f"sign:{p[0]}:{a}" for (a, _), _ in pairs] + [f"sign:{p[1]}:{b}" for (_, b), _ in pairs]
    elif kind == "rule" and var and len(var) > 1:
        out.append("варианты по выборке: " + ", ".join(f"{x} {round(100 * v)}%" for x, v in var.items()))
    by_variant = list(dict.fromkeys(k for k in by_variant if k != key))
    near = [k for k in dict.fromkeys(near) if k != key and k not in by_variant]
    often = [k for k in dict.fromkeys(often) if k != key and k not in by_variant and k not in near]
    if near or by_variant or often:
        parts = []
        if near:
            parts.append("всегда: " + "; ".join(f"«{describe(k, d)}»" for k in near[:6]))
        if by_variant:
            parts.append("смотря по варианту: " + "; ".join(f"«{describe(k, d)}»" for k in by_variant[:6]))
        if often:
            parts.append("часто: " + "; ".join(f"«{describe(k, d)}»" for k in often[:4]))
        out.append("в отчёте рядом стоят тексты " + ", ".join(parts)
                   + " — не пересказывай их, пиши о том, что добавляет именно это положение")
    yr = stats.get("birth_years", {}).get(key)
    if yr and yr[0] >= 2008:
        out.append("положение есть почти только у родившихся после 2008 года — читатель, скорее всего, ребёнок, "
                   "подросток или его родитель")
    if freq is not None:
        out.append(_share(freq))
    return f"{key} :: {describe(key, d)} :: " + "; ".join(x for x in out if x)


def _ym(s: str) -> float:
    m, y = s.split(".")
    return int(y) + (int(m) - 1) / 12


def scope_note(key: str, chart: dict, d: Doctrine, stats: dict, locale: str = "ru") -> str | None:
    """Пометка для отчёта: общее ли положение для ровесников — из эфемерид и даты рождения, а не из текста."""
    s = scope_info(key, chart, d, stats, locale)
    return s[1] if s else None


def scope_info(key: str, chart: dict, d: Doctrine, stats: dict, locale: str = "ru") -> tuple[str, str] | None:
    """(вид, пометка): generation — фон поколения, season — общее для родившихся в один сезон"""
    from .i18n import about, tr
    kind, *p = key.split(":")
    rec = None
    if kind == "sign" and d.body(p[0]).kind != "angle":
        rec = stats.get("sign_passage", {}).get(f"{p[0]}:{p[1]}")
    elif kind == "dignity" and p[0] in chart["bodies"] and d.body(p[0]).kind != "angle":
        rec = stats.get("sign_passage", {}).get(f"{p[0]}:{chart['bodies'][p[0]]['sign']}")
    elif kind == "aspect" and d.body(p[0]).kind != "angle" and d.body(p[2]).kind != "angle":
        rec = stats.get("aspect_episode", {}).get(f"{p[0]}:{p[1]}:{p[2]}")
    if not rec:
        return None
    t = rec.get("typical_days", rec["median_days"])
    if t >= 365:
        y, m = (int(x) for x in chart["meta"]["input"]["date"].split("-")[:2])
        born = y + (m - 1) / 12
        for a, z in rec.get("periods") or []:
            if _ym(a) - 1 / 12 <= born <= _ym(z) + 1 / 12:
                return "generation", tr(d, locale, "scope_generation_born", a=a, z=z)
        return "generation", tr(d, locale, "scope_generation_for", dur=about(t, d, locale))
    if t >= 60:
        return "season", tr(d, locale, "scope_season", dur=about(t, d, locale))
    return None


def authoring_prompt(path: str, kinds_path: str | None = None, d: Doctrine | None = None) -> str:
    """роль и принципы для любого автора + список видов советов (action_kind) и осей синтеза (axes) из доктрины"""
    text = open(path, encoding="utf-8").read().strip()
    if d is not None and d.params.get("synthesis_axes"):
        text += "\n\nОси синтеза (axes):\n" + "\n".join(
            f"- {a['code']} «{a['label']['ru']}»: " + "; ".join(f"{p['code']} — {p['label']['ru']} ({p['desc']})" for p in a["poles"])
            for a in d.params["synthesis_axes"])
    kinds_path = kinds_path or os.path.join(os.path.dirname(path), "advice_kinds.ru.json")
    if os.path.exists(kinds_path):
        kinds = json.load(open(kinds_path, encoding="utf-8"))
        text += "\n\nВиды советов (action_kind):\n" + "\n".join(
            f"- {k['code']} — {k['label']}: {k['description']}" for k in kinds)
    return text
