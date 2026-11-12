"""Instrument sensitivity-factor libraries.

Atomic percentages are only as good as the relative sensitivity factors (RSFs), and
the right ones belong to the instrument: Thermo Avantage, CasaXPS and Kratos all ship
their own libraries, which already contain the analyser transmission and escape
depth of that instrument.  A library is read from a small file the user exports or
types from the instrument software:

CSV (header required; ``line`` may be part of ``label``)::

    element,line,rsf,note
    C,1s,1.000,
    O,1s,2.881,Avantage ALTHERMO1
    Cu,2p3/2,16.73,

or YAML::

    name: Nexsa ALTHERMO1
    source: Thermo Avantage library, exported 2026-11-12
    factors:
      C 1s: 1.000
      O 1s: 2.881
      Cu 2p3/2: 16.73

When a library is in use its factors replace the recipe's (and the built-in Scofield
table's) wherever it has an entry for the region's element and line; the source of
every factor is written next to the atomic percentage.  Lines are matched exactly
(``Cu 2p3/2`` and ``Cu 2p`` are different factors: a component line and a doublet
total), ignoring case and spaces.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class RsfLibraryError(ValueError):
    """Raised for a library file that cannot be read."""


def _key(element: str, line: str) -> str:
    return f"{element.strip().lower()} {line.replace(' ', '').lower()}"


@dataclass
class RsfLibrary:
    name: str
    factors: dict[str, float]
    """``"Cu 2p3/2"``-style labels -> RSF, as written in the file."""
    source: str = ""
    path: str = ""
    notes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._index = {}
        for label, value in self.factors.items():
            element, _, line = label.strip().partition(" ")
            if not element or not line:
                raise RsfLibraryError(f"{label!r}: expected 'Element line', e.g. 'Cu 2p3/2'")
            if not value > 0:
                raise RsfLibraryError(f"{label!r}: the factor must be positive, got {value}")
            self._index[_key(element, line)] = float(value)

    def get(self, element: str | None, line: str | None) -> float | None:
        if not element or not line:
            return None
        return self._index.get(_key(element, line))

    def __len__(self) -> int:
        return len(self.factors)

    def describe(self) -> str:
        where = f" ({self.source})" if self.source else ""
        return f"RSF library {self.name}{where}, {len(self)} factors"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "factors": dict(self.factors),
        }


def _number(text: Any, where: str) -> float:
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError as exc:
        raise RsfLibraryError(f"{where}: {text!r} is not a number") from exc


def load_rsf_library(path: str | Path) -> RsfLibrary:
    """Read a CSV or YAML library (see the module docstring)."""
    p = Path(path)
    if not p.is_file():
        raise RsfLibraryError(f"{p}: no such file")
    if p.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not isinstance(data.get("factors"), dict):
            raise RsfLibraryError(f"{p.name}: expected a mapping with 'factors: {{label: rsf}}'")
        yaml_factors = {
            str(label): _number(value, f"{p.name}: {label}")
            for label, value in data["factors"].items()
        }
        return RsfLibrary(
            str(data.get("name") or p.stem), yaml_factors, str(data.get("source") or ""), str(p)
        )
    text = p.read_text(encoding="utf-8-sig")
    sample = text[:2048]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
    rsf_col = next((fields[k] for k in ("rsf", "factor", "sensitivity", "sf") if k in fields), None)
    if rsf_col is None:
        raise RsfLibraryError(f"{p.name}: needs an 'rsf' column (and element/line or label)")
    factors: dict[str, float] = {}
    notes: dict[str, str] = {}
    for n, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        if "element" in fields and "line" in fields:
            label = f"{row[fields['element']].strip()} {row[fields['line']].strip()}"
        elif "label" in fields:
            label = row[fields["label"]].strip()
        else:
            raise RsfLibraryError(f"{p.name}: needs 'element' and 'line' columns or a 'label'")
        factors[label] = _number(row[rsf_col], f"{p.name} line {n}")
        if "note" in fields and (row.get(fields["note"]) or "").strip():
            notes[label] = row[fields["note"]].strip()
    if not factors:
        raise RsfLibraryError(f"{p.name}: no factors")
    return RsfLibrary(p.stem, factors, "", str(p), notes)


def resolve_rsf(
    element: str | None,
    line: str | None,
    recipe_rsf: float | None,
    library: RsfLibrary | None = None,
    scofield: bool = False,
) -> tuple[float | None, str]:
    """The factor to use and where it comes from: the library (when it has the line),
    else the recipe, else (with ``scofield``) the built-in Scofield table."""
    if library is not None:
        value = library.get(element, line)
        if value is not None:
            return value, f"library {library.name}"
    if recipe_rsf is not None:
        return recipe_rsf, "recipe"
    if scofield:
        from .sensitivity_factors import get_rsf

        value = get_rsf(element, line)
        if value is not None:
            return value, "Scofield"
    return None, "missing"
