"""Relative quantification and Auger parameters.

``n_i = (A_i / S_i) / sum_j (A_j / S_j)`` with relative sensitivity factors ``S``.
Transmission-function and escape-depth corrections are *not* applied; the RSF must
already be appropriate for the instrument (CasaXPS-style empirical factors or
Scofield cross-sections with the instrument's own correction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NOT_CALCULABLE = "NOT_CALCULABLE"


@dataclass
class QuantEntry:
    label: str
    element: str | None
    line: str | None
    area: float
    rsf: float | None
    corrected: float | None = None
    atomic_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class QuantResult:
    status: str
    entries: list[QuantEntry] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "entries": [e.to_dict() for e in self.entries],
            "missing": self.missing,
            "note": self.note,
        }


def atomic_percent(
    items: list[tuple[str, str | None, str | None, float, float | None]],
) -> QuantResult:
    """Compute atomic percentages.

    ``items`` are ``(label, element, line, area, rsf)``.  If any RSF is missing the
    result is ``NOT_CALCULABLE`` and lists what is missing rather than guessing.
    """
    entries = [
        QuantEntry(label, el, line, float(area), rsf) for label, el, line, area, rsf in items
    ]
    missing = [e.label for e in entries if e.rsf is None or e.rsf <= 0]
    if missing:
        return QuantResult(
            NOT_CALCULABLE,
            entries,
            missing,
            "relative sensitivity factor missing for: " + ", ".join(missing),
        )
    if not entries:
        return QuantResult(NOT_CALCULABLE, [], [], "no entries")
    for e in entries:
        e.corrected = e.area / float(e.rsf)  # type: ignore[arg-type]
    total = sum(e.corrected for e in entries if e.corrected is not None)
    if total <= 0:
        return QuantResult(NOT_CALCULABLE, entries, [], "total corrected area is zero")
    for e in entries:
        e.atomic_percent = 100.0 * (e.corrected or 0.0) / total
    return QuantResult(
        "OK", entries, [], "RSF-normalised areas; no transmission or escape-depth correction"
    )


def auger_parameter(photoelectron_be: float, auger_ke: float) -> float:
    """Modified Auger parameter ``alpha' = BE(photoelectron) + KE(Auger)`` (eV).

    Independent of charging and of the photon energy, hence a robust chemical-state
    discriminator for Cu, Zn and others where the core-level shift alone is ambiguous.
    """
    return float(photoelectron_be + auger_ke)
