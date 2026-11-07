"""Initial peak guesses from a smoothed copy of the net signal.

Two detectors are combined:

* **maxima** of the Savitzky-Golay smoothed signal with a prominence above
  ``prominence_sigma`` times the noise, and
* **shoulders**: dips of the smoothed second derivative that stand out of the noise
  propagated through the derivative filter and that do not coincide with a maximum.
  An unresolved chemical state on the flank of a stronger line bends the curvature
  there long before it forms a maximum of its own.

Smoothing is used only to locate candidates; fits run on the raw data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import find_peaks, peak_widths, savgol_coeffs, savgol_filter

from ..core.preprocessing import detection_window, smooth_for_detection, uniform_grid


@dataclass
class PeakGuess:
    center: float
    height: float
    fwhm: float
    prominence: float
    kind: str = "maximum"
    """``"maximum"`` (local maximum of the smoothed signal) or ``"shoulder"``
    (second-derivative minimum without a maximum of its own)."""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def detect_peaks(
    x: np.ndarray,
    y_net: np.ndarray,
    noise_sigma: float,
    fwhm_hint: float = 1.0,
    min_separation: float = 0.3,
    max_peaks: int = 8,
    prominence_sigma: float = 3.0,
    shoulders: bool = True,
    shoulder_sigma: float = 8.0,
    sigma: np.ndarray | None = None,
) -> list[PeakGuess]:
    """Find local maxima whose prominence exceeds ``prominence_sigma * noise_sigma``
    and, with ``shoulders``, dips of the second derivative more prominent than
    ``shoulder_sigma`` times the derivative noise (see :func:`detect_shoulders`).

    ``sigma`` (per-point noise of the raw data, e.g. Poisson) makes the shoulder
    threshold local, so the larger noise on top of a strong peak does not pass as a
    shoulder.  Shoulder guesses are ranked below every maximum.  Returns guesses
    sorted by decreasing prominence (at most ``max_peaks``).
    """
    x = np.asarray(x, float)
    y_net = np.asarray(y_net, float)
    xu, ys = smooth_for_detection(x, y_net, fwhm_hint)
    step = float(xu[1] - xu[0]) if xu.size > 1 else 1.0
    distance = max(1, int(round(min_separation / step)))
    idx, props = find_peaks(
        ys, prominence=max(prominence_sigma * noise_sigma, 1e-12), distance=distance
    )
    guesses: list[PeakGuess] = []
    if idx.size:
        widths, _h, _l, _r = peak_widths(ys, idx, rel_height=0.5)
        guesses = [
            PeakGuess(
                center=float(xu[i]),
                height=float(ys[i]),
                fwhm=float(max(w * step, 0.3 * fwhm_hint)),
                prominence=float(p),
            )
            for i, w, p in zip(idx, widths, props["prominences"])
        ]
    guesses.sort(key=lambda g: g.prominence, reverse=True)
    if shoulders:
        found = detect_shoulders(
            x,
            y_net,
            noise_sigma,
            fwhm_hint,
            min_separation,
            [g.center for g in guesses],
            shoulder_sigma,
            sigma,
        )
        found.sort(key=lambda g: g.prominence, reverse=True)
        guesses.extend(found)
    return guesses[:max_peaks]


def detect_shoulders(
    x: np.ndarray,
    y_net: np.ndarray,
    noise_sigma: float,
    fwhm_hint: float,
    min_separation: float,
    exclude_centers: list[float],
    shoulder_sigma: float = 8.0,
    sigma: np.ndarray | None = None,
) -> list[PeakGuess]:
    """Dips of the second derivative that are not within ``min_separation`` of a
    maximum.

    On the flank of a single bell-shaped line the second derivative is monotonic
    beyond the inflection point, so a local dip there needs a second component.  The
    derivative is taken with a Savitzky-Golay filter spanning about one FWHM; white
    noise of standard deviation ``s`` propagates to ``s * sqrt(sum(c_k**2))`` with
    ``c_k`` the derivative weights.  A dip counts when its prominence exceeds
    ``shoulder_sigma`` times that value for the local noise (``noise_sigma`` or the
    per-point ``sigma``, whichever is larger).  The guess carries 30 % of the
    smoothed signal at the dip as height; the fit decides the rest.
    """
    xu, yu, step = uniform_grid(np.asarray(x, float), np.asarray(y_net, float))
    window = detection_window(step, fwhm_hint, xu.size, fraction=1.0)
    if window < 7:
        return []
    d2 = savgol_filter(yu, window, polyorder=2, deriv=2, delta=step)
    ys = savgol_filter(yu, window, polyorder=2)
    coeffs = savgol_coeffs(window, 2, deriv=2, delta=step)
    gain = float(np.sqrt(np.sum(coeffs**2)))
    local = np.full(xu.size, float(noise_sigma))
    if sigma is not None:
        local = np.maximum(local, np.interp(xu, np.asarray(x, float), np.asarray(sigma, float)))
    floor = max(shoulder_sigma * gain * float(noise_sigma), 1e-12)
    distance = max(1, int(round(min_separation / step)))
    idx, props = find_peaks(-d2, prominence=floor, distance=distance)
    out: list[PeakGuess] = []
    half = window // 2
    for i, prom in zip(idx, props["prominences"]):
        if i < half or i >= xu.size - half:
            continue  # derivative is unreliable in the filter's edge zone
        if prom < shoulder_sigma * gain * local[i]:
            continue
        c = float(xu[i])
        if any(abs(c - e) < min_separation for e in exclude_centers):
            continue
        h = float(max(0.3 * ys[i], 1e-9))
        out.append(PeakGuess(c, h, fwhm_hint, h, "shoulder"))
    return out


def pair_doublets(
    guesses: list[PeakGuess], splitting: float, area_ratio: float, tolerance: float
) -> list[PeakGuess]:
    """Collapse detected doublet partners onto their major (lower-BE) line.

    A guess ``h`` is a partner of ``g`` when it sits ``splitting`` eV above ``g`` within
    ``tolerance`` and its height ratio is plausible for the given area ratio.
    """
    ordered = sorted(guesses, key=lambda g: g.center)
    consumed: set[int] = set()
    majors: list[PeakGuess] = []
    for i, g in enumerate(ordered):
        if i in consumed:
            continue
        for j in range(i + 1, len(ordered)):
            if j in consumed:
                continue
            h = ordered[j]
            if abs(h.center - (g.center + splitting)) <= tolerance:
                ratio = h.height / g.height if g.height > 0 else 0.0
                if 0.3 * area_ratio <= ratio <= min(1.3, 2.0 * area_ratio):
                    consumed.add(j)
                    break
        majors.append(g)
    majors.sort(key=lambda g: g.prominence, reverse=True)
    return majors


def residual_peak(
    x: np.ndarray,
    residual: np.ndarray,
    fwhm_hint: float,
    exclude_centers: list[float],
    min_separation: float,
    edge_margin: float = 0.2,
) -> PeakGuess | None:
    """Location of the largest positive smoothed residual away from existing centres."""
    xu, rs = smooth_for_detection(np.asarray(x, float), np.asarray(residual, float), fwhm_hint)
    mask = (xu > xu[0] + edge_margin) & (xu < xu[-1] - edge_margin)
    for c in exclude_centers:
        mask &= np.abs(xu - c) >= min_separation
    if not mask.any():
        return None
    i = int(np.argmax(np.where(mask, rs, -np.inf)))
    if rs[i] <= 0:
        return None
    return PeakGuess(
        center=float(xu[i]), height=float(rs[i]), fwhm=fwhm_hint, prominence=float(rs[i])
    )
