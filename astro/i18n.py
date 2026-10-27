"""Языки отчёта и прогноза.

Код не знает слов ни одного языка: подписи — в доктрине ({ru: …, en: …} у тел, знаков, домов, модулей…),
строки, которые собирает сервер, — в params.strings.<язык>, шаблоны прогноза — в params.forecast.templates.<язык>.
Здесь только механика: какой язык, запасной язык, порядковые числительные, множественное число, перечисление.
"""
from __future__ import annotations

import re

DEFAULT = "ru"


def locales(d) -> list[str]:
    return list((d.params.get("strings") or {}).keys()) or [DEFAULT]


def norm(locale: str | None, d=None) -> str:
    """'en-US' -> 'en'; неизвестный язык -> язык по умолчанию"""
    loc = (locale or "").strip().lower().replace("_", "-").split("-")[0]
    known = locales(d) if d is not None else None
    return loc if loc and (known is None or loc in known) else DEFAULT


def lab(label: dict | None, locale: str, fallback: str = "") -> str:
    if not label:
        return fallback
    return label.get(locale) or label.get(DEFAULT) or fallback


def ordinal(n, locale: str) -> str:
    """порядковое числительное: в русском падежное окончание стоит в самом шаблоне ({n}-го, {n}-м)"""
    try:
        k = int(n)
    except (TypeError, ValueError):
        return str(n)
    if locale == "en":
        suf = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
        return f"{k}{suf}"
    return str(k)


def plural(n: int, forms: list[str], locale: str) -> str:
    """формы: ru — [1, 2–4, 5+], en — [1, остальное]; одна форма — без изменения"""
    if len(forms) == 1:
        return forms[0]
    n = abs(int(n))
    if len(forms) >= 3:
        a, b = n % 10, n % 100
        return forms[0] if a == 1 and b != 11 else forms[1] if 2 <= a <= 4 and not 12 <= b <= 14 else forms[2]
    return forms[0] if n == 1 else forms[1]


_NUM = re.compile(r"^\d+$")


def fmt(template: str, locale: str, **kw) -> str:
    """str.format, где к каждому числовому значению добавлено {имя_ord}"""
    extra = {f"{k}_ord": ordinal(v, locale) for k, v in kw.items()
             if isinstance(v, int) or (isinstance(v, str) and _NUM.match(v))}
    return template.format(**kw, **extra)


def strings(d, locale: str) -> dict:
    s = d.params.get("strings") or {}
    return {**s.get(DEFAULT, {}), **s.get(locale, {})}


def tr(d, locale: str, key: str, **kw) -> str:
    t = strings(d, locale).get(key)
    return fmt(t, locale, **kw) if t else key


def join(items: list[str], d, locale: str) -> str:
    """«a, b и c» / «a, b and c»"""
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + strings(d, locale).get("and", " & ") + items[-1]


def about(days: float, d, locale: str) -> str:
    """«около 3 месяцев» / «about 3 months»"""
    s = strings(d, locale)
    u = s.get("units") or {}

    def say(n, unit):
        return fmt(s["about"], locale, n=n, unit=plural(n, u[unit], locale))
    if days < 2:
        h = max(1, round(days * 24))
        return say(h, "hour") if h < 36 else s["about_day_and_half"]
    if days < 14:
        return say(round(days), "day")
    if days < 60:
        return say(round(days / 7), "week")
    if days < 548:
        return say(round(days / 30.4), "month")
    return say(round(days / 365.25), "year")


def label_gaps(y: dict) -> list[str]:
    """все подписи {ru: …} доктрины, у которых нет какого-то из языков params.strings (для проверки перед выкладкой)"""
    langs = list((y.get("params", {}).get("strings") or {}).keys()) or [DEFAULT]
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "label" and isinstance(v, dict):
                    out.extend(f"{path}: нет {l}" for l in langs if not v.get(l))
                else:
                    walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{path}[{x.get('code') or x.get('key') or i}]" if isinstance(x, dict) else f"{path}[{i}]")
    walk(y, "")
    p = y.get("params", {})
    for name in ("fact_templates", "dignity_labels", "element_labels", "modality_labels", "level_labels"):
        block = y.get(name) or {}
        out.extend(f"/{name}: нет {l}" for l in langs if not block.get(l))
    fc = p.get("forecast") or {}
    for name in ("templates", "intensity_labels"):
        out.extend(f"/params/forecast/{name}: нет {l}" for l in langs if not (fc.get(name) or {}).get(l))
    for l in langs:
        ref = set((fc.get("templates") or {}).get(DEFAULT, {}))
        miss = ref - set((fc.get("templates") or {}).get(l, {}))
        out.extend(f"/params/forecast/templates/{l}: нет {k}" for k in sorted(miss))
        ref = set((p.get("strings") or {}).get(DEFAULT, {}))
        miss = ref - set((p.get("strings") or {}).get(l, {}))
        out.extend(f"/params/strings/{l}: нет {k}" for k in sorted(miss))
        ref = set((y.get("fact_templates") or {}).get(DEFAULT, {}))
        miss = ref - set((y.get("fact_templates") or {}).get(l, {}))
        out.extend(f"/fact_templates/{l}: нет {k}" for k in sorted(miss))
    return out
