"""Side panels: sample tree, fit settings, component and model tables, status lamp, log."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from ..core.background import BACKGROUND_TYPES, BackgroundSpec
from ..core.constraints import DoubletSpec, PeakConstraints
from ..core.fitting import FitResult
from ..core.peak_shapes import SHAPES
from ..core.region import RegionSpec
from ..core.spectrum import Spectrum
from ..database.binding_energies import spin_orbit
from ..recipes import Recipe
from .session import LoadedSpectrum
from .theme import STATUS_COLORS, STATUS_TEXT


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
        self.refine = QCheckBox("Refine with free linear term")
        self.refine.setChecked(True)
        self.endpoints = QSpinBox()
        self.endpoints.setRange(1, 25)
        self.endpoints.setValue(3)
        f.addRow("Type", self.background)
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
        f.addRow("Min separation", self.min_sep)
        outer.addWidget(g_peaks)

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
                type=self.background.currentText(), endpoint_points=self.endpoints.value()
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
]


class ComponentsTable(QTableWidget):
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
class ModelTable(QTableWidget):
    modelPicked = Signal(int)

    HEADERS = ["n", "Criterion", "χ²red", "Physical", "Reasons"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cellClicked.connect(self._picked)

    def _picked(self, row: int, _col: int) -> None:
        item = self.item(row, 0)
        if item is not None:
            self.modelPicked.emit(int(item.text()))

    def show_selection(self, sel: SelectionResult | None) -> None:
        self.setRowCount(0)
        if sel is None:
            return
        for c in sel.candidates:
            r = self.rowCount()
            self.insertRow(r)
            reasons = "; ".join(v.message for v in c.violations) or "; ".join(
                v.message for v in c.warnings
            )
            cells = [
                str(c.n_components),
                f"{c.criterion_value:.1f}",
                f"{c.result.stats.redchi:.2f}",
                "pass" if c.physical_ok else "FAIL",
                reasons,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if sel.best is c:
                    item.setForeground(QColor(STATUS_COLORS["ok"]))
                if col == 3 and not c.physical_ok:
                    item.setForeground(QColor(STATUS_COLORS["failed"]))
                self.setItem(r, col, item)


class LogPanel(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)

    def log(self, text: str) -> None:
        self.appendPlainText(text)
