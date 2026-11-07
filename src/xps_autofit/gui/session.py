"""In-memory state of the desktop session: loaded spectra and their fit results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..automation.model_selection import Candidate, SelectionResult
from ..core.fitting import FitResult
from ..core.spectrum import Spectrum
from ..core.uncertainty import BootstrapResult
from ..readers import read_spectra
from ..recipes import Recipe


@dataclass
class LoadedSpectrum:
    path: Path
    index: int
    spectrum: Spectrum

    @property
    def key(self) -> str:
        return f"{self.path}#{self.index}"

    @property
    def display_name(self) -> str:
        return self.spectrum.name or f"{self.path.name} [{self.index + 1}]"


@dataclass
class RegionState:
    """What the user currently sees for one spectrum: the automatic selection and,
    when they edited components, the manual refit on top of it."""

    selection: SelectionResult | None = None
    manual: FitResult | None = None
    status: str = "idle"
    notes: list[str] = field(default_factory=list)
    bootstrap: BootstrapResult | None = None
    """Bootstrap of the displayed result (cleared when the result changes)."""

    @property
    def result(self) -> FitResult | None:
        if self.manual is not None:
            return self.manual
        if self.selection is not None and self.selection.best is not None:
            return self.selection.best.result
        return None

    def as_selection(self) -> SelectionResult | None:
        """A SelectionResult whose best model is what is displayed (for export)."""
        if self.selection is None:
            return None
        if self.manual is None:
            return self.selection
        sel = self.selection
        cand = Candidate(
            n_components=len(self.manual.majors()),
            result=self.manual,
            violations=[],
            warnings=[],
            criterion=sel.region.criterion,
            criterion_value=float(getattr(self.manual.stats, sel.region.criterion)),
        )
        return SelectionResult(
            region=sel.region,
            spectrum=sel.spectrum,
            background=sel.background,
            noise=sel.noise,
            detected=sel.detected,
            candidates=sel.candidates + [cand],
            best=cand,
            status="manual",
            seed=sel.seed,
            notes=sel.notes + ["manual refit after user edits"],
        )


class Session(QObject):
    spectraChanged = Signal()
    resultChanged = Signal(str)
    message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[str, LoadedSpectrum] = {}
        self.order: list[str] = []
        self.results: dict[str, RegionState] = {}
        self.recipe: Recipe | None = None

    def load_paths(self, paths: Sequence[str | Path], **reader_kwargs: Any) -> list[str]:
        """Read files; returns the keys added.  Unreadable files are reported, not fatal."""
        added: list[str] = []
        for p in map(Path, paths):
            try:
                spectra = read_spectra(p, **reader_kwargs)
            except Exception as exc:
                self.message.emit(f"cannot read {p.name}: {exc}")
                continue
            for i, s in enumerate(spectra):
                item = LoadedSpectrum(p, i, s)
                if item.key in self.items:
                    continue
                self.items[item.key] = item
                self.order.append(item.key)
                added.append(item.key)
            self.message.emit(f"loaded {p.name}: {len(spectra)} spectrum/spectra")
        if added:
            self.spectraChanged.emit()
        return added

    def remove(self, key: str) -> None:
        self.items.pop(key, None)
        self.results.pop(key, None)
        if key in self.order:
            self.order.remove(key)
        self.spectraChanged.emit()

    def state(self, key: str) -> RegionState:
        return self.results.setdefault(key, RegionState())

    def set_selection(self, key: str, selection: SelectionResult) -> None:
        st = self.state(key)
        st.selection = selection
        st.manual = None
        st.bootstrap = None
        st.status = selection.status
        st.notes = list(selection.notes)
        self.resultChanged.emit(key)

    def set_manual(self, key: str, result: FitResult, notes: list[str]) -> None:
        st = self.state(key)
        st.manual = result
        st.bootstrap = None
        st.status = "manual"
        st.notes = notes
        self.resultChanged.emit(key)

    def set_bootstrap(self, key: str, boot: BootstrapResult) -> None:
        st = self.state(key)
        st.bootstrap = boot
        self.resultChanged.emit(key)
