"""A recipe proposed from a survey identification.

After :func:`~xps_autofit.automation.identify.identify_elements` has named the
elements in a survey, this module turns each confident element into a
high-resolution region: the strongest matched photoelectron line, a range around
the *measured* peak position (so charging is already accounted for), the
spin-orbit doublet from the database where the line is a p, d or f level, the
Scofield sensitivity factor, and adventitious carbon as the charge reference when
a C 1s region is present.  The result is a starting point for the detailed fits,
not a finished analysis: ranges, component counts and candidate chemical states are
meant to be edited.
"""

from __future__ import annotations

from ..core.constraints import DoubletSpec
from ..core.region import RegionSpec
from ..database.binding_energies import spin_orbit
from ..database.sensitivity_factors import get_rsf
from ..recipes import ChargeReference, Recipe
from .identify import Identification

DEFAULT_HALF_WIDTH = 8.0
"""eV on either side of the main line (the high-energy side also gets the splitting)."""
C1S_REFERENCE_EV = 284.8


def _half_ev(value: float) -> float:
    return round(value * 2.0) / 2.0


def suggest_regions(
    ident: Identification,
    min_confidence: float = 0.5,
    half_width: float = DEFAULT_HALF_WIDTH,
    measured_positions: bool = True,
    max_components: int = 3,
) -> list[RegionSpec]:
    """One region per confident element, built from its strongest matched line."""
    regions: list[RegionSpec] = []
    seen: set[str] = set()
    for cand in sorted(ident.candidates, key=lambda c: -c.confidence):
        if cand.confidence < min_confidence:
            continue
        matches = [m for m in cand.matched if m.line.kind == "photoelectron" and m.peak is not None]
        if not matches:
            continue
        m = max(matches, key=lambda mm: mm.line.intensity)
        el, line = m.line.element, m.line.line
        name = f"{el} {line}"
        if name in seen:
            continue
        seen.add(name)
        assert m.peak is not None
        centre = m.peak.energy if measured_positions else m.expected_eV
        # A line listed as one spin-orbit component ("2p3/2", "4f7/2") is fitted on its
        # own, as the built-in recipes do; an unresolved "2p" / "3d" / "4f" gets the
        # doublet and a range that reaches the partner at higher binding energy.
        so = None if "/" in line else spin_orbit(el, line)
        doublet: DoubletSpec | None = None
        extra_high = 0.0
        if so is not None:
            doublet = DoubletSpec(splitting=so[0], area_ratio=so[1], splitting_tolerance=0.02)
            extra_high = so[0]  # the j - 1/2 partner sits at higher binding energy
        lo = _half_ev(centre - half_width)
        hi = _half_ev(centre + half_width + extra_high)
        rsf = get_rsf(el, line)
        offset = "" if m.offset_eV is None else f", {m.offset_eV:+.1f} eV from the typical value"
        notes = (
            f"suggested from survey {ident.spectrum_name!r}: peak at {centre:.1f} eV"
            f"{offset}; element confidence {cand.confidence:.2f}; "
            + ("Scofield RSF" if rsf is not None else "no RSF in the table (NOT_CALCULABLE)")
            + ". Edit the range, the component count and add candidate states."
        )
        regions.append(
            RegionSpec(
                name=name,
                element=el,
                line=line,
                range=(lo, hi),
                doublet=doublet,
                max_components=max_components,
                rsf=rsf,
                notes=notes,
            )
        )
    return regions


def suggest_recipe(
    ident: Identification,
    name: str = "suggested",
    min_confidence: float = 0.5,
    half_width: float = DEFAULT_HALF_WIDTH,
    measured_positions: bool = True,
    max_components: int = 3,
) -> Recipe:
    """A recipe with one region per identified element and a C 1s charge reference.

    Raises ``ValueError`` when no element reaches ``min_confidence``.
    """
    regions = suggest_regions(ident, min_confidence, half_width, measured_positions, max_components)
    if not regions:
        raise ValueError(
            f"no element in {ident.spectrum_name!r} reaches confidence {min_confidence:.2f}"
        )
    charge = None
    if any(r.element == "C" and r.line == "1s" for r in regions):
        charge = ChargeReference(
            region="C 1s",
            value=C1S_REFERENCE_EV,
            note="adventitious carbon; prefer an internal reference for conductors",
        )
    elements = ", ".join(f"{r.element} {r.line}" for r in regions)
    return Recipe(
        name=name,
        description=(
            f"Regions suggested from the survey {ident.spectrum_name!r}: {elements}. "
            "Ranges are centred on the measured peaks; doublets and RSFs come from the "
            "database. Review before use."
        ),
        photon_energy=ident.photon_energy,
        charge_reference=charge,
        regions=regions,
        source="survey",
        references=[f"identify_elements confidence >= {min_confidence:.2f}"],
    )
