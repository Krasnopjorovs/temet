"""Сервисный слой: карта, отчёт, профиль, подбор пар (ANN в обе стороны + Нэш)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from . import store
from .brief import load_stats
from .report import _dedupe, finalize
from .chart import build_chart
from .doctrine import Doctrine
from .ephemeris import BirthInput
from .forecast import Forecaster
from .rules import assemble_report, atomic_facts, match_rules, synthesis_keys
from .synastry import SynastryEngine, nash, percentile


@dataclass
class Runtime:
    doctrine_id: int
    d: Doctrine
    syn: SynastryEngine
    calibration: dict[str, list[float]]
    stats: dict | None = None      # факты из эфемерид (scripts.content_stats): пометки «фон поколения»

    @classmethod
    def load(cls, conn, code: str | None = None) -> "Runtime":
        code = code or os.environ.get("DOCTRINE", "classic_modern_v1")
        did, d = store.read_doctrine(conn, code)
        syn = SynastryEngine(d)
        return cls(did, d, syn, store.read_calibration(conn, did, syn.fingerprint), load_stats(d))

    # ------------------------------------------------------------- natal
    def chart(self, inp: BirthInput) -> dict:
        return build_chart(inp, self.d)

    def report(self, conn, chart: dict, locale: str = "ru", drafts: bool = False) -> dict:
        keys = [f["key"] for f in atomic_facts(chart, self.d)] + [r["key"] for r in match_rules(chart, self.d)[0]] \
            + synthesis_keys(self.d)
        content = store.read_content(conn, self.doctrine_id, keys, locale, include_drafts=drafts)
        return finalize(assemble_report(chart, self.d, content, locale), chart, self.d, self.stats or {}, locale, content)

    # ------------------------------------------------------------- forecast
    def forecast(self, conn, chart: dict, period: str, start, tz: str, locale: str = "ru", drafts: bool = False) -> dict:
        res = Forecaster(self.d, (self.stats or {}).get("forecast")).compute(chart, period, start, tz, locale)
        groups = ("main", "timeline", "background", "moon")
        keys = sorted({it["key"] for g in groups for it in res[g] if it.get("key")})
        content = store.read_content(conn, self.doctrine_id, keys, locale, include_drafts=drafts)
        for g in groups:
            for it in res[g]:
                c = content.get(it.get("key"))
                it["text"] = dict(c) if c else None
        # как в натальном отчёте: пункт или совет, уже показанный выше (сначала главное), не повторяется
        rest = [it for g in groups[1:] for it in res[g] if not it.get("main")]
        res["deduped"] = _dedupe([{"items": res["main"]}, {"items": rest}], float(self.d.params.get("report_dedupe_jaccard", 0.45)))
        for g in groups:
            for it in res[g]:
                if it["text"]:
                    it["text"].pop("_sig", None)
        res["content_gaps"] = [k for k in keys if k not in content]
        return res

    # ------------------------------------------------------------- profiles
    def create_profile(self, conn, handle: str, inp: BirthInput, modes: list[str], synthetic=False) -> int:
        bad = [m for m in modes if m not in self.d.modes]
        if bad:
            raise ValueError(f"unknown modes {bad}")
        chart = self.chart(inp)
        vecs = self.syn.vectors(chart)
        prof = {"handle": handle, "birth_local": f"{inp.date} {inp.time or '12:00'}", "tz": inp.tz,
                "lat": inp.lat, "lon": inp.lon, "place_label": inp.place_label, "modes": modes,
                "synthetic": synthetic, "syn_hash": self.syn.fingerprint}
        return store.insert_profile(conn, self.doctrine_id, self.d.code, prof, chart, vecs)

    # ------------------------------------------------------------- matching
    def _pct(self, raw: float, key: str) -> float | None:
        q = self.calibration.get(key)
        return None if q is None else percentile(raw, q)

    def matches(self, conn, handle: str, mode: str, k: int = 20, fanout: int = 100,
                include_synthetic: bool = False, explain_top: int = 5) -> dict:
        if mode not in self.d.modes:
            raise ValueError(f"unknown mode {mode}")
        if mode not in self.calibration:
            raise RuntimeError("doctrine is not calibrated: run scripts.calibrate")
        me = store.get_profile(conn, handle)
        if not me:
            raise LookupError(handle)
        dc, D = self.d.code, self.syn.D
        dims = list(self.d.modes[mode]["dim_weights"])
        kx, kq = f"{dc}:x", f"{dc}:q:{mode}"
        kd = [f"{dc}:qd:{x}" for x in dims]
        mine = store.get_vectors(conn, [me["id"]], [kx, kq, *kd])
        x_me, q_me = mine[(me["id"], kx)], mine[(me["id"], kq)]

        fwd = store.ann(conn, kx, q_me, D, fanout, me["id"], mode, include_synthetic)   # кто даёт мне
        rev = store.ann(conn, kq, x_me, D, fanout, me["id"], mode, include_synthetic)   # кому даю я
        ids = list({i for i, _ in fwd} | {i for i, _ in rev})
        if not ids:
            return {"handle": handle, "mode": mode, "candidates_scanned": 0, "matches": []}
        vecs = store.get_vectors(conn, ids, [kx, kq])
        lam = float(self.d.modes[mode]["nash_lambda"])
        scored = []
        for pid in ids:
            xb, qb = vecs[(pid, kx)], vecs[(pid, kq)]
            u_me, u_them = self._pct(float(q_me @ xb), mode), self._pct(float(qb @ x_me), mode)
            scored.append((nash(u_me, u_them, lam), pid, u_me, u_them))
        scored.sort(reverse=True)
        top = scored[:k]
        top_ids = [pid for _, pid, _, _ in top]
        dvec = store.get_vectors(conn, top_ids, kd)                 # разбивка — только для топа
        meta = store.profile_meta(conn, top_ids, with_chart=top_ids[:explain_top])
        out = []
        for n, (s, pid, u_me, u_them) in enumerate(top):
            xb = vecs[(pid, kx)]
            breakdown = {dim: {"you_receive_pct": _r(self._pct(float(mine[(me["id"], kdim)] @ xb), dim)),
                               "they_receive_pct": _r(self._pct(float(dvec[(pid, kdim)] @ x_me), dim))}
                         for dim, kdim in zip(dims, kd)}
            r = {"profile_id": pid, "handle": meta[pid]["handle"], "place": meta[pid]["place_label"],
                 "synthetic": meta[pid]["synthetic"], "time_known": meta[pid]["time_known"],
                 "score": round(100 * s, 2), "you_receive_pct": _r(u_me), "they_receive_pct": _r(u_them),
                 "asymmetry": round(abs(u_me - u_them), 3), "dims": breakdown}
            if n < explain_top:
                other = meta[pid]["chart"]
                r["you_receive_from_them"] = self.syn.explain(me["chart"], other, mode)
                r["they_receive_from_you"] = self.syn.explain(other, me["chart"], mode)
            out.append(r)
        return {"handle": handle, "mode": mode, "candidates_scanned": len(ids), "matches": out}

    def pair(self, ca: dict, cb: dict, mode: str) -> dict:
        va, vb = self.syn.vectors(ca), self.syn.vectors(cb)
        lam = float(self.d.modes[mode]["nash_lambda"])
        raw_ab = float(va[f"q:{mode}"] @ vb["x"])
        raw_ba = float(vb[f"q:{mode}"] @ va["x"])
        u_ab, u_ba = self._pct(raw_ab, mode), self._pct(raw_ba, mode)
        res = {"mode": mode, "raw": {"a_receives": raw_ab, "b_receives": raw_ba},
               "a_receives_pct": _r(u_ab), "b_receives_pct": _r(u_ba),
               "dims": {dim: {"a_receives_pct": _r(self._pct(float(va[f'qd:{dim}'] @ vb['x']), dim)),
                              "b_receives_pct": _r(self._pct(float(vb[f'qd:{dim}'] @ va['x']), dim))}
                        for dim in self.d.modes[mode]["dim_weights"]},
               "a_receives_from_b": self.syn.explain(ca, cb, mode),
               "b_receives_from_a": self.syn.explain(cb, ca, mode)}
        if u_ab is not None and u_ba is not None:
            res["score"] = round(100 * nash(u_ab, u_ba, lam), 2)
        return res


def _r(x):
    return None if x is None else round(100 * x, 2)


def birth_input(body: dict) -> BirthInput:
    return BirthInput(date=body["date"], time=body.get("time"), tz=body["tz"], lat=float(body["lat"]),
                      lon=float(body["lon"]), uncertainty_min=body.get("uncertainty_min"),
                      place_label=body.get("place_label", ""))


def synthetic_inputs(d: Doctrine, n: int, seed: int | None = None) -> list[BirthInput]:
    cal = d.params["calibration"]
    rng = np.random.default_rng(cal["seed"] if seed is None else seed)
    y0, y1 = cal["year_range"]
    la0, la1 = cal["lat_range"]
    out = []
    start = np.datetime64(f"{y0}-01-01T00:00")
    span_min = int((np.datetime64(f"{y1}-12-31T23:59") - start) / np.timedelta64(1, "m"))
    for _ in range(n):
        t = start + np.timedelta64(int(rng.integers(0, span_min)), "m")
        s = str(t)
        out.append(BirthInput(s[:10], s[11:16], "UTC", float(rng.uniform(la0, la1)),
                              float(rng.uniform(-180, 180)), uncertainty_min=None))
    return out
