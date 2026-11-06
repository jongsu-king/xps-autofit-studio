"""Relative sensitivity factors.

``SCOFIELD_AL_KALPHA`` lists Scofield photoionisation cross-sections at Al K-alpha
relative to C 1s = 1.00 (J. H. Scofield, *J. Electron Spectrosc. Relat. Phenom.* 8,
129 (1976)) for a small set of common lines.  They do **not** include the analyser
transmission function or the escape-depth dependence; for quantitative work use the
factors supplied with your instrument (e.g. the Avantage or CasaXPS libraries) and
state which library you used.  Lines not listed here must be supplied in the recipe.
"""

from __future__ import annotations

SCOFIELD_AL_KALPHA: dict[str, float] = {
    "C 1s": 1.000,
    "N 1s": 1.800,
    "O 1s": 2.930,
    "F 1s": 4.430,
    "Si 2p": 0.817,  # 2p total (2p3/2 + 2p1/2)
    "P 2p": 1.192,  # 2p total
    "S 2p": 1.677,  # 2p total
    "Cl 2p": 2.285,  # 2p total
    "Ti 2p3/2": 5.22,
    "Fe 2p3/2": 10.82,
    "Ni 2p3/2": 14.61,
    "Cu 2p3/2": 16.73,
    "Zn 2p3/2": 18.92,
    "Ag 3d5/2": 10.66,
    "Au 4f7/2": 9.58,
}

SOURCE = (
    "Scofield (1976) cross-sections at Al K-alpha, relative to C 1s = 1; no transmission correction"
)


def get_rsf(element: str | None, line: str | None) -> float | None:
    if not element or not line:
        return None
    return SCOFIELD_AL_KALPHA.get(f"{element} {line}")
