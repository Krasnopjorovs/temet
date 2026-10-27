"""Swiss Ephemeris + честная обработка времени.

* Исторические часовые пояса — zoneinfo/tzdata (не ручные смещения).
* Неоднозначное (осенний перевод) и несуществующее (весенний) локальное время
  не угадывается молча: окно неопределённости расширяется, чтобы накрыть оба момента.
* Неизвестное время рождения = равномерное распределение по суткам, а не «полдень».
* Без файлов эфемерид — ошибка (если доктрина не разрешила Moshier).
"""
from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import swisseph as swe

from .doctrine import Doctrine

_EPHE = os.environ.get("SE_EPHE_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "ephe")
TWO_PI = 2.0 * math.pi
# Swiss Ephemeris хранит своё состояние (включая путь к файлам) в thread-local
# памяти: путь, заданный в главном потоке, не виден рабочим потокам веб-сервера,
# и библиотека молча уходит в Moshier. Поэтому — инициализация на каждый поток.
_tls = threading.local()


def _ensure_thread_init():
    if getattr(_tls, "path", None) != _EPHE:
        swe.set_ephe_path(_EPHE)
        _tls.path = _EPHE


class EphemerisError(RuntimeError):
    pass


@dataclass
class BirthInput:
    date: str                       # YYYY-MM-DD
    time: str | None                # HH:MM, None = неизвестно
    tz: str                         # IANA, напр. Europe/Samara
    lat: float
    lon: float
    uncertainty_min: float | None = None
    place_label: str = ""


@dataclass
class Instant:
    utc: datetime
    half_window_min: float
    time_known: bool
    offset_hours: float
    flags: list[str]


def resolve_instant(inp: BirthInput, params: dict) -> Instant:
    z = ZoneInfo(inp.tz)
    flags: list[str] = []
    known = inp.time is not None
    hhmm = inp.time if known else "12:00"
    local = datetime.strptime(f"{inp.date} {hhmm}", "%Y-%m-%d %H:%M")
    unc = float(inp.uncertainty_min if inp.uncertainty_min is not None
                else params["default_time_uncertainty_min"])

    a = local.replace(tzinfo=z, fold=0)
    b = local.replace(tzinfo=z, fold=1)
    utc_a, utc_b = a.astimezone(timezone.utc), b.astimezone(timezone.utc)
    if utc_a != utc_b:
        roundtrip = utc_a.astimezone(z).replace(tzinfo=None)
        flags.append("nonexistent_local_time" if roundtrip != local else "ambiguous_local_time")
        center = utc_a + (utc_b - utc_a) / 2
        unc += abs((utc_b - utc_a).total_seconds()) / 120.0
    else:
        center = utc_a
    if not known:
        flags.append("time_unknown")
        unc = float(params["unknown_time_window_h"]) * 60.0
    return Instant(center, unc, known, a.utcoffset().total_seconds() / 3600.0, flags)


def julday(dt: datetime) -> float:
    h = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + dt.microsecond / 3.6e9
    return swe.julday(dt.year, dt.month, dt.day, h, swe.GREG_CAL)


def _calc(jd: float, se_id: int, allow_moshier: bool) -> tuple[float, float]:
    try:
        r, ret = swe.calc_ut(jd, se_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    except swe.Error as e:  # отсутствует файл (например, Хирон без seas_18.se1)
        raise EphemerisError(f"body {se_id}: {e}") from e
    if ret & swe.FLG_MOSEPH and not allow_moshier:
        raise EphemerisError(f"body {se_id}: Swiss Ephemeris files missing in {_EPHE}, fell back to Moshier")
    return r[0] % 360.0, r[3]


def raw_positions(jd: float, lat: float, lon: float, d: Doctrine) -> dict:
    _ensure_thread_init()
    p = d.params
    allow = bool(p.get("allow_moshier", False))
    hsys = p["house_system"]
    flags = []
    try:
        cusps, ascmc = swe.houses_ex(jd, lat, lon, hsys.encode())
    except swe.Error:
        hsys = p["house_system_fallback"]
        flags.append(f"house_system_fallback:{hsys}")
        cusps, ascmc = swe.houses_ex(jd, lat, lon, hsys.encode())
    angles = {"ASC": ascmc[0] % 360.0, "MC": ascmc[1] % 360.0}

    lon_out: dict[str, float] = {}
    spd_out: dict[str, float] = {}
    pending = []
    for b in d.bodies:
        src = b.source
        if "se" in src:
            lon_out[b.code], spd_out[b.code] = _calc(jd, int(src["se"]), allow)
        elif "angle" in src:
            lon_out[b.code], spd_out[b.code] = angles[src["angle"]], float("nan")
        elif "offset_of" in src:
            pending.append(b)
        else:
            raise EphemerisError(f"body {b.code}: unknown source {src}")
    for b in pending:
        base = b.source["offset_of"]
        lon_out[b.code] = (lon_out[base] + float(b.source["deg"])) % 360.0
        spd_out[b.code] = spd_out[base]
    return {"lon": lon_out, "speed": spd_out, "cusps": [c % 360.0 for c in cusps[:12]],
            "house_system": hsys, "flags": flags}


def sample_uncertainty(inst: Instant, inp: BirthInput, d: Doctrine) -> dict[str, float]:
    """Полуширина равномерного разброса долготы (рад) по окну времени для каждого тела."""
    n = int(d.params["uncertainty_samples"])
    if inst.half_window_min <= 0:
        return {b.code: 0.0 for b in d.bodies}
    offsets = np.linspace(-inst.half_window_min, inst.half_window_min, n)
    series: dict[str, list[float]] = {b.code: [] for b in d.bodies}
    for off in offsets:
        jd = julday(inst.utc + timedelta(minutes=float(off)))
        pos = raw_positions(jd, inp.lat, inp.lon, d)["lon"]
        for k, v in pos.items():
            series[k].append(math.radians(v))
    out = {}
    for k, vals in series.items():
        un = np.unwrap(np.array(vals))
        out[k] = float(min(math.pi, (un.max() - un.min()) / 2.0))
    return out
