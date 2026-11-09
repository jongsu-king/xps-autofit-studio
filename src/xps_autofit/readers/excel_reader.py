"""Excel workbook reader and writer (``.xlsx`` / ``.xlsm``).

Instrument software (Avantage, ESCApe, CasaXPS, MultiPak ...) and people both put
spectra into Excel, in a handful of layouts.  Every worksheet is scanned for numeric
tables: a table is a run of rows holding numbers in at least two columns, and the
text row just above it is its header.  Inside a table the energy columns are the ones
whose header says so (Binding / Kinetic Energy, BE, KE, eV) or, without a usable
header, the monotonic uniformly spaced columns; every other numeric column is an
intensity series belonging to the energy column on its left.  These layouts read:

    BE | Counts                                       one spectrum per sheet
    BE | sample A | sample B | sample C               one spectrum per column (shared axis)
    BE | Counts | BE | Counts | ...                   several regions side by side
    BE | Counts / s | Background | Envelope | C-C     vendor export: measured column only

Rows above a table such as ``Photon energy | 1486.6``, ``Dwell time (s) | 0.1`` or
``Number of scans | 10`` are used.  Formula cells contribute their cached value; a
workbook saved by a library that stores none reads as empty.  Sheet titles or series
headers like ``C1s Scan`` or ``S 2p`` set ``species`` / ``transition`` metadata so
recipes match them the way they match VAMAS blocks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import Workbook, load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from ..core.spectrum import AL_KALPHA_EV, Spectrum
from ..database.elements import ELEMENTS
from .columns import (
    infer_axis,
    infer_unit,
    is_derived_header,
    is_energy_header,
    is_intensity_header,
)

MIN_ROWS = 5

_PHOTON_KEYS = (
    "photon energy",
    "excitation energy",
    "source energy",
    "x-ray energy",
    "anode energy",
)
_DWELL_KEYS = ("dwell",)
_SCAN_KEYS = ("number of scans", "no. of scans", "n scans", "scans", "sweeps")
# "C1s Scan", "Region S 2p", "P3HT Cu2p3/2": an element symbol and a transition
_TITLE_RE = re.compile(r"(?<![A-Za-z])([A-Z][a-z]?)\s*([1-7][spdf](?:\s*\d/\d)?)(?![A-Za-z])")
_LETTERS_RE = re.compile(r"^[A-Za-z]{1,3}$")
_FORBIDDEN_TITLE = re.compile(r"[\[\]:*?/\\]")


class ExcelReadError(ValueError):
    """Raised when a workbook holds no numeric table that can be read as a spectrum."""


# ---------------------------------------------------------------------------- cells
def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _numeric_cells(row: Sequence[Any]) -> int:
    return sum(1 for v in row if _number(v) is not None)


# --------------------------------------------------------------------------- tables
@dataclass
class _Table:
    first_row: int  # 0-based index of the first data row in the sheet
    values: np.ndarray  # data rows x sheet columns, NaN where not numeric
    header: list[str | None] | None
    header_row: int | None
    title: str | None = None  # a lone text cell above the header ("Region S 2p", "C1s Scan")
    fields: dict[str, float] = field(default_factory=dict)  # photon_energy, dwell_time_s, n_scans


_KEY_VALUE_RE = re.compile(r"[:=]\s*[-+]?\d")


def _lone_title(row: Sequence[Any]) -> str | None:
    """The single text cell of ``row``, unless it is a ``key: number`` pair or a number."""
    cells = [t for t in (_text(v) for v in row) if t]
    if len(cells) != 1 or _number(cells[0]) is not None or _KEY_VALUE_RE.search(cells[0]):
        return None
    return cells[0]


def _metadata_fields(rows: Sequence[Sequence[Any]]) -> dict[str, float]:
    """``Photon energy | 1486.6``-style rows (also ``Dwell time: 0.1`` in one cell)."""
    found: dict[str, float] = {}
    for row in rows:
        cells = [v for v in row if v is not None and str(v).strip() != ""]
        for k, v in enumerate(cells):
            if not isinstance(v, str):
                continue
            key = v.lower()
            number: float | None = None
            m = re.search(r"[:=]\s*([-+]?\d+(?:[.,]\d+)?)", v)
            if m:
                number = _number(m.group(1))
                key = v[: m.start()].lower()
            elif k + 1 < len(cells):
                number = _number(cells[k + 1])
            if number is None:
                continue
            if any(p in key for p in _PHOTON_KEYS) and 100.0 <= number <= 20000.0:
                found.setdefault("photon_energy", number)
            elif any(p in key for p in _DWELL_KEYS) and 0.0 < number <= 3600.0:
                found.setdefault("dwell_time_s", number / 1000.0 if "ms" in key else number)
            elif any(p in key for p in _SCAN_KEYS) and number >= 1 and number == int(number):
                found.setdefault("n_scans", number)
    return found


def _tables(grid: list[list[Any]]) -> list[_Table]:
    tables: list[_Table] = []
    n = len(grid)
    i = 0
    text_rows: list[int] = []  # non-numeric rows since the previous table
    pending_meta: list[list[Any]] = []
    while i < n:
        if _numeric_cells(grid[i]) >= 2:
            j = i
            while j < n and _numeric_cells(grid[j]) >= 2:
                j += 1
            if j - i >= MIN_ROWS:
                width = max(len(r) for r in grid[i:j])
                values = np.full((j - i, width), np.nan)
                for r, row in enumerate(grid[i:j]):
                    for c, v in enumerate(row):
                        x = _number(v)
                        if x is not None:
                            values[r, c] = x
                header: list[str | None] | None = None
                header_row = text_rows[-1] if text_rows else None
                title = None
                if header_row is not None:
                    title = _lone_title(grid[header_row])
                    if title is not None:  # a lone title row, not a header
                        header_row = None
                    else:
                        header = [_text(v) for v in grid[header_row]]
                        for r in reversed(text_rows[:-1]):  # nearest lone text above it
                            title = _lone_title(grid[r])
                            if title is not None:
                                break
                tables.append(
                    _Table(i, values, header, header_row, title, _metadata_fields(pending_meta))
                )
                pending_meta = []
            else:
                pending_meta.extend(grid[i:j])
            text_rows = []
            i = j
        else:
            if any(_text(v) for v in grid[i]):
                text_rows.append(i)
                pending_meta.append(grid[i])
            i += 1
    return tables


def _monotonic_uniform(col: np.ndarray) -> bool:
    x = col[np.isfinite(col)]
    if x.size < MIN_ROWS:
        return False
    d = np.diff(x)
    if np.all(d > 0) or np.all(d < 0):
        a = np.abs(d)
        return bool(np.std(a) <= 0.5 * np.median(a))
    return False


def _resolve(
    spec: int | str | None, headers: dict[int, str | None], candidates: Sequence[int]
) -> int | None:
    """Column from a 0-based index, an Excel letter or a header text."""
    if spec is None:
        return None
    if isinstance(spec, int):
        if spec not in candidates:
            raise ExcelReadError(
                f"column {spec} holds no numeric data (numeric columns: "
                f"{', '.join(get_column_letter(c + 1) for c in candidates)})"
            )
        return spec
    for c in candidates:
        h = headers.get(c)
        if h is not None and h.lower() == spec.lower():
            return c
    if _LETTERS_RE.match(spec):
        c = column_index_from_string(spec.upper()) - 1
        if c in candidates:
            return c
    raise ExcelReadError(f"column {spec!r} not found among {[headers.get(c) for c in candidates]}")


def _species_transition(label: str) -> tuple[str, str] | None:
    for m in _TITLE_RE.finditer(label):
        if m.group(1) in ELEMENTS:
            return m.group(1), m.group(2).replace(" ", "")
    return None


@dataclass
class _Series:
    sheet: str
    energy_col: int
    intensity_col: int
    energy: np.ndarray
    intensity: np.ndarray
    e_name: str
    i_name: str
    table: _Table
    block_index: int


def _series_from_table(
    table: _Table,
    sheet: str,
    block_index: int,
    energy_col: int | str | None,
    intensity_col: int | str | None,
    errors: list[str],
) -> list[_Series]:
    values = table.values
    count = np.isfinite(values).sum(axis=0)
    numeric = [c for c in range(values.shape[1]) if count[c] >= MIN_ROWS]
    if len(numeric) < 2:
        return []
    headers: dict[int, str | None] = {
        c: (table.header[c] if table.header and c < len(table.header) else None) for c in numeric
    }

    try:
        forced_e = _resolve(energy_col, headers, numeric)
    except ExcelReadError as exc:
        errors.append(f"sheet {sheet!r}, row {table.first_row + 1}: {exc}")
        return []
    if forced_e is not None:
        e_cols = [forced_e]
    else:
        e_cols = [c for c in numeric if headers[c] and is_energy_header(headers[c] or "")]
        if not e_cols:
            e_cols = [c for c in numeric if _monotonic_uniform(values[:, c])]
            if len(e_cols) == len(numeric):
                e_cols = e_cols[:1]
        if not e_cols:
            e_cols = [numeric[0]]

    groups: dict[int, list[int]] = {e: [] for e in e_cols}
    for c in numeric:
        if c in groups:
            continue
        owner = max([e for e in e_cols if e < c], default=e_cols[0])
        groups[owner].append(c)

    out: list[_Series] = []
    for e, cands in groups.items():
        if not cands:
            continue
        try:
            forced_i = _resolve(intensity_col, headers, cands if len(e_cols) > 1 else numeric)
            if forced_i is not None and forced_i == e:
                raise ExcelReadError("energy and intensity columns are the same")
        except ExcelReadError as exc:
            errors.append(f"sheet {sheet!r}, row {table.first_row + 1}: {exc}")
            continue
        if forced_i is not None:
            chosen = [forced_i]
        else:
            # Drop vendor columns (background, envelope, residual ...).  When the column
            # next to the energy is the measured intensity ("Counts / s") and nothing
            # else claims to be one, the remaining columns are fitted peaks: skip them.
            # Otherwise every column is a series (sample A, sample B, cycle 3 ...).
            kept = [c for c in cands if not (headers[c] and is_derived_header(headers[c] or ""))]
            named = [c for c in kept if headers[c] and is_intensity_header(headers[c] or "")]
            chosen = named if kept and named == kept[:1] else kept
        for c in chosen:
            x, y = values[:, e], values[:, c]
            mask = np.isfinite(x) & np.isfinite(y)
            k = int(mask.size)
            while k > 0 and not mask[k - 1]:  # ragged tail below a shorter column
                k -= 1
            if mask[:k].sum() < MIN_ROWS:
                continue
            e_name = headers[e] or f"column {get_column_letter(e + 1)}"
            i_name = headers[c] or (
                f"columns {get_column_letter(e + 1)}-{get_column_letter(c + 1)}"
            )
            out.append(_Series(sheet, e, c, x[:k], y[:k], e_name, i_name, table, block_index))
    return out


# --------------------------------------------------------------------------- reader
def _grids(path: Path, sheet: int | str | None) -> list[tuple[str, list[list[Any]]]]:
    # A file object (not the path) so that a workbook without the .xlsx extension,
    # reached through content sniffing, is accepted as well.
    with path.open("rb") as fh:
        try:
            wb = load_workbook(fh, read_only=True, data_only=True)
        except Exception as exc:  # zip errors, wrong format, encrypted workbook
            raise ExcelReadError(f"cannot open workbook: {exc}") from exc
        try:
            return _sheet_grids(wb, sheet)
        finally:
            wb.close()


def _sheet_grids(wb: Any, sheet: int | str | None) -> list[tuple[str, list[list[Any]]]]:
    sheets = list(wb.worksheets)
    if sheet is not None:
        if isinstance(sheet, int):
            if not 0 <= sheet < len(sheets):
                raise ExcelReadError(f"sheet index {sheet} out of range (0..{len(sheets) - 1})")
            sheets = [sheets[sheet]]
        else:
            wanted = [ws for ws in sheets if ws.title.lower() == str(sheet).lower()]
            if not wanted:
                raise ExcelReadError(
                    f"sheet {sheet!r} not found; sheets: {[ws.title for ws in sheets]}"
                )
            sheets = wanted
    grids: list[tuple[str, list[list[Any]]]] = []
    for ws in sheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        width = max((len(r) for r in rows), default=0)
        grids.append((ws.title, [r + [None] * (width - len(r)) for r in rows]))
    return grids


def read_excel(
    path: str | Path,
    *,
    sheet: int | str | None = None,
    energy_col: int | str | None = None,
    intensity_col: int | str | None = None,
    axis: str | None = None,
    photon_energy: float | None = None,
    intensity_unit: str | None = None,
    dwell_time_s: float | None = None,
    n_scans: int | None = None,
    **_: Any,
) -> list[Spectrum]:
    """Read every spectrum in an Excel workbook.

    ``sheet`` restricts the read to one worksheet (0-based index or title).
    ``energy_col`` / ``intensity_col`` override the column choice: a 0-based column
    index, an Excel column letter or a header text.  Keyword arguments meant for
    other readers are ignored.
    """
    p = Path(path)
    series: list[_Series] = []
    errors: list[str] = []
    for title, grid in _grids(p, sheet):
        for k, table in enumerate(_tables(grid)):
            series.extend(_series_from_table(table, title, k, energy_col, intensity_col, errors))
    if not series:
        if errors:
            raise ExcelReadError(f"{p.name}: {errors[0]}")
        raise ExcelReadError(
            f"{p.name}: no numeric table with at least {MIN_ROWS} rows and two columns"
        )

    # Names: sheet (several sheets) / table title (several tables in a sheet) / series
    # header (several series in a table); a lone spectrum is named after the file.
    tables_per_sheet: dict[str, set[int]] = {}
    series_per_table: dict[tuple[str, int], int] = {}
    for s in series:
        tables_per_sheet.setdefault(s.sheet, set()).add(s.block_index)
        key = (s.sheet, s.block_index)
        series_per_table[key] = series_per_table.get(key, 0) + 1
    multi_sheet = len(tables_per_sheet) > 1

    spectra: list[Spectrum] = []
    for s in series:
        parts: list[str] = []
        if multi_sheet:
            parts.append(s.sheet)
        if len(tables_per_sheet[s.sheet]) > 1:
            parts.append(s.table.title or f"[{s.block_index + 1}]")
        if series_per_table[(s.sheet, s.block_index)] > 1:
            parts.append(s.i_name)
        name = " / ".join(parts) if parts else p.stem
        label_sources = [s.table.title, s.sheet, s.i_name]

        fields = s.table.fields
        hv = photon_energy if photon_energy is not None else fields.get("photon_energy")
        dwell = dwell_time_s if dwell_time_s is not None else fields.get("dwell_time_s")
        scans = n_scans if n_scans is not None else fields.get("n_scans")
        ax = axis if axis is not None else infer_axis(s.e_name)
        unit = intensity_unit if intensity_unit is not None else infer_unit(s.i_name, s.intensity)
        meta: dict[str, Any] = {
            "path": str(p),
            "format": "Excel",
            "sheet": s.sheet,
            "header": s.table.header,
            "header_row": None if s.table.header_row is None else s.table.header_row + 1,
            "first_row": s.table.first_row + 1,
            "energy_column": s.e_name,
            "intensity_column": s.i_name,
            "excel_columns": f"{get_column_letter(s.energy_col + 1)}/"
            f"{get_column_letter(s.intensity_col + 1)}",
            "intensity_unit_inferred": intensity_unit is None,
            "block_index": s.block_index,
        }
        if s.table.title:
            meta["table_title"] = s.table.title
        if fields:
            meta["sheet_fields"] = dict(fields)
        for label in label_sources:
            st = _species_transition(label) if label else None
            if st is not None:
                meta["species"], meta["transition"] = st
                break
        spec = Spectrum(
            s.energy,
            s.intensity,
            name=name,
            axis=ax,
            intensity_unit=unit,
            photon_energy=hv,
            dwell_time_s=dwell,
            n_scans=None if scans is None else int(scans),
            metadata=meta,
        )
        if spec.axis == "kinetic":
            hv_used = hv if hv is not None else AL_KALPHA_EV
            spec = spec.to_binding(hv_used)
            if hv is None:
                spec.history.append(
                    {
                        "step": "assumed_photon_energy",
                        "photon_energy_eV": hv_used,
                        "note": "Al K-alpha assumed",
                    }
                )
        spectra.append(spec)
    return spectra


# --------------------------------------------------------------------------- writer
def _sheet_title(name: str, used: set[str]) -> str:
    title = _FORBIDDEN_TITLE.sub("-", name).strip() or "spectrum"
    title = title[:31]
    base, k = title, 2
    while title.lower() in used:
        suffix = f" ({k})"
        title = base[: 31 - len(suffix)] + suffix
        k += 1
    used.add(title.lower())
    return title


def write_excel(
    path: str | Path,
    spectra: Sequence[Spectrum],
    *,
    layout: str = "sheets",
    header: tuple[str, str] = ("Binding Energy (eV)", "Counts"),
    descending: bool = False,
    metadata: bool = False,
) -> Path:
    """Write spectra to a workbook in one of the layouts the reader understands.

    ``layout``: ``"sheets"`` (one worksheet per spectrum, energy and intensity
    columns), ``"columns"`` (one worksheet, a shared energy column and one intensity
    column per spectrum; the spectra must share their energy grid) or ``"pairs"``
    (one worksheet, an energy / intensity pair per spectrum side by side).  With
    ``metadata`` the photon energy, dwell time and number of scans are written above
    the table when a spectrum has them.
    """
    if layout not in ("sheets", "columns", "pairs"):
        raise ValueError(f"layout must be sheets, columns or pairs, got {layout!r}")
    if not spectra:
        raise ValueError("no spectra to write")
    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Spectra"

    def columns(s: Spectrum) -> tuple[np.ndarray, np.ndarray]:
        e, i = s.energy, s.intensity
        return (e[::-1], i[::-1]) if descending else (e, i)

    def series_header(s: Spectrum, k: int) -> str:
        """The spectrum name, unless the reader would take it for an energy column."""
        name = s.name or f"spectrum {k + 1}"
        return name if not is_energy_header(name) else f"{header[1]} ({name})"

    def meta_rows(s: Spectrum) -> list[list[Any]]:
        rows: list[list[Any]] = []
        if s.photon_energy is not None:
            rows.append(["Photon energy (eV)", float(s.photon_energy)])
        if s.dwell_time_s is not None:
            rows.append(["Dwell time (s)", float(s.dwell_time_s)])
        if s.n_scans is not None:
            rows.append(["Number of scans", int(s.n_scans)])
        return rows + [[]] if rows else rows

    if layout == "sheets":
        used: set[str] = set()
        for k, s in enumerate(spectra):
            sheet = ws if k == 0 else wb.create_sheet()
            sheet.title = _sheet_title(s.name or f"spectrum {k + 1}", used)
            if metadata:
                for row in meta_rows(s):
                    sheet.append(row)
            sheet.append(list(header))
            for e, i in zip(*columns(s)):
                sheet.append([float(e), float(i)])
    elif layout == "columns":
        first = spectra[0]
        for s in spectra[1:]:
            if s.n != first.n or not np.allclose(s.energy, first.energy):
                raise ValueError("the 'columns' layout needs spectra on one energy grid")
        if metadata:
            for row in meta_rows(first):
                ws.append(row)
        ws.append([header[0]] + [series_header(s, k) for k, s in enumerate(spectra)])
        data = [columns(s)[1] for s in spectra]
        e = columns(first)[0]
        for r in range(first.n):
            ws.append([float(e[r])] + [float(d[r]) for d in data])
    else:
        if metadata:
            for row in meta_rows(spectra[0]):
                ws.append(row)
        ws.append([h for k, s in enumerate(spectra) for h in (header[0], series_header(s, k))])
        cols = [columns(s) for s in spectra]
        for r in range(max(s.n for s in spectra)):
            cells: list[Any] = []
            for e, i in cols:
                cells.extend([float(e[r]), float(i[r])] if r < e.size else [None, None])
            ws.append(cells)
    wb.save(path)
    return path
