"""Pre-processing: axis checks, noise estimation and charge correction.

Smoothing here is only ever used to *locate* features; fits always run on the raw
data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import savgol_filter

from .spectrum import Spectrum

C1S_REFERENCE_WARNING = (
    "Charge referencing to adventitious C 1s = 284.8 eV is a convention, not an absolute "
    "standard: the adventitious carbon position varies between samples and substrates "
    "(see Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020)). Report the method "
    "and treat small shifts between samples with caution."
)


@dataclass
class AxisReport:
    n_points: int
    lo: float
    hi: float
    step_median: float
    uniform: bool
    input_order: str
    duplicates_merged: int
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def check_axis(spectrum: Spectrum) -> AxisReport:
    """Summarise what the constructor did to the axis and flag oddities."""
    order = "ascending"
    merged = 0
    for h in spectrum.history:
        if h.get("step") == "sort_ascending":
            order = h.get("input_order", "unsorted")
        if h.get("step") == "merge_duplicate_energies":
            merged = int(h.get("points_removed", 0))
    issues: list[str] = []
    d = np.diff(spectrum.energy)
    if not spectrum.is_uniform:
        ratio = float(d.max() / d.min())
        issues.append(f"non-uniform spacing (max/min step ratio {ratio:.2f})")
    if spectrum.axis == "kinetic":
        issues.append("kinetic-energy axis; convert with Spectrum.to_binding() before fitting")
    if spectrum.step > 0.5:
        issues.append(f"coarse step {spectrum.step:.2f} eV; peak widths will be poorly resolved")
    return AxisReport(
        n_points=spectrum.n,
        lo=float(spectrum.energy[0]),
        hi=float(spectrum.energy[-1]),
        step_median=spectrum.step,
        uniform=spectrum.is_uniform,
        input_order=order,
        duplicates_merged=merged,
        issues=issues,
    )


@dataclass
class NoiseReport:
    sigma: float
    """Robust noise estimate from the high-frequency residual (intensity units)."""
    poisson_sigma: float | None
    """Expected sigma at the low-intensity baseline if the data are counts."""
    baseline: float
    peak_height: float
    snr: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _odd_window(points: float, n: int, minimum: int = 5) -> int:
    w = int(max(minimum, round(points)))
    if w % 2 == 0:
        w += 1
    if w >= n:
        w = n - 1 if (n - 1) % 2 == 1 else n - 2
    return max(w, 3)


def smooth_for_detection(
    x: np.ndarray, y: np.ndarray, fwhm_hint: float
) -> tuple[np.ndarray, np.ndarray]:
    """Resample to a uniform grid and Savitzky-Golay smooth with a window of ~0.6 FWHM."""
    step = float(np.median(np.diff(x)))
    xu = np.arange(x[0], x[-1] + step / 2, step)
    yu = np.interp(xu, x, y)
    window = _odd_window(0.6 * fwhm_hint / step, xu.size)
    if window < 5 or xu.size <= window:
        return xu, yu
    return xu, savgol_filter(yu, window, polyorder=2)


def estimate_noise(x: np.ndarray, y: np.ndarray, fwhm_hint: float = 1.0) -> NoiseReport:
    """Noise from the residual against a smooth version of the data.

    The residual's median absolute deviation (scaled by 1.4826) is robust to the peaks
    themselves.  For counts the Poisson expectation at the baseline is reported too.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xu, ys = smooth_for_detection(x, y, fwhm_hint)
    yu = np.interp(xu, x, y)
    resid = yu - ys
    mad = float(np.median(np.abs(resid - np.median(resid))))
    sigma = 1.4826 * mad
    baseline = float(np.percentile(y, 10))
    if sigma <= 0:
        # Flat regions or synthetic noiseless data; fall back to a tiny fraction of range.
        sigma = max(1e-12, 1e-6 * float(np.ptp(y)))
        method = "fallback_ptp_fraction"
    else:
        method = "mad_of_savgol_residual"
    peak_height = float(np.max(y) - baseline)
    poisson = float(np.sqrt(max(baseline, 1.0))) if np.all(y >= 0) else None
    return NoiseReport(
        sigma=sigma,
        poisson_sigma=poisson,
        baseline=baseline,
        peak_height=peak_height,
        snr=peak_height / sigma if sigma > 0 else float("inf"),
        method=method,
    )


def charge_correct(
    spectrum: Spectrum, measured: float, reference: float, label: str = ""
) -> tuple[Spectrum, dict[str, Any]]:
    """Shift so that ``measured`` lands on ``reference``; returns the record of what was done."""
    delta = float(reference - measured)
    reason = f"charge correction: {label or 'reference'} {measured:.3f} -> {reference:.3f} eV"
    record = {
        "step": "charge_correction",
        "reference_label": label,
        "measured_eV": float(measured),
        "reference_eV": float(reference),
        "delta_eV": delta,
    }
    if label.strip().lower().startswith("c 1s") or abs(reference - 284.8) < 0.05:
        record["warning"] = C1S_REFERENCE_WARNING
    return spectrum.shift(delta, reason), record
