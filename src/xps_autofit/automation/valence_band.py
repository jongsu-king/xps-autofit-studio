"""Valence-band maximum (VBM) by linear extrapolation of the leading edge.

The usual reading of a valence-band spectrum: a straight line through the leading
edge (the steep rise from the baseline towards the first band maximum) meets a
straight line through the baseline below the edge; the binding energy of the
intersection is the VBM.

Automatic windows, on a binding-energy axis increasing into the band:

* the first band maximum is the lowest-energy maximum of the smoothed spectrum whose
  prominence is at least a fifth of the full rise;
* the edge is the stretch below that maximum whose smoothed intensity lies between
  ``edge_window`` fractions (default 0.2-0.6) of the rise from the baseline level
  (median of the lowest-energy twentieth of the points, which must be flat) to the
  maximum;
* the baseline runs from the lowest energy up to the foot of the edge (where the
  smoothed intensity first exceeds 5 % of the rise), less one smoothing width.

Both lines are fitted to the raw points (Poisson weights for counts), the VBM error
comes from their covariances, and ``window_spread`` is half the range of VBMs given
by edge windows shifted by +/- 0.1 at either end, a measure of how linear the edge
is.  Explicit ``edge`` and ``baseline`` energy ranges override the automatic choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..core.preprocessing import uniform_grid
from ..core.spectrum import Spectrum


class VBEdgeError(ValueError):
    """The spectrum has no usable leading edge (or the windows are inconsistent)."""


@dataclass
class Line:
    slope: float
    intercept: float
    cov: np.ndarray = field(repr=False)
    """Covariance of ``(slope, intercept)``."""
    lo: float
    hi: float
    """Energy range of the points the line was fitted to."""
    n: int

    def __call__(self, x: np.ndarray | float) -> np.ndarray | float:
        return self.slope * np.asarray(x) + self.intercept

    def to_dict(self) -> dict[str, Any]:
        return {
            "slope": self.slope,
            "intercept": self.intercept,
            "range_eV": [self.lo, self.hi],
            "n_points": self.n,
        }


@dataclass
class VBEdge:
    vbm: float
    """Binding energy (eV) where the edge line meets the baseline line."""
    vbm_err: float | None
    """Standard error from the two line fits."""
    window_spread: float | None
    """Half the range of VBMs from edge windows shifted by +/- 0.1 (automatic windows)."""
    edge: Line
    baseline: Line
    band_maximum: float
    """Energy of the first band maximum the edge rises to."""
    edge_window: tuple[float, float] | None
    spectrum_name: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spectrum": self.spectrum_name,
            "vbm_eV": self.vbm,
            "vbm_err": self.vbm_err,
            "window_spread_eV": self.window_spread,
            "band_maximum_eV": self.band_maximum,
            "edge_window": list(self.edge_window) if self.edge_window else None,
            "edge": self.edge.to_dict(),
            "baseline": self.baseline.to_dict(),
            "notes": self.notes,
        }


def _fit_line(x: np.ndarray, y: np.ndarray, sigma: np.ndarray | None) -> tuple[float, float, Any]:
    w = None if sigma is None else 1.0 / np.maximum(sigma, 1e-12)
    a = np.vstack([x, np.ones_like(x)]).T
    if w is not None:
        aw, yw = a * w[:, None], y * w
    else:
        aw, yw = a, y
    coef, *_ = np.linalg.lstsq(aw, yw, rcond=None)
    resid = yw - aw @ coef
    dof = max(x.size - 2, 1)
    scale = float(resid @ resid) / dof
    if w is not None:
        scale = max(scale, 1.0)  # Poisson weights: never claim more than counting allows
    cov = np.linalg.pinv(aw.T @ aw) * scale
    return float(coef[0]), float(coef[1]), cov


def _intersect(edge: Line, base: Line) -> tuple[float, float | None]:
    dm = edge.slope - base.slope
    if dm <= 0:
        raise VBEdgeError("the edge does not rise above the baseline")
    x0 = (base.intercept - edge.intercept) / dm
    # d x0 / d (m_e, b_e, m_b, b_b)
    g_e = np.array([-x0 / dm, -1.0 / dm])
    g_b = np.array([x0 / dm, 1.0 / dm])
    var = float(g_e @ edge.cov @ g_e + g_b @ base.cov @ g_b)
    return float(x0), (float(np.sqrt(var)) if np.isfinite(var) and var >= 0 else None)


def _smooth(x: np.ndarray, y: np.ndarray, smooth_eV: float) -> tuple[np.ndarray, np.ndarray]:
    from scipy.signal import savgol_filter

    xu, yu, step = uniform_grid(x, y)
    window = int(round(smooth_eV / step)) | 1
    if window >= 5 and window < xu.size:
        yu = savgol_filter(yu, window, polyorder=2)
    return xu, yu


def find_vb_edge(
    spectrum: Spectrum,
    *,
    energy_range: tuple[float, float] | None = None,
    edge_window: tuple[float, float] = (0.2, 0.6),
    edge: tuple[float, float] | None = None,
    baseline: tuple[float, float] | None = None,
    smooth_eV: float = 0.3,
) -> VBEdge:
    """VBM of a binding-energy valence-band spectrum (see the module docstring)."""
    if spectrum.axis != "binding":
        raise VBEdgeError("the valence-band edge needs a binding-energy axis")
    spec = spectrum.crop(*energy_range) if energy_range else spectrum
    order = np.argsort(spec.energy)
    x = np.asarray(spec.energy, dtype=float)[order]
    y = np.asarray(spec.intensity, dtype=float)[order]
    if x.size < 20:
        raise VBEdgeError(f"{x.size} points are too few for an edge")
    sigma_all = spec.sigma
    sigma = None if sigma_all is None else np.asarray(sigma_all, dtype=float)[order]
    lo_f, hi_f = edge_window
    if not 0.0 <= lo_f < hi_f <= 1.0:
        raise VBEdgeError("edge_window needs 0 <= low < high <= 1")
    notes: list[str] = []

    xs, ys = _smooth(x, y, smooth_eV)
    n_base = max(5, xs.size // 20)
    base0 = float(np.median(ys[:n_base]))
    top = float(np.max(ys))
    rise = top - base0
    if rise <= 0:
        raise VBEdgeError("no rise above the low-energy baseline")
    if ys[n_base - 1] - ys[0] > 0.1 * rise:
        raise VBEdgeError(
            f"the spectrum starts on the edge (it rises {ys[n_base - 1] - ys[0]:.0f} over the "
            f"first {xs[n_base - 1] - xs[0]:.2f} eV); include the baseline below the edge"
        )
    from scipy.signal import find_peaks

    peaks, _ = find_peaks(ys, prominence=0.2 * rise)
    peaks = peaks[ys[peaks] - base0 > 0.2 * rise]
    i_max = int(peaks[0]) if peaks.size else int(np.argmax(ys))
    band_max = float(xs[i_max])
    amp = float(ys[i_max]) - base0

    def crossing(level: float) -> float:
        """Energy below the band maximum where the smoothed rise last crosses
        ``base0 + level * amp`` (scanning down from the maximum)."""
        target = base0 + level * amp
        below = np.nonzero(ys[: i_max + 1] < target)[0]
        if below.size == 0:
            raise VBEdgeError(
                f"the spectrum starts above {level:.0%} of the rise; widen the range "
                "to include the baseline below the edge"
            )
        k = int(below[-1])
        x1, x2, y1, y2 = xs[k], xs[k + 1], ys[k], ys[k + 1]
        return float(x1 + (target - y1) * (x2 - x1) / (y2 - y1)) if y2 != y1 else float(x1)

    def lines_for(window: tuple[float, float]) -> tuple[Line, Line]:
        e_lo, e_hi = edge if edge else (crossing(window[0]), crossing(window[1]))
        sel = (x >= e_lo) & (x <= e_hi)
        if sel.sum() < 4:
            raise VBEdgeError(
                f"only {int(sel.sum())} points on the edge ({e_lo:.2f}-{e_hi:.2f} eV)"
            )
        m, b, cov = _fit_line(x[sel], y[sel], None if sigma is None else sigma[sel])
        edge_line = Line(m, b, cov, float(e_lo), float(e_hi), int(sel.sum()))
        if baseline:
            b_lo, b_hi = baseline
        else:
            b_lo, b_hi = float(x[0]), crossing(0.05) - smooth_eV
        bsel = (x >= b_lo) & (x <= b_hi)
        if bsel.sum() >= 5:
            mb, bb, covb = _fit_line(x[bsel], y[bsel], None if sigma is None else sigma[bsel])
        else:
            msg = (
                f"fewer than 5 baseline points in {b_lo:.2f}-{b_hi:.2f} eV; flat baseline "
                "at the low-energy level"
            )
            if msg not in notes:
                notes.append(msg)
            mb, bb = 0.0, base0
            spread = float(np.std(y[:n_base])) / np.sqrt(n_base)
            covb = np.diag([0.0, spread**2])
        return edge_line, Line(mb, bb, covb, float(b_lo), float(b_hi), int(bsel.sum()))

    edge_line, base_line = lines_for(edge_window)
    vbm, err = _intersect(edge_line, base_line)
    spread: float | None = None
    if edge is None:
        others = []
        for d_lo, d_hi in ((-0.1, 0.0), (0.1, 0.0), (0.0, -0.1), (0.0, 0.1)):
            w = (lo_f + d_lo, hi_f + d_hi)
            if 0.0 < w[0] < w[1] < 1.0:
                try:
                    others.append(_intersect(*lines_for(w))[0])
                except VBEdgeError:
                    continue
        if others:
            spread = 0.5 * (max(others + [vbm]) - min(others + [vbm]))
    if not (x[0] <= vbm <= band_max):
        notes.append(f"VBM {vbm:.2f} eV lies outside {x[0]:.2f}-{band_max:.2f} eV")
    if spread is not None and err is not None and spread > 3 * err:
        notes.append(
            f"the VBM moves by +/- {spread:.2f} eV with the edge window: the edge is not "
            "straight; check the window"
        )
    return VBEdge(
        vbm=vbm,
        vbm_err=err,
        window_spread=spread,
        edge=edge_line,
        baseline=base_line,
        band_maximum=band_max,
        edge_window=None if edge else (lo_f, hi_f),
        spectrum_name=spectrum.name,
        notes=notes,
    )
