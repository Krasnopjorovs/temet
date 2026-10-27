"""Синастрия как точное скалярное произведение.

Направленная полезность «A получает от B» по измерению dim:

  U(A<-B) = Σ_{i∈A, j∈B} Σ_a W[i,j,a] · K_a(θ_i^A - θ_j^B)      (аспекты)
          + Σ_{j∈B} Σ_h V[j,h] · 1[θ_j^B ∈ дом_h(A)]              (наложения домов)

Каждое ядро K_a — чётная периодическая функция, K_a(Δ) = c0 + Σ c_n cos nΔ, и
cos n(α-β) = cos nα cos nβ + sin nα sin nβ. Индикатор дуги дома тоже раскладывается
в ряд. Значит всё выражение БИЛИНЕЙНО:  U(A<-B) = q_A · x_B, где
  x_B — «что человек излучает»: [1, cos nθ, sin nθ] по всем телам,
  q_A — «что человеку нужно»: доктрина W, V, свёрнутая с картой A.
Неопределённость времени (окно ±Δt) входит точно: для θ ~ U[θ0-w, θ0+w]
E[e^{inθ}] = sinc(nw)·e^{inθ0}, поэтому x и q — это математические ожидания.

Следствие: поиск по pgvector (max inner product) ищет РОВНО ту величину, по
которой потом ранжируем, а не грубую прокси.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from .doctrine import Doctrine
from .kernels import (arc_indicator_coeffs, aspect_strength, fourier_coeffs, sinc_damping,
                      truncated_kernel)


class SynastryEngine:
    def __init__(self, d: Doctrine):
        p = d.params
        self.d = d
        self.N = int(p["harmonics_N"])
        self.F = 1 + 2 * self.N
        self.nb = len(d.bodies)
        self.D = self.nb * self.F
        self.shape, self.floor = p["kernel_shape"], float(p["orb_floor"])
        self.cusp_sigma = math.radians(float(p["cusp_sigma_deg"]))
        self.dims = [x["code"] for x in d.dimensions]
        self.kc = {a.code: fourier_coeffs(a.angle_deg, a.orb_deg, self.shape, self.floor, self.N)
                   for a in d.aspects}
        bi = d.body_index
        self.C = {dim: np.zeros((self.nb, self.nb, self.N + 1)) for dim in self.dims}
        self.V = {dim: np.zeros((self.nb, 12)) for dim in self.dims}
        self.rows = {dim: [] for dim in self.dims}
        for r in d.syn_aspect_w:
            i, j = bi[r["receiver_body"]], bi[r["sender_body"]]
            self.C[r["dimension"]][i, j, :] += r["weight"] * self.kc[r["aspect_code"]]
            self.rows[r["dimension"]].append((i, j, r["aspect_code"], r["weight"]))
        self.ov = {dim: [] for dim in self.dims}
        for r in d.syn_overlay_w:
            self.V[r["dimension"]][bi[r["sender_body"]], r["receiver_house"] - 1] += r["weight"]
            self.ov[r["dimension"]].append((bi[r["sender_body"]], r["receiver_house"], r["weight"]))
        self._n = np.arange(1, self.N + 1)
        self.fingerprint = self._fingerprint(d)

    def _fingerprint(self, d: Doctrine) -> str:
        """Отпечаток всего, от чего зависят векторы и квантили. Калибровка и
        профили с другим отпечатком считаются устаревшими, а не используются молча."""
        p = d.params
        payload = {
            "N": self.N, "shape": self.shape, "floor": self.floor, "cusp": p["cusp_sigma_deg"],
            "unc": [p["default_time_uncertainty_min"], p["unknown_time_window_h"], p["uncertainty_samples"]],
            "house_system": [p["house_system"], p["house_system_fallback"]],
            "calibration": p.get("calibration"),
            "bodies": [(b.code, b.source) for b in d.bodies],
            "aspects": [(a.code, a.angle_deg, a.orb_deg) for a in d.aspects],
            "w": sorted((r["dimension"], r["receiver_body"], r["sender_body"], r["aspect_code"],
                         round(float(r["weight"]), 6)) for r in d.syn_aspect_w),
            "v": sorted((r["dimension"], r["sender_body"], int(r["receiver_house"]), round(float(r["weight"]), 6))
                        for r in d.syn_overlay_w),
            "modes": {m: v["dim_weights"] for m, v in sorted(d.modes.items())},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # ------------------------------------------------------------- embeddings
    def _angles(self, chart):
        th = np.array([math.radians(chart["bodies"][b.code]["lon"]) for b in self.d.bodies])
        w = np.array([chart["bodies"][b.code]["w_rad"] for b in self.d.bodies])
        return th, w

    def embed(self, chart: dict) -> np.ndarray:
        th, w = self._angles(chart)
        x = np.zeros((self.nb, self.F))
        x[:, 0] = 1.0
        for i in range(self.nb):
            damp = sinc_damping(w[i], self.N)[1:]
            x[i, 1:self.N + 1] = damp * np.cos(self._n * th[i])
            x[i, self.N + 1:] = damp * np.sin(self._n * th[i])
        return x

    def _house_basis(self, chart: dict):
        """Фурье-коэффициенты (мягких) индикаторов 12 домов получателя."""
        if not chart["meta"]["time_known"]:
            return None
        cusps = [math.radians(c) for c in chart["cusps"]]
        w_asc = chart["bodies"]["ASC"]["w_rad"] if "ASC" in chart["bodies"] else 0.0
        damp = np.exp(-(self._n * self.cusp_sigma) ** 2 / 2) * sinc_damping(w_asc, self.N)[1:]
        a0 = np.zeros(12)
        A = np.zeros((12, self.N))
        B = np.zeros((12, self.N))
        for h in range(12):
            start = cusps[h]
            length = (cusps[(h + 1) % 12] - start) % (2 * math.pi)
            a0[h], A[h], B[h] = arc_indicator_coeffs(start, length, self.N)
            A[h] *= damp
            B[h] *= damp
        return a0, A, B

    def query_dims(self, chart: dict, xa: np.ndarray | None = None) -> dict[str, np.ndarray]:
        xa = self.embed(chart) if xa is None else xa
        hb = self._house_basis(chart)
        out = {}
        N = self.N
        for dim in self.dims:
            C = self.C[dim]
            q = np.zeros((self.nb, self.F))
            q[:, 0] = np.einsum("ij,i->j", C[:, :, 0], xa[:, 0])
            q[:, 1:N + 1] = np.einsum("ijn,in->jn", C[:, :, 1:], xa[:, 1:N + 1])
            q[:, N + 1:] = np.einsum("ijn,in->jn", C[:, :, 1:], xa[:, N + 1:])
            V = self.V[dim]
            if hb is None:
                q[:, 0] += V.sum(1) / 12.0          # ожидание при неизвестном ASC
            else:
                a0, A, B = hb
                q[:, 0] += V @ a0
                q[:, 1:N + 1] += V @ A
                q[:, N + 1:] += V @ B
            out[dim] = q
        return out

    def query_mode(self, qdims: dict[str, np.ndarray], mode: str) -> np.ndarray:
        m = self.d.modes[mode]
        return sum(float(lam) * qdims[dim] for dim, lam in m["dim_weights"].items())

    def vectors(self, chart: dict) -> dict[str, np.ndarray]:
        """Плоские векторы для БД: 'x' и 'q:<MODE>' (+ 'qd:<dim>' для разбивки)."""
        x = self.embed(chart)
        qd = self.query_dims(chart, x)
        out = {"x": x.ravel()}
        for mode in self.d.modes:
            out[f"q:{mode}"] = self.query_mode(qd, mode).ravel()
        for dim, q in qd.items():
            out[f"qd:{dim}"] = q.ravel()
        return out

    # ------------------------------------------------------------- reference & explanation
    def brute_force(self, ca: dict, cb: dict, dim: str, *, truncated: bool) -> float:
        """Прямой перебор пар (для проверки тождества и объяснений). Без неопределённости."""
        tha, _ = self._angles(ca)
        thb, _ = self._angles(cb)
        s = 0.0
        for i, j, asp, w in self.rows[dim]:
            delta = tha[i] - thb[j]
            if truncated:
                s += w * float(truncated_kernel(delta, self.kc[asp]))
            else:
                a = self.d.aspect_by_code[asp]
                s += w * float(aspect_strength(delta, a.angle_deg, a.orb_deg, self.shape, self.floor))
        if ca["meta"]["time_known"]:
            cusps = [math.radians(c) for c in ca["cusps"]]
            for j, h, w in self.ov[dim]:
                start = cusps[h - 1]
                length = (cusps[h % 12] - start) % (2 * math.pi)
                s += w * _soft_arc(thb[j], start, length, self.cusp_sigma)
        else:
            s += sum(w for _, _, w in self.ov[dim]) / 12.0
        return s

    def explain(self, ca: dict, cb: dict, mode: str, top: int = 8) -> list[dict]:
        """Крупнейшие вклады контактов в U(A<-B) для режима (точное ядро, центры)."""
        lam = self.d.modes[mode]["dim_weights"]
        tha, _ = self._angles(ca)
        thb, _ = self._angles(cb)
        codes = [b.code for b in self.d.bodies]
        acc: dict[tuple, dict[str, float]] = {}

        def add(key, dim, v):
            acc.setdefault(key, {})
            acc[key][dim] = acc[key].get(dim, 0.0) + v

        for dim, l in lam.items():
            for i, j, asp, w in self.rows[dim]:
                a = self.d.aspect_by_code[asp]
                k = float(aspect_strength(tha[i] - thb[j], a.angle_deg, a.orb_deg, self.shape, self.floor))
                if k > 0.05:
                    add(("aspect", codes[i], codes[j], asp), dim, l * w * k)
            if ca["meta"]["time_known"]:
                cusps = ca["cusps"]
                for j, h, w in self.ov[dim]:
                    lon = math.degrees(thb[j]) % 360
                    a, b = cusps[h - 1], cusps[h % 12]
                    if (a <= lon < b) if a <= b else (lon >= a or lon < b):
                        add(("overlay", codes[j], h), dim, l * w)
        out = []
        for key, dims in sorted(acc.items(), key=lambda kv: -abs(sum(kv[1].values())))[:top]:
            v = sum(dims.values())
            extra = {"dims": {d: round(x, 4) for d, x in dims.items()},
                     "main_dim": max(dims, key=lambda d: abs(dims[d]))}
            if key[0] == "aspect":
                _, ra, sb, asp = key
                sep = abs((ca["bodies"][ra]["lon"] - cb["bodies"][sb]["lon"] + 180) % 360 - 180)
                orb = abs(sep - self.d.aspect_by_code[asp].angle_deg)
                out.append({"type": "aspect", "receiver": ra, "sender": sb, "aspect": asp,
                            "orb": round(orb, 2), "contribution": round(v, 4), **extra})
            else:
                out.append({"type": "overlay", "sender": key[1], "receiver_house": key[2],
                            "contribution": round(v, 4), **extra})
        return out


def _soft_arc(theta: float, start: float, length: float, sigma: float) -> float:
    """Точный индикатор дуги, размытый гауссом σ (эталон для ряда Фурье)."""
    if sigma <= 0:
        u = (theta - start) % (2 * math.pi)
        return float(u < length)
    u = (theta - start) % (2 * math.pi)
    phi = lambda z: 0.5 * (1.0 + math.erf(z / (sigma * math.sqrt(2.0))))
    return sum(phi(u + 2 * math.pi * k) - phi(u + 2 * math.pi * k - length) for k in (-1, 0, 1))


# ------------------------------------------------------------------ scoring
def percentile(raw: float, quantiles) -> float:
    q = np.asarray(quantiles, dtype=float)
    return float(np.interp(raw, q, np.linspace(0.0, 1.0, len(q))))


def nash(u_ab: float, u_ba: float, lam: float) -> float:
    """Произведение Нэша по перцентилям + штраф асимметрии (союз «за счёт другого»)."""
    return math.sqrt(max(u_ab, 0) * max(u_ba, 0)) * math.exp(-lam * abs(u_ab - u_ba) / (u_ab + u_ba + 1e-9))


def quantile_table(scores: np.ndarray, k: int) -> list[float]:
    return np.quantile(scores, np.linspace(0.0, 1.0, k)).tolist()
