"""Формы, выдающие род читателя, в русском тексте — по морфологии (pymorphy3), без LLM.

Отчёт читают люди любого пола. Ловим предикаты о читателе в мужском или женском роде:
  «быть услышанным», «становитесь холодным», «чувствуете себя живым», «делает вас щедрым»,
  «вы первым замечаете», «тащить одному», «вы такой», «таким, какой вы есть», «я сам», «я решил».
Не трогаем согласование с существительным («тёплым тоном», «первым делом»), предложные
обороты («с другим»), субстантивы мн. ч. («окружающим») и связки с другим подлежащим
(«авторитет мог быть подавляющим»).
"""
import re
from functools import lru_cache

import pymorphy3

_M = pymorphy3.MorphAnalyzer()
WORD = re.compile(r"[а-яё]+(?:-[а-яё]+)*")
TOK = re.compile(r"[а-яёА-ЯЁ]+(?:-[а-яёА-ЯЁ]+)*|[.!?…,;:—–()«»\"]")

COPULA = set("""быть будьте побыть стать станьте становиться становитесь стали станете казаться кажетесь показаться
оказаться оказываетесь окажетесь оставаться остаётесь остаетесь остаться останетесь оставайтесь выглядеть выглядите
бываете будете были родиться вырасти выходите выйти возвращаетесь приходите просыпаетесь
оставаясь становясь будучи оказавшись оставшись став""".split())
OBJ = {"вас", "себя"}                      # «делает вас щедрым», «чувствуете себя живым»
PREP = {"для", "у", "от", "без", "до", "из", "около", "о", "об", "с", "со", "к", "ко", "про", "на", "в", "во", "за",
        "через", "перед", "при", "кроме", "вокруг"}
IMPERSONAL = {"хочется", "хотелось", "приходится", "приходилось", "удаётся", "удается", "получается", "стоит",
              "следует", "важно", "нужно", "трудно", "легко", "страшно", "проще", "сложно"}
SOFT = {"не", "бы", "уже", "ещё", "просто", "легко", "всегда", "снова", "вдруг", "даже"}
ORDINAL = {"первым", "последним", "единственным", "первыми", "последними", "единственными"}
DATIVE_SELF = {"одному", "самому"}         # «тащить одному», «справляться самому»
POSSESSIVE = {"ваш", "мой", "наш", "твой"}   # «чужое настроение может стать вашим» — не о роде читателя
FILLER = {"не", "ни", "ещё", "уже", "всё", "же", "тоже", "ведь", "и", "так", "очень", "совсем", "вовсе"}
PATTERNS = [
    re.compile(r"\bкак(?:ой|ая)\s+вы\s+есть\b", re.I),                                  # «таким, какой вы есть»
    re.compile(r"\b(?:вам|вас)\s+сам(?:ому|ого|ой)\b|\bсам(?:им|ой)\s+собой\b", re.I),  # «вам самому», «быть самим собой»
]


@lru_cache(maxsize=None)
def _parse(w):
    return tuple(_M.parse(w))


def _has(w, pos=None, gr=()):
    return any((pos is None or p.tag.POS in pos) and set(gr) <= p.tag.grammemes for p in _parse(w))


def _gendered(w):
    """может быть м. р. ед. ч. творит. (или ж. р. ед. ч. творит.) прилагательного/причастия; не местоимение-сущ."""
    if _has(w, ("NPRO",)) or any(p.tag.POS == "NOUN" and "Pltm" in p.tag.grammemes for p in _parse(w)) \
            or any(p.normal_form in POSSESSIVE for p in _parse(w)):
        return False
    return _has(w, ("ADJF", "PRTF"), ("masc", "sing", "ablt")) or \
        (w.endswith(("ой", "ей")) and _has(w, ("ADJF", "PRTF"), ("femn", "sing", "ablt")))


ROLE_OK = {"человек", "люди", "ребёнок", "ребенок", "дети", "существо"}


def _plural_pred(w):
    """полное прилагательное/причастие мн. ч. творит.: «вас считают холодными», «быть отвергнутыми»"""
    if _has(w, ("NPRO",)) or any(p.tag.POS == "NOUN" and "Pltm" in p.tag.grammemes for p in _parse(w)) \
            or any(p.normal_form in POSSESSIVE for p in _parse(w)):
        return False
    return w.endswith(("ыми", "ими")) and _has(w, ("ADJF", "PRTF"), ("plur", "ablt"))


def _role_noun(w):
    """одушевлённое существительное-роль в творит.: «стать наставником», «вас называют чудаком»"""
    ps = _parse(w)
    return any(p.tag.POS == "NOUN" and {"anim", "ablt"} <= p.tag.grammemes and p.normal_form not in ROLE_OK
               and "Name" not in p.tag.grammemes for p in ps) and not _has(w, ("ADJF", "PRTF", "NPRO"))


def _passable(w):
    """может стоять между связкой и предикатом: наречие, частица, «кому-то», однородный предикат, союз"""
    return w in ("и", "или", "не", "ни", "то") or _has(w, ("ADVB", "PRCL", "COMP")) or \
        _has(w, ("NPRO",), ("datv",)) or _gendered(w) or _plural_pred(w)


def _other_subject(low, j):
    """перед связкой глагол 3-го лица/прош. ед. ч. — подлежащее не читатель («авторитет мог быть …»)"""
    k = j - 1
    while k >= 0 and low[k] in SOFT:
        k -= 1
    if k < 0 or not WORD.fullmatch(low[k]) or low[k] in IMPERSONAL:
        return False
    w = low[k]
    if any(p.tag.POS in ("ADJS", "PRTS") and "plur" in p.tag.grammemes for p in _parse(w)):
        return False                                   # «вы должны быть …» — читатель
    return _has(w, ("VERB",), ("3per",)) or (_has(w, ("VERB",), ("past", "sing")) and not _has(w, ("VERB",), ("plur",))) \
        or _has(w, ("ADJS", "PRTS"), ("sing",))        # «союз должен оставаться живым»


def _noun(w):
    """существительное, а не предлог/союз/частица («с», «и» pymorphy умеет читать и как сокращения)"""
    return bool(WORD.fullmatch(w or "-")) and _has(w, ("NOUN",)) and \
        not (len(w) <= 2 and _has(w, ("PREP", "CONJ", "PRCL", "INTJ")))


def _attributive(low, i):
    """за словом идёт существительное (через 0–2 согласованных прилагательных): «тёплым тоном», «одному такому желанию»"""
    k = i + 1
    while k < len(low) and k <= i + 3 and WORD.fullmatch(low[k]):
        if low[k] == "собой":
            return False
        if _noun(low[k]):
            return True
        if not _has(low[k], ("ADJF", "PRTF")):
            return False
        k += 1
    return False


def _sing_nominal(w):
    """ед. ч., выдающее род: «я решил», «я хорош», «вы маленький», «вы сама», «вы один»"""
    ps = _parse(w)
    if any(p.tag.POS in ("ADJF", "ADJS", "PRTS", "VERB", "PRTF") and "plur" in p.tag.grammemes for p in ps):
        return False                                    # «вы готовы», «вы решили» — нейтрально
    return any((p.tag.POS == "VERB" and "past" in p.tag.grammemes and ({"masc", "femn"} & p.tag.grammemes)) or
               (p.tag.POS in ("ADJS", "PRTS") and "sing" in p.tag.grammemes and ({"masc", "femn"} & p.tag.grammemes)) or
               (p.tag.POS == "ADJF" and {"sing", "nomn"} <= p.tag.grammemes and ({"masc", "femn"} & p.tag.grammemes))
               for p in ps)


def _pronoun_predicates(low, toks):
    """«вы такой», «вы маленький взрослый», «я думал», «я недостаточно хорош», «я могу сам»"""
    out = []
    for i, w in enumerate(low):
        if w not in ("вы", "я"):
            continue
        k, seen = i + 1, 0
        while k < len(low) and seen < 3 and WORD.fullmatch(low[k]):
            t = low[k]
            if t not in FILLER:
                seen += 1
                if _sing_nominal(t) and not (_has(t, ("ADJF",)) and _attributive(low, k)):
                    out.append(" ".join(toks[i:k + 1]))
                    break
                if w == "вы" and t not in ("сами", "все") and _has(t, ("ADJF",), ("plur", "nomn")) \
                        and not _has(t, ("ADJS", "PRTS", "VERB", "NPRO")) and not _attributive(low, k):
                    out.append(" ".join(toks[i:k + 1]))     # «вы первые», «вы спокойные» — полная форма о читателе
                    break
                if w == "вы" or not _has(t, ("VERB", "INFN", "ADVB", "PRED")):
                    break                               # после «я» пропускаем глагол/наречие: «я могу сам»
            k += 1
    return out


def _bare_short_questions(low, toks):
    """краткая форма без подлежащего в вопросе к читателю: «Спросите себя: готов ли …»"""
    out = []
    for i, w in enumerate(low[:-2]):
        after = low[i + 2]
        if low[i + 1] == "ли" and (i == 0 or not WORD.fullmatch(low[i - 1])) and \
                (after == "я" or (WORD.fullmatch(after) and _has(after, ("INFN",)))) and \
                any(p.tag.POS in ("ADJS", "PRTS") and "sing" in p.tag.grammemes and ({"masc", "femn"} & p.tag.grammemes)
                    for p in _parse(w)):
            out.append(f"{toks[i]} ли")
    return out


def gender_hits(text: str) -> list[str]:
    hits = [m.group(0) for rx in PATTERNS for m in rx.finditer(text)]
    toks = TOK.findall(text)
    low = [t.lower() for t in toks]
    hits += _pronoun_predicates(low, toks) + _bare_short_questions(low, toks)
    for i, w in enumerate(low):
        if len(w) < 4 or not WORD.fullmatch(w):
            continue
        dative = w in DATIVE_SELF
        adj = _gendered(w)
        weak = not adj and not dative and (_plural_pred(w) or _role_noun(w))   # только после связки/«вас»/«себя»
        if not (adj or dative or weak):
            continue
        if not _role_noun(w) and _attributive(low, i):
            continue                                   # «тёплым тоном», «одному человеку»
        k = i - 1
        while k >= 0 and WORD.fullmatch(low[k]) and _has(low[k], ("ADJF", "PRTF")) and not _has(low[k], ("PREP",)):
            k -= 1
        if k >= 0 and WORD.fullmatch(low[k]) and _has(low[k], ("PREP",)):
            continue                                   # «с другим», «по одному», «с самым первым»
        if (dative or w in ORDINAL) and not _role_noun(w):
            nxt = low[i + 1] if i + 1 < len(low) else ""
            if WORD.fullmatch(nxt or "-") and _has(nxt, ("VERB",), ("3per",)):
                continue                               # «первым приходит «нет»» — подлежащее не читатель
            if not _other_subject(low, i) and not (i and low[i - 1] in ("его", "её", "ее", "их", "ему", "ей", "им")):             # «способ становится единственным» — не о читателе
                hits.append(" ".join(toks[max(0, i - 1):i + 1]))
            continue
        j = i - 1
        while j >= 0 and j >= i - 4 and WORD.fullmatch(low[j]):
            t = low[j]
            if t in OBJ and not (j and low[j - 1] in PREP) and i - j <= 2:
                if not (t == "себя" and _other_subject(low, j)):   # «партнёр чувствует себя интересным»
                    hits.append(" ".join(toks[j:i + 1]))
                break
            if t in COPULA:
                if t in ("стали", "были", "будут", "станут") and j and WORD.fullmatch(low[j - 1]) \
                        and _has(low[j - 1], ("NOUN",), ("nomn",)) and low[j - 1] != "вы":
                    break                              # «перемены стали знакомым …» — подлежащее не читатель
                if j and WORD.fullmatch(low[j - 1]) and _has(low[j - 1], ("NOUN",), ("datv",)):
                    break                              # «позволяете жизни быть спокойной» — подлежащее не читатель
                if not _other_subject(low, j):
                    hits.append(" ".join(toks[j:i + 1]))
                break
            if not _passable(t):
                # «вас называют спокойными», «вас считают холодным»: вас/себя + глагол + предикат
                if _has(t, ("VERB",)) and j >= 1 and low[j - 1] in OBJ and not (j >= 2 and low[j - 2] in PREP) \
                        and not (low[j - 1] == "себя" and _other_subject(low, j - 1)):
                    hits.append(" ".join(toks[j - 1:i + 1]))
                break
            j -= 1
    return hits
