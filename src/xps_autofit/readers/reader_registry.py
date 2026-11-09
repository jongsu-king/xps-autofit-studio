"""Extension-based reader dispatch with content sniffing as a fallback."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.spectrum import Spectrum
from .csv_reader import read_text
from .excel_reader import read_excel
from .vamas_reader import FORMAT_PREFIX, read_vamas

Reader = Callable[..., list[Spectrum]]

_ZIP_MAGIC = b"PK\x03\x04"  # an .xlsx is a zip archive

_READERS: dict[str, Reader] = {
    ".csv": read_text,
    ".tsv": read_text,
    ".txt": read_text,
    ".dat": read_text,
    ".xy": read_text,
    ".asc": read_text,
    ".vms": read_vamas,
    ".vamas": read_vamas,
    ".xlsx": read_excel,
    ".xlsm": read_excel,
}


def register_reader(extension: str, reader: Reader) -> None:
    """Register ``reader`` for files ending in ``extension`` (e.g. ``".spe"``)."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext
    _READERS[ext] = reader


def supported_extensions() -> list[str]:
    return sorted(_READERS)


def read_spectra(path: str | Path, **kwargs: Any) -> list[Spectrum]:
    """Read every spectrum in ``path``.

    Keyword arguments are passed to the reader (e.g. ``photon_energy``,
    ``energy_col``, ``intensity_col`` for text and Excel files, ``sheet`` for
    workbooks).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    reader = _READERS.get(p.suffix.lower())
    if reader is None:
        raw = p.read_bytes()[:200]
        if raw.startswith(_ZIP_MAGIC):
            reader = read_excel
        else:
            head = raw.decode("ascii", errors="ignore")
            reader = read_vamas if head.lstrip().startswith(FORMAT_PREFIX) else read_text
    return reader(p, **kwargs)
