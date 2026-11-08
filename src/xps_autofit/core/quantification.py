"""Relative quantification and Auger parameters.

``n_i = (A_i / S_i) / sum_j (A_j / S_j)`` with relative sensitivity factors ``S``.

By default no transmission-function or escape-depth correction is applied: the RSF
must then already be appropriate for the instrument (CasaXPS-style empirical factors
or the instrument library).  For *cross-section* factors (Scofield) an optional
:class:`QuantCorrection` divides each area additionally by ``KE ** (a + b)``, where
``KE`` is the kinetic energy of the line, ``a`` models the inelastic mean free path
(``lambda ~ KE**a``, ``a`` about 0.6-0.75) and ``b`` the analyser transmission
(``T ~ KE**b``; ``-1`` for constant-retard-ratio operation, instrument dependent in
constant-analyser-energy mode).  The exponents are stated in every output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

NOT_CALCULABLE = "NOT_CALCULABLE"


@dataclass
class QuantCorrection:
    """Energy-dependent factors applied on top of the RSF (see the module docstring)."""

    imfp_exponent: float = 0.0
    transmission_exponent: float = 0.0

    @property
    def exponent(self) -> float:
        return float(self.imfp_exponent + self.transmission_exponent)

    @property
    def active(self) -> bool:
        return abs(self.exponent) > 1e-12

    def factor(self, kinetic_energy: float) -> float:
        """``KE ** (a + b)``; the corrected area is ``A / (RSF * factor)``."""
        if kinetic_energy <= 0:
            raise ValueError("kinetic energy must be positive")
        return float(kinetic_energy**self.exponent)

    def describe(self) -> str:
        if not self.active:
            return "no transmission or escape-depth correction"
        return (
            f"areas divided by KE^({self.imfp_exponent:g} + {self.transmission_exponent:g}) "
            "(escape depth + transmission)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "imfp_exponent": self.imfp_exponent,
            "transmission_exponent": self.transmission_exponent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> QuantCorrection:
        if not d:
            return cls()
        return cls(
            imfp_exponent=float(d.get("imfp_exponent", 0.0)),
            transmission_exponent=float(d.get("transmission_exponent", 0.0)),
        )


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
    kinetic_energy: float | None = None
    """Kinetic energy used for the energy-dependent correction (``None``: none)."""
    correction_factor: float = 1.0
    """``KE ** (a + b)`` of :class:`QuantCorrection`; 1 without correction."""
    rsf_source: str = ""
    """Where the RSF came from (``recipe``, ``Scofield`` ...); informational."""

    @property
    def divisor(self) -> float | None:
        """``RSF * correction_factor`` (what the area is divided by)."""
        if self.rsf is None or self.rsf <= 0:
            return None
        return float(self.rsf) * self.correction_factor

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
    correction: QuantCorrection | None = None,
    kinetic_energies: dict[str, float] | None = None,
) -> QuantResult:
    """Compute atomic percentages.

    ``items`` are ``(label, element, line, area, rsf)``.  If any RSF is missing the
    result is ``NOT_CALCULABLE`` and lists what is missing rather than guessing.
    With an active *correction*, ``kinetic_energies`` (eV, by label) must cover
    every entry; otherwise the result is ``NOT_CALCULABLE`` as well.
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
    corr = correction or QuantCorrection()
    if corr.active:
        kes = kinetic_energies or {}
        no_ke = [e.label for e in entries if e.label not in kes or kes[e.label] <= 0]
        if no_ke:
            return QuantResult(
                NOT_CALCULABLE,
                entries,
                no_ke,
                "kinetic energy needed for the energy-dependent correction is missing for: "
                + ", ".join(no_ke),
            )
        for e in entries:
            e.kinetic_energy = float(kes[e.label])
            e.correction_factor = corr.factor(e.kinetic_energy)
    for e in entries:
        e.corrected = e.area / float(e.divisor)  # type: ignore[arg-type]
    total = sum(e.corrected for e in entries if e.corrected is not None)
    if total <= 0:
        return QuantResult(NOT_CALCULABLE, entries, [], "total corrected area is zero")
    for e in entries:
        e.atomic_percent = 100.0 * (e.corrected or 0.0) / total
    return QuantResult("OK", entries, [], "RSF-normalised areas; " + corr.describe())


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
        arrays.append(np.asarray(arr, dtype=float) / float(e.divisor))  # type: ignore[arg-type]
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
