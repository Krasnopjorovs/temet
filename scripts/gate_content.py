"""Гейт качества текстов отчёта — без LLM, только правила.

Жёсткие проверки (провал = текст на перегенерацию):
  ключ из словаря доктрины; все поля; длина и число предложений; обращение на «вы»
  (нет «ты», глаголов 2-го лица ед. числа и типичных повелительных форм на «ты»);
  нейтральность к полу читателя (морфология, scripts/ru_gender.py: «быть услышанным», «делает вас щедрым»,
  «вы первым», «я решил» — провал);
  запрещённые обещания и советы (медицина, финансы, предсказания).
Корпус (scripts/corpus_checks.py, вместе с --context): шаблонные начала полей, избитые обороты,
переклички между текстами, повторы внутри текста, занятые заголовки.

python -m scripts.gate_content new/*.json [--context accepted/*.json] [--fail-list failed.txt] [--quiet]
Код выхода 1, если есть жёсткие провалы.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

from astro.doctrine import load_yaml
from astro.brief import FORECAST_KINDS, brief, forecast_text_long, load_stats
from astro.rules import key_space
from scripts.corpus_checks import check_corpus, lemmas
from scripts.ru_gender import _M as MORPH, gender_hits

RULES = {
    "title_words": (2, 9),
    "body_chars": (250, 1500),
    "body_sentences": (3, 8),
    "in_life": (2, 4),
    "field_chars": (25, 420),
}
TY = re.compile(r"\b(ты|тебя|тебе|тобой|твой|твоя|твоё|твое|твои|твоего|твоей|твоих|твоим|твоими|твою|сам себе)\b", re.I)
SG2 = re.compile(r"\b[а-яё]{2,}(ешь|ёшь|ишь)(ся)?\b", re.I)
SG2_OK = {"лишь", "мышь", "тишь", "глушь", "малышь", "камыш", "фетиш", "кишь"}
IMP = re.compile(r"\b(попробуй|задай|спроси|сделай|подумай|запиши|вспомни|помни|позволь|дай|найди|обрати|выбери|"
                 r"отметь|назови|скажи|начни|оставь|составь|проверь|посмотри|попроси|раздели|договорись|"
                 r"остановись|позаботься|откажись|научись|разреши|признай|напиши|выпиши|определи|сформулируй|"
                 r"представь|ответь|отпусти|прими|замечай|наблюдай|следи|береги|старайся|учись|держи)\b", re.I)
# только с начала слова: «лечение» — да, «увлечение» — нет
BANNED = re.compile(r"(судьба предрешена|вам суждено|обязательно случится|непременно произойд|\bгарантир|"
                    r"\bдиагноз|\bлекарств|\bлечени|\bинвестир|\bинвестиц|\bкредит(?!ор)|\bразвед[её]т|\bумр[её]т)", re.I)
QUOTED = re.compile(r"«[^»]*»")
ASPECT_LEMMA = {"CONJ": "соединение", "OPP": "оппозиция", "TRI": "тригон", "SQR": "квадрат", "SXT": "секстиль"}
# словари задаются словами и приводятся тем же лемматизатором, что и текст («напряжённых» → «напрячь»)
_L = lambda *words: {x for w in words for x in lemmas(w)}
GENERATION = _L("поколение", "ровесник", "сверстник", "одногодка", "одногодок")
BORN = re.compile(r"\bкто\s+(?:\w+\s+)?(?:родил|появил)\w*|\bродивш\w+|\bпоявил\w*\s+на\s+свет|"
                  r"\bв\s+те\s+же\s+(?:месяц|год|сезон|недел)\w*|\bтого\s+же\s+(?:года|сезона)|"
                  r"\bдержит(?:ся)?\s+(?:в\s+знаке\s+)?(?:около|примерно|почти|всего)?\s*\S*\s*(?:лет|года?|месяц\w*|недел\w*)\b", re.I)
HYPO = re.compile(r"[^.!?]*\bбы\b[^.!?]*", re.I)
ASPECT_WORDS = _L("аспект", "угол", "соединение", "квадрат", "тригон", "оппозиция", "секстиль", "слияние", "противостояние")
SOFT_HARD = _L("мягкий", "напряжённый", "плавный", "гармоничный", "жёсткий", "лёгкий", "острый")
YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b|\b\d0-[хе]\b")
# сравнение с другими аспектами той же пары: предложение называет пару и другой её аспект
# («в отличие от напряжённых аспектов этой пары», «при мягких связях Солнца и Урана», «другие связи этих планет»)
ASPECT_NOUNS = ASPECT_WORDS | _L("связь", "сочетание", "контакт")
CMP_ADJ = _L("другой", "иной", "остальной")
CMP_ANY = _L("отличие", "отличаться")
KIND_ADJ = {"soft": _L("мягкий", "плавный", "гармоничный", "лёгкий"),
            "hard": _L("напряжённый", "жёсткий", "острый")}

OWN_KIND = {"TRI": "soft", "SXT": "soft", "SQR": "hard", "OPP": "hard"}
PAIR_REF = (_L("пара"), _L("планета", "точка"))
# служебные слова синтеза из брифа: читатель не знает, что такое «ось» и «полюс» отчёта
SYNTH_JARGON = _L("полюс", "ось")
# отсылка к деталям карты, которых в тексте нет («тон задают знак и дом, где стоит пара»)
CHART_REF = (_L("знак", "дом"), _L("где", "какой", "который"))
MIXED = re.compile(r"[а-яё][a-z]|[a-z][а-яё]", re.I)   # «Саturn»: латиница внутри русского слова
FIELDS = ("title", "body", "strength", "shadow", "action")
# требования к тексту по виду ключа: натальный; прогноз — короткий (быстрые влияния) и полный (медленные, затмения, прогрессии)
PROFILES = {
    "natal": {**RULES, "fields": FIELDS, "axes": True},
    "forecast_short": {"title_words": (2, 7), "body_chars": (110, 600), "body_sentences": (2, 4), "in_life": (2, 3),
                       "field_chars": (25, 300), "fields": ("title", "body", "action"), "axes": False},
    "forecast_long": {"title_words": (2, 7), "body_chars": (330, 1300), "body_sentences": (4, 7), "in_life": (2, 3),
                      "field_chars": (25, 420), "fields": FIELDS, "axes": False},
}
# даты, сроки и повторяемость показывает страница прогноза, не текст
FC_TIME = re.compile(r"\b(раз в (?:год|месяц|недел\w*|\d+)|кажд(?:ый|ую|ое) (?:год|месяц|недел\w*|лет)|"
                     r"(?:\d+|два|две|три|четыре|пять|пару|несколько|полтора|полгода)\s+(?:дн\w*|сут\w*|недел\w*|месяц\w*|лет|год\w*)|"
                     r"январ\w*|феврал\w*|март\w*|апрел\w*|ма[яе]\b|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|"
                     r"понедельник\w*|вторник\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)", re.I)   # «среда» — и окружение


# ключи, где планета не задана заранее (управитель дома, правило, синтез): у неё нет известного рода
VARIABLE_BODY = ("ruler:", "rule:", "synth:", "element:", "modality:")
FEM_AGENT = re.compile(r"\b(хозяйк\w*|повелительниц\w*|владычиц\w*|госпож\w*|королев\w*)\b", re.I)


def profile(key: str | None, d) -> dict:
    kind = (key or "").split(":")[0]
    if kind in FORECAST_KINDS:
        return PROFILES["forecast_long" if forecast_text_long(key, d) else "forecast_short"]
    return PROFILES["natal"]


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if len(s) > 3])


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?…;:])\s+", text) if x.strip()]


def _near(ls: list[str], first: set, then: set, gap: int = 2) -> bool:
    return any(w in first and set(ls[i + 1:i + 1 + gap]) & then for i, w in enumerate(ls))


def pair_comparison(key: str, text: str, names: dict | None = None) -> str | None:
    """предложение аспектного текста, сравнивающее аспект с другими аспектами той же пары"""
    a, asp, b = key.split(":")[1:4]
    # у соединения нет «мягкости» или «напряжённости»: любая такая связь пары — уже другой аспект
    other_kind = {"soft": KIND_ADJ["hard"], "hard": KIND_ADJ["soft"]}.get(OWN_KIND.get(asp), KIND_ADJ["soft"] | KIND_ADJ["hard"])
    own_nouns = _L(ASPECT_LEMMA.get(asp, ""), *(["слияние"] if asp == "CONJ" else []))
    pair_names = [set(lemmas(n)) for n in ((names or {}).get(a, ""), (names or {}).get(b, ""))]
    for sent in _sentences(text):
        ls = lemmas(sent)
        sl = set(ls)
        named = sl & PAIR_REF[0] or _near(ls, {"этот"}, PAIR_REF[1], 1) or all(n and n <= sl for n in pair_names)
        if not named or not sl & ASPECT_NOUNS:
            continue
        if (_near(ls, CMP_ADJ, ASPECT_NOUNS) or sl & CMP_ANY or _near(ls, other_kind, ASPECT_NOUNS - own_nouns)
                or (sl & (set(ASPECT_LEMMA.values()) - {ASPECT_LEMMA.get(asp)}))):
            return sent.strip()
    return None


def load_kinds(path: str) -> dict:
    """виды советов: {код: {label, family}}; файла нет — проверка вида выключена"""
    if not path or not os.path.exists(path):
        return {}
    return {k["code"]: {"label": k["label"], "family": k.get("family", k["code"])}
            for k in json.load(open(path, encoding="utf-8"))}


def axes_errors(item: dict, axes: dict) -> list[str]:
    """разметка осей синтеза: список до трёх отметок {axis, pole, s 1–3}; у карточек синтеза — пусто"""
    val = item.get("axes")
    if (item.get("key") or "").startswith("synth:"):
        return [] if not val else ["у карточки синтеза axes должен быть пустым"]
    if not isinstance(val, list):
        return ["нет разметки axes (список отметок осей синтеза, можно пустой)"]
    if len(val) > 3:
        return [f"axes: {len(val)} отметок, больше трёх"]
    for t in val:
        if not isinstance(t, dict) or t.get("pole") not in axes.get(t.get("axis"), ()) or t.get("s") not in (1, 2, 3):
            return [f"axes: неверная отметка {t}"]
    return []


# начало придаточной части: «когда…», «даже если…», «о котором…», «кого…», «в которых…»
SUBORDINATE = re.compile(r"\s*(?:(?:а|и|но|даже)\s+)?(?:[а-яё]{1,6}\s+)?(?:когда|если|чтобы|пока|где|куда|откуда|как|будто|хотя|"
                         r"потому|ибо|котор\w+|кто|кого|кому|кем|ком|что|чего|чему|чем|чём|чей|чья|чьё|чьи|чьих)\b", re.I)


def infinitive_bullets(life: list[str]) -> list[str]:
    """пункты «в жизни», начатые инфинитивом («Утешать друга советом…»): это не описание читателя, а обрывок фразы"""
    out = []
    for x in life:
        words = re.findall(r"[А-Яа-яЁё-]+", x)
        lead = 0
        # «Подолгу откладывать…» — чистое наречие перед инфинитивом; «Трудно сказать…», «Проще присоединиться…» —
        # слово состояния, это сказуемое, и такая фраза законченная
        while lead < min(3, len(words) - 1) and all(q.tag.POS == "ADVB" for q in MORPH.parse(words[lead].lower())):
            lead += 1
        if not words or "INFN" not in MORPH.parse(words[lead].lower())[0].tag:
            continue
        # сказуемое ищется в главных частях: придаточные («когда никто не смотрит», «чем требует ситуация») не в счёт
        main = [seg for seg in re.split(r"[,;:—–()]", x) if seg.strip() and not SUBORDINATE.match(seg)]
        ws = [w.lower() for seg in main for w in re.findall(r"[А-Яа-яЁё-]+", seg)][lead + 1:]
        addressed = any(w in ("вы", "вас", "вам", "вами") for w in ws)
        # «Делиться планами не хочется», «Отказать вы можете спокойно» — сказуемое есть, это законченная фраза
        if not addressed and not any({"VERB", "PRED", "ADJS", "PRTS"} & {MORPH.parse(w)[0].tag.POS} for w in ws):
            out.append(x.strip())
    return out


def check(item: dict, valid: set, names: dict | None = None, kinds: dict | None = None,
          axes: dict | None = None, prof: dict | None = None) -> list[str]:
    errs = []
    prof = prof or PROFILES["natal"]
    key = item.get("key")
    if key not in valid:
        errs.append("unknown key")
    for f in prof["fields"]:
        if not isinstance(item.get(f), str) or not item[f].strip():
            errs.append(f"missing {f}")
    life = item.get("in_life")
    if not isinstance(life, list) or not all(isinstance(x, str) and x.strip() for x in life):
        errs.append("in_life must be a list of strings")
    elif not prof["in_life"][0] <= len(life) <= prof["in_life"][1]:
        errs.append(f"in_life has {len(life)} items")
    if errs:
        return errs
    if bad := infinitive_bullets(life):
        errs.append(f"пункт «в жизни» начат инфинитивом: «{bad[0][:50]}» — напишите законченной фразой о читателе")
    tw = len(item["title"].split())
    if not prof["title_words"][0] <= tw <= prof["title_words"][1]:
        errs.append(f"title {tw} words")
    bl = len(item["body"])
    if not prof["body_chars"][0] <= bl <= prof["body_chars"][1]:
        errs.append(f"body {bl} chars")
    ns = sentences(item["body"])
    if not prof["body_sentences"][0] <= ns <= prof["body_sentences"][1]:
        errs.append(f"body {ns} sentences")
    for f in ("strength", "shadow", "action"):
        if f not in prof["fields"] and not item.get(f):
            continue
        n = len(item.get(f) or "")
        if not prof["field_chars"][0] <= n <= prof["field_chars"][1]:
            errs.append(f"{f} {n} chars")
    text = " ".join([item["title"], item["body"], item.get("strength") or "", item.get("shadow") or "", item["action"], *life])
    voice = QUOTED.sub(" ", text)   # чужая прямая речь в «ёлочках» может быть на «ты» — это не обращение к читателю
    if m := TY.search(voice):
        errs.append(f"«ты»-форма: {m.group(0)}")
    for m in SG2.finditer(voice):
        if m.group(0).lower() not in SG2_OK:
            errs.append(f"глагол 2 л. ед. ч.: {m.group(0)}")
            break
    if m := IMP.search(voice):
        errs.append(f"повелительное на «ты»: {m.group(0)}")
    if g := gender_hits(" . ".join([item["title"], item["body"], item.get("strength") or "", item.get("shadow") or "", item["action"], *life])):
        errs.append(f"о читателе — род или полная форма: {'; '.join(dict.fromkeys(g))}")
    ls = set(lemmas(text))
    if key and key.startswith("aspect:"):
        own = ASPECT_LEMMA.get(key.split(":")[2])
        if other := sorted((ls & set(ASPECT_LEMMA.values())) - {own}):
            errs.append(f"сравнение с другими аспектами: {', '.join(other)} — опишите этот аспект через поведение")
    if (g := ls & GENERATION) or YEAR.search(text) or BORN.search(text):
        what = ", ".join(sorted(g)) or (YEAR.search(text) or BORN.search(text)).group(0)
        errs.append(f"о поколении, годах и длительности пишет пометка отчёта, не текст: {what}")
    if key and key.startswith("aspect:"):
        for sent in HYPO.findall(text):
            sl = set(lemmas(sent))
            if sl & ASPECT_WORDS or ("связь" in sl and sl & SOFT_HARD):
                errs.append(f"сравнение с другими аспектами: «{sent.strip()[:60]}…» — опишите этот аспект через поведение")
                break
    if key and key.startswith("aspect:") and (sent := pair_comparison(key, text, names)):
        errs.append(f"сравнение с другими аспектами пары: «{sent[:70]}…» — опишите этот аспект через поведение")
    for sent in _sentences(text):
        sl = set(lemmas(sent))
        if CHART_REF[0] <= sl and sl & CHART_REF[1]:
            errs.append(f"отсылка к деталям карты, которых нет в тексте: «{sent.strip()[:70]}…»")
            break
    if axes and prof["axes"]:
        errs += axes_errors(item, axes)
    elif not prof["axes"] and item.get("axes"):
        errs.append("у текста прогноза разметка axes не нужна")
    if not prof["axes"] and (m := FC_TIME.search(text)):
        errs.append(f"даты, сроки и повторяемость показывает страница, не текст: «{m.group(0)}»")
    if key and key.startswith("synth:") and (j := ls & SYNTH_JARGON):
        errs.append(f"служебное слово синтеза в тексте: {', '.join(sorted(j))} — скажите обычными словами")
    if kinds and item.get("action_kind") not in kinds:
        errs.append(f"action_kind «{item.get('action_kind')}» не из списка видов советов")
    if key and key.startswith(VARIABLE_BODY) and (m := FEM_AGENT.search(item["title"] + " " + text)):
        errs.append(f"планета здесь любая, её род неизвестен: «{m.group(0)}» — скажите «управитель» или «хозяин»")
    if m := MIXED.search(text):
        errs.append(f"смешанная латиница: …{text[max(0, m.start() - 6):m.end() + 6]}…")
    if m := BANNED.search(text):
        errs.append(f"запрещено: {m.group(0)}")
    return errs


def load_items(paths):
    items, bad = [], {}
    for path in paths:
        try:
            items += json.load(open(path, encoding="utf-8"))
        except Exception as e:
            bad[path] = [f"bad JSON: {e}"]
    return items, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="проверяемые файлы")
    ap.add_argument("--context", nargs="*", default=[],
                    help="уже принятые файлы: участвуют в проверках корпуса, но сами не проваливаются")
    ap.add_argument("--doctrine", default="doctrine/classic_modern_v1.yaml")
    ap.add_argument("--advice-kinds", default="doctrine/prompts/advice_kinds.ru.json", help="виды советов для action_kind")
    ap.add_argument("--fail-list")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    d = load_yaml(a.doctrine)
    valid = set(key_space(d))
    focus_paths = [os.path.abspath(p) for p in a.files]
    # порядок файлов контекста сохраняется: более поздний файл обновляет поля ключа из более раннего
    ctx_paths = [p for p in dict.fromkeys(os.path.abspath(p) for p in a.context) if p not in focus_paths]
    items, failed = load_items(focus_paths)
    focus_keys = {it.get("key") for it in items}
    loaded, _ = load_items(ctx_paths)
    accepted: dict = {}
    for it in loaded:
        accepted[it.get("key")] = {**accepted.get(it.get("key"), {}), **it}
    context = list(accepted.values())
    # частичный текст (перегенерация отдельных полей) дополняется остальными полями принятой версии ключа
    items = [{**accepted.get(it.get("key"), {}), **it} for it in items]
    context = [it for it in context if it.get("key") not in focus_keys]   # новая версия ключа заменяет старую
    seen = Counter(it.get("key") for it in items)
    names = {b.code: b.label.get("ru", "") for b in d.bodies}
    kinds = load_kinds(a.advice_kinds)
    axes = {ax["code"]: {p["code"] for p in ax["poles"]} for ax in d.params.get("synthesis_axes", [])}
    for it in items:
        if errs := check(it, valid, names, kinds, axes, profile(it.get("key"), d)):
            failed.setdefault(it.get("key"), []).extend(errs)
    stats = load_stats(d)
    label = lambda k: brief(k, d, stats) if k in valid else ""     # термины названия и брифа — не «избитые обороты»
    # итоговый размер корпуса — пространство ключей того же семейства (прогноз или натал), что и проверяемые тексты
    fam = lambda k: (k or "").split(":")[0] in FORECAST_KINDS
    fc_focus = any(fam(it.get("key")) for it in items)
    family = [k for k in valid if fam(k) == fc_focus]
    for k, errs in check_corpus(context, items, label, kinds, len(family), family).items():
        failed.setdefault(k, []).extend(errs)
    dups = [k for k, n in seen.items() if n > 1]
    for k in dups:
        failed.setdefault(k, []).append("ключ повторяется")
    print(f"items {len(items)} (+{len(context)} context) · failed {len(failed)} · duplicate keys {len(dups)}")
    if not a.quiet:
        for k, errs in list(failed.items())[:80]:
            print(f"  FAIL {k}: {'; '.join(errs)}")
    if a.fail_list:
        with open(a.fail_list, "w", encoding="utf-8") as f:
            f.write("\n".join(k for k in failed if k))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
