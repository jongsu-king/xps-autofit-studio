"""Principal XPS lines for identifying elements in a survey spectrum.

Each entry gives the *typical* binding energy of a core level (Al K-alpha scale,
charge-referenced) and a relative intensity that follows the Scofield
cross-sections (C 1s = 1) to within the accuracy needed for a yes/no decision.
Auger lines are listed by kinetic energy (``kind="auger"``) and converted to the
binding-energy scale of the spectrum with its photon energy.

The positions are typical values with a spread of about +/-1 eV across chemical
states (metals versus oxides, charging); the identification therefore works with a
tolerance of a few eV and never reports a chemical state - that is the job of the
high-resolution regions and :mod:`.binding_energies`.

Sources: NIST X-ray Photoelectron Spectroscopy Database (SRD 20); J. H. Scofield,
J. Electron Spectrosc. Relat. Phenom. 8, 129 (1976); Moulder, Stickle, Sobol,
Bomben, *Handbook of X-ray Photoelectron Spectroscopy* (1992).  Values are rounded
to 0.5 eV where the handbooks disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SurveyLine:
    element: str
    line: str
    energy: float
    """Binding energy (eV) for photoelectron lines; kinetic energy for Auger lines."""
    intensity: float
    """Relative intensity (Scofield-like, C 1s = 1); Auger lines carry a rough value."""
    kind: str = "photoelectron"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _p(el: str, line: str, be: float, rel: float, note: str = "") -> SurveyLine:
    return SurveyLine(el, line, be, rel, "photoelectron", note)


def _a(el: str, line: str, ke: float, rel: float, note: str = "") -> SurveyLine:
    return SurveyLine(el, line, ke, rel, "auger", note)


SURVEY_LINES: list[SurveyLine] = [
    # ---- light elements
    _p("Li", "1s", 55.0, 0.06),
    _p("Be", "1s", 111.5, 0.07),
    _p("B", "1s", 188.5, 0.13),
    _p("C", "1s", 284.8, 1.00, "adventitious carbon reference"),
    _a("C", "KLL", 1223.0, 0.3),
    _p("N", "1s", 399.5, 1.80),
    _a("N", "KLL", 381.0, 0.4),
    _p("O", "1s", 531.5, 2.93),
    _p("O", "2s", 23.0, 0.14),
    _a("O", "KLL", 510.0, 1.5),
    _p("F", "1s", 686.0, 4.43),
    _p("F", "2s", 31.0, 0.21),
    _a("F", "KLL", 655.0, 1.2),
    _p("Na", "1s", 1071.5, 8.52),
    _p("Na", "2s", 63.5, 0.42),
    _a("Na", "KLL", 990.0, 2.0),
    _p("Mg", "2p", 49.8, 0.33),
    _p("Mg", "2s", 88.5, 0.50),
    _p("Mg", "1s", 1303.5, 3.0, "kinetic energy ~183 eV at Al K-alpha: weak in practice"),
    _a("Mg", "KLL", 1186.0, 1.0),
    _p("Al", "2p", 73.5, 0.54),
    _p("Al", "2s", 118.5, 0.75),
    _p("Si", "2p", 100.5, 0.82, "99.5 Si(0), 103.5 SiO2"),
    _p("Si", "2s", 151.0, 0.95),
    _p("P", "2p", 133.0, 1.19),
    _p("P", "2s", 190.5, 1.18),
    _p("S", "2p", 164.0, 1.68),
    _p("S", "2s", 228.0, 1.43),
    _p("Cl", "2p", 199.0, 2.29),
    _p("Cl", "2s", 270.0, 1.69),
    _p("K", "2p3/2", 293.0, 2.65),
    _p("K", "2p1/2", 295.8, 1.33),
    _p("K", "2s", 378.0, 1.10),
    _p("Ca", "2p3/2", 347.0, 3.35),
    _p("Ca", "2p1/2", 350.5, 1.70),
    _p("Ca", "2s", 438.5, 1.30),
    # ---- 3d transition metals
    _p("Ti", "2p3/2", 458.5, 5.22, "454 Ti(0), 458.7 TiO2"),
    _p("Ti", "2p1/2", 464.2, 2.65),
    _p("Ti", "2s", 561.0, 1.60),
    _p("Ti", "3p", 37.0, 0.40),
    _a("Ti", "LMM", 418.0, 0.8),
    _p("V", "2p3/2", 516.5, 6.30),
    _p("V", "2p1/2", 524.0, 3.20),
    _p("Cr", "2p3/2", 576.5, 7.60),
    _p("Cr", "2p1/2", 586.0, 3.90),
    _p("Cr", "3p", 43.0, 0.50),
    _p("Mn", "2p3/2", 641.5, 9.20),
    _p("Mn", "2p1/2", 653.0, 4.70),
    _p("Mn", "3p", 48.0, 0.60),
    _p("Fe", "2p3/2", 710.5, 10.82, "707 Fe(0), 710-711 oxides"),
    _p("Fe", "2p1/2", 724.0, 5.50),
    _p("Fe", "3p", 55.5, 0.70),
    _a("Fe", "LMM", 703.0, 1.5),
    _p("Co", "2p3/2", 780.0, 12.60),
    _p("Co", "2p1/2", 796.0, 6.40),
    _p("Co", "3p", 60.0, 0.80),
    _a("Co", "LMM", 775.0, 1.5),
    _p("Ni", "2p3/2", 855.0, 14.61, "852.6 Ni(0), 854-856 oxides/hydroxide"),
    _p("Ni", "2p1/2", 872.5, 7.40),
    _p("Ni", "3p", 67.0, 1.00),
    _a("Ni", "LMM", 846.0, 2.0),
    _p("Cu", "2p3/2", 933.0, 16.73, "932.6 Cu(0)/Cu(I), 933.6 CuO"),
    _p("Cu", "2p1/2", 952.8, 8.50),
    _p("Cu", "3p", 75.5, 1.20),
    _p("Cu", "3s", 122.5, 0.90),
    _a("Cu", "LMM", 918.0, 2.5),
    _p("Zn", "2p3/2", 1021.8, 18.92),
    _p("Zn", "2p1/2", 1044.9, 9.60),
    _p("Zn", "3p", 89.0, 1.40),
    _p("Zn", "3s", 140.0, 1.00),
    _a("Zn", "LMM", 992.0, 2.5),
    _p("Ga", "2p3/2", 1117.5, 15.0, "kinetic energy ~369 eV at Al K-alpha"),
    _p("Ga", "2p1/2", 1144.5, 7.5),
    _p("Ga", "3d", 19.5, 1.10),
    _p("Ga", "3p", 106.0, 1.60),
    _a("Ga", "LMM", 1066.0, 1.5),
    _p("Ge", "3d", 29.5, 1.30),
    _p("Ge", "2p3/2", 1217.5, 12.0, "kinetic energy ~269 eV at Al K-alpha"),
    _p("Ge", "3p", 123.0, 1.90),
    _a("Ge", "LMM", 1145.0, 1.5),
    _p("As", "3d", 41.5, 1.60),
    _p("As", "2p3/2", 1323.5, 6.0, "kinetic energy ~163 eV at Al K-alpha: weak in practice"),
    _p("As", "3p", 142.0, 2.20),
    _p("Se", "3d", 55.5, 1.90),
    _p("Se", "3p", 162.0, 2.60),
    _p("Br", "3d", 69.5, 2.30),
    _p("Br", "3p", 184.0, 3.00),
    _p("Rb", "3d", 110.5, 3.40),
    _p("Sr", "3d5/2", 134.0, 3.90),
    _p("Sr", "3d3/2", 135.8, 2.60),
    _p("Y", "3d5/2", 156.0, 4.40),
    _p("Y", "3d3/2", 158.1, 2.90),
    _p("Zr", "3d5/2", 179.0, 5.00, "178.8 Zr(0), 182.2 ZrO2"),
    _p("Zr", "3d3/2", 181.4, 3.40),
    _p("Nb", "3d5/2", 202.5, 5.60),
    _p("Nb", "3d3/2", 205.3, 3.80),
    _p("Mo", "3d5/2", 228.0, 6.20, "227.9 Mo(0), 232.5 MoO3"),
    _p("Mo", "3d3/2", 231.1, 4.10),
    _p("Mo", "3p3/2", 394.5, 3.30),
    _p("Ru", "3d5/2", 280.0, 7.10, "overlaps C 1s"),
    _p("Ru", "3d3/2", 284.2, 4.70),
    _p("Rh", "3d5/2", 307.2, 7.80),
    _p("Rh", "3d3/2", 312.0, 5.20),
    _p("Pd", "3d5/2", 335.3, 8.50),
    _p("Pd", "3d3/2", 340.6, 5.70),
    _a("Pd", "MNN", 326.0, 1.0),
    _p("Ag", "3d5/2", 368.2, 10.66),
    _p("Ag", "3d3/2", 374.2, 7.40),
    _a("Ag", "MNN", 357.8, 1.5),
    _p("Cd", "3d5/2", 405.0, 11.50),
    _p("Cd", "3d3/2", 411.7, 7.90),
    _a("Cd", "MNN", 381.0, 1.5),
    _p("In", "3d5/2", 444.5, 12.40),
    _p("In", "3d3/2", 452.0, 8.50),
    _a("In", "MNN", 405.0, 1.5),
    _p("Sn", "3d5/2", 486.5, 14.80, "484.9 Sn(0), 486.7 SnO2"),
    _p("Sn", "3d3/2", 494.9, 10.30),
    _a("Sn", "MNN", 431.0, 1.5),
    _p("Sb", "3d5/2", 528.5, 15.60, "overlaps O 1s"),
    _p("Sb", "3d3/2", 537.9, 10.80),
    _p("Te", "3d5/2", 573.0, 17.60),
    _p("Te", "3d3/2", 583.4, 12.20),
    _p("I", "3d5/2", 619.0, 19.80),
    _p("I", "3d3/2", 630.5, 13.70),
    _p("Cs", "3d5/2", 724.5, 22.50),
    _p("Cs", "3d3/2", 738.5, 15.60),
    _p("Ba", "3d5/2", 780.0, 25.80, "overlaps Co 2p3/2"),
    _p("Ba", "3d3/2", 795.3, 17.90),
    _p("La", "3d5/2", 835.0, 28.30),
    _p("La", "3d3/2", 851.8, 19.60),
    _p("Ce", "3d5/2", 882.0, 30.90),
    _p("Ce", "3d3/2", 900.5, 21.40),
    # ---- 5d metals and heavy p-block (4f doublets, 4:3)
    _p("Hf", "4f7/2", 14.5, 2.60, "17.0 HfO2"),
    _p("Hf", "4f5/2", 16.2, 2.00),
    _p("Hf", "4d5/2", 211.5, 5.00),
    _p("Ta", "4f7/2", 22.0, 2.80, "26.5 Ta2O5"),
    _p("Ta", "4f5/2", 23.9, 2.10),
    _p("Ta", "4d5/2", 226.5, 5.50),
    _p("W", "4f7/2", 31.5, 3.00, "31.4 W(0), 35.7 WO3"),
    _p("W", "4f5/2", 33.7, 2.30),
    _p("W", "4d5/2", 243.5, 6.00),
    _p("Re", "4f7/2", 40.5, 3.30),
    _p("Re", "4f5/2", 42.9, 2.50),
    _p("Os", "4f7/2", 51.0, 3.60),
    _p("Os", "4f5/2", 53.8, 2.70),
    _p("Ir", "4f7/2", 61.0, 3.90),
    _p("Ir", "4f5/2", 64.0, 2.90),
    _p("Ir", "4d5/2", 296.5, 7.60),
    _p("Pt", "4f7/2", 71.2, 4.20),
    _p("Pt", "4f5/2", 74.5, 3.30),
    _p("Pt", "4d5/2", 314.5, 8.30),
    _p("Au", "4f7/2", 84.0, 4.60, "spectrometer calibration line"),
    _p("Au", "4f5/2", 87.7, 3.50),
    _p("Au", "4d5/2", 335.0, 9.10, "overlaps Pd 3d5/2"),
    _p("Hg", "4f7/2", 100.5, 5.00),
    _p("Hg", "4f5/2", 104.5, 3.80),
    _p("Tl", "4f7/2", 118.5, 5.40),
    _p("Tl", "4f5/2", 122.9, 4.10),
    _p("Pb", "4f7/2", 138.0, 5.80, "136.9 Pb(0), 138.5 halide/oxide"),
    _p("Pb", "4f5/2", 142.9, 4.40),
    _p("Pb", "4d5/2", 413.0, 8.00),
    _p("Bi", "4f7/2", 159.0, 6.20, "157.0 Bi(0), 159 oxide; overlaps S 2p"),
    _p("Bi", "4f5/2", 164.3, 4.70),
    _p("Bi", "4d5/2", 441.0, 8.50),
]

ELEMENTS_COVERED: tuple[str, ...] = tuple(dict.fromkeys(line.element for line in SURVEY_LINES))

SOURCE = (
    "Typical positions (NIST SRD 20, Moulder et al. 1992) with Scofield-like relative "
    "intensities; +/-1 eV across chemical states, no transmission correction"
)


def lines_of(element: str) -> list[SurveyLine]:
    return [line for line in SURVEY_LINES if line.element == element]
