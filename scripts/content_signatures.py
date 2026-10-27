"""Подписи смысла для коротких полей текстов — чтобы отчёт без LLM убирал повторы между карточками.

Для каждого пункта in_life и полей strength/shadow/action:
  w  — значимые леммы (pymorphy3, без служебных слов);
  t  — обороты из трёх лемм подряд, в которых есть не самое частое по корпусу значимое слово
       («тот кто доверять», «борьба за контроль»);
  t2 — те из них, где значимых слов два и больше;
  r  — значимые леммы, не входящие в самые частые по корпусу.
Считается офлайн по всему корпусу и кладётся в payload как `_sig`; сервису морфология не нужна.

python -m scripts.content_signatures in.json out.json [--common 0.04]
"""
import argparse
import json
from collections import Counter

from scripts.corpus_checks import FUNC, lang_of, lemmas

FIELDS = ("strength", "shadow", "action")


def _content(ws):
    return [w for w in ws if w not in FUNC and len(w) > 2]


def unit(text: str, common: set) -> dict:
    ls = lemmas(text)
    # в английском грамматику несут служебные слова (артикли, предлоги), которые русский выражает окончаниями:
    # обороты считаются по значимым словам, иначе «the urge to» и «when the urge» — уже два общих оборота
    seq = _content(ls) if lang_of(text) == "en" else ls
    tri = [seq[i:i + 3] for i in range(len(seq) - 2)]
    t = [" ".join(g) for g in tri if any(w not in common for w in _content(g))]
    t2 = [" ".join(g) for g in tri if len(_content(g)) >= 2 and any(w not in common for w in _content(g))]
    w = sorted(set(_content(ls)))
    return {"w": w, "r": [x for x in w if x not in common], "t": sorted(set(t)), "t2": sorted(set(t2))}


def sign(items: list[dict], rate: float = 0.04) -> tuple[list[dict], int]:
    """подписи по корпусу одного языка: «общие» слова считаются внутри этого корпуса"""
    items = [{k: v for k, v in it.items() if k not in ("_sig", "_seq")} for it in items]
    df = Counter()
    for it in items:
        s = set()
        for x in [*it.get("in_life", []), *(it.get(f, "") or "" for f in FIELDS)]:
            s |= set(_content(lemmas(x)))
        df.update(s)
    common = {w for w, c in df.items() if c / len(items) > rate}
    for it in items:
        it["_sig"] = {"in_life": [unit(x, common) for x in it.get("in_life", [])],
                      **{f: unit(it.get(f, "") or "", common) for f in FIELDS}}
    return items, len(common)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--common", type=float, default=0.04, help="слово чаще этой доли текстов считается общим")
    a = ap.parse_args()
    items, n = sign(json.load(open(a.src, encoding="utf-8")), a.common)
    json.dump(items, open(a.dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(items)} texts signed -> {a.dst} ({n} common words)")


if __name__ == "__main__":
    main()
