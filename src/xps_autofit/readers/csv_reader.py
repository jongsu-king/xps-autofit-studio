"""Delimited text reader (CSV, TSV, whitespace; instrument ASCII exports).

Handles header lines, several numeric blocks in one file (multi-region exports),
decimal commas, descending energy axes and kinetic-energy columns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from ..core.spectrum import AL_KALPHA_EV, Spectrum

_ENERGY_PATTERNS = ("binding", "b.e", "kinetic", "k.e", "energy", "ev")
_ENERGY_EXACT = {"be", "ke", "e", "x", "energy"}
_INTENSITY_PATTERNS = ("count", "intens", "cps", "c/s", "signal", "raw", "y")
_CPS_PATTERNS = ("cps", "c/s", "counts/s", "counts per second")


class TextReadError(ValueError):
    """Raised when no numeric table can be found in a text file."""


def _decode(path: Path, encoding: str | None) -> tuple[str, str]:
    raw = path.read_bytes()
    candidates: list[str] = [encoding] if encoding else ["utf-8-sig", "cp949", "latin-1"]
    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def _tokens(line: str, delimiter: str) -> list[str]:
    toks = line.split() if delimiter == "whitespace" else [t.strip() for t in line.split(delimiter)]
    if delimiter != "," and any("," in t and "." not in t for t in toks):
        toks = [t.replace(",", ".") for t in toks]
    return [t for t in toks if t != ""]


def _is_number(tok: str) -> bool:
    try:
        float(tok)
    except ValueError:
        return False
    return True


def _numeric_count(line: str, delimiter: str) -> int:
    toks = _tokens(line, delimiter)
    if len(toks) < 2 or not all(_is_number(t) for t in toks):
        return 0
    return len(toks)


def _sniff_delimiter(lines: list[str]) -> str:
    best, best_score = "whitespace", -1
    sample = [ln for ln in lines if ln.strip()][:400]
    for delim in ("\t", ",", ";", "whitespace"):
        rows = [_numeric_count(ln, delim) for ln in sample]
        score = sum(1 for r in rows if r >= 2)
        if score > best_score:
            best, best_score = delim, score
    if best_score <= 0:
        raise TextReadError("no line with at least two numeric columns was found")
    return best


def _blocks(lines: list[str], delimiter: str) -> list[tuple[list[str] | None, np.ndarray]]:
    blocks: list[tuple[list[str] | None, np.ndarray]] = []
    rows: list[list[float]] = []
    header: list[str] | None = None
    last_text: str | None = None
    width = 0

    def close() -> None:
        nonlocal rows, header
        if len(rows) >= 5:
            w = min(len(r) for r in rows)
            arr = np.array([r[:w] for r in rows], dtype=float)
            blocks.append((header, arr))
        rows = []
        header = None

    for ln in lines:
        n = _numeric_count(ln, delimiter)
        if n >= 2:
            if rows and n != width:
                close()
            if not rows:
                header = _tokens(last_text, delimiter) if last_text else None
                width = n
            rows.append([float(t) for t in _tokens(ln, delimiter)])
        else:
            if rows:
                close()
            if ln.strip():
                last_text = ln
    close()
    if not blocks:
        raise TextReadError("no numeric table with at least 5 rows was found")
    return blocks


def _match(
    header: list[str] | None, patterns: tuple[str, ...], exact: set[str], exclude: int | None
) -> int | None:
    if not header:
        return None
    for i, h in enumerate(header):
        if i == exclude:
            continue
        hl = h.lower()
        base = re.sub(r"\(.*?\)|\[.*?\]", "", hl).strip()
        if base in exact or any(p in hl for p in patterns):
            return i
    return None


def _resolve_col(spec: int | str | None, header: list[str] | None, ncol: int) -> int | None:
    if spec is None:
        return None
    if isinstance(spec, int):
        if not 0 <= spec < ncol:
            raise TextReadError(f"column index {spec} out of range (0..{ncol - 1})")
        return spec
    if header:
        for i, h in enumerate(header):
            if h.lower() == spec.lower():
                return i
    raise TextReadError(f"column {spec!r} not found in header {header}")


def read_text(
    path: str | Path,
    *,
    energy_col: int | str | None = None,
    intensity_col: int | str | None = None,
    delimiter: str | None = None,
    axis: str | None = None,
    photon_energy: float | None = None,
    intensity_unit: str | None = None,
    encoding: str | None = None,
    dwell_time_s: float | None = None,
    n_scans: int | None = None,
) -> list[Spectrum]:
    """Read one or more spectra from a delimited text file."""
    p = Path(path)
    text, enc = _decode(p, encoding)
    lines = text.splitlines()
    delim = delimiter or _sniff_delimiter(lines)
    blocks = _blocks(lines, delim)
    spectra: list[Spectrum] = []
    for k, (header, arr) in enumerate(blocks):
        ncol = arr.shape[1]
        if header is not None and len(header) != ncol:
            header = None
        e_idx = _resolve_col(energy_col, header, ncol)
        if e_idx is None:
            e_idx = _match(header, _ENERGY_PATTERNS, _ENERGY_EXACT, None)
        if e_idx is None:
            e_idx = 0
        i_idx = _resolve_col(intensity_col, header, ncol)
        if i_idx is None:
            i_idx = _match(header, _INTENSITY_PATTERNS, {"i", "y", "counts"}, e_idx)
        if i_idx is None:
            i_idx = 1 if e_idx != 1 else 0
        if i_idx == e_idx:
            raise TextReadError("energy and intensity columns are the same")

        e_name = header[e_idx] if header else f"col{e_idx}"
        i_name = header[i_idx] if header else f"col{i_idx}"
        ax = axis
        if ax is None:
            el = e_name.lower()
            ax = (
                "kinetic"
                if ("kinetic" in el or re.sub(r"\(.*?\)", "", el).strip() in {"ke", "k.e."})
                else "binding"
            )
        unit = intensity_unit
        if unit is None:
            il = i_name.lower()
            if any(pat in il for pat in _CPS_PATTERNS):
                unit = "cps"
            elif "count" in il:
                unit = "counts"
            else:
                col = arr[:, i_idx]
                unit = (
                    "counts"
                    if np.all(np.abs(col - np.round(col)) < 1e-9) and np.all(col >= 0)
                    else "arbitrary"
                )

        meta: dict[str, Any] = {
            "path": str(p),
            "encoding": enc,
            "delimiter": "whitespace" if delim == "whitespace" else repr(delim),
            "header": header,
            "energy_column": e_name,
            "intensity_column": i_name,
            "intensity_unit_inferred": intensity_unit is None,
            "block_index": k,
        }
        name = p.stem if len(blocks) == 1 else f"{p.stem} [{k + 1}]"
        spec = Spectrum(
            arr[:, e_idx],
            arr[:, i_idx],
            name=name,
            axis=ax,
            intensity_unit=unit,
            photon_energy=photon_energy,
            dwell_time_s=dwell_time_s,
            n_scans=n_scans,
            metadata=meta,
        )
        if spec.axis == "kinetic":
            hv = photon_energy if photon_energy is not None else AL_KALPHA_EV
            spec = spec.to_binding(hv)
            if photon_energy is None:
                spec.history.append(
                    {
                        "step": "assumed_photon_energy",
                        "photon_energy_eV": hv,
                        "note": "Al K-alpha assumed",
                    }
                )
        spectra.append(spec)
    return spectra
