"""HTTP API. Без LLM в рантайме: эфемериды + доктрина из Postgres + pgvector."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
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


def _page_lang(request: Request, lang: str | None) -> str:
    """язык страницы: ?lang=, иначе выбор на сайте (cookie temet_lang), иначе язык браузера"""
    loc = lang or request.cookies.get("temet_lang") or request.cookies.get("neoastro_lang")
    if not loc:
        loc = (request.headers.get("accept-language") or "").split(",")[0]
    return i18n.norm(loc, _rt().d)


def _page(name: str, request: Request, lang: str | None) -> HTMLResponse:
    """about.html — язык по умолчанию; about.en.html — английская версия той же страницы"""
    loc = _page_lang(request, lang)
    stem, ext = name.rsplit(".", 1)
    html = PAGES.get(f"{stem}.{loc}.{ext}") or PAGES[name]
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "Vary": "Cookie, Accept-Language"})


@app.get("/")
def index(request: Request, lang: str | None = None):
    return _page("index.html", request, lang)


@app.get("/about")
def about(request: Request, lang: str | None = None):
    return _page("about.html", request, lang)
