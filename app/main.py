"""HTTP API. Без LLM в рантайме: эфемериды + доктрина из Postgres + pgvector."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from html import escape as html_escape
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from astro import i18n, store
from astro.ephemeris import BirthInput, EphemerisError
from astro.rules import key_space
from astro.service import Runtime

STATE: dict = {}
# Сеть совпадений хранит данные рождения. Выключена по умолчанию: сервис только считает и
# сравнивает, ничего не сохраняя. Включается ENABLE_NETWORK=1.
NETWORK = os.environ.get("ENABLE_NETWORK", "0") == "1"
# Черновики текстов (ещё не одобренные) видны только изнутри сети: запрос пришёл не через прокси/туннель
# (нет заголовков CF-Connecting-IP / X-Forwarded-For) и с частного адреса. Снаружи галочки нет, а ?drafts игнорируется.
DRAFTS_NETS = [ipaddress.ip_network(n.strip()) for n in
               os.environ.get("DRAFTS_NETS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8").split(",") if n.strip()]
# Защита от перебора: не больше RATE_LIMIT запросов к /api в минуту с одного адреса (0 — без ограничения).
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "120"))


def _require_network():
    if not NETWORK:
        raise HTTPException(404, "network is disabled on this instance")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=int(os.environ.get("POOL_SIZE", 8)),
                          kwargs={"row_factory": dict_row}, configure=store.configure, open=True)
    STATE["pool"] = pool
    STATE["rt"] = None
    try:
        with pool.connection() as conn:
            STATE["rt"] = Runtime.load(conn)
    except LookupError:
        pass   # доктрина ещё не загружена (bootstrap не прогнан) — поднимемся, будем отвечать 503
    yield
    pool.close()


app = FastAPI(title="Temet nosce", version="0.17.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
FORWARDED = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip")


def client_ip(request: Request) -> str:
    """адрес посетителя: за туннелем Cloudflare — из его заголовка, иначе — адрес соединения"""
    for h in FORWARDED:
        if v := request.headers.get(h):
            return v.split(",")[0].strip()
    return request.client.host if request.client else ""


def drafts_allowed(request: Request) -> bool:
    if any(request.headers.get(h) for h in FORWARDED):
        return False
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return False
    return any(ip in n for n in DRAFTS_NETS)


_HITS: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if RATE_LIMIT > 0 and request.url.path.startswith("/api/"):
        now, q = time.monotonic(), _HITS[client_ip(request)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return JSONResponse({"detail": "too many requests, try again in a minute"}, status_code=429,
                                headers={"Retry-After": "60"})
        q.append(now)
        if len(_HITS) > 50000:          # память не растёт без конца: старые адреса выбрасываются
            for k in [k for k, v in _HITS.items() if not v or now - v[-1] > 60]:
                del _HITS[k]
    return await call_next(request)


def compact(chart: dict) -> dict:
    """Минимум для отрисовки круга: долготы тел, куспиды, известность времени."""
    return {"bodies": {k: {"lon": v["lon"], "shown": v["shown"], "retro": v.get("retro", False), "house": v.get("house")}
                       for k, v in chart["bodies"].items()},
            "cusps": chart.get("cusps"), "time_known": chart["meta"]["time_known"],
            "strong": chart["dominance"]["order"][:3]}


class Birth(BaseModel):
    date: str = Field(examples=["1983-01-16"])
    time: str | None = Field(default=None, examples=["02:00"], description="HH:MM; null = неизвестно")
    tz: str = Field(examples=["Europe/Samara"])
    lat: float
    lon: float
    uncertainty_min: float | None = None
    place_label: str = ""

    def to_input(self) -> BirthInput:
        return BirthInput(self.date, self.time, self.tz, self.lat, self.lon, self.uncertainty_min, self.place_label)


class ProfileIn(Birth):
    handle: str = Field(min_length=2, max_length=64)
    modes: list[str] = Field(min_length=1)


class ForecastIn(Birth):
    period: str = Field("week", pattern="^(week|month)$")
    start: str | None = Field(default=None, description="YYYY-MM-DD; неделя — 7 дней с этой даты, месяц — её календарный месяц")
    tz_now: str | None = Field(default=None, description="часовой пояс, где человек сейчас (IANA); по умолчанию — пояс рождения")


class PairIn(BaseModel):
    a: Birth
    b: Birth
    mode: str


def _rt() -> Runtime:
    if STATE.get("rt") is None:
        try:
            with STATE["pool"].connection() as conn:
                STATE["rt"] = Runtime.load(conn)
        except LookupError:
            raise HTTPException(503, "doctrine not loaded: run python -m scripts.bootstrap")
    return STATE["rt"]


def _guard(fn):
    try:
        return fn()
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (ValueError, EphemerisError) as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/healthz")
def healthz():
    return {"ok": True, "doctrine": _rt().d.code, "calibrated": sorted(_rt().calibration)}


@app.get("/api/places")
def places(q: str = Query(min_length=2), limit: int = 8):
    with STATE["pool"].connection() as conn:
        return store.search_places(conn, q, limit)


@app.post("/api/chart")
def chart(b: Birth, request: Request, locale: str = "ru", drafts: bool = False):
    drafts = drafts and drafts_allowed(request)

    def run():
        rt = _rt()
        loc = i18n.norm(locale, rt.d)
        c = rt.chart(b.to_input())
        with STATE["pool"].connection() as conn:
            return {"chart": c, "report": rt.report(conn, c, loc, drafts=drafts)}
    return _guard(run)


@app.post("/api/forecast")
def forecast(b: ForecastIn, request: Request, locale: str = "ru", drafts: bool = False):
    drafts = drafts and drafts_allowed(request)

    def run():
        rt = _rt()
        tz = b.tz_now or b.tz
        try:
            today = datetime.now(ZoneInfo(tz)).date()
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {tz}")
        start = date.fromisoformat(b.start) if b.start else (today - timedelta(days=today.weekday())
                                                             if b.period == "week" else today)
        c = rt.chart(b.to_input())
        with STATE["pool"].connection() as conn:
            return {"chart": c, "forecast": rt.forecast(conn, c, b.period, start, tz, i18n.norm(locale, rt.d), drafts=drafts)}
    return _guard(run)


@app.post("/api/profiles")
def create_profile(p: ProfileIn):
    _require_network()

    def run():
        with STATE["pool"].connection() as conn:
            pid = _rt().create_profile(conn, p.handle, p.to_input(), p.modes)
        return {"id": pid, "handle": p.handle}
    return _guard(run)


@app.get("/api/profiles/{handle}/matches")
def matches(handle: str, mode: str, k: int = Query(20, le=100), include_synthetic: bool = False):
    _require_network()

    def run():
        with STATE["pool"].connection() as conn:
            return _rt().matches(conn, handle, mode, k=k, include_synthetic=include_synthetic)
    return _guard(run)


@app.post("/api/synastry")
def synastry(p: PairIn):
    def run():
        rt = _rt()
        if p.mode not in rt.d.modes:
            raise ValueError(f"unknown mode {p.mode}")
        ca, cb = rt.chart(p.a.to_input()), rt.chart(p.b.to_input())
        return {**rt.pair(ca, cb, p.mode), "charts": {"a": compact(ca), "b": compact(cb)}}
    return _guard(run)


@app.get("/api/doctrine")
def doctrine(request: Request, locale: str = "ru"):
    rt = _rt()
    with STATE["pool"].connection() as conn:
        have = store.content_keys(conn, rt.doctrine_id)
        with conn.cursor() as cur:
            cur.execute("select count(*) n from profile where doctrine_id=%s and syn_hash is distinct from %s",
                        (rt.doctrine_id, rt.syn.fingerprint))
            stale = cur.fetchone()["n"]
    ks = key_space(rt.d)
    loc = i18n.norm(locale, rt.d)
    L = lambda label, code: i18n.lab(label, loc, code)
    return {
        "code": rt.d.code, "title": rt.d.title, "fingerprint": rt.syn.fingerprint, "network": NETWORK,
        "stale_profiles": stale,   # > 0 -> python -m scripts.reembed
        "labels": {
            "bodies": {b.code: L(b.label, b.code) for b in rt.d.bodies},
            "signs": {s["code"]: L(s["label"], s["code"]) for s in rt.d.signs},
            "aspects": {a.code: L(a.label, a.code) for a in rt.d.aspects},
            "dignities": rt.d.params.get("dignity_labels", {}).get(loc, {}),
            "dimensions": {x["code"]: L(x["label"], x["code"]) for x in rt.d.dimensions},
            "houses": {str(h["num"]): L(h["label"], str(h["num"])) for h in rt.d.houses},
            "modes": {m: L(v["label"], m) for m, v in rt.d.modes.items()},
        },
        "locale": loc, "locales": i18n.locales(rt.d), "drafts_allowed": drafts_allowed(request),
        "palette": rt.d.params.get("ui_palette", {}),
        "sign_elements": {s["code"]: s["element"] for s in rt.d.signs},
        "sign_order": [s["code"] for s in rt.d.signs],
        "element_labels": rt.d.params.get("element_labels", {}).get(loc, {}),
        "embedding_dim": rt.syn.D, "harmonics": rt.syn.N,
        "modes": {m: {"label": v["label"], "dims": v["dim_weights"]} for m, v in rt.d.modes.items()},
        "content": {"key_space": len(ks), "approved": sum(1 for s in have.values() if s == "approved"),
                    "draft": sum(1 for s in have.values() if s == "draft")},
        "channels_verified": all(r["verified"] for r in rt.d.channels.values()),
        "calibrated": sorted(rt.calibration),
    }


def _versioned(page: str) -> str:
    """страница со ссылками на /static/<файл>?v=<хеш содержимого>: после обновления браузер не возьмёт старый скрипт из кэша"""
    static = Path(__file__).parent / "static"
    html = (static / page).read_text(encoding="utf-8")
    def ver(m):
        f = static / m.group(1)
        return m.group(0) if not f.is_file() else f'/static/{m.group(1)}?v={hashlib.sha256(f.read_bytes()).hexdigest()[:10]}'
    return re.sub(r"/static/([\w.\-/]+\.(?:js|css))", ver, html)


PAGES = {p.name: _versioned(p.name) for p in (Path(__file__).parent / "static").glob("*.html")}

# ---------------------------------------------------------------- страницы: язык в адресе, разметка для поисковиков
# Слова страниц — app/i18n/<язык>.json. Адреса: основной язык — «/», «/about»; остальные — «/en/», «/en/about».
# Сервер сам подставляет слова в разметку, заголовок, описание, canonical, hreflang, Open Graph и JSON-LD,
# поэтому поисковик видит готовую страницу на нужном языке, а скрипты только оживляют её.
DICTS = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted((Path(__file__).parent / "i18n").glob("*.json"))}
BASE_LANG = i18n.DEFAULT
LANGS = [BASE_LANG] + [l for l in DICTS if l != BASE_LANG]
SITE = os.environ.get("PUBLIC_URL", "https://temet.artjoms.ai").rstrip("/")
SITE_PAGES = {"index": ("seo_title", "seo_desc"), "about": ("about_title", "about_desc")}   # страница: (заголовок, описание)


def page_path(page: str, lang: str) -> str:
    return ("/" if lang == BASE_LANG else f"/{lang}/") + ("" if page == "index" else page)


def _page_file(page: str, lang: str) -> str:
    return f"{page}.{lang}.html" if f"{page}.{lang}.html" in PAGES else f"{page}.html"


def _fill(html: str, d: dict) -> str:
    """data-i18n — текст элемента, data-i18n-html — разметка, data-i18n-attr="атрибут:ключ,…" — атрибуты"""
    esc = lambda v: html_escape(str(v), quote=True)
    html = re.sub(r'(<([a-zA-Z0-9]+)\b[^>]*\sdata-i18n="(\w+)"[^>]*>)\s*(</\2>)',
                  lambda m: m.group(1) + esc(d.get(m.group(3), "")) + m.group(4), html)
    html = re.sub(r'(<([a-zA-Z0-9]+)\b[^>]*\sdata-i18n-html="(\w+)"[^>]*>)\s*(</\2>)',
                  lambda m: m.group(1) + str(d.get(m.group(3), "")) + m.group(4), html)
    return re.sub(r'data-i18n-attr="([^"]+)"', lambda m: m.group(0) + "".join(
        f' {a.strip()}="{esc(d.get(k.strip(), ""))}"' for a, k in (x.split(":") for x in m.group(1).split(","))), html)


def _seo_head(page: str, lang: str, d: dict) -> str:
    esc = lambda v: html_escape(str(v), quote=True)
    title, desc = (d.get(k, "") for k in SITE_PAGES[page])
    url = SITE + page_path(page, lang)
    alt = "".join(f'\n<link rel="alternate" hreflang="{l}" href="{SITE}{page_path(page, l)}">' for l in LANGS)
    site = {"@type": "WebSite", "name": d.get("site_name"), "url": SITE + "/", "inLanguage": LANGS}
    if page == "index":
        ld = {"@context": "https://schema.org", "@type": "WebApplication", "name": d.get("site_name"), "url": url,
              "description": desc, "inLanguage": lang, "applicationCategory": "LifestyleApplication",
              "operatingSystem": "Any", "isAccessibleForFree": True, "isPartOf": site,
              "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CHF"}}
    else:
        ld = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url,
              "description": desc, "inLanguage": lang, "isPartOf": site}
    return (f'<title>{esc(title)}</title>\n<meta name="description" content="{esc(desc)}">\n'
            f'<link rel="canonical" href="{url}">{alt}\n'
            f'<link rel="alternate" hreflang="x-default" href="{SITE}{page_path(page, BASE_LANG)}">\n'
            f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="{esc(d.get("site_name", ""))}">\n'
            f'<meta property="og:title" content="{esc(title)}">\n<meta property="og:description" content="{esc(desc)}">\n'
            f'<meta property="og:url" content="{url}">\n<meta property="og:locale" content="{esc(d.get("og_locale", lang))}">\n'
            f'<meta property="og:image" content="{SITE}/static/og.png">\n'
            f'<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
            f'<meta property="og:image:alt" content="{esc(d.get("og_alt", ""))}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n<meta name="theme-color" content="#060918">\n'
            f'<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">\n'
            f'<link rel="icon" href="/favicon.ico" sizes="32x32">\n<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">\n'
            f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>')


def render_page(page: str, lang: str) -> str:
    d = {**DICTS.get(BASE_LANG, {}), **DICTS.get(lang, {})}
    html = PAGES[_page_file(page, lang)]
    html = re.sub(r'<html lang="[^"]*"', f'<html lang="{lang}"', html, count=1)
    html = re.sub(r"<title>.*?</title>", lambda m: _seo_head(page, lang, d), html, count=1, flags=re.S)
    html = _fill(html, d)
    if lang != BASE_LANG:          # внутренние ссылки — на страницы этого языка
        for p in SITE_PAGES:
            html = html.replace(f'href="{page_path(p, BASE_LANG)}"', f'href="{page_path(p, lang)}"')
            html = re.sub(rf'href="{re.escape(page_path(p, BASE_LANG))}([#?])', rf'href="{page_path(p, lang)}\1', html) if p != "index" else html
    boot = {"I18N_LANG": lang, "I18N_BASE": BASE_LANG, "I18N_LANGS": LANGS,
            "I18N_NAMES": {l: DICTS[l].get("lang_name", l) for l in LANGS},
            "I18N_DATA": {lang: d}}          # слова этого языка, недостающие — из основного
    script = "<script>" + "".join(f"window.{k}={json.dumps(v, ensure_ascii=False).replace('</', '<\\/')};" for k, v in boot.items()) + "</script>\n"
    return html.replace('<script src="/static/i18n.js', script + '<script src="/static/i18n.js', 1)


RENDERED = {(p, l): render_page(p, l) for p in SITE_PAGES for l in LANGS}


def _preferred(request: Request) -> str | None:
    """язык, который посетитель выбрал на сайте (cookie), иначе первый знакомый язык браузера"""
    c = request.cookies.get("temet_lang") or request.cookies.get("neoastro_lang")
    if c in DICTS:
        return c
    langs = []
    for part in (request.headers.get("accept-language") or "").split(","):
        tag, _, q = part.strip().partition(";q=")
        try:
            langs.append((float(q or 1), tag.split("-")[0].lower()))
        except ValueError:
            continue
    return next((l for _, l in sorted(langs, key=lambda x: -x[0]) if l in DICTS), None)


def _serve(page: str, lang: str, request: Request, negotiate: bool) -> Response:
    q = request.query_params.get("lang")
    if q in DICTS:                                   # старые ссылки «?lang=en» — на адрес языка
        return RedirectResponse(page_path(page, q), status_code=301)
    if negotiate and (p := _preferred(request)) and p != lang:
        r = RedirectResponse(page_path(page, p), status_code=302)
        r.headers["Vary"] = "Cookie, Accept-Language"
        return r
    return HTMLResponse(RENDERED[(page, lang)], headers={"Cache-Control": "no-cache", "Vary": "Cookie, Accept-Language"})


@app.get("/")
def index(request: Request):
    return _serve("index", BASE_LANG, request, negotiate=True)


@app.get("/about")
def about(request: Request):
    return _serve("about", BASE_LANG, request, negotiate=True)


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {SITE}/sitemap.xml\n")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    urls = []
    for page in SITE_PAGES:
        alts = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{SITE}{page_path(page, l)}"/>' for l in LANGS)
        urls += [f"<url><loc>{SITE}{page_path(page, l)}</loc>{alts}</url>" for l in LANGS]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n")
    return Response(xml, media_type="application/xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(Path(__file__).parent / "static" / "favicon-32.png", media_type="image/png")


@app.get("/{lang}/")
def index_lang(lang: str, request: Request):
    if lang not in DICTS or lang == BASE_LANG:
        raise HTTPException(404)
    return _serve("index", lang, request, negotiate=False)


@app.get("/{lang}")
def index_lang_noslash(lang: str):
    if lang not in DICTS or lang == BASE_LANG:
        raise HTTPException(404)
    return RedirectResponse(page_path("index", lang), status_code=301)


@app.get("/{lang}/about")
def about_lang(lang: str, request: Request):
    if lang not in DICTS or lang == BASE_LANG:
        raise HTTPException(404)
    return _serve("about", lang, request, negotiate=False)
