"""Side panels: sample tree, fit settings, component and model tables, status lamp, log."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..automation.model_selection import SelectionResult
from ..core.background import BACKGROUND_MODES, BACKGROUND_TYPES, BackgroundSpec
from ..core.constraints import DoubletSpec, PeakConstraints
from ..core.fitting import LOSSES, FitResult
from ..core.peak_shapes import SHAPES
from ..core.quality import grade_fit
from ..core.region import RegionSpec
from ..core.spectrum import Spectrum
from ..core.uncertainty import BootstrapResult
from ..database.binding_energies import spin_orbit
from ..recipes import Recipe
from .session import LoadedSpectrum
from .theme import STATUS_COLORS, STATUS_TEXT


def table_to_tsv(table: QTableWidget, selected_only: bool = True) -> str:
    """Header plus rows as tab-separated text (for the clipboard)."""
    rows = sorted({i.row() for i in table.selectedItems()}) if selected_only else []
    if not rows:
        rows = list(range(table.rowCount()))
    header = []
    for c in range(table.columnCount()):
        h = table.horizontalHeaderItem(c)
        header.append(h.text() if h is not None else "")
    lines = ["\t".join(header)]
    for r in rows:
        cells = []
        for c in range(table.columnCount()):
            item = table.item(r, c)
            cells.append(item.text().strip() if item is not None else "")
        lines.append("\t".join(cells))
    return "\n".join(lines)


class CopyableTable(QTableWidget):
    """Table whose selection (or whole content) goes to the clipboard with Ctrl+C."""

    def copy_to_clipboard(self, selected_only: bool = True) -> str:
        text = table_to_tsv(self, selected_only)
        QApplication.clipboard().setText(text)
        return text

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)


# ----------------------------------------------------------------------------- lamp
class StatusLamp(QWidget):
    """Coloured indicator with a caption, like the ready/busy lamp on an instrument."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._blink_on = True
        self._timer = QTimer(self)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._blink)
        self.label = QLabel(STATUS_TEXT["idle"])
        self.label.setObjectName("readout")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.addSpacing(18)
        lay.addWidget(self.label)
        self.setMinimumWidth(170)

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, text: str | None = None) -> None:
        self._state = state if state in STATUS_COLORS else "idle"
        self.label.setText(text or STATUS_TEXT.get(self._state, state.upper()))
        if self._state == "running":
            self._timer.start()
        else:
            self._timer.stop()
            self._blink_on = True
        self.update()

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(STATUS_COLORS[self._state])
        if not self._blink_on:
            color = color.darker(250)
        painter.setBrush(color)
        painter.setPen(QColor("#0b0b0b"))
        r = 6
        painter.drawEllipse(8, self.height() // 2 - r, 2 * r, 2 * r)
        painter.end()


# ---------------------------------------------------------------------- sample tree
class SampleTree(QTreeWidget):
    spectrumSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Sample / spectrum", "Pts", "Range (eV)", "Fit"])
        for col, width in enumerate((170, 48, 96, 96)):
            self.setColumnWidth(col, width)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.currentItemChanged.connect(self._on_current)
        self._items: dict[str, QTreeWidgetItem] = {}

    def populate(self, items: list[LoadedSpectrum], status: dict[str, str]) -> None:
        current = self.current_key()
        self.clear()
        self._items.clear()
        by_file: dict[str, QTreeWidgetItem] = {}
        for it in items:
            node = by_file.get(str(it.path))
            if node is None:
                node = QTreeWidgetItem([it.path.name, "", "", ""])
                node.setToolTip(0, str(it.path))
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.addTopLevelItem(node)
                node.setExpanded(True)
                by_file[str(it.path)] = node
            lo, hi = it.spectrum.range
            child = QTreeWidgetItem(
                [
                    it.display_name,
                    str(it.spectrum.n),
                    f"{lo:.1f} - {hi:.1f}",
                    STATUS_TEXT.get(status.get(it.key, "idle"), ""),
                ]
            )
            child.setData(0, Qt.ItemDataRole.UserRole, it.key)
            st = status.get(it.key, "idle")
            child.setForeground(3, QColor(STATUS_COLORS.get(st, "#898781")))
            node.addChild(child)
            self._items[it.key] = child
        if current in self._items:
            self.setCurrentItem(self._items[current])

    def set_status(self, key: str, state: str) -> None:
        item = self._items.get(key)
        if item is not None:
            item.setText(3, STATUS_TEXT.get(state, state.upper()))
            item.setForeground(3, QColor(STATUS_COLORS.get(state, "#898781")))

    def current_key(self) -> str | None:
        item = self.currentItem()
        if item is None:
            return None
        key = item.data(0, Qt.ItemDataRole.UserRole)
        return str(key) if key else None

    def select_key(self, key: str) -> None:
        item = self._items.get(key)
        if item is not None:
            self.setCurrentItem(item)

    def _on_current(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.spectrumSelected.emit(str(key))


# --------------------------------------------------------------------- fit settings
def _dspin(
    lo: float, hi: float, value: float, step: float = 0.1, decimals: int = 2
) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    return s


class FitSettingsPanel(QWidget):
    """Everything that defines a region fit; produces a :class:`RegionSpec`."""

    recipeChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recipe: Recipe | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        g_region = QGroupBox("REGION")
        f = QFormLayout(g_region)
        self.recipe_combo = QComboBox()
        self.region_combo = QComboBox()
        self.region_combo.currentIndexChanged.connect(self._region_picked)
        self.element = QComboBox()
        self.element.setEditable(True)
        self.element.addItems(
            ["", "C", "N", "O", "S", "P", "Si", "Cu", "Bi", "Zn", "Ti", "Sn", "Pb", "I"]
        )
        self.line = QComboBox()
        self.line.setEditable(True)
        self.line.addItems(["", "1s", "2p", "2p3/2", "3d", "3d5/2", "4f", "4f7/2"])
        self.range_lo = _dspin(0, 1500, 0.0, 0.5, 2)
        self.range_hi = _dspin(0, 1500, 0.0, 0.5, 2)
        rng = QHBoxLayout()
        rng.addWidget(self.range_lo)
        rng.addWidget(QLabel("to"))
        rng.addWidget(self.range_hi)
        f.addRow("Recipe", self.recipe_combo)
        f.addRow("Region", self.region_combo)
        el = QHBoxLayout()
        el.addWidget(self.element)
        el.addWidget(self.line)
        f.addRow("Element / line", el)
        f.addRow("Range (eV)", rng)
        outer.addWidget(g_region)

        g_bg = QGroupBox("BACKGROUND")
        f = QFormLayout(g_bg)
        self.background = QComboBox()
        self.background.addItems([*BACKGROUND_TYPES, "auto"])
        self.background.setCurrentText("shirley")
        self.bg_mode = QComboBox()
        self.bg_mode.addItems([*BACKGROUND_MODES, "auto"])
        self.bg_mode.setCurrentText("static")
        self.bg_mode.setToolTip(
            "static: computed from the endpoints before the fit.\n"
            "active: Shirley/Tougaard generated from the fitted peaks inside the fit\n"
            "(offset and scattering factor are free parameters; no endpoint bias).\n"
            "auto: try both and choose with the criterion."
        )
        self.refine = QCheckBox("Refine with free linear term")
        self.refine.setChecked(True)
        self.endpoints = QSpinBox()
        self.endpoints.setRange(1, 25)
        self.endpoints.setValue(3)
        f.addRow("Type", self.background)
        f.addRow("Mode", self.bg_mode)
        f.addRow("Endpoint points", self.endpoints)
        f.addRow("", self.refine)
        outer.addWidget(g_bg)

        g_peaks = QGroupBox("PEAKS")
        f = QFormLayout(g_peaks)
        self.shape = QComboBox()
        self.shape.addItems([*SHAPES, "auto"])
        self.shape.setCurrentText("voigt")
        self.min_n = QSpinBox()
        self.min_n.setRange(1, 8)
        self.max_n = QSpinBox()
        self.max_n.setRange(1, 8)
        self.max_n.setValue(3)
        n = QHBoxLayout()
        n.addWidget(self.min_n)
        n.addWidget(QLabel("to"))
        n.addWidget(self.max_n)
        self.fwhm_g_lo = _dspin(0.05, 10, 0.3, 0.05)
        self.fwhm_g_hi = _dspin(0.05, 10, 3.0, 0.05)
        self.fwhm_l_lo = _dspin(0.01, 5, 0.02, 0.01)
        self.fwhm_l_hi = _dspin(0.01, 5, 1.0, 0.05)
        self.share_l = QCheckBox("Share Lorentzian width")
        self.share_l.setChecked(True)
        self.asym_hi = _dspin(0.01, 0.5, 0.5, 0.05)
        self.asym_hi.setToolTip("Upper bound of the Doniach-Sunjic asymmetry (metals: 0.05-0.2)")
        self.min_sep = _dspin(0.0, 5, 0.3, 0.05)
        fg = QHBoxLayout()
        fg.addWidget(self.fwhm_g_lo)
        fg.addWidget(QLabel("to"))
        fg.addWidget(self.fwhm_g_hi)
        fl = QHBoxLayout()
        fl.addWidget(self.fwhm_l_lo)
        fl.addWidget(QLabel("to"))
        fl.addWidget(self.fwhm_l_hi)
        f.addRow("Shape", self.shape)
        f.addRow("Components", n)
        f.addRow("FWHM G (eV)", fg)
        f.addRow("FWHM L (eV)", fl)
        f.addRow("", self.share_l)
        f.addRow("DS asymmetry max", self.asym_hi)
        f.addRow("Min separation", self.min_sep)
        outer.addWidget(g_peaks)
        self.shape.currentTextChanged.connect(
            lambda t: self.asym_hi.setEnabled(t in ("doniach_sunjic", "auto"))
        )
        self.asym_hi.setEnabled(False)

        g_d = QGroupBox("SPIN-ORBIT DOUBLET")
        f = QFormLayout(g_d)
        self.doublet = QCheckBox("Fit as doublets")
        self.split = _dspin(0.01, 50, 1.18, 0.01, 3)
        self.ratio = _dspin(0.05, 1.5, 0.5, 0.01, 3)
        self.split_tol = _dspin(0.0, 1.0, 0.02, 0.01, 3)
        f.addRow("", self.doublet)
        f.addRow("Splitting (eV)", self.split)
        f.addRow("Area ratio minor/major", self.ratio)
        f.addRow("Splitting tolerance", self.split_tol)
        outer.addWidget(g_d)

        g_sel = QGroupBox("MODEL SELECTION")
        f = QFormLayout(g_sel)
        self.criterion = QComboBox()
        self.criterion.addItems(["aicc", "bic", "aic"])
        self.optimizer = QComboBox()
        self.optimizer.addItems(["leastsq", "global"])
        self.optimizer.setToolTip("global: differential evolution inside the bounds, then LM")
        self.n_starts = QSpinBox()
        self.n_starts.setRange(1, 20)
        self.n_starts.setValue(4)
        self.min_improvement = _dspin(0.0, 50, 2.0, 0.5, 1)
        self.auto_refit = QCheckBox("Refit when a peak is dragged")
        self.auto_refit.setChecked(True)
        f.addRow("Criterion", self.criterion)
        f.addRow("Optimizer", self.optimizer)
        f.addRow("Starts per model", self.n_starts)
        f.addRow("Min improvement", self.min_improvement)
        f.addRow("", self.auto_refit)
        outer.addWidget(g_sel)

        g_rob = QGroupBox("ROBUSTNESS")
        f = QFormLayout(g_rob)
        self.loss = QComboBox()
        self.loss.addItems(list(LOSSES))
        self.loss.setToolTip(
            "linear: ordinary least squares.\n"
            "soft_l1 / huber / cauchy / arctan: residuals beyond the scale pull less,\n"
            "so spikes and misfit tails distort the components less."
        )
        self.loss_scale = _dspin(0.5, 20, 3.0, 0.5, 1)
        self.loss_scale.setToolTip("Residual size (in sigma) where down-weighting starts")
        self.mask_spikes = QCheckBox("Mask spikes above")
        self.spike_sigma = _dspin(3.0, 30, 6.0, 0.5, 1)
        self.spike_sigma.setToolTip(
            "Exclude isolated points this many local standard deviations off the\n"
            "running median (cosmic-ray hits, detector glitches)"
        )
        sp = QHBoxLayout()
        sp.addWidget(self.mask_spikes)
        sp.addWidget(self.spike_sigma)
        sp.addWidget(QLabel("sigma"))
        f.addRow("Loss", self.loss)
        f.addRow("Loss scale", self.loss_scale)
        f.addRow("", sp)
        outer.addWidget(g_rob)
        self.loss.currentTextChanged.connect(lambda t: self.loss_scale.setEnabled(t != "linear"))
        self.loss_scale.setEnabled(False)
        self.mask_spikes.toggled.connect(self.spike_sigma.setEnabled)
        self.spike_sigma.setEnabled(False)
        outer.addStretch(1)

        self.element.currentTextChanged.connect(self._auto_doublet)
        self.line.currentTextChanged.connect(self._auto_doublet)

    # ---------------------------------------------------------------- recipes
    def set_recipes(self, names: list[str]) -> None:
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem("(none - manual settings)", None)
        for n in names:
            self.recipe_combo.addItem(n, n)
        self.recipe_combo.blockSignals(False)

    def set_recipe(self, recipe: Recipe | None) -> None:
        self._recipe = recipe
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        self.region_combo.addItem("(auto / ad-hoc)", None)
        if recipe is not None:
            for r in recipe.regions:
                if r.fit:
                    self.region_combo.addItem(r.name, r.name)
        self.region_combo.blockSignals(False)
        self.recipeChanged.emit()

    def select_region_for(self, spectrum: Spectrum) -> RegionSpec | None:
        """Pick the recipe region covering this spectrum and load it; None if no match."""
        if self._recipe is None:
            return None
        from ..automation.batch_fitting import match_regions

        pairs = match_regions([spectrum], self._recipe)
        for _spectrum, region in pairs:
            if region.fit:
                idx = self.region_combo.findData(region.name)
                if idx >= 0:
                    self.region_combo.setCurrentIndex(idx)
                return region
        self.region_combo.setCurrentIndex(0)
        return None

    def _region_picked(self, _index: int) -> None:
        name = self.region_combo.currentData()
        if self._recipe is None or not name:
            return
        region = self._recipe.region(str(name))
        if region is not None:
            self.load_region(region)

    def _auto_doublet(self, _text: str = "") -> None:
        so = spin_orbit(
            self.element.currentText().strip() or None, self.line.currentText().strip() or None
        )
        if so is not None:
            self.split.setValue(so[0])
            self.ratio.setValue(so[1])
            self.doublet.setChecked(True)

    # ------------------------------------------------------------------ values
    def set_range(self, lo: float, hi: float) -> None:
        self.range_lo.setValue(lo)
        self.range_hi.setValue(hi)

    def load_region(self, region: RegionSpec) -> None:
        self.element.setCurrentText(region.element or "")
        self.line.setCurrentText(region.line or "")
        if region.range:
            self.set_range(*region.range)
        self.background.setCurrentText(region.background.type)
        self.bg_mode.setCurrentText(region.background.mode)
        self.endpoints.setValue(region.background.endpoint_points)
        self.refine.setChecked(region.refine_background)
        self.shape.setCurrentText(region.shape)
        self.min_n.setValue(region.min_components)
        self.max_n.setValue(region.max_components)
        c = region.constraints
        self.fwhm_g_lo.setValue(c.fwhm_g[0])
        self.fwhm_g_hi.setValue(c.fwhm_g[1])
        self.fwhm_l_lo.setValue(c.fwhm_l[0])
        self.fwhm_l_hi.setValue(c.fwhm_l[1])
        self.share_l.setChecked(c.share_fwhm_l)
        self.asym_hi.setValue(c.asym[1])
        self.min_sep.setValue(c.min_separation)
        self.doublet.setChecked(region.doublet is not None)
        if region.doublet is not None:
            self.split.setValue(region.doublet.splitting)
            self.ratio.setValue(region.doublet.area_ratio)
            self.split_tol.setValue(region.doublet.splitting_tolerance)
        self.criterion.setCurrentText(region.criterion)
        self.optimizer.setCurrentText(region.optimizer)
        self.n_starts.setValue(region.n_starts)
        self.min_improvement.setValue(region.min_improvement)
        self.loss.setCurrentText(region.loss)
        self.loss_scale.setValue(region.loss_scale)
        self.mask_spikes.setChecked(region.spike_sigma is not None)
        if region.spike_sigma is not None:
            self.spike_sigma.setValue(region.spike_sigma)

    def region_spec(self, spectrum: Spectrum) -> RegionSpec:
        """RegionSpec from the panel; candidates/RSF come from the selected recipe region."""
        name = self.region_combo.currentData()
        base = self._recipe.region(str(name)) if (self._recipe is not None and name) else None
        lo, hi = self.range_lo.value(), self.range_hi.value()
        if hi - lo < 1.0:
            lo, hi = spectrum.range
        constraints = PeakConstraints(
            fwhm_g=(self.fwhm_g_lo.value(), self.fwhm_g_hi.value()),
            fwhm_l=(self.fwhm_l_lo.value(), self.fwhm_l_hi.value()),
            asym=(0.0, max(self.asym_hi.value(), 0.01)),
            share_fwhm_l=self.share_l.isChecked(),
            min_separation=self.min_sep.value(),
        )
        doublet = None
        if self.doublet.isChecked():
            doublet = DoubletSpec(
                splitting=self.split.value(),
                area_ratio=self.ratio.value(),
                splitting_tolerance=self.split_tol.value(),
            )
        element = self.element.currentText().strip() or None
        line = self.line.currentText().strip() or None
        region_name = (
            base.name
            if base is not None
            else (" ".join(t for t in (element, line) if t) or "region")
        )
        return RegionSpec(
            name=region_name,
            element=element,
            line=line,
            range=(lo, hi),
            background=BackgroundSpec(
                type=self.background.currentText(),
                endpoint_points=self.endpoints.value(),
                mode=self.bg_mode.currentText(),
            ),
            refine_background=self.refine.isChecked(),
            shape=self.shape.currentText(),
            constraints=constraints,
            doublet=doublet,
            candidates=list(base.candidates) if base is not None else [],
            min_components=min(self.min_n.value(), self.max_n.value()),
            max_components=max(self.min_n.value(), self.max_n.value()),
            rsf=base.rsf if base is not None else None,
            rsf_applies_to=base.rsf_applies_to if base is not None else "total",
            n_starts=self.n_starts.value(),
            criterion=self.criterion.currentText(),
            min_improvement=self.min_improvement.value(),
            optimizer=self.optimizer.currentText(),
            loss=self.loss.currentText(),
            loss_scale=self.loss_scale.value(),
            spike_sigma=self.spike_sigma.value() if self.mask_spikes.isChecked() else None,
            require_assignment=base.require_assignment if base is not None else False,
        )


# ----------------------------------------------------------------- components table
COMPONENT_HEADERS = [
    "Component",
    "Centre (eV)",
    "±",
    "FWHM",
    "Area",
    "±",
    "Comp. %",
    "FWHM G",
    "FWHM L",
    "Asym",
]


class ComponentsTable(CopyableTable):
    componentEdited = Signal(str, str, float)  # parent label, field, value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(COMPONENT_HEADERS), parent)
        self.setHorizontalHeaderLabels(COMPONENT_HEADERS)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._loading = False
        self.itemChanged.connect(self._changed)

    def show_result(self, result: FitResult | None) -> None:
        self._loading = True
        self.setRowCount(0)
        if result is not None:
            for comp in result.components:
                r = self.rowCount()
                self.insertRow(r)
                values = [
                    ("    " if comp.is_minor else "") + comp.label,
                    f"{comp.center:.3f}",
                    f"{comp.center_err:.3f}" if comp.center_err is not None else "-",
                    f"{comp.fwhm:.3f}",
                    f"{comp.area:.1f}",
                    f"{comp.area_err:.1f}" if comp.area_err is not None else "-",
                    f"{comp.component_fraction:.1f}" if comp.component_fraction is not None else "",
                    f"{comp.fwhm_g:.3f}" if comp.fwhm_g is not None else "",
                    f"{comp.fwhm_l:.3f}" if comp.fwhm_l is not None else "",
                    f"{comp.asym:.3f}" if comp.asym is not None else "",
                ]
                for c, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, comp.parent)
                    editable = (not comp.is_minor) and c in (1, 7, 8)
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if c > 0:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.setItem(r, c, item)
        self._loading = False

    def selected_parent(self) -> str | None:
        items = self.selectedItems()
        if not items:
            return None
        return str(items[0].data(Qt.ItemDataRole.UserRole))

    def _changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        field = {1: "center", 7: "fwhm_g", 8: "fwhm_l"}.get(item.column())
        if field is None:
            return
        try:
            value = float(item.text())
        except ValueError:
            return
        self.componentEdited.emit(str(item.data(Qt.ItemDataRole.UserRole)), field, value)


# ------------------------------------------------------------------- model table
GRADE_COLORS = {"A": "ok", "B": "ok", "C": "ambiguous", "D": "failed", "E": "failed"}


class ModelTable(CopyableTable):
    modelPicked = Signal(int)
    """Index of the clicked candidate in ``SelectionResult.candidates``."""

    HEADERS = ["n", "Model", "Criterion", "χ²red", "DW", "Grade", "Physical", "Reasons"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cellClicked.connect(self._picked)

    def _picked(self, row: int, _col: int) -> None:
        item = self.item(row, 0)
        if item is not None:
            self.modelPicked.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def show_selection(self, sel: SelectionResult | None) -> None:
        self.setRowCount(0)
        if sel is None:
            return
        for index, c in enumerate(sel.candidates):
            r = self.rowCount()
            self.insertRow(r)
            reasons = "; ".join(v.message for v in c.violations) or "; ".join(
                v.message for v in c.warnings
            )
            dw = c.result.stats.durbin_watson
            grade = c.grade.letter if c.grade else "-"
            cells = [
                str(c.n_components),
                c.variant,
                f"{c.criterion_value:.1f}",
                f"{c.result.stats.redchi:.2f}",
                f"{dw:.2f}" if dw is not None else "-",
                grade,
                "pass" if c.physical_ok else "FAIL",
                reasons,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, index)
                if sel.best is c:
                    item.setForeground(QColor(STATUS_COLORS["ok"]))
                if col == 6 and not c.physical_ok:
                    item.setForeground(QColor(STATUS_COLORS["failed"]))
                if col == 4 and dw is not None and dw < 1.0:
                    item.setForeground(QColor(STATUS_COLORS["ambiguous"]))
                if col == 5 and grade in GRADE_COLORS:
                    item.setForeground(QColor(STATUS_COLORS[GRADE_COLORS[grade]]))
                    item.setToolTip(c.grade.description if c.grade else "")
                self.setItem(r, col, item)


# ------------------------------------------------------------- diagnostics readout
class DiagnosticsPanel(QPlainTextEdit):
    """Monospace readout of the fit statistics, residual diagnostics, background
    parameters, warnings and (when run) the bootstrap uncertainties."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("readout")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def display(
        self,
        result: FitResult | None = None,
        selection: SelectionResult | None = None,
        status: str = "",
        boot: BootstrapResult | None = None,
    ) -> None:
        self.setPlainText(diagnostics_text(result, selection, status, boot))


def diagnostics_text(
    result: FitResult | None,
    selection: SelectionResult | None,
    status: str = "",
    boot: BootstrapResult | None = None,
) -> str:
    if result is None:
        return "No fit yet.  Select a spectrum and run AUTO FIT."
    s = result.stats
    bg = result.background
    lines: list[str] = []
    model = selection.best.variant if (selection and selection.best) else result.settings.shape
    lines.append(
        f"MODEL       {model}   n = {len(result.majors())}   "
        f"{STATUS_TEXT.get(status, status.upper())}"
    )
    weight = "Poisson weights" if s.weighted else "unweighted"
    lines.append(f"DATA        {s.ndata} points   {weight}   free parameters {s.nvarys}")
    lines.append(
        f"FIT         chi2red {s.redchi:.3f}   AICc {s.aicc:.1f}   BIC {s.bic:.1f}   "
        f"nfev {s.nfev}   {'converged' if s.success else 'NOT converged'}"
    )
    if s.durbin_watson is not None:
        verdict = "white" if s.durbin_watson >= 1.0 else "STRUCTURED"
        rz = f"{s.runs_z:+.2f}" if s.runs_z is not None else "-"
        lag = f"{s.lag1_autocorr:+.3f}" if s.lag1_autocorr is not None else "-"
        lines.append(
            f"RESIDUAL    Durbin-Watson {s.durbin_watson:.2f} ({verdict}; 2 = white noise)   "
            f"runs z {rz}   lag-1 r {lag}"
        )
    best = selection.best if selection is not None else None
    if best is not None and best.result is result and best.grade is not None:
        grade = best.grade
    else:
        grade = grade_fit(result)
    lines.append(f"QUALITY     grade {grade.letter} ({grade.score:.0f}/100) - {grade.description}")
    lines.extend(f"              {r}" for r in grade.reasons)
    extras = []
    if s.max_correlation is not None:
        extras.append(f"max cross-component |r| {s.max_correlation:.3f} ({s.max_correlation_pair})")
    if s.n_masked:
        extras.append(f"{s.n_masked} point(s) masked as spikes")
    if s.loss != "linear":
        extras.append(f"robust loss {s.loss}")
    if extras:
        lines.append("PARAMETERS  " + "   ".join(extras))
    info = bg.info
    bg_line = f"BACKGROUND  {bg.spec.type} {info.get('mode', bg.spec.mode)}"
    if "offset" in info:
        bg_line += f"   offset {info['offset']:.1f}   scatter k {info['scatter']:.4g}"
    elif "I_low_BE" in info:
        bg_line += f"   I(low BE) {info['I_low_BE']:.1f}   I(high BE) {info['I_high_BE']:.1f}"
    if result.settings.refine_linear_background:
        slope = result.params.get("bg_slope", {}).get("value")
        offset = result.params.get("bg_offset", {}).get("value")
        extra = []
        if offset is not None and info.get("mode") != "active":
            extra.append(f"offset {offset:+.2f}")
        if slope is not None:
            extra.append(f"slope {slope:+.3g}/eV")
        if extra:
            bg_line += "   linear term " + ", ".join(extra)
    lines.append(bg_line)
    for c in result.majors():
        err = f" ± {c.center_err:.3f}" if c.center_err is not None else ""
        aerr = f" ± {c.area_err:.0f}" if c.area_err is not None else ""
        frac = f"{c.component_fraction:5.1f} %" if c.component_fraction is not None else ""
        asym = f"   asym {c.asym:.3f}" if c.asym is not None else ""
        lines.append(
            f"            {c.label[:26]:<26} {c.center:9.3f}{err:<9} eV   FWHM {c.fwhm:5.3f}   "
            f"area {c.area:10.1f}{aerr:<9} {frac}{asym}"
        )
    warnings = list(result.warnings)
    if selection is not None and selection.best is not None and selection.best.result is result:
        warnings += [v.message for v in selection.best.violations + selection.best.warnings]
    if warnings:
        lines.append("WARNINGS")
        lines.extend(f"  - {w}" for w in dict.fromkeys(warnings))
    if selection is not None and selection.notes:
        lines.append("NOTES")
        lines.extend(f"  - {n}" for n in selection.notes[:8])
    if boot is not None:
        lines.append(
            f"BOOTSTRAP   {boot.n_succeeded}/{boot.n_requested} replicates ({boot.mode}); "
            "std and 95 % interval"
        )
        for label, attrs in boot.summary.items():
            area = attrs.get("area")
            frac_s = attrs.get("component_fraction") or attrs.get("fraction")
            cen = attrs.get("center")
            parts = [f"            {label[:26]:<26}"]
            if area:
                parts.append(f"area ± {area['std']:.0f} [{area['p2.5']:.0f}, {area['p97.5']:.0f}]")
            if frac_s:
                parts.append(
                    f"  % ± {frac_s['std']:.2f} [{frac_s['p2.5']:.1f}, {frac_s['p97.5']:.1f}]"
                )
            if cen:
                parts.append(f"  centre ± {cen['std']:.3f} eV")
            lines.append(" ".join(parts))
    return "\n".join(lines)


class LogPanel(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)

    def log(self, text: str) -> None:
        self.appendPlainText(text)
