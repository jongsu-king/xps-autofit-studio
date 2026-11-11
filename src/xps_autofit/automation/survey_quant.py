"""Rough composition from a survey spectrum.

After :func:`~xps_autofit.automation.identify.identify_elements` has named the
elements, each one is quantified from one line of the survey:

1. the strongest matched photoelectron line whose integration window holds no line
   of another identified element (if every line overlaps, the strongest one is used
   and the overlap is reported);
2. the window spans ``window_widths`` peak widths on each side of the measured peak
   (at least ``min_half_width`` eV); lines of the *same* element inside it (a
   spin-orbit partner such as Au 4f5/2 next to 4f7/2) are integrated together and
   their relative intensities summed into the sensitivity factor;
3. a Shirley background between the window ends is subtracted and the rest
   integrated; with counts the area carries its Poisson error;
4. areas are divided by the survey table's relative intensities (Scofield-like
   cross sections, C 1s = 1) and, optionally, by ``KE^(a+b)`` for the escape depth
   and the analyser transmission (:class:`~xps_autofit.core.quantification.QuantCorrection`)
   and normalised to 100 %.

This is a survey-level estimate, typically good to 10-20 % relative: peak shapes,
satellites, the background model and the instrument's own sensitivity factors are
not taken into account the way a fit of high-resolution regions does.  The result
says so in its note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..core.background import BackgroundSpec, compute_background
from ..core.quantification import NOT_CALCULABLE, QuantCorrection, QuantEntry, QuantResult
from ..core.spectrum import Spectrum
from ..database.survey_lines import SURVEY_LINES, SurveyLine
from .identify import Identification, LineMatch

SURVEY_NOTE = (
    "survey estimate: Shirley-subtracted areas of one line per element divided by "
    "Scofield-like relative intensities; typically 10-20 % relative - fit "
    "high-resolution regions for numbers to report"
)


@dataclass
class SurveyQuantLine:
    """One element's line, window, area and share."""

    element: str
    line: str
    peak_eV: float
    window: tuple[float, float]
    area: float
    area_err: float | None
    sensitivity: float
    """Sum of the relative intensities of the element's lines inside the window."""
    kinetic_energy: float
    lines_in_window: list[str] = field(default_factory=list)
    atomic_percent: float | None = None
    atomic_percent_err: float | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.element} {self.line}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "line": self.line,
            "peak_eV": round(self.peak_eV, 2),
            "window_eV": [round(self.window[0], 2), round(self.window[1], 2)],
            "area": self.area,
            "area_err": self.area_err,
            "sensitivity": self.sensitivity,
            "lines_in_window": list(self.lines_in_window),
            "kinetic_energy_eV": round(self.kinetic_energy, 1),
            "atomic_percent": self.atomic_percent,
            "atomic_percent_err": self.atomic_percent_err,
            "note": self.note,
        }


@dataclass
class SurveyQuant:
    spectrum_name: str
    status: str
    lines: list[SurveyQuantLine]
    skipped: dict[str, str]
    """Element -> why it was not quantified."""
    correction: QuantCorrection
    note: str = SURVEY_NOTE

    def composition(self) -> dict[str, float]:
        return {
            q.element: float(q.atomic_percent) for q in self.lines if q.atomic_percent is not None
        }

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "element": q.element,
                "line": q.line,
                "peak_eV": round(q.peak_eV, 1),
                "window_eV": f"{q.window[0]:.1f}-{q.window[1]:.1f}",
                "area": q.area,
                "sensitivity": round(q.sensitivity, 3),
                "atomic_percent": None if q.atomic_percent is None else round(q.atomic_percent, 2),
                "atomic_percent_err": (
                    None if q.atomic_percent_err is None else round(q.atomic_percent_err, 2)
                ),
                "note": q.note,
            }
            for q in self.lines
        ]

    def to_quant_result(self) -> QuantResult:
        """The same numbers as a :class:`QuantResult` (for the Composition tab)."""
        entries = []
        for q in self.lines:
            e = QuantEntry(
                f"{q.label} (survey)", q.element, q.line, q.area, q.sensitivity, rsf_source="survey"
            )
            e.kinetic_energy = q.kinetic_energy
            e.correction_factor = self.correction.factor(q.kinetic_energy)
            e.corrected = q.area / (q.sensitivity * e.correction_factor)
            e.atomic_percent = q.atomic_percent
            e.atomic_percent_std = q.atomic_percent_err
            entries.append(e)
        missing = sorted(self.skipped)
        return QuantResult(self.status, entries, missing, self.note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spectrum": self.spectrum_name,
            "status": self.status,
            "lines": [q.to_dict() for q in self.lines],
            "skipped": dict(self.skipped),
            "correction": self.correction.to_dict(),
            "note": self.note,
        }


def _expected_be(line: SurveyLine, photon_energy: float, shift: float) -> float:
    return (photon_energy - line.energy if line.kind == "auger" else line.energy) + shift


def _window_area(
    x: np.ndarray, y: np.ndarray, lo: float, hi: float, counts: bool, endpoint_points: int
) -> tuple[float, float | None]:
    sel = (x >= lo) & (x <= hi)
    if sel.sum() < 2 * endpoint_points + 3:
        raise ValueError("window holds too few points")
    xs, ys = x[sel], y[sel]
    bg = compute_background(xs, ys, BackgroundSpec(type="shirley", endpoint_points=endpoint_points))
    net = ys - bg.values
    area = float(np.trapezoid(net, xs))
    err: float | None = None
    if counts:
        dx = np.gradient(xs)
        err = float(np.sqrt(np.sum(np.clip(ys, 0.0, None) * dx * dx)))
    return area, err


def quantify_survey(
    spectrum: Spectrum,
    ident: Identification,
    min_confidence: float = 0.5,
    window_widths: float = 2.5,
    min_half_width: float = 3.0,
    correction: QuantCorrection | None = None,
    endpoint_points: int = 3,
) -> SurveyQuant:
    """Atomic percentages of the identified elements from the survey itself."""
    corr = correction or QuantCorrection()
    x, y = spectrum.energy, spectrum.intensity
    counts = spectrum.intensity_unit == "counts"
    shift = ident.charge_shift_eV
    hv = ident.photon_energy
    chosen = [c for c in ident.candidates if c.confidence >= min_confidence]
    skipped: dict[str, str] = {
        c.element: f"confidence {c.confidence:.2f} below {min_confidence:.2f}"
        for c in ident.candidates
        if c.confidence < min_confidence
    }
    # every identified element's matched peaks, to detect overlaps
    others: dict[str, list[float]] = {
        c.element: [m.peak.energy for m in c.matched if m.peak is not None] for c in chosen
    }
    by_element: dict[str, list[SurveyLine]] = {}
    for line in SURVEY_LINES:
        by_element.setdefault(line.element, []).append(line)

    lines: list[SurveyQuantLine] = []
    for cand in chosen:
        matches: list[LineMatch] = sorted(
            (m for m in cand.matched if m.peak is not None and m.line.kind == "photoelectron"),
            key=lambda m: -m.line.intensity,
        )
        if not matches:
            skipped[cand.element] = "no matched photoelectron line"
            continue
        picked: tuple[LineMatch, float, float, list[str]] | None = None
        fallback: tuple[LineMatch, float, float, list[str]] | None = None
        for m in matches:
            assert m.peak is not None
            hw = max(min_half_width, window_widths * m.peak.width)
            lo, hi = m.peak.energy - hw, m.peak.energy + hw
            clash = sorted(
                el
                for el, peaks in others.items()
                if el != cand.element and any(lo <= p <= hi for p in peaks)
            )
            if fallback is None:
                fallback = (m, lo, hi, clash)
            if not clash:
                picked = (m, lo, hi, clash)
                break
        assert fallback is not None
        m, lo, hi, clash = picked or fallback
        assert m.peak is not None
        lo, hi = max(lo, float(x[0])), min(hi, float(x[-1]))
        inside = [
            ln
            for ln in by_element.get(cand.element, [])
            if ln.kind == "photoelectron" and lo <= _expected_be(ln, hv, shift) <= hi
        ]
        if m.line not in inside:
            inside.append(m.line)
        sensitivity = float(sum(ln.intensity for ln in inside))
        try:
            area, area_err = _window_area(x, y, lo, hi, counts, endpoint_points)
        except Exception as exc:  # window at the edge of the data, background failure
            skipped[cand.element] = f"{m.label}: {exc}"
            continue
        if area <= 0:
            skipped[cand.element] = f"{m.label}: no area above the background"
            continue
        note = f"overlaps {', '.join(clash)}" if clash else ""
        lines.append(
            SurveyQuantLine(
                element=cand.element,
                line=m.line.line,
                peak_eV=float(m.peak.energy),
                window=(lo, hi),
                area=area,
                area_err=area_err,
                sensitivity=sensitivity,
                kinetic_energy=hv - m.peak.energy,
                lines_in_window=[f"{cand.element} {ln.line}" for ln in inside],
                note=note,
            )
        )
    if not lines:
        return SurveyQuant(
            spectrum.name, NOT_CALCULABLE, [], skipped, corr, "no element could be quantified"
        )
    corrected = np.array(
        [q.area / (q.sensitivity * corr.factor(q.kinetic_energy)) for q in lines], dtype=float
    )
    total = float(corrected.sum())
    for q, r in zip(lines, corrected):
        q.atomic_percent = 100.0 * float(r) / total
    if all(q.area_err is not None for q in lines):
        # first-order propagation of the area errors to the shares
        sig = np.array(
            [(q.area_err or 0.0) / (q.sensitivity * corr.factor(q.kinetic_energy)) for q in lines]
        )
        for i, q in enumerate(lines):
            d_self = (total - corrected[i]) / total**2
            d_other = corrected[i] / total**2
            var = (d_self * sig[i]) ** 2 + sum(
                (d_other * sig[j]) ** 2 for j in range(len(lines)) if j != i
            )
            q.atomic_percent_err = 100.0 * float(np.sqrt(var))
    note = SURVEY_NOTE + ("; " + corr.describe() if corr.active else "")
    return SurveyQuant(spectrum.name, "OK", lines, skipped, corr, note)
