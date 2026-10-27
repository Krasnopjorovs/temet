"""Гейт переводов текстов (без LLM): перевод сверяется с исходным текстом и с уже переведёнными.

Жёсткие проверки (провал = перевести заново):
  ключ есть в исходном корпусе; те же текстовые поля, что у исходника, и столько же пунктов in_life;
  нет кириллицы; длина каждого поля и число предложений body — в разумных пределах от исходника (не пересказ и не урезка);
  имена тел и знаков ключа, названные в исходнике, названы и в переводе;
  запрещённые обещания и советы (медицина, финансы, предсказания) — на языке перевода;
  в текстах прогноза — без дат, сроков и повторяемости (их показывает страница); в натальных — без поколения и годов;
  у ключей, где планета любая (управитель, правило, синтез), — без женских ролей («hostess», «mistress»).
Корпус (scripts/corpus_checks.py по основам слов): жёстко — занятый или почти такой же заголовок, перекличка
с другим текстом (два общих оборота из 5 слов), повтор внутри текста; остальные корпусные пометки — предупреждения.

python -m scripts.gate_translation out/part.json --source content/forecast_v1.json --locale en [--context out/*.json]
Код выхода 1, если есть жёсткие провалы.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

from astro.doctrine import load_yaml
from astro.rules import key_space
from scripts.corpus_checks import check_corpus, lemmas

TEXT = ("title", "body", "strength", "shadow", "action")
CYR = re.compile(r"[А-Яа-яЁё]")
# правила по языку перевода; общий смысл — как у русского гейта (scripts/gate_content.py)
LANG = {
    "en": {
        "banned": re.compile(r"\b(destined|doomed|fate is sealed|will certainly happen|guarantee\w*|diagnos\w*|medication\w*|"
                             r"medicines?|medical treatment|investments?|investors?|stock market|stocks\b|loans?\b|mortgages?|divorce\w*|"
                             r"will die)", re.I),
        "fc_time": re.compile(r"\b(every (?:week|month|year)|once a (?:week|month|year)|"
                              r"(?:\d+|two|three|four|five|six|seven|eight|nine|ten|a few|several|a couple of|one and a half)\s+"
                              r"(?:days?|weeks?|months?|years?)|"
                              r"january|february|march|april|june|july|august|september|october|november|december|"
                              r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I),
        "generation": re.compile(r"\b(generations?|generational|peers born|born in the same|(?:18|19|20)\d\d)\b", re.I),
        "fem_agent": re.compile(r"\b(hostess|mistress|queen|lady|she|herself)\b", re.I),
        "archaic": re.compile(r"\b(thou|thee|thy|thine)\b", re.I),
        # британское написание — как во всём сайте (colour, behaviour, realise, centre)
        "spelling": re.compile(r"\b(colors?|colored|coloring|behaviors?|favorites?|neighbors?|honors?|humor|centers?|centered|"
                               r"realiz\w*|recogniz\w*|organiz\w*|apologiz\w*|prioritiz\w*|emphasiz\w*|criticiz\w*|"
                               r"analyz\w*|traveled|traveling|canceled|labor)\b", re.I),
    },
}
# пределы от исходника: длина поля (доля символов) и число предложений body (±)
RATIO = {"title": (0.3, 2.8), "body": (0.6, 1.5), "field": (0.5, 1.75), "life": (0.45, 1.9)}
SENT_DELTA = 1
HARD_CORPUS = ("заголовок уже занят", "заголовок почти как у", "перекличка с", "повтор внутри текста")
VARIABLE_BODY = ("ruler:", "rule:", "synth:", "element:", "modality:")
FORECAST = ("tr:", "trh:", "moon:", "lun:", "ecl:", "retro:", "pm:", "pmh:", "pms:")


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if len(s) > 3])


def names_of(key: str, d, locale: str) -> list[tuple[set, list[set]]]:
    """имена тел и знаков из ключа: (леммы русского имени, [основы имени в переводе, …]) — с вариантом в скобках"""
    out = []
    codes = key.split(":")[1:]
    for c in codes:
        lab = None
        if c in d.body_index:
            lab = d.body(c).label
        elif c in d.sign_by_code:
            lab = d.sign_by_code[c]["label"]
        if not lab or not lab.get(locale):
            continue
        def forms(s):
            m = re.match(r"\s*(.*?)\s*\((.*?)\)\s*$", s)
            return [m.group(1), m.group(2)] if m else [s]
        ru = [set(lemmas(f)) for f in forms(lab["ru"]) if lemmas(f)]
        tr = [set(lemmas(f)) for f in forms(lab[locale]) if lemmas(f)]
        if ru and tr:
            out.append((ru, tr))
    return out


def check(item: dict, src: dict, d, locale: str) -> list[str]:
    errs = []
    rules = LANG[locale]
    key = item.get("key")
    for f in TEXT:
        if src.get(f) and not (isinstance(item.get(f), str) and item[f].strip()):
            errs.append(f"нет поля {f}")
        if item.get(f) and not src.get(f):
            errs.append(f"лишнее поле {f}: в исходнике его нет")
    life, slife = item.get("in_life"), src.get("in_life") or []
    if not isinstance(life, list) or not all(isinstance(x, str) and x.strip() for x in life):
        errs.append("in_life — список строк")
    elif len(life) != len(slife):
        errs.append(f"in_life: {len(life)} пунктов, в исходнике {len(slife)}")
    if errs:
        return errs
    every = [item[f] for f in TEXT if item.get(f)] + life
    for x in every:
        if m := CYR.search(x):
            errs.append(f"кириллица в переводе: …{x[max(0, m.start() - 10):m.end() + 10]}…")
            break
    for f in TEXT:
        if not item.get(f):
            continue
        lo, hi = RATIO["title" if f == "title" else "body" if f == "body" else "field"]
        r = len(item[f]) / max(1, len(src[f]))
        if not lo <= r <= hi:
            errs.append(f"{f}: длина {len(item[f])} при {len(src[f])} в исходнике (×{r:.2f}, норма ×{lo}–{hi})")
    for x, y in zip(life, slife):
        r = len(x) / max(1, len(y))
        if not RATIO["life"][0] <= r <= RATIO["life"][1]:
            errs.append(f"пункт in_life «{x[:40]}…»: длина ×{r:.2f} от исходника")
            break
    if abs(sentences(item["body"]) - sentences(src["body"])) > SENT_DELTA:
        errs.append(f"body: {sentences(item['body'])} предложений, в исходнике {sentences(src['body'])}")
    text = " ".join(every)
    src_text = " ".join([src[f] for f in TEXT if src.get(f)] + slife)
    sl, tl = set(lemmas(src_text)), set(lemmas(text))
    for ru, tr in names_of(key, d, locale):
        if any(f <= sl for f in ru) and not any(f <= tl for f in tr):
            errs.append(f"в исходнике названо «{' / '.join(' '.join(sorted(f)) for f in ru)}», в переводе нет")
    if m := rules["banned"].search(text):
        errs.append(f"запрещено: {m.group(0)}")
    if m := rules["archaic"].search(text):
        errs.append(f"архаичное обращение: {m.group(0)}")
    if m := rules["spelling"].search(text):
        errs.append(f"американское написание «{m.group(0)}»: на сайте британское (colour, behaviour, realise, centre)")
    if key.startswith(FORECAST):
        if m := rules["fc_time"].search(text):
            errs.append(f"даты, сроки и повторяемость показывает страница, не текст: «{m.group(0)}»")
    elif m := rules["generation"].search(text):
        errs.append(f"о поколении и годах пишет пометка отчёта, не текст: «{m.group(0)}»")
    if key.startswith(VARIABLE_BODY) and (m := rules["fem_agent"].search(text)):
        errs.append(f"планета здесь любая, у неё нет рода: «{m.group(0)}» — пишите «the ruler» или «it»")
    return errs


def load(paths):
    out = {}
    for p in paths:
        for it in json.load(open(p, encoding="utf-8")):
            out[it.get("key")] = {**out.get(it.get("key"), {}), **it}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--source", nargs="+", required=True, help="исходные тексты (более поздний файл обновляет ключ)")
    ap.add_argument("--context", nargs="*", default=[], help="уже переведённые тексты: для корпусных проверок")
    ap.add_argument("--locale", default="en")
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    valid = set(key_space(d))
    src = load(a.source)
    focus_paths = [os.path.abspath(p) for p in a.files]
    items = []
    for p in focus_paths:
        items += json.load(open(p, encoding="utf-8"))
    seen = Counter(it.get("key") for it in items)
    failed, warned = {}, {}
    for it in items:
        k = it.get("key")
        if k not in valid or k not in src:
            failed.setdefault(k, []).append("ключа нет в доктрине или в исходных текстах")
            continue
        if errs := check(it, src[k], d, a.locale):
            failed.setdefault(k, []).extend(errs)
    focus_keys = set(seen)
    ctx = [v for k, v in load([p for p in a.context if os.path.abspath(p) not in focus_paths]).items() if k not in focus_keys]
    full = lambda it: {**{f: "" for f in TEXT}, "in_life": [], **it}
    for k, errs in check_corpus([full(x) for x in ctx], [full(x) for x in items if x.get("key") in src]).items():
        for e in errs:
            (failed if e.startswith(HARD_CORPUS) else warned).setdefault(k, []).append(e)
    for k in [k for k, n in seen.items() if n > 1]:
        failed.setdefault(k, []).append("ключ повторяется")
    print(f"items {len(items)} (+{len(ctx)} context) · failed {len(failed)} · warnings {len(warned)}")
    if not a.quiet:
        for k, errs in list(failed.items())[:80]:
            print(f"  FAIL {k}: {'; '.join(errs)}")
        for k, errs in list(warned.items())[:40]:
            print(f"  warn {k}: {'; '.join(errs)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
