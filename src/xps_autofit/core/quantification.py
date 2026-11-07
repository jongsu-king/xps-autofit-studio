"""Relative quantification and Auger parameters.

``n_i = (A_i / S_i) / sum_j (A_j / S_j)`` with relative sensitivity factors ``S``.
Transmission-function and escape-depth corrections are *not* applied; the RSF must
already be appropriate for the instrument (CasaXPS-style empirical factors or
Scofield cross-sections with the instrument's own correction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

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
    atomic_percent_std: float | None = None
    """Standard deviation over bootstrap replicates (``None`` without bootstrap)."""
    atomic_percent_p2_5: float | None = None
    atomic_percent_p97_5: float | None = None

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


def atomic_percent_samples(result: QuantResult, samples: dict[str, np.ndarray]) -> int:
    """Propagate bootstrap area replicates to atomic-percent uncertainties.

    ``samples`` maps a region label to its replicate areas.  Replicates are paired by
    index (the regions' noise is independent), so the number used is the smallest
    replicate count among the regions.  Entries are updated in place; returns the
    number of replicates used (0 when nothing could be propagated).
    """
    if result.status != "OK" or not result.entries:
        return 0
    arrays = []
    for e in result.entries:
        arr = samples.get(e.label)
        if arr is None or arr.size < 2:
            return 0
        arrays.append(np.asarray(arr, dtype=float) / float(e.rsf))  # type: ignore[arg-type]
    n = min(a.size for a in arrays)
    mat = np.vstack([a[:n] for a in arrays])
    total = mat.sum(axis=0)
    good = total > 0
    if good.sum() < 2:
        return 0
    pct = 100.0 * mat[:, good] / total[good]
    for e, row in zip(result.entries, pct):
        e.atomic_percent_std = float(np.std(row, ddof=1))
        e.atomic_percent_p2_5 = float(np.percentile(row, 2.5))
        e.atomic_percent_p97_5 = float(np.percentile(row, 97.5))
    result.note += f"; uncertainties from {int(good.sum())} bootstrap replicates"
    return int(good.sum())


def auger_parameter(photoelectron_be: float, auger_ke: float) -> float:
    """Modified Auger parameter ``alpha' = BE(photoelectron) + KE(Auger)`` (eV).

    Independent of charging and of the photon energy, hence a robust chemical-state
    discriminator for Cu, Zn and others where the core-level shift alone is ambiguous.
    """
    return float(photoelectron_be + auger_ke)
