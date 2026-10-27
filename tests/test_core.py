import math
import os
import random
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from astro.chart import build_chart
from astro.doctrine import DoctrineError, doctrine_from_tables, load_yaml, tables_from_yaml
from astro.ephemeris import BirthInput, resolve_instant
from astro.kernels import truncated_kernel
from astro.rules import key_space, match_rules
from astro.synastry import SynastryEngine

ROOT = os.path.dirname(os.path.dirname(__file__))
YAML = os.path.join(ROOT, "doctrine", "classic_modern_v1.yaml")
D = load_yaml(YAML)
ME = BirthInput("1983-01-16", "02:00", "Europe/Samara", 56.8498, 53.2045)


def rnd_charts(n, seed, unc=0):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        y, m, d = rng.randint(1960, 2005), rng.randint(1, 12), rng.randint(1, 28)
        out.append(build_chart(BirthInput(f"{y}-{m:02d}-{d:02d}", f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}",
                                          "UTC", rng.uniform(-40, 62), rng.uniform(-180, 180), uncertainty_min=unc), D))
    return out


def aspects_only_engine():
    e = SynastryEngine(D)
    for dim in e.dims:
        e.V[dim][:] = 0
        e.ov[dim] = []
    return e


# ---------------------------------------------------------------- natal
def test_known_chart():
    c = build_chart(ME, D)
    b = c["bodies"]
    assert c["meta"]["utc_offset_h"] == 4.0
    assert b["SUN"]["sign"] == "CAPRICORN" and abs(b["SUN"]["deg_in_sign"] - 25.19) < 0.05
    assert b["ASC"]["sign"] == "SCORPIO"
    assert b["RAHU"]["sign"] == "CANCER" and b["RAHU"]["house"] == 9
    assert abs(((b["KETU"]["lon"] - b["RAHU"]["lon"]) % 360) - 180) < 1e-9
    assert b["CHIRON"]["sign"] == "TAURUS"
    conj = {(a["a"], a["b"], a["aspect"]) for a in c["aspects"]}
    assert ("SATURN", "PLUTO", "CONJ") in conj
    hits = {h["key"] for h in match_rules(c, D)[0]}
    assert "rule:SATURN_PLUTO_ON_ASC" in hits


def test_worker_thread_uses_swiss_files():
    # регрессия: в рабочем потоке SE раньше молча уходил в Moshier
    with ThreadPoolExecutor(2) as ex:
        c = ex.submit(build_chart, ME, D).result()
    assert c["bodies"]["CHIRON"]["sign"] == "TAURUS"


def test_dst_ambiguous_and_nonexistent_are_flagged():
    p = D.params
    amb = resolve_instant(BirthInput("2023-10-29", "02:30", "Europe/Zurich", 47.37, 8.54), p)
    gap = resolve_instant(BirthInput("2023-03-26", "02:30", "Europe/Zurich", 47.37, 8.54), p)
    assert "ambiguous_local_time" in amb.flags and amb.half_window_min >= 40
    assert "nonexistent_local_time" in gap.flags and gap.half_window_min >= 40


def test_unknown_time():
    c = build_chart(BirthInput("1983-01-16", None, "Europe/Samara", 56.8498, 53.2045), D)
    assert not c["bodies"]["ASC"]["shown"] and "house" not in c["bodies"]["SUN"]
    assert 4 < c["bodies"]["MOON"]["w_deg"] < 9
    assert abs(c["bodies"]["ASC"]["w_rad"] - math.pi) < 1e-5
    assert "RULER2_IN_8_OR_12" in match_rules(c, D)[1]


def test_doctrine_validation():
    t = tables_from_yaml(open(YAML, encoding="utf-8").read())
    t["synastry_aspect_weight"].append({"dimension": "bond", "receiver_body": "VULCAN", "sender_body": "SUN",
                                        "aspect_code": "CONJ", "weight": 1.0})
    with pytest.raises(DoctrineError):
        doctrine_from_tables(t)


def test_key_space_covers_report_keys():
    ks = set(key_space(D))
    c = build_chart(ME, D)
    from astro.rules import atomic_facts
    assert {f["key"] for f in atomic_facts(c, D)} <= ks


# ---------------------------------------------------------------- synastry math
def test_bilinear_identity_exact():
    e = aspects_only_engine()
    cs = rnd_charts(12, 1)
    for a, b in zip(cs, cs[1:]):
        qa, xb = e.query_dims(a), e.embed(b)
        for dim in e.dims:
            assert abs((qa[dim] * xb).sum() - e.brute_force(a, b, dim, truncated=True)) < 1e-9


def test_matches_exact_model():
    e = SynastryEngine(D)
    cs = rnd_charts(60, 2)
    f, x = [], []
    for a, b in zip(cs, cs[1:]):
        qa, xb = e.query_dims(a), e.embed(b)
        for dim in e.dims:
            f.append((qa[dim] * xb).sum())
            x.append(e.brute_force(a, b, dim, truncated=False))
    f, x = np.array(f), np.array(x)
    assert np.corrcoef(f, x)[0, 1] > 0.9995
    assert np.abs(f - x).max() < 0.05 * x.std()


def test_uncertainty_is_exact_expectation():
    """q·x с затуханием sinc = матожидание по равномерному окну времени (Монте-Карло)."""
    e = aspects_only_engine()
    a, b = rnd_charts(2, 3, unc=90)
    qa, xb = e.query_dims(a), e.embed(b)
    analytic = (qa["bond"] * xb).sum()
    rng = np.random.default_rng(0)
    tha = np.radians([a["bodies"][x.code]["lon"] for x in D.bodies])
    thb = np.radians([b["bodies"][x.code]["lon"] for x in D.bodies])
    wa = np.array([a["bodies"][x.code]["w_rad"] for x in D.bodies])
    wb = np.array([b["bodies"][x.code]["w_rad"] for x in D.bodies])
    sims = []
    for _ in range(4000):
        sa = tha + rng.uniform(-1, 1, len(wa)) * wa
        sb = thb + rng.uniform(-1, 1, len(wb)) * wb
        sims.append(sum(w * truncated_kernel(sa[i] - sb[j], e.kc[asp]) for i, j, asp, w in e.rows["bond"]))
    sims = np.array(sims)
    assert abs(sims.mean() - analytic) < 4 * sims.std() / math.sqrt(len(sims)) + 1e-6


# ---------------------------------------------------------------- report & fingerprints
def test_rules_and_facts_share_one_scale_and_covers_dedupe():
    from astro.rules import assemble_report
    c = build_chart(ME, D)
    rep = assemble_report(c, D, {})
    items = {i["key"]: i for m in rep["modules"] for i in m["items"]}
    rule = items["rule:SATURN_PLUTO_ON_ASC"]
    assert rule["title"] == "Соединение Сатурна и Плутона на Асценденте"
    assert rule["salience"] < 1.0                       # масса PageRank, а не голый приоритет
    assert "aspect:SATURN:CONJ:PLUTO" not in items      # поглощено правилом
    assert "ruler:2:in:12" not in items and "rule:RULER2_IN_8_OR_12" in items


def test_fingerprint_tracks_weights_not_texts():
    t = tables_from_yaml(open(YAML, encoding="utf-8").read())
    base = SynastryEngine(doctrine_from_tables(t)).fingerprint
    t["rule"][0]["label"] = {"ru": "другое"}
    assert SynastryEngine(doctrine_from_tables(t)).fingerprint == base
    t["synastry_aspect_weight"][0]["weight"] += 0.1
    assert SynastryEngine(doctrine_from_tables(t)).fingerprint != base


def test_overview_themes():
    from astro.rules import assemble_report
    c = build_chart(ME, D)
    assert abs(sum(c["balance"]["elements"].values()) - 1) < 1e-3
    rep = assemble_report(c, D, {})
    ov = rep["modules"][0]
    assert ov["code"] == "overview"
    keys = [i["key"] for i in ov["items"]]
    assert keys[0] == "dominant:SATURN:PLUTO"
    assert all(k.split(":")[0] in ("dominant", "element", "modality") for k in keys)
    assert set(keys) <= set(key_space(D))


def test_generator_parser():
    from scripts.generate_content import parse_items
    out = parse_items('<think>[x]</think>```json\n[{"key":"a","body":"t"},{"key":"z","body":"y"}]\n```', ["a"])
    assert out == [{"key": "a", "body": "t"}]
    with pytest.raises(ValueError):
        parse_items("<think>…</think>без json", ["a"])


def test_gate_rejects_informal_and_accepts_formal():
    from scripts.gate_content import check
    valid = set(key_space(D))
    good = {"key": "sign:SUN:LEO", "title": "Сцена, на которой вы живёте",
            "body": ("Вам важно, чтобы ваше присутствие замечали. Это не тщеславие, а способ ощущать, что вы есть. "
                     "В отношениях вы щедры, пока чувствуете отклик. Без признания энергия быстро гаснет. "
                     "Под нагрузкой вы держите лицо, даже когда внутри пусто и хочется спрятаться от всех. "
                     "Задача — светить, не завися от аплодисментов, и находить радость в самом деле."),
            "in_life": ["Вы оживаете, когда вас слушают", "Вам трудно работать в тени"],
            "strength": "Вы умеете вдохновлять людей своим примером и теплом.",
            "shadow": "Перегиб — когда без похвалы опускаются руки и пропадает интерес.",
            "action": "Раз в неделю делайте что-то для себя без зрителей и замечайте, как это ощущается."}
    assert check(good, valid) == []
    bad = dict(good, action="Попробуй делать что-то для себя и замечай, как ты себя чувствуешь.")
    errs = check(bad, valid)
    assert any("ты" in e for e in errs)


def test_gate_gender_neutral():
    from scripts.ru_gender import gender_hits
    for bad in ("Вам важно быть услышанным.", "Это делает вас щедрым.", "Вы первым поднимаете руку.",
                "Не тащите всё одному.", "«Я справлюсь сам»", "«Я так решила»", "Вы становитесь резкой.",
                "можете быть честным с собой.", "оставаясь таким же чутким.", "«я недостаточно хорош»", "кто вы такой.", "Спросите себя, готов ли нести это.",
                "Вы чувствуете себя чужим.", "Вы должны быть сильным.", "Вас называют спокойными.",
                "страх быть отвергнутыми.", "Вы первыми предлагаете.", "стать наставником.",
                "Вас называют то гением, то чудаком."):
        assert gender_hits(bad), bad
    for ok in ("Вы становитесь холоднее.", "Вы уверены в себе.", "Говорите тёплым тоном.", "Помогайте окружающим.",
               "Авторитет мог быть подавляющим.", "Один способ становится единственным.", "Вы решили уйти.",
               "«Что, если я подожду один день?»", "Быть собой важнее.", "хотя бы одному такому желанию.",
               "чужое настроение может стать вашим.", "Вы каждый раз проверяете.", "Вы готовы рискнуть.", "Вы сами решаете.", "Партнёр готов помочь.", "Нужен ли вам отдых?",
               "Уязвимость связана с самым первым впечатлением.", "Союз должен оставаться живым.",
               "Рядом с вами партнёр чувствует себя интересным.", "Позволяете жизни быть спокойной.", "быть человеком слова.", "Работайте с партнёром.",
               "Делает вас и партнёра ближе.", "быть частью команды.", "Вас знают как надёжную опору.",
               "чтобы перемены стали знакомым, а не пугающим ощущением.", "на любое предложение первым приходит «нет»."):
        assert not gender_hits(ok), ok


def test_corpus_checks_flag_templates_and_echoes():
    from scripts.corpus_checks import check_corpus
    base = {"title": "Заголовок", "in_life": ["а", "б"], "strength": "Сила в том, что вы держите слово.",
            "action": "Записывайте по вечерам одну удачу."}
    ctx = [dict(base, key=f"k{i}", title=f"Заголовок {i}", body=f"Текст номер {i} про разное.",
                shadow="Перегиб — когда контроль съедает живое.") for i in range(3)]
    new = dict(base, key="new", title="Свежий заголовок", body="Совсем другой текст.",
               shadow="Перегиб — когда вы держите всё сами.")
    errs = check_corpus(ctx, [new])["new"]
    assert any("начало shadow" in e for e in errs)
    echo = dict(base, key="echo", title="Ещё один", body="Совсем иной текст.",
                shadow="Вы помните обиду годами и долго не прощаете близких. Вы помните обиду годами и долго молчите.")
    ctx2 = [dict(base, key="old", title="Старый", body="Иное.",
                 shadow="Вы помните обиду годами и долго не прощаете близких, а потом молчите.")]
    assert any("перекличка" in e for e in check_corpus(ctx2, [echo]).get("echo", []))


def test_scope_note_from_ephemeris():
    from astro.brief import load_stats, scope_note
    st = load_stats(D)
    c = build_chart(ME, D)
    assert c["bodies"]["PLUTO"]["sign"] == "LIBRA"
    assert scope_note("sign:PLUTO:LIBRA", c, D, st) == "Фон поколения: у всех, кто родился с 10.1971 по 08.1984"
    assert scope_note("sign:SUN:CAPRICORN", c, D, st) is None
    assert scope_note("aspect:MOON:TRI:SUN", c, D, st) is None


def test_gate_flags_aspect_comparison_and_generation():
    from scripts.gate_content import check
    valid = set(key_space(D))
    base = {"title": "Тихая сила вдвоём", "in_life": ["Вам легче решать в тишине", "Вы бережёте силы"],
            "strength": "Вы умеете долго держать курс, не тратя лишнего.",
            "shadow": "Если давить слишком долго, упорство переходит в глухоту к себе и к близким.",
            "action": "Раз в месяц пересматривайте одно своё правило и решайте, нужно ли оно ещё."}
    body = ("Вы держите слово даже тогда, когда это неудобно. Решения вы принимаете медленно и потом редко их меняете. "
            "Под давлением вы не спорите, а просто продолжаете своё. Близким с вами спокойно, хотя иногда тесно. "
            "Силы вы тратите экономно и не любите суеты, а отдыхаете так же основательно, как работаете.")
    ok = dict(base, key="aspect:SATURN:TRI:PLUTO", body=body)
    assert check(ok, valid) == []
    cmp_ = dict(ok, body=body + " Квадрат дал бы больше трения, а здесь всё течёт само.")
    assert any("сравнение с другими аспектами" in e for e in check(cmp_, valid))
    gen = dict(ok, body=body + " Это общее для поколения, родившегося в 1980-х.")
    assert any("о поколении" in e for e in check(gen, valid))
    names = {b.code: b.label["ru"] for b in D.bodies}
    for extra in (" В отличие от напряжённых аспектов этой пары, здесь всё идёт ровнее.",
                  " При жёстких связях Сатурна и Плутона это далось бы с боем, у вас — спокойнее.",
                  " Другие связи этих планет так не работают.",
                  " При напряжённых углах этой пары всё шло бы резче, а здесь спокойно."):
        assert any("аспектами пары" in e for e in check(dict(ok, body=body + extra), valid, names)), extra
    fine = dict(ok, body=body + " Плавный угол этой пары помогает держать курс. Острые углы в разговоре вы сглаживаете.")
    assert check(fine, valid, names) == []
    ref = dict(ok, body=body + " Конкретный тон задают знак и дом, где стоит пара.")
    assert any("отсылка к деталям карты" in e for e in check(ref, valid, names))


def test_report_dedupe_and_ruler_groups():
    from astro.report import _dup, _group_rulers
    from scripts.content_signatures import unit
    common = {"вы", "свой"}
    a = unit("Расскажите тому, кому доверяете, об одном небольшом страхе.", common)
    b = unit("Позвоните тому, кому доверяете, и расскажите, как вам.", common)
    c = unit("Назначьте дату и запишите её на бумаге.", common)
    assert _dup(b, [a], 0.45) and not _dup(c, [a], 0.45)
    item = lambda h, s: {"key": f"ruler:{h}:in:3", "title": f"Управитель {h}-го дома в 3-м доме", "salience": s, "text": {"body": "x"}}
    mods = [{"code": "love", "items": [item(7, 0.3)]}, {"code": "career", "items": [item(10, 0.2)]},
            {"code": "mind", "items": [item(9, 0.1)]}]
    _group_rulers(mods, D, "ru", 2)
    lead = mods[2]["items"][0]
    assert [len(m["items"]) for m in mods] == [0, 0, 1] and lead["key"] == "ruler:7:in:3"
    assert lead["group_title"] == "В 3-й дом сходятся управители 7-го, 9-го и 10-го домов"
    assert [g["title"] for g in lead["group"]] == ["Управитель 9-го дома в 3-м доме", "Управитель 10-го дома в 3-м доме"]


def test_advice_kind_caps():
    from scripts import corpus_checks as cc
    kinds = {"write_out": {"label": "Записать", "family": "writing"}, "journal": {"label": "Дневник", "family": "writing"},
             "body": {"label": "Тело", "family": "body"}}
    base = {"title": "т", "body": "б", "in_life": ["x"], "strength": "с", "shadow": "т", "action": "д"}
    mk = lambda i, k: dict(base, key=f"k{i}", action=f"действие номер {i}", action_kind=k)
    ctx = [mk(i, "write_out" if i < 4 else "journal" if i < 8 else "body" if i < 10 else None) for i in range(100)]
    ok = cc.check_corpus(ctx, [mk(200, "body")], kinds=kinds)
    assert not any("вид совета" in e or "одного рода" in e for e in ok.get("k200", []))
    many = cc.check_corpus(ctx, [mk(200, "journal")], kinds=kinds)      # дневников 4 из 101 — вид в норме
    assert not any("вид совета" in e for e in many.get("k200", []))
    fam_ctx = [mk(i, "write_out" if i < 6 else "journal" if i < 11 else None) for i in range(100)]
    fam = cc.check_corpus(fam_ctx, [mk(200, "journal")], kinds=kinds)   # «записать» вместе 12 из 101 > 9%
    assert any("одного рода" in e for e in fam["k200"])


def test_synthesis_tension_and_theme():
    from astro.synthesis import shares, synthesize
    ax = lambda a, p, s: {"axis": a, "pole": p, "s": s}
    it = lambda k, sal, tags: {"key": k, "title": k, "salience": sal, "text": {"body": "x", "axes": tags}}
    mods = [{"code": "core", "items": [
        it("sign:MOON:AQUARIUS", 0.3, [ax("close_free", "free", 3)]),
        it("aspect:MOON:CONJ:VENUS", 0.2, [ax("close_free", "close", 3)]),
        it("sign:VENUS:AQUARIUS", 0.1, [ax("close_free", "free", 2)]),
        it("aspect:MOON:SQR:URANUS", 0.2, [ax("close_free", "free", 2), ax("close_free", "close", 2)]),   # сам спор — не в счёт
        it("house:SATURN:1", 0.1, [ax("impulse_caution", "caution", 3)]),
        it("sign:SUN:CAPRICORN", 0.2, [ax("impulse_caution", "caution", 2)]),
        it("aspect:SATURN:CONJ:ASC", 0.2, [ax("impulse_caution", "caution", 2)]),    # тот же Сатурн — то же свидетельство
        it("sign:MERCURY:VIRGO", 0.1, [ax("impulse_caution", "caution", 2)]),
    ]}]
    sh = shares(mods, D)
    assert sh["close_free"]["free"] > sh["close_free"]["close"] > 0 and sh["impulse_caution"]["impulse"] == 0
    flat = [0.0] * 51 + [0.5] * 50          # половина карт популяции без полюса, остальные — 0.5
    cal = {"axes": {a["code"]: {p["code"]: [x * 0.4 for x in flat] for p in a["poles"]} for a in D.params["synthesis_axes"]}}
    content = {"synth:tension:close_free": {"body": "t"}, "synth:theme:impulse_caution:caution": {"body": "c"}}
    cards = synthesize(mods, D, cal, content)
    keys = [c["key"] for c in cards]
    assert keys[0] == "synth:tension:close_free" and "synth:theme:impulse_caution:caution" in keys
    assert cards[0]["detail"].startswith("Близость: aspect:MOON:CONJ:VENUS · Свобода: sign:MOON:AQUARIUS")
    tagged = {i["key"] for i in mods[0]["items"] if "↔ Близость и свобода" in i.get("tags", [])}
    assert "aspect:MOON:SQR:URANUS" not in tagged and "sign:MOON:AQUARIUS" in tagged
    assert synthesize(mods, D, {}, content) == []                                   # без калибровки синтеза нет
    theme = next(c for c in cards if c["key"] == "synth:theme:impulse_caution:caution")
    assert theme["detail"].count("Сатурн") + theme["detail"].count("SATURN") == 1      # по одному от свидетельства
    mods[0]["items"] = [i for i in mods[0]["items"] if i["key"] != "sign:MERCURY:VIRGO"]   # осталось 2 независимых
    assert "synth:theme:impulse_caution:caution" not in [c["key"] for c in synthesize(mods, D, cal, content)]


def test_gate_infinitive_bullets():
    from scripts.gate_content import infinitive_bullets
    bad = ["Утешать друга советом и идеей, а не объятием", "Работать лучше всего в тишине, когда никто не смотрит",
           "Поддерживать связь с человеком, о котором мало кто знает", "Подолгу откладывать звонок",
           "Задавать вопрос, после которого разговор меняется"]
    ok = ["Делиться планами до их воплощения не хочется.", "Скрыть настроение не удаётся: его выдают интонации.",
          "Отказать в том, чего вам не хочется, вы можете спокойно.", "Помогать другим вам проще, чем заняться своими.",
          "Вы долго присматриваетесь, прежде чем шутить.", "Проще присоединиться к чужому проекту, чем запустить свой",
          "Чтобы переубедить вас, нужны не эмоции, а время и факты."]
    assert infinitive_bullets(bad) == bad and infinitive_bullets(ok) == []


def test_forecast_window_and_keys():
    """прогноз: события с ключами из пространства ключей, даты в окне, Луна по дням покрывает неделю без дыр"""
    from datetime import date

    from astro.forecast import Forecaster, forecast_keys
    from astro.rules import describe
    ks = set(key_space(D))
    fk = forecast_keys(D)
    assert fk and set(fk) <= ks
    assert all(describe(k, D) != k for k in fk)
    c = build_chart(BirthInput("1985-03-14", "07:40", "Europe/Riga", 56.95, 24.1, 10), D)
    f = Forecaster(D).compute(c, "week", date(2026, 10, 26), "Europe/Zurich")
    items = f["main"] + f["timeline"] + f["background"]
    assert f["main"] and all(it["key"] in ks for it in items if it.get("key"))
    assert all(w for it in f["main"] for w in [it["peak_in_window"]])
    moon = f["moon"]
    assert moon[0]["start"] <= f["window"]["start"] and moon[-1]["end"] >= f["window"]["end"]
    assert all(a["end"] == b["start"] for a, b in zip(moon, moon[1:]))
    nf = Forecaster(D).compute(build_chart(BirthInput("1979-07-28", None, "Europe/Riga", 56.95, 24.1), D),
                               "month", date(2026, 11, 1), "UTC")
    assert not nf["moon"] and not any(it["kind"].startswith("pm") for it in nf["timeline"] + nf["background"])


def test_locales_complete_and_english_titles():
    """у каждой подписи доктрины есть все языки params.strings; английские заголовки собираются без русских слов"""
    import re
    import yaml
    from datetime import date
    from astro.forecast import Forecaster
    from astro.i18n import label_gaps, about, ordinal
    from astro.rules import describe
    y = yaml.safe_load(open("doctrine/classic_modern_v1.yaml", encoding="utf-8"))
    assert label_gaps(y) == []
    assert [ordinal(n, "en") for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]
    assert about(400, D, "en") == "about 13 months" and about(3, D, "ru") == "около 3 дней"
    cyr = re.compile("[А-Яа-яЁё]")
    for k in key_space(D):
        assert not cyr.search(describe(k, D, "en")), k
    c = build_chart(BirthInput("1983-01-16", "02:00", "Europe/Samara", 56.85, 53.2), D)
    f = Forecaster(D).compute(c, "month", date(2026, 10, 1), "Europe/Zurich", "en")
    for it in f["main"] + f["timeline"] + f["background"] + f["moon"]:
        for fld in ("title", "short", "note"):
            assert not cyr.search(it.get(fld) or ""), (fld, it.get(fld))
    assert not cyr.search(f["intensity"]["label"] or "")
