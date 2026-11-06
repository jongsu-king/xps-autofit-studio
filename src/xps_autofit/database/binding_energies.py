"""Reference binding energies, Auger kinetic energies and spin-orbit splittings.

Each entry carries a typical range and a source note.  The ranges are deliberately
wide; XPS assignments depend on referencing, matrix and resolution, and the program
reports these as *candidates*, never as a verdict.

Sources: NIST X-ray Photoelectron Spectroscopy Database (SRD 20); Thermo Scientific
XPS knowledge base; M. C. Biesinger, *Surf. Interface Anal.* 49, 1325 (2017) for Cu;
Greczynski & Hultman, *Prog. Mater. Sci.* 107, 100591 (2020) for C 1s referencing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceLine:
    element: str
    line: str
    species: str
    energy: float
    """Typical binding energy (eV); kinetic energy for Auger lines (``kind="auger"``)."""
    low: float
    high: float
    note: str = ""
    kind: str = "photoelectron"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _l(
    el: str,
    line: str,
    species: str,
    e: float,
    lo: float,
    hi: float,
    note: str = "",
    kind: str = "photoelectron",
) -> ReferenceLine:
    return ReferenceLine(el, line, species, e, lo, hi, note, kind)


REFERENCE_LINES: list[ReferenceLine] = [
    # Carbon
    _l(
        "C",
        "1s",
        "C-C / C-H (adventitious)",
        284.8,
        284.4,
        285.1,
        "common reference; position varies with sample",
    ),
    _l("C", "1s", "C-S / C-N (thiophene, amine)", 285.5, 285.2, 285.9),
    _l("C", "1s", "C-O (alcohol, ether)", 286.3, 285.9, 286.8),
    _l("C", "1s", "C=O (carbonyl)", 287.8, 287.4, 288.3),
    _l("C", "1s", "O-C=O (carboxyl, ester)", 288.8, 288.4, 289.4),
    _l("C", "1s", "pi-pi* shake-up", 291.0, 290.5, 291.8, "aromatic systems"),
    _l("C", "1s", "CF2", 291.5, 291.0, 292.0),
    # Nitrogen
    _l("N", "1s", "pyridinic N", 398.8, 398.4, 399.2),
    _l("N", "1s", "amine / carbazole N", 400.0, 399.5, 400.6),
    _l("N", "1s", "protonated / quaternary N", 401.9, 401.4, 402.5),
    _l("N", "1s", "nitro / nitrate", 406.0, 405.0, 407.5),
    # Oxygen
    _l("O", "1s", "lattice oxide O2-", 530.0, 529.3, 530.6),
    _l("O", "1s", "hydroxide / defective oxide", 531.5, 531.0, 532.1),
    _l("O", "1s", "C-O / adsorbed water", 532.9, 532.3, 533.8),
    # Sulfur (2p3/2 of the doublet)
    _l("S", "2p", "metal sulfide / thiolate", 162.0, 161.4, 162.6),
    _l("S", "2p", "thiophene C-S-C (P3HT)", 164.0, 163.7, 164.4, "doublet, 2p3/2 position"),
    _l("S", "2p", "sulfoxide / sulfone", 166.5, 165.8, 167.6),
    _l("S", "2p", "sulfonate / sulfate", 168.5, 167.8, 169.6),
    # Phosphorus (2p3/2)
    _l(
        "P", "2p", "phosphonic acid / phosphonate", 133.3, 132.7, 134.1, "SAM anchors such as 2PACz"
    ),
    _l("P", "2p", "phosphide", 129.5, 128.8, 130.2),
    # Silicon (2p3/2)
    _l("Si", "2p", "Si(0)", 99.4, 99.1, 99.7),
    _l("Si", "2p", "SiO2", 103.5, 103.0, 104.0),
    # Copper (2p3/2)
    _l("Cu", "2p3/2", "Cu(0) metal", 932.6, 932.4, 932.8, "overlaps Cu(I); use Cu LMM"),
    _l("Cu", "2p3/2", "Cu(I) Cu2O", 932.4, 932.1, 932.8, "overlaps Cu(0); use Cu LMM"),
    _l("Cu", "2p3/2", "Cu(II) CuO", 933.6, 933.3, 934.0, "strong satellites 940-945 eV"),
    _l("Cu", "2p3/2", "Cu(II) Cu(OH)2", 934.8, 934.4, 935.2, "satellites present"),
    _l(
        "Cu",
        "2p3/2",
        "Cu(II) shake-up satellite",
        941.5,
        939.5,
        944.5,
        "broad; absent for Cu(0)/Cu(I)",
    ),
    _l("Cu", "LMM", "Cu(0) metal", 918.6, 918.4, 918.8, "kinetic energy; alpha' ~ 1851.2", "auger"),
    _l("Cu", "LMM", "Cu(I) Cu2O", 916.8, 916.4, 917.1, "kinetic energy; alpha' ~ 1849.2", "auger"),
    _l("Cu", "LMM", "Cu(II) CuO", 917.9, 917.6, 918.2, "kinetic energy; alpha' ~ 1851.5", "auger"),
    # Bismuth (4f7/2)
    _l("Bi", "4f", "Bi(0) metal", 157.0, 156.8, 157.2),
    _l("Bi", "4f", "Bi(III) oxide", 159.0, 158.4, 159.6, "doublet, 4f7/2 position"),
    # Zinc, titanium, tin
    _l("Zn", "2p3/2", "ZnO", 1021.8, 1021.4, 1022.3),
    _l("Ti", "2p3/2", "TiO2 Ti(IV)", 458.7, 458.3, 459.1),
    _l("Sn", "3d5/2", "SnO2", 486.7, 486.3, 487.1),
    # Lead, iodine (halide perovskites)
    _l("Pb", "4f", "Pb(0) metal", 136.9, 136.7, 137.2),
    _l("Pb", "4f", "Pb(II) halide", 138.5, 138.2, 138.8, "doublet, 4f7/2 position"),
    _l("I", "3d", "iodide", 619.3, 619.0, 619.7, "doublet, 3d5/2 position"),
    # Gold, silver references
    _l("Au", "4f", "Au(0)", 84.0, 83.9, 84.1, "spectrometer calibration line"),
    _l("Ag", "3d", "Ag(0)", 368.2, 368.1, 368.4, "spectrometer calibration line"),
]

#: ``(element, line) -> (splitting eV, area ratio minor/major)``.
SPIN_ORBIT: dict[tuple[str, str], tuple[float, float]] = {
    ("S", "2p"): (1.18, 0.5),
    ("P", "2p"): (0.84, 0.5),
    ("Si", "2p"): (0.61, 0.5),
    ("Cl", "2p"): (1.60, 0.5),
    ("K", "2p"): (2.80, 0.5),
    ("Ca", "2p"): (3.50, 0.5),
    ("Ti", "2p"): (5.70, 0.5),
    ("Fe", "2p"): (13.1, 0.5),
    ("Co", "2p"): (15.0, 0.5),
    ("Ni", "2p"): (17.3, 0.5),
    ("Cu", "2p"): (19.75, 0.5),
    ("Zn", "2p"): (23.1, 0.5),
    ("Se", "3d"): (0.86, 2.0 / 3.0),
    ("Br", "3d"): (1.04, 2.0 / 3.0),
    ("Mo", "3d"): (3.13, 2.0 / 3.0),
    ("Ag", "3d"): (6.00, 2.0 / 3.0),
    ("Cd", "3d"): (6.74, 2.0 / 3.0),
    ("In", "3d"): (7.54, 2.0 / 3.0),
    ("Sn", "3d"): (8.41, 2.0 / 3.0),
    ("I", "3d"): (11.5, 2.0 / 3.0),
    ("W", "4f"): (2.17, 0.75),
    ("Au", "4f"): (3.67, 0.75),
    ("Pb", "4f"): (4.87, 0.75),
    ("Bi", "4f"): (5.31, 0.75),
}


def spin_orbit(element: str | None, line: str | None) -> tuple[float, float] | None:
    if not element or not line:
        return None
    key = (element, line.split("/")[0].rstrip("0123456789").strip() if "/" in line else line)
    # "2p3/2" -> "2p"
    base = line[:2] if len(line) >= 2 and line[1] in "spdf" else line
    return SPIN_ORBIT.get((element, base)) or SPIN_ORBIT.get(key)


def suggest_assignments(
    element: str | None, line: str | None, energy: float, tolerance: float = 0.5
) -> list[dict[str, Any]]:
    """Reference species whose typical range (widened by ``tolerance``) contains ``energy``.

    Sorted by distance to the typical value.  An empty list means 'no reference', not
    'wrong'.
    """
    if not element or not line:
        return []
    base = line[:2] if len(line) >= 2 and line[1] in "spdf" else line
    out = []
    for ref in REFERENCE_LINES:
        if ref.element != element or ref.kind != "photoelectron":
            continue
        ref_base = ref.line[:2] if len(ref.line) >= 2 and ref.line[1] in "spdf" else ref.line
        if ref_base != base:
            continue
        if ref.low - tolerance <= energy <= ref.high + tolerance:
            d = ref.to_dict()
            d["distance_eV"] = round(abs(energy - ref.energy), 3)
            out.append(d)
    out.sort(key=lambda d: d["distance_eV"])
    return out
