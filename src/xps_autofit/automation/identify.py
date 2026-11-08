"""Element identification in survey spectra.

Peaks are located on a smoothed copy of the survey (prominence above the noise), and
every element of :data:`~xps_autofit.database.survey_lines.SURVEY_LINES` is scored by
how much of its expected line intensity, within the measured range, is accounted for
by detected peaks:

* an element is a candidate only when its **strongest line in range** is matched;
* ``confidence = matched intensity / expected intensity``, reduced when a matched
  peak is far weaker than the element's main line would require (so a chance
  coincidence of a weak secondary line does not score as a detection);
* a peak claimed by several elements is reported as *ambiguous*, with the
  alternatives, instead of being awarded to one of them.

The result is a ranked list of candidates with the matched and missing lines, the
detected peaks that no element explains, and the parameters used.  It is a *first
look* at a survey, not an assignment: confirm with high-resolution regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from ..core.preprocessing import detection_window, estimate_noise, uniform_grid
from ..core.spectrum import AL_KALPHA_EV, Spectrum
from ..database.survey_lines import SURVEY_LINES, SurveyLine


@dataclass
class SurveyPeak:
    energy: float
    """Binding energy of the maximum (eV)."""
    height: float
    """Prominence above the local baseline (counts or intensity units)."""
    width: float
    """Width at half prominence (eV)."""
    snr: float
    claims: list[str] = field(default_factory=list)
    """``"Cu 2p3/2"``-style labels of every line matched to this peak."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "energy_eV": round(self.energy, 2),
            "height": round(self.height, 1),
            "width_eV": round(self.width, 2),
            "snr": round(self.snr, 1),
            "claims": list(self.claims),
        }


@dataclass
class LineMatch:
    line: SurveyLine
    expected_eV: float
    """Expected position on the binding-energy scale (Auger lines converted)."""
    peak: SurveyPeak | None
    """Matched peak, or ``None`` when the line is missing."""

    @property
    def label(self) -> str:
        return f"{self.line.element} {self.line.line}"

    @property
    def offset_eV(self) -> float | None:
        return None if self.peak is None else self.peak.energy - self.expected_eV

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.label,
            "kind": self.line.kind,
            "expected_eV": round(self.expected_eV, 1),
            "found_eV": None if self.peak is None else round(self.peak.energy, 2),
            "offset_eV": None if self.offset_eV is None else round(self.offset_eV, 2),
            "height": None if self.peak is None else round(self.peak.height, 1),
            "relative_intensity": self.line.intensity,
        }


@dataclass
class ElementCandidate:
    element: str
    confidence: float
    matched: list[LineMatch]
    missing: list[LineMatch]
    ambiguous_with: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def main_line(self) -> LineMatch | None:
        return max(self.matched, key=lambda m: m.line.intensity, default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "confidence": round(self.confidence, 3),
            "matched": [m.to_dict() for m in self.matched],
            "missing": [m.to_dict() for m in self.missing],
            "ambiguous_with": list(self.ambiguous_with),
            "note": self.note,
        }


@dataclass
class Identification:
    spectrum_name: str
    candidates: list[ElementCandidate]
    peaks: list[SurveyPeak]
    photon_energy: float
    tolerance_eV: float
    charge_shift_eV: float
    noise_sigma: float
    notes: list[str] = field(default_factory=list)

    @property
    def unassigned(self) -> list[SurveyPeak]:
        return [p for p in self.peaks if not p.claims]

    def elements(self, min_confidence: float = 0.0) -> list[str]:
        return [c.element for c in self.candidates if c.confidence >= min_confidence]

    def rows(self) -> list[dict[str, Any]]:
        """One row per candidate, for tables."""
        out = []
        for c in self.candidates:
            main = c.main_line
            out.append(
                {
                    "element": c.element,
                    "confidence": round(c.confidence, 2),
                    "main_line": main.label if main else "",
                    "main_line_eV": (
                        round(main.peak.energy, 2) if main and main.peak is not None else None
                    ),
                    "offset_eV": (
                        round(main.offset_eV, 2) if main and main.offset_eV is not None else None
                    ),
                    "lines_found": "; ".join(
                        f"{m.label} {m.peak.energy:.1f}" for m in c.matched if m.peak
                    ),
                    "lines_missing": "; ".join(f"{m.label} {m.expected_eV:.0f}" for m in c.missing),
                    "ambiguous_with": ", ".join(c.ambiguous_with),
                    "note": c.note,
                }
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "spectrum": self.spectrum_name,
            "photon_energy_eV": self.photon_energy,
            "tolerance_eV": self.tolerance_eV,
            "charge_shift_eV": self.charge_shift_eV,
            "noise_sigma": self.noise_sigma,
            "candidates": [c.to_dict() for c in self.candidates],
            "peaks": [p.to_dict() for p in self.peaks],
            "unassigned": [p.to_dict() for p in self.unassigned],
            "notes": list(self.notes),
        }


# ------------------------------------------------------------------- peak finding
def find_survey_peaks(
    spectrum: Spectrum,
    prominence_sigma: float = 5.0,
    smooth_eV: float = 1.0,
    max_peaks: int = 60,
) -> tuple[list[SurveyPeak], float]:
    """Locate maxima in a survey.

    The data are put on a uniform grid, smoothed with a Savitzky-Golay window of
    about ``smooth_eV``, and :func:`scipy.signal.find_peaks` is run with a prominence
    floor of ``prominence_sigma`` times the noise.  Each maximum must also rise
    ``prominence_sigma`` times its own Poisson noise above the local baseline, which
    removes the ripples of a strong step background.  Returns the peaks (strongest
    first) and the noise estimate.
    """
    from scipy.signal import savgol_filter

    x = spectrum.energy
    y = spectrum.intensity
    xu, yu, step = uniform_grid(x, y)
    noise = estimate_noise(x, y, fwhm_hint=smooth_eV)
    sigma = noise.sigma
    window = detection_window(step, smooth_eV, xu.size, fraction=1.0)
    ys = savgol_filter(yu, window, polyorder=2) if window else yu
    span = float(xu[-1] - xu[0])
    wlen = max(int(round(min(30.0, span / 2) / step)), 5)
    idx, props = find_peaks(
        ys,
        prominence=max(prominence_sigma * sigma, 1e-12),
        distance=max(int(round(0.6 / step)), 1),
        width=max(int(round(0.3 / step)), 1),
        wlen=wlen,
        rel_height=0.5,
    )
    peaks: list[SurveyPeak] = []
    for i, prom, width in zip(idx, props["prominences"], props["widths"]):
        local = max(sigma, float(np.sqrt(max(ys[i], 1.0))) if np.all(y >= 0) else sigma)
        if prom < prominence_sigma * local:
            continue
        peaks.append(
            SurveyPeak(
                energy=float(xu[i]),
                height=float(prom),
                width=float(width * step),
                snr=float(prom / local),
            )
        )
    peaks.sort(key=lambda p: -p.height)
    return peaks[:max_peaks], float(sigma)


# ------------------------------------------------------------------- matching
def _expected_be(line: SurveyLine, photon_energy: float) -> float:
    return photon_energy - line.energy if line.kind == "auger" else line.energy


def strongest_intensity_fraction(in_range: list[tuple[SurveyLine, float]], overall: float) -> float:
    """``sqrt(strongest line in range / strongest line of the element)``, or 1.

    Equal to 1 when the element's main line is inside the measured range; smaller
    when only secondary lines can be seen, which makes a chance match more likely.
    """
    if not in_range or overall <= 0:
        return 1.0
    best = max(line.intensity for line, _ in in_range)
    return float(min(1.0, np.sqrt(best / overall)))


def identify_elements(
    spectrum: Spectrum,
    tolerance: float = 1.5,
    min_confidence: float = 0.3,
    prominence_sigma: float = 5.0,
    charge_shift: float = 0.0,
    photon_energy: float | None = None,
    elements: list[str] | None = None,
) -> Identification:
    """Rank the elements whose lines explain the peaks of a survey spectrum.

    Parameters
    ----------
    tolerance
        Maximum distance (eV) between a detected maximum and the typical line
        position.  Chemical shifts and charging move lines by about 1 eV; use a
        larger value for strongly charging samples, or set ``charge_shift``.
    charge_shift
        Added to every expected position (eV): the amount by which the measured
        scale is displaced, e.g. ``measured C 1s - 284.8``.
    photon_energy
        Needed to place Auger lines; defaults to the spectrum's value or Al K-alpha.
    elements
        Restrict the search to these symbols (``None``: every element in the table).
    """
    if spectrum.axis != "binding":
        spectrum = spectrum.to_binding(photon_energy)
    hv = float(photon_energy or spectrum.photon_energy or AL_KALPHA_EV)
    peaks, sigma = find_survey_peaks(spectrum, prominence_sigma)
    lo, hi = spectrum.range
    notes: list[str] = []
    if not peaks:
        notes.append("no peaks above the noise")
    if hi - lo < 200:
        notes.append(
            f"range {lo:.0f}-{hi:.0f} eV is narrow for a survey; secondary lines may be outside"
        )

    wanted = set(elements) if elements else None
    by_element: dict[str, list[SurveyLine]] = {}
    for line in SURVEY_LINES:
        if wanted is not None and line.element not in wanted:
            continue
        by_element.setdefault(line.element, []).append(line)

    peak_energies = np.array([p.energy for p in peaks]) if peaks else np.empty(0)
    candidates: list[ElementCandidate] = []
    claims: dict[int, list[str]] = {}
    for element, lines in by_element.items():
        in_range = []
        for line in lines:
            e = _expected_be(line, hv) + charge_shift
            if lo + tolerance <= e <= hi - tolerance:
                in_range.append((line, e))
        if not in_range:
            continue
        matched: list[LineMatch] = []
        missing: list[LineMatch] = []
        used: list[int] = []
        for line, e in in_range:
            peak = None
            if peak_energies.size:
                d = np.abs(peak_energies - e)
                j = int(np.argmin(d))
                if d[j] <= tolerance:
                    peak = peaks[j]
                    used.append(j)
            (matched if peak is not None else missing).append(LineMatch(line, e, peak))
        if not matched:
            continue
        strongest = max(in_range, key=lambda t: t[0].intensity)[0]
        if all(m.line is not strongest for m in matched):
            continue  # the main line is absent: a secondary line alone is a coincidence
        expected = sum(line.intensity for line, _ in in_range)
        got = sum(m.line.intensity for m in matched)
        confidence = got / expected if expected > 0 else 0.0
        # When the element's strongest line lies outside the measured range, only
        # weaker lines can be seen and a coincidence is more likely: cap accordingly.
        overall = max(line.intensity for line in lines)
        if strongest_fraction := strongest_intensity_fraction(in_range, overall):
            confidence *= strongest_fraction
        # Intensity consistency: a photoelectron secondary line that is matched must
        # not be much stronger than the main line allows (that peak is something else).
        main = next(m for m in matched if m.line is strongest)
        assert main.peak is not None
        penalty = 1.0
        for m in matched:
            if m is main or m.peak is None or m.line.kind != "photoelectron":
                continue
            expected_ratio = m.line.intensity / strongest.intensity
            observed_ratio = m.peak.height / max(main.peak.height, 1e-12)
            if observed_ratio > 4.0 * expected_ratio + 0.05:
                penalty *= 0.7
        confidence *= penalty
        if confidence < min_confidence:
            continue
        cand = ElementCandidate(element, float(confidence), matched, missing)
        if penalty < 1.0:
            cand.note = "a secondary line is stronger than the main line allows"
        candidates.append(cand)
        for j, m in zip(used, matched):
            claims.setdefault(j, []).append(m.label)

    for j, labels in claims.items():
        peaks[j].claims = labels

    # Shared peaks: walk the candidates from the most to the least confident.  A
    # candidate whose main line sits on a peak already explained by a stronger
    # candidate is ambiguous (half confidence); if every one of its peaks is already
    # explained it is most likely a coincidence (quarter confidence).
    candidates.sort(key=lambda c: (-c.confidence, c.element))
    explained: dict[int, str] = {}
    for c in candidates:
        own = [peaks.index(m.peak) for m in c.matched if m.peak is not None]
        lead = c.main_line
        main_idx = peaks.index(lead.peak) if lead is not None and lead.peak is not None else None
        prior = sorted({explained[j] for j in own if j in explained})
        if main_idx is not None and main_idx in explained:
            c.ambiguous_with = [e for e in prior if e != c.element]
            c.confidence *= 0.5
            if all(j in explained for j in own):
                c.confidence *= 0.5
                c.note = (c.note + "; " if c.note else "") + (
                    "every matched peak is explained by " + ", ".join(c.ambiguous_with)
                )
        for j in own:
            explained.setdefault(j, c.element)
    dropped = [c.element for c in candidates if c.confidence < min_confidence]
    candidates = [c for c in candidates if c.confidence >= min_confidence]
    if dropped:
        notes.append(
            f"below confidence {min_confidence:g} after resolving shared peaks: "
            + ", ".join(dropped)
        )
    candidates.sort(key=lambda c: (-c.confidence, c.element))
    unassigned = [p for p in peaks if not p.claims]
    if unassigned:
        notes.append(f"{len(unassigned)} peak(s) matched no line in the table")
    return Identification(
        spectrum_name=spectrum.name,
        candidates=candidates,
        peaks=peaks,
        photon_energy=hv,
        tolerance_eV=tolerance,
        charge_shift_eV=charge_shift,
        noise_sigma=sigma,
        notes=notes,
    )


def nearest_lines(energy: float, photon_energy: float = AL_KALPHA_EV, k: int = 3) -> list[str]:
    """Labels of the ``k`` table lines closest to ``energy`` (hints for unassigned peaks)."""
    ranked = sorted(SURVEY_LINES, key=lambda ln: abs(_expected_be(ln, photon_energy) - energy))
    return [f"{ln.element} {ln.line} ({_expected_be(ln, photon_energy):.0f})" for ln in ranked[:k]]
