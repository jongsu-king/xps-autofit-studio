"""Minimal element table for the lines covered by the reference data."""

from __future__ import annotations

ELEMENTS: dict[str, tuple[int, str]] = {
    "C": (6, "carbon"),
    "N": (7, "nitrogen"),
    "O": (8, "oxygen"),
    "F": (9, "fluorine"),
    "Na": (11, "sodium"),
    "Al": (13, "aluminium"),
    "Si": (14, "silicon"),
    "P": (15, "phosphorus"),
    "S": (16, "sulfur"),
    "Cl": (17, "chlorine"),
    "K": (19, "potassium"),
    "Ca": (20, "calcium"),
    "Ti": (22, "titanium"),
    "Fe": (26, "iron"),
    "Co": (27, "cobalt"),
    "Ni": (28, "nickel"),
    "Cu": (29, "copper"),
    "Zn": (30, "zinc"),
    "Se": (34, "selenium"),
    "Br": (35, "bromine"),
    "Mo": (42, "molybdenum"),
    "Ag": (47, "silver"),
    "Cd": (48, "cadmium"),
    "In": (49, "indium"),
    "Sn": (50, "tin"),
    "I": (53, "iodine"),
    "Cs": (55, "caesium"),
    "W": (74, "tungsten"),
    "Au": (79, "gold"),
    "Pb": (82, "lead"),
    "Bi": (83, "bismuth"),
}


def atomic_number(symbol: str) -> int | None:
    entry = ELEMENTS.get(symbol)
    return entry[0] if entry else None
