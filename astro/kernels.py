"""Ядра аспектов на окружности и их ряды Фурье.

Аспект a — чётная периодическая функция угла между точками K_a(Δ), равная 1 в
точном аспекте и orb_floor на границе классического орбиса. Любую такую функцию
можно разложить в косинусный ряд  K_a(Δ) = c0 + Σ c_n cos(nΔ).  Это и делает
синастрию скалярным произведением (см. synastry.py).
"""
from __future__ import annotations

import math

import numpy as np

GRID = 8192


def _wrap(x):
    return (x + math.pi) % (2 * math.pi) - math.pi


def _dist_to_aspect(delta, angle_rad):
    """Круговое расстояние от Δ до ближайшей точки аспекта (±angle)."""
    return np.minimum(np.abs(_wrap(delta - angle_rad)), np.abs(_wrap(delta + angle_rad)))


def _gauss(d, orb, floor):
    return np.exp(math.log(floor) * (d / orb) ** 2)


def _linear(d, orb, floor):
    return np.clip(1.0 - (1.0 - floor) * d / orb, 0.0, 1.0)


SHAPES = {"gauss": _gauss, "linear": _linear}


def aspect_strength(delta_rad, angle_deg: float, orb_deg: float, shape: str, floor: float):
    d = _dist_to_aspect(np.asarray(delta_rad, dtype=float), math.radians(angle_deg))
    return SHAPES[shape](d, math.radians(orb_deg), floor)


def fourier_coeffs(angle_deg: float, orb_deg: float, shape: str, floor: float, n_max: int) -> np.ndarray:
    """c[0..n_max]: K(Δ) ≈ c0 + Σ_{n≥1} c_n cos(nΔ)."""
    grid = np.linspace(0.0, 2 * math.pi, GRID, endpoint=False)
    k = aspect_strength(grid, angle_deg, orb_deg, shape, floor)
    f = np.fft.rfft(k) / GRID
    c = np.empty(n_max + 1)
    c[0] = f[0].real
    c[1:] = 2.0 * f[1:n_max + 1].real
    # ядро чётное -> синусные коэффициенты обязаны быть нулём
    assert np.max(np.abs(f[1:n_max + 1].imag)) < 1e-9
    return c


def truncated_kernel(delta_rad, coeffs: np.ndarray):
    n = np.arange(len(coeffs))
    delta = np.asarray(delta_rad, dtype=float)[..., None]
    return (coeffs * np.cos(n * delta)).sum(-1)


def arc_indicator_coeffs(start: float, length: float, n_max: int):
    """Фурье-коэффициенты индикатора дуги [start, start+length) (радианы).

    1_arc(θ) = a0 + Σ (A_n cos nθ + B_n sin nθ)."""
    end = start + length
    n = np.arange(1, n_max + 1)
    a0 = length / (2 * math.pi)
    A = (np.sin(n * end) - np.sin(n * start)) / (n * math.pi)
    B = (np.cos(n * start) - np.cos(n * end)) / (n * math.pi)
    return a0, A, B


def sinc_damping(w: float, n_max: int) -> np.ndarray:
    """E[e^{inθ}] / e^{inθ0} для θ ~ U[θ0-w, θ0+w]: sin(nw)/(nw), n = 0..n_max."""
    n = np.arange(n_max + 1)
    return np.sinc(n * w / math.pi)
