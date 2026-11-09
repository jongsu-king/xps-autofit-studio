"""Files that OriginLab Origin opens as a labelled workbook, and a way to open them.

Origin's CSV / ASCII import reads text lines above the numbers as column labels:
the first as *Long Name*, the second as *Units*, the third as *Comments*.  The files
written here follow that layout, with the binding energy as the first (X) column,
so dropping one onto Origin, or opening it with *File > Open*, gives a workbook
whose columns already carry names and units and whose Y columns plot against the
energy at once:

    Binding Energy, Raw,    Background, Envelope, C-C,    ..., Residual
    eV,             counts, counts,     counts,   counts, ..., counts
    X,              data,   shirley,    model,    284.80 eV / 1.10 eV / 62.3 %, ...
    280.0,          1234,   ...

Only ASCII is written in the label rows so every Origin version and code page reads
them.  :func:`open_in_origin` starts Origin with a file on Windows when it can find
the program (``XPS_AUTOFIT_ORIGIN`` names it explicitly) and otherwise hands the
file to the system's default application.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..core.fitting import FitResult
from ..core.spectrum import Spectrum

ORIGIN_SUFFIX = "_origin.csv"
ORIGIN_COMPONENTS_SUFFIX = "_origin_components.csv"
ORIGIN_ENV = "XPS_AUTOFIT_ORIGIN"
"""Environment variable with the full path of Origin's executable (overrides the search)."""


@dataclass
class OriginColumn:
    """One worksheet column: the three label rows and the values."""

    long_name: str
    units: str
    comment: str
    values: Sequence[float] | np.ndarray | Sequence[str]


def _ascii(text: str) -> str:
    """Label text Origin reads in any code page: ASCII, no commas or quotes."""
    replacements = {"±": "+/-", "σ": "sigma", "η": "eta", "°": " deg", "—": "-", "–": "-"}
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = text.encode("ascii", errors="replace").decode("ascii").replace("?", "_")
    return text.replace(",", ";").replace('"', "'").strip()


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _ascii(value)
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _ascii(str(value))
    return "" if not np.isfinite(v) else f"{v:.10g}"


def write_origin_csv(path: str | Path, columns: Sequence[OriginColumn]) -> Path:
    """Write columns with Origin's Long Name / Units / Comments rows.

    Columns may differ in length (pairs of spectra on different grids); shorter
    ones are padded with empty cells, which Origin imports as missing values.
    """
    if not columns:
        raise ValueError("no columns to write")
    path = Path(path)
    rows = [
        ",".join(_ascii(c.long_name) for c in columns),
        ",".join(_ascii(c.units) for c in columns),
        ",".join(_ascii(c.comment) for c in columns),
    ]
    n = max(len(c.values) for c in columns)
    for i in range(n):
        rows.append(",".join(_cell(c.values[i]) if i < len(c.values) else "" for c in columns))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="")
    return path


def _intensity_units(result: FitResult) -> str:
    return "counts" if result.stats.weighted else "a.u."


def fit_columns(result: FitResult) -> list[OriginColumn]:
    """Binding energy, raw data, background, envelope, every component (drawn on the
    background, as in the figures) and the residual."""
    units = _intensity_units(result)
    bg = result.background_total
    bg_kind = result.background.spec.type
    if result.background.info.get("mode") == "active":
        bg_kind += " active"
    if result.settings.refine_linear_background:
        bg_kind += " + linear"
    cols = [
        OriginColumn("Binding Energy", "eV", "X", result.x),
        OriginColumn("Raw", units, "measured data", result.y),
        OriginColumn("Background", units, bg_kind, bg),
        OriginColumn(
            "Envelope", units, f"model; reduced chi-sq {result.stats.redchi:.4g}", result.model
        ),
    ]
    for comp in result.components:
        if comp.values is None:
            continue
        if comp.is_minor:
            note = f"spin-orbit partner of {comp.parent}; {comp.center:.2f} eV"
        else:
            frac = f"; {comp.fraction:.1f} %" if comp.fraction is not None else ""
            note = f"{comp.center:.2f} eV; FWHM {comp.fwhm:.2f} eV; area {comp.area:.5g}{frac}"
        cols.append(OriginColumn(comp.label, units, note + "; on background", comp.values + bg))
    cols.append(OriginColumn("Residual", units, "data - model", result.residual))
    return cols


def component_columns(result: FitResult) -> list[OriginColumn]:
    """The components table: one row per component."""
    comps = result.components

    def num(attr: str) -> list[float]:
        out: list[float] = []
        for c in comps:
            v = getattr(c, attr)
            out.append(float(v) if v is not None else float("nan"))
        return out

    return [
        OriginColumn("Component", "", "label", [c.label for c in comps]),
        OriginColumn("Centre", "eV", "binding energy", num("center")),
        OriginColumn("Centre error", "eV", "1 sigma", num("center_err")),
        OriginColumn("FWHM", "eV", "total width", num("fwhm")),
        OriginColumn("Area", _intensity_units(result) + " eV", "area", num("area")),
        OriginColumn("Area error", _intensity_units(result) + " eV", "1 sigma", num("area_err")),
        OriginColumn("Fraction", "%", "of the region", num("fraction")),
        OriginColumn(
            "Component fraction", "%", "doublet partners summed", num("component_fraction")
        ),
        OriginColumn("FWHM G", "eV", "Gaussian part", num("fwhm_g")),
        OriginColumn("FWHM L", "eV", "Lorentzian part", num("fwhm_l")),
    ]


def spectrum_columns(spectrum: Spectrum) -> list[OriginColumn]:
    """A spectrum without a fit: energy and intensity."""
    return [
        OriginColumn("Binding Energy", "eV", "X", spectrum.energy),
        OriginColumn(
            spectrum.name or "Intensity",
            spectrum.intensity_unit,
            "measured data",
            spectrum.intensity,
        ),
    ]


def overlay_columns(entries: Sequence[tuple[str, Spectrum]]) -> list[OriginColumn]:
    """Several spectra as X/Y column pairs (the comparison view).

    The pairs keep each spectrum's own energy grid; in Origin set the designations
    to XY XY ... (or plot each pair) to overlay them.
    """
    cols: list[OriginColumn] = []
    for name, spec in entries:
        cols.append(OriginColumn("Binding Energy", "eV", f"X of {name}", spec.energy))
        cols.append(OriginColumn(name, spec.intensity_unit, "Y", spec.intensity))
    return cols


def write_fit_for_origin(base: str | Path, result: FitResult) -> dict[str, Path]:
    """``<base>_origin.csv`` (curves) and ``<base>_origin_components.csv`` (table)."""
    base = Path(base)
    curves = write_origin_csv(base.parent / f"{base.name}{ORIGIN_SUFFIX}", fit_columns(result))
    table = write_origin_csv(
        base.parent / f"{base.name}{ORIGIN_COMPONENTS_SUFFIX}", component_columns(result)
    )
    return {"curves": curves, "components": table}


# ------------------------------------------------------------------ opening in Origin
def find_origin_executable(
    env: dict[str, str] | None = None, platform: str | None = None
) -> Path | None:
    """Path of Origin's program, or ``None``.

    ``XPS_AUTOFIT_ORIGIN`` wins when it names an existing file.  Otherwise, on
    Windows only (Origin runs nowhere else), the newest ``Origin*64.exe`` /
    ``Origin*.exe`` under ``Program Files\\OriginLab`` is used.
    """
    env = dict(os.environ) if env is None else env
    platform = sys.platform if platform is None else platform
    explicit = env.get(ORIGIN_ENV)
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    if not platform.startswith("win"):
        return None
    roots = [env.get(k) for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    found: list[Path] = []
    for root in dict.fromkeys(r for r in roots if r):
        lab = Path(root) / "OriginLab"
        if not lab.is_dir():
            continue
        for pattern in ("*/Origin*64.exe", "*/Origin*.exe"):
            found.extend(p for p in lab.glob(pattern) if p.is_file())
        if found:
            break
    if not found:
        return None
    # newest installation folder first ("Origin 2025b" > "Origin 2024"), 64-bit first
    return sorted(found, key=lambda p: (p.parent.name, "64" in p.name, p.name))[-1]


def _open_with_default(path: Path) -> None:  # pragma: no cover - depends on the desktop
    # ``sys.platform == "win32"`` (not ``startswith``) lets mypy check os.startfile on
    # Windows and skip it elsewhere, so no platform-dependent "type: ignore" is needed.
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


def open_in_origin(
    path: str | Path,
    executable: Path | None = None,
    launcher: Callable[[list[str]], object] | None = None,
    fallback: Callable[[Path], None] | None = None,
) -> str:
    """Open ``path`` in Origin when it is installed, else with the default program.

    Returns ``"origin"`` or ``"default"``.  ``launcher`` and ``fallback`` exist for
    tests (``subprocess.Popen`` and the platform's "open" by default).
    """
    p = Path(path)
    exe = executable if executable is not None else find_origin_executable()
    if exe is not None:
        (launcher or subprocess.Popen)([str(exe), str(p)])
        return "origin"
    (fallback or _open_with_default)(p)
    return "default"
