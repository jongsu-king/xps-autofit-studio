"""In-memory state of the desktop session: loaded spectra and their fit results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..automation.model_selection import Candidate, SelectionResult
from ..core.fitting import FitResult, rename_component
from ..core.quantification import QuantCorrection, QuantResult, atomic_percent
from ..core.quantification import atomic_percent_samples as _propagate_samples
from ..core.spectrum import AL_KALPHA_EV, Spectrum
from ..core.uncertainty import BootstrapResult
from ..database.sensitivity_factors import SOURCE as SCOFIELD_SOURCE
from ..database.sensitivity_factors import get_rsf
from ..readers import read_spectra
from ..recipes import Recipe

MAX_HISTORY = 50


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
class Snapshot:
    """What undo/redo restores: the displayed result and its annotations."""

    manual: FitResult | None
    best_result: FitResult | None
    status: str
    notes: list[str]
    bootstrap: BootstrapResult | None


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
    history: list[Snapshot] = field(default_factory=list)
    """Earlier states of this spectrum's result (undo), oldest first."""
    future: list[Snapshot] = field(default_factory=list)
    """States undone (redo), most recently undone last."""

    def snapshot(self) -> Snapshot:
        best = self.selection.best.result if self.selection and self.selection.best else None
        return Snapshot(self.manual, best, self.status, list(self.notes), self.bootstrap)

    def restore(self, snap: Snapshot) -> None:
        self.manual = snap.manual
        if self.selection is not None and self.selection.best is not None and snap.best_result:
            self.selection.best.result = snap.best_result
        self.status = snap.status
        self.notes = list(snap.notes)
        self.bootstrap = snap.bootstrap

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
        st.history.clear()  # a new automatic fit is a new baseline
        st.future.clear()
        self.resultChanged.emit(key)

    def _remember(self, st: RegionState) -> None:
        st.history.append(st.snapshot())
        del st.history[:-MAX_HISTORY]
        st.future.clear()

    def set_manual(self, key: str, result: FitResult, notes: list[str]) -> None:
        st = self.state(key)
        self._remember(st)
        st.manual = result
        st.bootstrap = None
        st.status = "manual"
        st.notes = notes
        self.resultChanged.emit(key)

    def can_undo(self, key: str) -> bool:
        st = self.results.get(key)
        return bool(st and st.history)

    def can_redo(self, key: str) -> bool:
        st = self.results.get(key)
        return bool(st and st.future)

    def undo(self, key: str) -> bool:
        """Go back one edit (component edit, drag, add/remove, rename); ``False`` when
        there is nothing to undo."""
        st = self.results.get(key)
        if st is None or not st.history:
            return False
        st.future.append(st.snapshot())
        st.restore(st.history.pop())
        self.resultChanged.emit(key)
        return True

    def redo(self, key: str) -> bool:
        st = self.results.get(key)
        if st is None or not st.future:
            return False
        st.history.append(st.snapshot())
        st.restore(st.future.pop())
        self.resultChanged.emit(key)
        return True

    def shift_file(self, key: str, delta: float, reason: str = "") -> list[str]:
        """Shift every spectrum loaded from the same file as *key* by *delta* eV (charge
        correction) and drop their results, which no longer match the data.  Returns
        the keys that had a result before (candidates for a refit)."""
        keys = self.siblings(key)
        had_result = [k for k in keys if self.results.get(k) is not None]
        for k in keys:
            item = self.items[k]
            item.spectrum = item.spectrum.shift(delta, reason)
            self.results.pop(k, None)
        if keys:
            self.spectraChanged.emit()
        return had_result

    def set_bootstrap(self, key: str, boot: BootstrapResult) -> None:
        st = self.state(key)
        st.bootstrap = boot
        self.resultChanged.emit(key)

    # --------------------------------------------------------------- composition
    def siblings(self, key: str) -> list[str]:
        """Keys of every spectrum loaded from the same file as *key*, in load order."""
        item = self.items.get(key)
        if item is None:
            return []
        return [k for k in self.order if self.items[k].path == item.path]

    def composition(self, key: str) -> QuantResult | None:
        """Relative composition of the sample that *key* belongs to: every fitted region
        of the same file, with the recipe's RSF or, failing that, the Scofield table.

        The same arithmetic as the batch summary (:func:`atomic_percent`, the recipe's
        energy-dependent correction, bootstrap replicates when every region has them).
        ``None`` when no sibling has a fit.
        """
        rows: list[tuple[str, str | None, str | None, float, float | None]] = []
        sources: dict[str, str] = {}
        kinetic: dict[str, float] = {}
        samples: dict[str, np.ndarray] = {}
        recipe = self.recipe
        hv_recipe = recipe.photon_energy if recipe is not None else None
        for k in self.siblings(key):
            st = self.results.get(k)
            if st is None or st.result is None or st.selection is None:
                continue
            region = st.selection.region
            result = st.result
            label = region.name or self.items[k].display_name
            if label in sources:  # two spectra fitted as the same region: keep them apart
                label = f"{label} [{self.items[k].display_name}]"
            total = region.rsf_applies_to == "total"
            area = result.total_area if total else sum(c.area for c in result.majors())
            rsf, source = region.rsf, "recipe"
            if rsf is None:
                rsf = get_rsf(region.element, region.line)
                source = "Scofield" if rsf is not None else "missing"
            rows.append((label, region.element, region.line, area, rsf))
            sources[label] = source
            main = max(result.majors(), key=lambda c: c.area)
            hv = self.items[k].spectrum.photon_energy or hv_recipe or AL_KALPHA_EV
            kinetic[label] = float(hv - main.center)
            if st.bootstrap is not None:
                samples[label] = (
                    st.bootstrap.total_area_samples if total else st.bootstrap.major_area_samples
                )
        if not rows:
            return None
        correction = recipe.quantification if recipe is not None else QuantCorrection()
        quant = atomic_percent(rows, correction, kinetic)
        for e in quant.entries:
            e.rsf_source = sources.get(e.label, "")
            if e.kinetic_energy is None:
                e.kinetic_energy = kinetic.get(e.label)
        if quant.status == "OK" and len(samples) == len(rows):
            _propagate_samples(quant, samples)
        if any(s == "Scofield" for s in sources.values()):
            quant.note += f"; Scofield factors: {SCOFIELD_SOURCE}"
        return quant

    # ------------------------------------------------------------------ renaming
    def rename_spectrum(self, key: str, name: str) -> bool:
        """Give the spectrum a title of the user's choosing.

        The name is stored on the spectrum itself (with a ``rename`` step in its
        history), so the tree, the plot title, the exported figure and the project
        file all show it; output file names keep the source file's stem.  Returns
        ``False`` when nothing changed (unknown key, empty or identical name).
        """
        item = self.items.get(key)
        name = name.strip()
        if item is None or not name or name == item.display_name:
            return False
        old = item.display_name
        item.spectrum.name = name
        item.spectrum.history.append({"step": "rename", "from": old, "to": name})
        st = self.results.get(key)
        if st is not None and st.selection is not None:
            st.selection.spectrum.name = name
        self.spectraChanged.emit()
        return True

    def rename_component(self, key: str, old: str, new: str) -> None:
        """Rename a fitted component (and its minor doublet line) of the displayed
        result without refitting; the fit status is unchanged.

        Raises ``ValueError`` (from :func:`rename_component`) when there is no fit,
        the component is unknown, or the name is empty or already used.
        """
        st = self.results.get(key)
        result = st.result if st is not None else None
        if st is None or result is None:
            raise ValueError("run AUTO FIT first; there is no component to rename")
        renamed = rename_component(result, old, new)
        if renamed is result:
            return
        self._remember(st)
        if st.manual is not None:
            st.manual = renamed
        else:
            assert st.selection is not None and st.selection.best is not None
            st.selection.best.result = renamed
        if st.bootstrap is not None:
            st.bootstrap = st.bootstrap.renamed(old, new.strip())
        self.resultChanged.emit(key)
