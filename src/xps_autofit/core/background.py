"""Inelastic background models: linear, Shirley and Tougaard.

All functions take an ascending *binding-energy* axis.  Inelastically scattered
electrons lose kinetic energy and therefore appear at **higher** binding energy, so
the step of a Shirley or Tougaard background rises towards the high-BE end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.integrate import cumulative_trapezoid

BACKGROUND_TYPES = ("none", "linear", "shirley", "tougaard")
BACKGROUND_MODES = ("static", "active")
#: Types for which an *active* (fitted together with the peaks) version exists.
ACTIVE_TYPES = ("shirley", "tougaard")

TOUGAARD_CROSS_SECTIONS: dict[str, tuple[float, float | None]] = {
    "universal": (1643.0, None),
    "polymer": (551.0, 436.0),
}
"""Tougaard inelastic cross-sections ``(C, D)`` in eV**2.  ``universal`` is the
two-parameter ``F(T) = B T / (C + T**2)**2`` for metals and many inorganic solids;
``polymer`` is the three-parameter ``F(T) = B T / ((C - T**2)**2 + D T**2)`` of
Tougaard's polymer class (S. Tougaard, Surf. Interface Anal. 25 (1997) 137), whose
loss peaks at higher energy loss and is narrower."""
#: Default relative window of the active scattering factor around its static estimate
#: (see :attr:`BackgroundSpec.scatter_window`); ``None`` leaves it free.
DEFAULT_SCATTER_WINDOW: float | None = 0.3


class BackgroundError(ValueError):
    """Raised when a background cannot be computed."""


@dataclass
class BackgroundSpec:
    """How to compute the background of a region.

    Parameters
    ----------
    type
        ``"none"``, ``"linear"``, ``"shirley"`` or ``"tougaard"``.
    mode
        ``"static"``: the background is computed from the data (endpoints) before
        the fit and held fixed.  ``"active"``: for Shirley and Tougaard the
        background is generated from the fitted peak envelope inside the fit,
        ``B(E) = offset + k * S[envelope](E)``, with ``offset`` and the scattering
        factor ``k`` as free parameters.  The endpoints then no longer bias the
        result and background and peaks are self-consistent.  ``"auto"`` (regions
        only) tries both.
    endpoint_points
        Number of points averaged at each end of the region to define the endpoint
        intensities.
    max_iterations, tolerance
        Shirley iteration control.  ``tolerance`` is relative to the step height.
    tougaard_B, tougaard_C, tougaard_D
        Tougaard cross-section parameters (eV**2).  Without ``tougaard_D`` the
        two-parameter universal form ``F(T) = B*T / (C + T**2)**2``; with it the
        three-parameter form ``F(T) = B*T / ((C - T**2)**2 + D*T**2)`` (polymers:
        ``C = 551, D = 436``; see :data:`TOUGAARD_CROSS_SECTIONS`).  In a recipe,
        ``tougaard_cross_section: polymer`` sets both.  ``tougaard_B=None`` scales
        ``B`` so the background meets the high-BE endpoint.
    scatter_window
        Active mode only.  The scattering factor ``k`` is kept within
        ``[k0 / (1 + w), k0 * (1 + w)]`` around the static estimate ``k0`` (the
        factor that makes the Shirley/Tougaard background meet the high-BE
        endpoint).  Without the window a weak component next to the region edge
        and ``k`` can trade off against each other; ``None`` leaves ``k`` free.
    """

    type: str = "shirley"
    endpoint_points: int = 3
    max_iterations: int = 100
    tolerance: float = 1e-6
    tougaard_B: float | None = None
    tougaard_C: float = 1643.0
    tougaard_D: float | None = None
    mode: str = "static"
    scatter_window: float | None = DEFAULT_SCATTER_WINDOW

    def __post_init__(self) -> None:
        if self.type not in BACKGROUND_TYPES and self.type != "auto":
            raise BackgroundError(f"background type must be one of {BACKGROUND_TYPES} or 'auto'")
        if self.mode not in BACKGROUND_MODES and self.mode != "auto":
            raise BackgroundError(f"background mode must be one of {BACKGROUND_MODES} or 'auto'")
        if self.endpoint_points < 1:
            raise BackgroundError("endpoint_points must be >= 1")
        if self.scatter_window is not None and self.scatter_window <= 0:
            raise BackgroundError("scatter_window must be positive or None (free)")
        if self.tougaard_C <= 0:
            raise BackgroundError("tougaard_C must be positive (eV^2)")
        if self.tougaard_D is not None and self.tougaard_D < 0:
            raise BackgroundError("tougaard_D must be >= 0 (eV^2) or None (universal form)")

    @property
    def tougaard_cross_section(self) -> str:
        """``"universal"``, ``"polymer"`` or ``"custom"`` for the current C and D."""
        for name, (c, d) in TOUGAARD_CROSS_SECTIONS.items():
            if self.tougaard_C == c and self.tougaard_D == d:
                return name
        return "custom"

    @property
    def is_active(self) -> bool:
        """True when the background is fitted with the peaks (active Shirley/Tougaard)."""
        return self.mode == "active" and self.type in ACTIVE_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "mode": self.mode,
            "endpoint_points": self.endpoint_points,
            "max_iterations": self.max_iterations,
            "tolerance": self.tolerance,
            "tougaard_B": self.tougaard_B,
            "tougaard_C": self.tougaard_C,
            "tougaard_D": self.tougaard_D,
            "scatter_window": self.scatter_window,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | str | None) -> BackgroundSpec:
        if d is None:
            return cls()
        if isinstance(d, str):
            return cls(type=d)
        d = dict(d)
        preset = d.pop("tougaard_cross_section", None)
        if preset is not None:
            if preset not in TOUGAARD_CROSS_SECTIONS:
                raise BackgroundError(
                    f"tougaard_cross_section must be one of {sorted(TOUGAARD_CROSS_SECTIONS)}"
                )
            d["tougaard_C"], d["tougaard_D"] = TOUGAARD_CROSS_SECTIONS[preset]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BackgroundResult:
    values: np.ndarray
    spec: BackgroundSpec
    info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, include_values: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "spec": self.spec.to_dict(),
            "info": self.info,
            "warnings": self.warnings,
        }
        if include_values:
            d["values"] = self.values.tolist()
        return d


def _endpoints(y: np.ndarray, n: int) -> tuple[float, float]:
    n = int(max(1, min(n, y.size // 2)))
    return float(np.mean(y[:n])), float(np.mean(y[-n:]))


def _check(x: np.ndarray, y: np.ndarray) -> None:
    if x.ndim != 1 or x.shape != y.shape:
        raise BackgroundError("x and y must be 1-D arrays of equal length")
    if x.size < 5:
        raise BackgroundError("need at least 5 points")
    if np.any(np.diff(x) <= 0):
        raise BackgroundError("x must be strictly ascending binding energy")


def linear_background(x: np.ndarray, y: np.ndarray, endpoint_points: int = 3) -> np.ndarray:
    """Straight line through the averaged endpoint intensities."""
    _check(x, y)
    lo, hi = _endpoints(y, endpoint_points)
    return lo + (hi - lo) * (x - x[0]) / (x[-1] - x[0])


def shirley_background(
    x: np.ndarray,
    y: np.ndarray,
    endpoint_points: int = 3,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Iterative Shirley background.

    ``B(E) = I_lo + (I_hi - I_lo) * Q(E) / Q_total`` where ``Q(E)`` is the integral of
    the background-subtracted signal from the low-BE end up to ``E``.  Iteration stops
    when the maximum change is below ``tolerance * |I_hi - I_lo|``.
    """
    _check(x, y)
    lo, hi = _endpoints(y, endpoint_points)
    step_height = hi - lo
    info: dict[str, Any] = {"I_low_BE": lo, "I_high_BE": hi, "step_height": step_height}
    if abs(step_height) < 1e-12 * max(1.0, float(np.max(np.abs(y)))):
        info.update(iterations=0, converged=True, note="flat endpoints; constant background")
        return np.full_like(y, lo), info

    bg = linear_background(x, y, endpoint_points)
    converged = False
    it = 0
    while it < max_iterations:
        it += 1
        signal = y - bg
        q = cumulative_trapezoid(signal, x, initial=0.0)
        q_total = q[-1]
        if q_total <= 0:
            info["note"] = "non-positive integrated signal; Shirley is ill-defined here"
            break
        new_bg = lo + step_height * q / q_total
        change = float(np.max(np.abs(new_bg - bg)))
        bg = new_bg
        if change < tolerance * abs(step_height):
            converged = True
            break
    info.update(iterations=it, converged=converged)
    return bg, info


def tougaard_kernel(x: np.ndarray, C: float = 1643.0, D: float | None = None) -> np.ndarray:
    """Matrix ``K[i, k] = F(x_i - x_k) * dx_k`` of the loss function, so that ``K @ signal``
    is the Tougaard integral of ``signal`` (unit ``B``).  ``D=None``: universal
    two-parameter form; otherwise the three-parameter form."""
    t = x[:, None] - x[None, :]
    denom = (C + t**2) ** 2 if D is None else (C - t**2) ** 2 + D * t**2
    kernel = np.where(t > 0, t / np.where(t > 0, denom, 1.0), 0.0)
    return kernel * np.gradient(x)[None, :]


def shirley_operator(x: np.ndarray, signal: np.ndarray) -> np.ndarray:
    """Running integral of ``signal`` from the low-BE end (unit scattering factor)."""
    return cumulative_trapezoid(signal, x, initial=0.0)


def tougaard_background(
    x: np.ndarray,
    y: np.ndarray,
    endpoint_points: int = 3,
    B: float | None = None,
    C: float = 1643.0,
    D: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Tougaard background (universal form, or the three-parameter form with ``D``).

    ``B(E) = I_lo + B * sum_{E' < E} F(E - E') * (I(E') - I_lo) * dE'`` with
    ``F(T) = T / (C + T**2)**2`` (universal) or ``F(T) = T / ((C - T**2)**2 + D * T**2)``
    (three-parameter, e.g. polymers).  When ``B`` is ``None`` it is scaled so the background
    meets the averaged high-BE endpoint, which is the usual practical choice when the
    loss region beyond the scanned range is unavailable.
    """
    _check(x, y)
    lo, hi = _endpoints(y, endpoint_points)
    j = y - lo
    k = tougaard_kernel(x, C, D) @ j
    info: dict[str, Any] = {"I_low_BE": lo, "I_high_BE": hi, "C": C, "D": D}
    n = int(max(1, min(endpoint_points, x.size // 2)))
    k_end = float(np.mean(k[-n:]))
    if B is None:
        if k_end <= 0:
            info["note"] = "no loss signal reaching the high-BE end; constant background"
            info["B"] = 0.0
            return np.full_like(y, lo), info
        B = (hi - lo) / k_end
    info["B"] = float(B)
    return lo + B * k, info


def compute_background(x: np.ndarray, y: np.ndarray, spec: BackgroundSpec) -> BackgroundResult:
    """Dispatch on :attr:`BackgroundSpec.type`."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    warnings: list[str] = []
    if spec.type == "auto":
        raise BackgroundError("background type 'auto' must be resolved by model selection")
    if spec.type == "none":
        return BackgroundResult(np.zeros_like(y), spec, {"note": "no background"}, warnings)
    if spec.type == "linear":
        return BackgroundResult(linear_background(x, y, spec.endpoint_points), spec, {}, warnings)
    lo, hi = _endpoints(y, spec.endpoint_points)
    if hi < lo:
        warnings.append(
            "high-BE endpoint is below the low-BE endpoint; Shirley/Tougaard assume the step "
            "rises towards high binding energy. Check the axis or widen the region."
        )
    if spec.type == "shirley":
        bg, info = shirley_background(
            x, y, spec.endpoint_points, spec.max_iterations, spec.tolerance
        )
        if not info.get("converged", False):
            warnings.append(f"Shirley did not converge in {info.get('iterations')} iterations")
        if spec.is_active:
            signal = y - bg
            q_total = float(cumulative_trapezoid(signal, x, initial=0.0)[-1])
            info["scatter"] = float(info["step_height"] / q_total) if q_total > 0 else 0.0
        return BackgroundResult(bg, spec, info, warnings)
    bg, info = tougaard_background(
        x, y, spec.endpoint_points, spec.tougaard_B, spec.tougaard_C, spec.tougaard_D
    )
    if spec.is_active:
        info["scatter"] = float(info.get("B", 0.0))
    return BackgroundResult(bg, spec, info, warnings)
