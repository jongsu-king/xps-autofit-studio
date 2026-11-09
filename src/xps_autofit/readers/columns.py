"""Header heuristics shared by the text and Excel readers.

Instrument exports name their columns in many ways (``Binding Energy (eV)``, ``B.E.``,
``KE``, ``Counts / s``, ``Intensity [cps]``, ``CPS`` ...).  The helpers here decide
which column is the energy axis, which columns are measured intensities, which ones
a vendor added next to the data (background, envelope, residual, fitted peaks) and
what unit an intensity column carries.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np

ENERGY_PATTERNS = ("binding", "b.e", "kinetic", "k.e", "energy", "ev")
ENERGY_EXACT = frozenset({"be", "ke", "e", "x", "energy"})
INTENSITY_PATTERNS = ("count", "intens", "cps", "c/s", "signal", "raw")
INTENSITY_EXACT = frozenset({"i", "y", "counts", "intensity"})
CPS_PATTERNS = ("cps", "c/s", "counts/s", "counts per second")
# Columns a vendor export places next to the measured intensity.  They are never read
# as data unless asked for by name.
DERIVED_PATTERNS = (
    "background",
    "backgnd",
    "baseline",
    "envelope",
    "residual",
    "resid",
    "fit",
    "smooth",
    "deriv",
    "sigma",
    "error",
    "sum",
)


def base_name(header: str) -> str:
    """Lower-case header without bracketed units: ``"Counts / s (Resid.)" -> "counts / s"``."""
    return re.sub(r"\(.*?\)|\[.*?\]", "", header.lower()).strip()


def header_matches(header: str, patterns: Sequence[str], exact: frozenset[str] | set[str]) -> bool:
    hl = header.lower()
    return base_name(header) in exact or any(p in hl for p in patterns)


def is_energy_header(header: str) -> bool:
    """Energy-axis header, unless its unbracketed part names an intensity.

    ``"Binding Energy (eV)"`` and ``"KE"`` are energies; ``"Counts (Energy loss)"``
    is a series whose qualifier happens to contain the word.
    """
    if not header_matches(header, ENERGY_PATTERNS, ENERGY_EXACT):
        return False
    base = base_name(header)
    return not (base in INTENSITY_EXACT or any(p in base for p in INTENSITY_PATTERNS))


def is_intensity_header(header: str) -> bool:
    return header_matches(header, INTENSITY_PATTERNS, INTENSITY_EXACT)


def is_derived_header(header: str) -> bool:
    hl = header.lower()
    return any(p in hl for p in DERIVED_PATTERNS)


def match_column(
    header: Sequence[str] | None,
    patterns: Sequence[str],
    exact: frozenset[str] | set[str],
    exclude: int | None,
) -> int | None:
    """Index of the first header cell matching ``patterns``/``exact``, skipping ``exclude``."""
    if not header:
        return None
    for i, h in enumerate(header):
        if i == exclude:
            continue
        if header_matches(h, patterns, exact):
            return i
    return None


def infer_axis(energy_name: str) -> str:
    """``"kinetic"`` for KE columns, ``"binding"`` otherwise."""
    el = energy_name.lower()
    if "kinetic" in el or re.sub(r"\(.*?\)", "", el).strip() in {"ke", "k.e."}:
        return "kinetic"
    return "binding"


def infer_unit(intensity_name: str, values: np.ndarray) -> str:
    """``cps`` / ``counts`` from the header, else ``counts`` for non-negative integers."""
    il = intensity_name.lower()
    compact = il.replace(" ", "")  # "Counts / s" -> "counts/s"
    if any(pat in il or pat in compact for pat in CPS_PATTERNS):
        return "cps"
    if "count" in il:
        return "counts"
    col = np.asarray(values, dtype=float)
    col = col[np.isfinite(col)]
    if col.size and np.all(np.abs(col - np.round(col)) < 1e-9) and np.all(col >= 0):
        return "counts"
    return "arbitrary"
