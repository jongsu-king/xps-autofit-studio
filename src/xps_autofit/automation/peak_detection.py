"""Initial peak guesses from a smoothed copy of the net signal.

Smoothing is used only to locate candidates; fits run on the raw data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import find_peaks, peak_widths

from ..core.preprocessing import smooth_for_detection


@dataclass
class PeakGuess:
    center: float
    height: float
    fwhm: float
    prominence: float

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
) -> list[PeakGuess]:
    """Find local maxima whose prominence exceeds ``prominence_sigma * noise_sigma``.

    Returns guesses sorted by decreasing prominence (at most ``max_peaks``).
    """
    xu, ys = smooth_for_detection(np.asarray(x, float), np.asarray(y_net, float), fwhm_hint)
    step = float(xu[1] - xu[0]) if xu.size > 1 else 1.0
    distance = max(1, int(round(min_separation / step)))
    idx, props = find_peaks(
        ys, prominence=max(prominence_sigma * noise_sigma, 1e-12), distance=distance
    )
    if idx.size == 0:
        return []
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
    return guesses[:max_peaks]


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
