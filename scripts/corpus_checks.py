"""Проверки корпуса целиком (без LLM): шаблонность и переклички между текстами.

Тексты идут по порядку: сначала контекст (уже принятые), потом проверяемые. Проверяемый текст
проваливается, если именно он переходит предел — контекст никогда не проваливается, но считается.

  opener   — одинаковое начало поля (title/strength/shadow/action — первое значимое слово, body — два) чаще 2% корпуса;
  phrase   — оборот из 2–3 слов (по леммам) встречается чаще чем в 6% текстов («под нагрузкой», «заметить это можно»);
  echo     — с более ранним текстом ≥ 2 общих оборотов из 5 слов (почти одинаковые фразы в одном отчёте);
  inner    — внутри текста body и другое поле повторяют оборот из 5 слов;
  title    — заголовок уже занят;
  inner opener — начало 2-го и последнего предложения поля чаще 4% («Признак —», «Задача —», «Поэтому»);
  shape    — поле в форме «ярлык: пояснение» чаще чем в 15% текстов;
  group    — оборот повторяется больше чем в 12% текстов одного вида (имена тел и знаков обобщены);
  sentence — начало любого предложения body чаще 1.5% корпуса («Обратная сторона», «Риск в том»);
  action   — оборот поля action чаще 2% корпуса («раз в неделю», «три шага»);
  gopener  — начало body повторяет каркас своего вида чаще 15% («когда <тело> …, выручает <тело>»);
  brief    — текст пересказывает бриф (общие обороты из 4 слов);
  similar  — заголовок почти как у другого текста (75% общих слов).
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from functools import lru_cache

import pymorphy3

_M = pymorphy3.MorphAnalyzer()
WORDS = re.compile(r"[а-яё]+")                     # русский текст: леммы pymorphy (латиница вроде «MC» не в счёт)
WORDS_EN = re.compile(r"[a-z]+(?:'[a-z]+)?")         # английский текст: основы Snowball
FUNC = set("""и а но или да же ли бы не ни что чтобы как когда если где куда пока хотя будто словно тоже также лишь только
вы вас вам вами ваш ваша ваше ваши себя себе собой я он она оно они его её ее их ему ей им ним ней нём мы нас нам
это этот эта эти тот та то те такой такая такие который которая которое которые свой своя своё свои
весь вся всё все сам сама сами один одна одно одни быть есть уже ещё очень более менее так там тут здесь
в во на с со к ко по за из у о об от до для при под над без про через между перед чем
мочь уметь хотеть стать становиться давать делать сделать говорить сказать знать видеть иметь казаться
легко часто долго быстро обычно скорее хорошо трудно важно можно нужно потом наоборот почти иногда всегда снова сразу
даже потому кто где чем прежде большой ранний сильный другой друг кто-то что-то тем рядом вместо именно дело жизнь""".split())
# английские служебные слова — в той же форме, что и слова текста (основа Snowball)
FUNC_EN_WORDS = """and but or so not no nor if when where while that which who whom whose what how as than then too also only
just even you your yours yourself yourselves i me my he him his she her it its we us our they them their this these those
the a an all some any each every own same other such be is are was were been being am do does did done have has had having
can could will would may might must shall should to of in on at by for with about from into onto over under through
between before after without within up down out off again very more most less much many there here often usually easily
rather almost always sometimes never once now still already get gets got make makes let lets one something someone
anything anyone everything everyone way thing things life it's don't doesn't isn't can't won't you're you've you'll""".split()
FIELDS_FIRST = {"title": 1, "body": 2, "strength": 1, "shadow": 1, "action": 1}
RATE_OPENER, RATE_PHRASE, MIN_OPENER, MIN_PHRASE = 0.02, 0.06, 3, 5
RATE_INNER_OPENER = 0.04      # начала второго и последнего предложений поля («Признак —», «Задача —», «Поэтому»)
RATE_SHAPE = 0.15             # форма поля «ярлык: пояснение» / «ярлык — пояснение»
RATE_GROUP_PHRASE, MIN_GROUP = 0.12, 20   # оборот внутри одного вида ключей (все тригоны, все рецепции …)
RATE_SENT_START = 0.015       # начало любого предложения body (два слова): «Обратная сторона», «Риск в том»
RATE_ACTION_PHRASE = 0.02     # оборот в полях action/shadow/strength («раз в неделю», «узнать это можно»)
RATE_LAST_LABEL = 0.03        # последнее предложение body в форме «Риск — …», «Обратная сторона: …»
RATE_GROUP_OPENER = 0.15      # начало body внутри одного вида — с заменой имён тел и знаков на <тело>/<знак>
RATE_ACTION_KIND = 0.05       # доля одного вида совета (action_kind) во всём корпусе
RATE_ACTION_FAMILY = 0.09     # доля семейства видов (одно действие для читателя: писать, говорить о себе, выжидать)
TITLE_SIMILAR = 0.75          # заголовки с почти одинаковым набором слов
BODIES = set("""солнце луна меркурий венера марс юпитер сатурн уран нептун плутон раху кету лилит хирон асцендент
mc узел""".split())
SIGNS = set("""овен телец близнецы рак лев дева весы скорпион стрелец козерог водолей рыба рыбы""".split())


def norm(ls):
    return ["<тело>" if w in BODIES else "<знак>" if w in SIGNS else w for w in ls]
SENT = re.compile(r"(?<=[.!?…])\s+")
LABEL = re.compile(r"^\s*([^.:;!?—–]{1,40}?)\s*[:—–]\s+\S")


def group_of(key: str) -> str:
    kind, *p = key.split(":")
    return f"aspect:{p[1]}" if kind == "aspect" else f"{kind}:{p[0]}" if kind in ("element", "modality") else kind


@lru_cache(maxsize=None)
def lemma(w: str) -> str:
    return _M.parse(w)[0].normal_form


@lru_cache(maxsize=None)
def _stem(w: str) -> str:
    import snowballstemmer        # только для английских текстов
    w = w[:-2] if w.endswith("'s") else w          # притяжательное: «Uranus's» → «Uranus»
    return snowballstemmer.stemmer("english").stemWord(w.replace("'", ""))


CYR, LAT = re.compile(r"[а-яё]"), re.compile(r"[a-z]")


def lang_of(text: str) -> str:
    """язык — по письму текста: больше кириллицы — русский, иначе английский"""
    t = text.lower()
    return "ru" if len(CYR.findall(t)) >= len(LAT.findall(t)) else "en"


def lemmas(text: str) -> list[str]:
    t = text.lower()
    if lang_of(t) == "ru":
        return [lemma(w) for w in WORDS.findall(t)]
    return [_stem(w) for w in WORDS_EN.findall(t)]


try:        # английские служебные слова, имена тел и знаков — основами, как и слова английских текстов
    FUNC |= {_stem(w) for w in FUNC_EN_WORDS}
    BODIES |= {_stem(w) for w in "sun moon mercury venus mars jupiter saturn uranus neptune pluto rahu ketu lilith chiron ascendant node".split()}
    SIGNS |= {_stem(w) for w in "aries taurus gemini cancer leo virgo libra scorpio sagittarius capricorn aquarius pisces".split()}
except ImportError:
    pass


def _content(g) -> int:
    return sum(1 for w in g if w not in FUNC and len(w) > 2)


def grams(ls: list[str], n: int, min_content: int) -> set[str]:
    return {" ".join(ls[i:i + n]) for i in range(len(ls) - n + 1) if _content(ls[i:i + n]) >= min_content}


def item_text(it: dict) -> str:
    return " ".join([it["body"], it["strength"], it["shadow"], it["action"], *it["in_life"]])


def check_corpus(context: list[dict], focus: list[dict], label=lambda k: "", kinds: dict | None = None,
                 expected: int = 0, expected_keys: list[str] | None = None) -> dict[str, list[str]]:
    """-> {key: [ошибки]} только для focus; kinds — {код вида совета: {"label", "family"}} из advice_kinds"""
    # короткие тексты прогноза без полей strength/shadow проверяются по тем полям, что есть
    fill = lambda it: {**it, **{f: it.get(f) or "" for f in ("strength", "shadow")}}
    allitems = [(fill(it), False) for it in context] + [(fill(it), True) for it in focus]
    # пределы считаются от итогового размера корпуса: пока он пишется параллельно, ранние тексты не душит минимум
    n = max(len(allitems), expected)
    lim_open = max(MIN_OPENER, math.ceil(RATE_OPENER * n))
    lim_phrase = max(MIN_PHRASE, math.ceil(RATE_PHRASE * n))
    lim_inner = max(MIN_OPENER, math.ceil(RATE_INNER_OPENER * n))
    lim_shape = max(MIN_OPENER, math.ceil(RATE_SHAPE * n))
    gsize = Counter(group_of(it.get("key", "")) for it, _ in allitems)
    for g, c in Counter(group_of(k) for k in expected_keys or []).items():   # и вид ключей — от итогового размера
        gsize[g] = max(gsize[g], c)
    gphrase: Counter = Counter()
    lim_sent = max(MIN_PHRASE, math.ceil(RATE_SENT_START * n))
    lim_action = max(MIN_PHRASE, math.ceil(RATE_ACTION_PHRASE * n))
    sent_starts: Counter = Counter()
    action_df: Counter = Counter()
    gopen: Counter = Counter()
    title_sets: list[tuple[set, str]] = []
    errs: dict[str, list[str]] = defaultdict(list)
    openers: Counter = Counter()
    phrase_df: Counter = Counter()
    titles: dict[str, str] = {}
    five_idx: dict[str, set[str]] = defaultdict(set)
    for it, is_focus in allitems:
        key = it.get("key")
        if not all(isinstance(it.get(f), str) for f in FIELDS_FIRST) or not isinstance(it.get("in_life"), list):
            continue
        own = set(lemmas(label(key).split(" :: ")[1] if " :: " in label(key) else label(key))) if label else set()
        # opener
        for f, k in FIELDS_FIRST.items():
            ls = lemmas(it[f])
            k += sum(1 for w in ls[:k] if w in FUNC)        # «Вы умеете», «Когда вы …» — служебное слово не в счёт
            ls = ls[:k]
            if len(ls) < k:
                continue
            o = f"{f}:{' '.join(ls)}"
            openers[o] += 1
            if is_focus and openers[o] > lim_open:
                errs[key].append(f"шаблонное начало {f}: «{' '.join(it[f].split()[:k])}» (уже {openers[o] - 1} раз)")
        # начала второго и последнего предложений и форма «ярлык: …»
        for f in ("body", "strength", "shadow", "action"):
            sents = [x for x in SENT.split(it[f].strip()) if x]
            pos = {"2-го": sents[1]} if len(sents) > 1 else {}
            if len(sents) > 2:
                pos["последнего"] = sents[-1]
            for where, sent in pos.items():
                ls = [w for w in lemmas(sent) if w not in FUNC][:1]
                if not ls:
                    continue
                o = f"{f}:{where}:{ls[0]}"
                openers[o] += 1
                if is_focus and openers[o] > lim_inner:
                    errs[key].append(f"шаблонное начало {where} предложения {f}: «{' '.join(sent.split()[:2])}» "
                                     f"(уже {openers[o] - 1} раз)")
            m = LABEL.match(it[f])
            if m and len(m.group(1).split()) <= 4:
                o = f"{f}:shape:label"
                openers[o] += 1
                if is_focus and openers[o] > lim_shape:
                    errs[key].append(f"шаблонная форма {f}: «ярлык{it[f][m.end(1):m.end(1) + 1]} …» (уже {openers[o] - 1} раз)")
        # начала всех предложений body (два значимых слова)
        for sent in [x for x in SENT.split(it["body"].strip()) if x][1:]:
            w = [x for x in lemmas(sent) if x not in FUNC][:2]
            if len(w) == 2:
                o = " ".join(w)
                sent_starts[o] += 1
                if is_focus and sent_starts[o] > lim_sent:
                    errs[key].append(f"шаблонное начало предложения в body: «{' '.join(sent.split()[:3])}» (уже {sent_starts[o] - 1} раз)")
                    break
        # обороты коротких полей (action, shadow, strength) — по каждому полю отдельно
        for f in ("action", "shadow", "strength"):
            la = lemmas(it[f])
            ahot = []
            for g in grams(la, 2, 1) | grams(la, 3, 1):
                if set(g.split()) <= FUNC | own:
                    continue
                action_df[(f, g)] += 1
                if is_focus and action_df[(f, g)] > lim_action:
                    ahot.append(g)
            if ahot:
                errs[key].append(f"шаблонный оборот в {f}: " + "; ".join(
                    f"«{g}» ×{action_df[(f, g)] - 1}" for g in sorted(ahot, key=lambda g: -action_df[(f, g)])[:2]))
        # последнее предложение body — формула «Риск — …»
        ss = [x for x in SENT.split(it["body"].strip()) if x]
        mm = LABEL.match(ss[-1]) if len(ss) > 1 else None
        if mm and len(mm.group(1).split()) <= 3:
            openers["body:last:label"] += 1
            if is_focus and openers["body:last:label"] > max(MIN_OPENER, math.ceil(RATE_LAST_LABEL * n)):
                errs[key].append(f"body заканчивается формулой «{mm.group(1)} —»")
        # начало body внутри вида — без имён тел и знаков
        grp0 = group_of(key or "")
        if gsize[grp0] >= MIN_GROUP:
            w = [x for x in norm(lemmas(it["body"])) if x not in FUNC][:3]
            if len(w) == 3:
                o = (grp0, " ".join(w))
                gopen[o] += 1
                if is_focus and gopen[o] > max(MIN_OPENER, math.ceil(RATE_GROUP_OPENER * gsize[grp0])):
                    errs[key].append(f"начало body повторяет каркас вида {grp0}: «{' '.join(it['body'].split()[:4])}…»")
        # пересказ брифа
        br = label(key) if label else ""
        if is_focus and " :: " in br:
            b4 = grams(lemmas(br.split(" :: ", 2)[-1]), 4, 2)
            if b4 & grams(lemmas(item_text(it)), 4, 2):
                errs[key].append("пересказ брифа: " + "; ".join(f"«{g}»" for g in sorted(b4 & grams(lemmas(item_text(it)), 4, 2))[:2]))
        # почти одинаковые заголовки
        tl = {x for x in lemmas(it["title"]) if x not in FUNC}
        if is_focus and len(tl) >= 2:
            for other_set, other_key in title_sets:
                if len(tl & other_set) / len(tl | other_set) >= TITLE_SIMILAR:
                    errs[key].append(f"заголовок почти как у {other_key}")
                    break
        if len(tl) >= 2:
            title_sets.append((tl, key))
        # title
        t = it["title"].strip().lower()
        if t in titles and is_focus:
            errs[key].append(f"заголовок уже занят: {titles[t]}")
        titles.setdefault(t, key)
        ls = lemmas(item_text(it))
        # phrase
        g23 = {g for g in grams(ls, 2, 1) | grams(ls, 3, 1) if not set(g.split()) <= own | FUNC}   # термины из названия не в счёт
        nls = norm(ls)
        g23n = {g for g in grams(nls, 2, 1) | grams(nls, 3, 1)
                if not set(g.split()) <= FUNC | {"<тело>", "<знак>"} | set(norm(list(own)))}   # термины названия не в счёт
        hot = []
        for g in g23:
            phrase_df[g] += 1
            if is_focus and phrase_df[g] > lim_phrase and _content(g.split()) >= 1:
                hot.append(g)
        if hot:
            hot.sort(key=lambda g: -phrase_df[g])
            errs[key].append("избитый оборот: " + "; ".join(f"«{g}» ×{phrase_df[g] - 1}" for g in hot[:3]))
        grp = group_of(key or "")
        if gsize[grp] >= MIN_GROUP:
            lim_g = max(MIN_PHRASE, math.ceil(RATE_GROUP_PHRASE * gsize[grp]))
            ghot = []
            for g in g23n:
                gphrase[(grp, g)] += 1
                if is_focus and gphrase[(grp, g)] > lim_g and _content([w for w in g.split() if w[0] != "<"]) >= 1:
                    ghot.append(g)
            if ghot:
                ghot.sort(key=lambda g: -gphrase[(grp, g)])
                errs[key].append(f"оборот, повторяющийся в текстах вида {grp}: "
                                 + "; ".join(f"«{g}» ×{gphrase[(grp, g)] - 1}" for g in ghot[:3]))
        # echo
        five = grams(ls, 5, 3)
        if is_focus:
            hits = Counter(k for g in five if g in five_idx for k in five_idx[g] if k != key)
            if hits:
                other, c = hits.most_common(1)[0]
                if c >= 2:
                    errs[key].append(f"перекличка с {other}: {c} общих оборота из 5 слов")
        for g in five:
            five_idx[g].add(key)
        # inner
        if is_focus:
            body5 = grams(lemmas(it["body"]), 5, 3)
            for f in ("strength", "shadow", "action"):
                if body5 & grams(lemmas(it[f]), 5, 3):
                    errs[key].append(f"повтор внутри текста: body и {f}")
                    break
    if kinds:
        fam_of = lambda k: kinds[k]["family"] if k in kinds else None
        kind_n = Counter(it.get("action_kind") for it, _ in allitems)
        fam_n = Counter(fam_of(it.get("action_kind")) for it, _ in allitems)
        fam_size = Counter(v["family"] for v in kinds.values())
        lim_kind = max(MIN_PHRASE, math.ceil(RATE_ACTION_KIND * n))
        lim_fam = max(MIN_PHRASE, math.ceil(RATE_ACTION_FAMILY * n))
        for it, is_focus in allitems:
            k = it.get("action_kind")
            if not is_focus or k not in kinds:
                continue
            f = fam_of(k)
            if kind_n[k] > lim_kind:
                errs[it.get("key")].append(f"вид совета «{kinds[k]['label']}» уже в {kind_n[k]} текстах из {n} (предел {lim_kind}) — "
                                           "выберите действие, которое следует именно из этого положения")
            elif fam_size[f] > 1 and fam_n[f] > lim_fam:
                same = ", ".join(v["label"] for v in kinds.values() if v["family"] == f)
                errs[it.get("key")].append(f"советы одного рода ({same}) уже в {fam_n[f]} текстах из {n} (предел {lim_fam}) — "
                                           "выберите действие другого рода, которое следует именно из этого положения")
    return dict(errs)
