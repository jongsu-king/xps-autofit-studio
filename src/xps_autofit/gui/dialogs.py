"""Export and batch dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..readers import supported_extensions
from ..recipes import builtin_recipe_names

FORMATS = ("csv", "xlsx", "json", "png", "svg", "pdf", "origin", "report")


class _FolderField(QWidget):
    def __init__(self, initial: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit(initial)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit)
        lay.addWidget(btn)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Choose folder", self.edit.text() or str(Path.home())
        )
        if d:
            self.edit.setText(d)

    def path(self) -> Path:
        return Path(self.edit.text()).expanduser()


class _FormatBox(QGroupBox):
    def __init__(
        self, checked: tuple[str, ...] = ("csv", "json", "png"), parent: QWidget | None = None
    ) -> None:
        super().__init__("FORMATS", parent)
        self.boxes: dict[str, QCheckBox] = {}
        lay = QHBoxLayout(self)
        for f in FORMATS:
            b = QCheckBox(f.upper())
            b.setChecked(f in checked)
            self.boxes[f] = b
            lay.addWidget(b)

    def formats(self) -> tuple[str, ...]:
        return tuple(f for f, b in self.boxes.items() if b.isChecked())


class ExportDialog(QDialog):
    def __init__(self, default_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export results")
        self.folder = _FolderField(str(default_dir))
        self.formats = _FormatBox()
        self.bootstrap = QSpinBox()
        self.bootstrap.setRange(0, 2000)
        self.bootstrap.setValue(0)
        form = QFormLayout()
        form.addRow("Output folder", self.folder)
        form.addRow("Bootstrap replicates", self.bootstrap)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.formats)
        lay.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "output_dir": self.folder.path(),
            "formats": self.formats.formats(),
            "bootstrap": self.bootstrap.value(),
        }


class BatchDialog(QDialog):
    def __init__(self, default_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch process")
        self.resize(640, 480)
        self.files = QListWidget()
        add_files = QPushButton("Add files…")
        add_folder = QPushButton("Add folder…")
        clear = QPushButton("Clear")
        add_files.clicked.connect(self._add_files)
        add_folder.clicked.connect(self._add_folder)
        clear.clicked.connect(self.files.clear)
        row = QHBoxLayout()
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addWidget(clear)
        row.addStretch(1)
        self.recipe = QComboBox()
        for n in builtin_recipe_names():
            self.recipe.addItem(n, n)
        self.recipe.addItem("Custom YAML…", "__custom__")
        self.recipe.currentIndexChanged.connect(self._recipe_changed)
        self.custom_recipe = QLineEdit()
        self.custom_recipe.setPlaceholderText("path to recipe .yaml")
        self.custom_recipe.setEnabled(False)
        self.output = _FolderField(str(default_dir / "xps_autofit_results"))
        self.formats = _FormatBox(("csv", "xlsx", "json", "png"))
        self.charge = QCheckBox("Apply the recipe's charge reference (with warning)")
        self.charge.setChecked(True)
        self.regions = QLineEdit()
        self.regions.setPlaceholderText("optional: comma-separated region names, e.g. S 2p, C 1s")
        form = QFormLayout()
        form.addRow("Recipe", self.recipe)
        form.addRow("Custom recipe", self.custom_recipe)
        form.addRow("Only regions", self.regions)
        form.addRow("Output folder", self.output)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run batch")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.files)
        lay.addLayout(row)
        lay.addLayout(form)
        lay.addWidget(self.formats)
        lay.addWidget(self.charge)
        lay.addWidget(buttons)

    def _recipe_changed(self, _i: int) -> None:
        self.custom_recipe.setEnabled(self.recipe.currentData() == "__custom__")

    def _add_files(self) -> None:
        pats = " ".join(f"*{e}" for e in supported_extensions())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add spectra", "", f"Spectra ({pats});;All files (*)"
        )
        for p in paths:
            self.files.addItem(p)

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.files.addItem(d)

    def add_paths(self, paths: list[str]) -> None:
        for p in paths:
            self.files.addItem(p)

    def values(self) -> dict[str, Any]:
        recipe = self.recipe.currentData()
        if recipe == "__custom__":
            recipe = self.custom_recipe.text().strip()
        regions = [r.strip() for r in self.regions.text().split(",") if r.strip()]
        return {
            "paths": [self.files.item(i).text() for i in range(self.files.count())],
            "recipe": recipe,
            "output_dir": self.output.path(),
            "formats": self.formats.formats(),
            "charge_correct": self.charge.isChecked(),
            "regions": regions or None,
        }


class TableDialog(QDialog):
    """Show a DataFrame (batch summary) with a button to reveal the output folder."""

    def __init__(
        self,
        title: str,
        frame: pd.DataFrame,
        folder: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(960, 520)
        table = QTableWidget(len(frame.index), len(frame.columns))
        table.setHorizontalHeaderLabels([str(c) for c in frame.columns])
        table.verticalHeader().setVisible(False)
        for r, (_idx, row) in enumerate(frame.iterrows()):
            for c, value in enumerate(row):
                text = (
                    ""
                    if pd.isna(value)
                    else (f"{value:.4g}" if isinstance(value, float) else str(value))
                )
                table.setItem(r, c, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        lay = QVBoxLayout(self)
        lay.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        if folder is not None:
            reveal = QPushButton("Open output folder")
            reveal.clicked.connect(lambda: _open_folder(folder))
            buttons.addButton(reveal, QDialogButtonBox.ButtonRole.ActionRole)
        lay.addWidget(buttons)


def _open_folder(folder: Path) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class PlotOptionsDialog(QDialog):
    """Title, axis labels, fonts, symbol and line sizes, legend, fills and ranges of
    the live plot.  Zero or empty means "as the plot style decides"."""

    def __init__(self, options: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plot options")
        self.title = QLineEdit(options.title)
        self.title.setPlaceholderText("automatic (spectrum and region)")
        self.x_label = QLineEdit(options.x_label)
        self.x_label.setPlaceholderText("Binding energy (eV)")
        self.y_label = QLineEdit(options.y_label)
        self.y_label.setPlaceholderText("automatic (Intensity (unit))")
        self.tick_pt = QSpinBox()
        self.tick_pt.setRange(0, 24)
        self.tick_pt.setSpecialValueText("style")
        self.tick_pt.setValue(options.tick_font_pt)
        self.label_pt = QSpinBox()
        self.label_pt.setRange(0, 28)
        self.label_pt.setSpecialValueText("style")
        self.label_pt.setValue(options.label_font_pt)
        self.symbol = QSpinBox()
        self.symbol.setRange(0, 14)
        self.symbol.setSpecialValueText("style")
        self.symbol.setValue(options.symbol_size)
        self.envelope = QDoubleSpinBox()
        self.envelope.setRange(0.0, 6.0)
        self.envelope.setSingleStep(0.2)
        self.envelope.setSpecialValueText("style")
        self.envelope.setValue(options.envelope_width)
        self.fill = QSpinBox()
        self.fill.setRange(-1, 100)
        self.fill.setSpecialValueText("style")
        self.fill.setSuffix(" %")
        self.fill.setValue(options.fill_alpha)
        self.legend = QCheckBox("Show legend")
        self.legend.setChecked(options.show_legend)
        self.fills = QCheckBox("Fill the components")
        self.fills.setChecked(options.show_fills)
        self.center_labels = QCheckBox("Label the centre lines")
        self.center_labels.setChecked(options.show_center_labels)
        self.x_auto = QCheckBox("automatic")
        self.x_lo, self.x_hi = QDoubleSpinBox(), QDoubleSpinBox()
        self.y_auto = QCheckBox("automatic")
        self.y_lo, self.y_hi = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.x_lo, self.x_hi):
            box.setRange(-10000.0, 10000.0)
            box.setDecimals(2)
        for box in (self.y_lo, self.y_hi):
            box.setRange(-1e9, 1e9)
            box.setDecimals(1)
        self.x_auto.setChecked(options.x_range is None)
        self.y_auto.setChecked(options.y_range is None)
        if options.x_range:
            self.x_lo.setValue(options.x_range[0])
            self.x_hi.setValue(options.x_range[1])
        if options.y_range:
            self.y_lo.setValue(options.y_range[0])
            self.y_hi.setValue(options.y_range[1])
        for auto, boxes in (
            (self.x_auto, (self.x_lo, self.x_hi)),
            (self.y_auto, (self.y_lo, self.y_hi)),
        ):
            for b in boxes:
                b.setEnabled(not auto.isChecked())
            auto.toggled.connect(lambda on, bs=boxes: [b.setEnabled(not on) for b in bs])

        form = QFormLayout()
        form.addRow("Title", self.title)
        form.addRow("X axis label", self.x_label)
        form.addRow("Y axis label", self.y_label)
        form.addRow("Tick label size (pt)", self.tick_pt)
        form.addRow("Axis label size (pt)", self.label_pt)
        form.addRow("Data symbol size", self.symbol)
        form.addRow("Envelope line width", self.envelope)
        form.addRow("Component fill opacity", self.fill)
        x_row = QHBoxLayout()
        x_row.addWidget(self.x_lo)
        x_row.addWidget(self.x_hi)
        x_row.addWidget(self.x_auto)
        form.addRow("X range (eV)", x_row)
        y_row = QHBoxLayout()
        y_row.addWidget(self.y_lo)
        y_row.addWidget(self.y_hi)
        y_row.addWidget(self.y_auto)
        form.addRow("Y range", y_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self.restore_defaults
        )
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.legend)
        lay.addWidget(self.fills)
        lay.addWidget(self.center_labels)
        lay.addWidget(buttons)

    def restore_defaults(self) -> None:
        self.title.clear()
        self.x_label.clear()
        self.y_label.clear()
        for box in (self.tick_pt, self.label_pt, self.symbol):
            box.setValue(0)
        self.envelope.setValue(0.0)
        self.fill.setValue(-1)
        for cb in (self.legend, self.fills, self.center_labels, self.x_auto, self.y_auto):
            cb.setChecked(True)

    def values(self) -> Any:
        from .plot_widget import PlotOptions

        def rng(
            auto: QCheckBox, lo: QDoubleSpinBox, hi: QDoubleSpinBox
        ) -> tuple[float, float] | None:
            if auto.isChecked() or lo.value() == hi.value():
                return None
            return (min(lo.value(), hi.value()), max(lo.value(), hi.value()))

        return PlotOptions(
            title=self.title.text().strip(),
            x_label=self.x_label.text().strip(),
            y_label=self.y_label.text().strip(),
            tick_font_pt=self.tick_pt.value(),
            label_font_pt=self.label_pt.value(),
            symbol_size=self.symbol.value(),
            envelope_width=self.envelope.value(),
            fill_alpha=self.fill.value(),
            show_legend=self.legend.isChecked(),
            show_fills=self.fills.isChecked(),
            show_center_labels=self.center_labels.isChecked(),
            x_range=rng(self.x_auto, self.x_lo, self.x_hi),
            y_range=rng(self.y_auto, self.y_lo, self.y_hi),
        )


class SeriesDialog(QDialog):
    """Composition of every loaded file against the sample order: a table, a plot
    (atomic percent per element with error bars) and CSV / Origin export."""

    def __init__(
        self,
        frame: pd.DataFrame,
        export: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        import pyqtgraph as pg

        from ..automation.series import series_elements
        from ..export.plots import SERIES

        super().__init__(parent)
        self.setWindowTitle("Composition series")
        self.resize(1000, 640)
        self.frame = frame
        self.table = QTableWidget(len(frame.index), len(frame.columns))
        self.table.setHorizontalHeaderLabels([str(c) for c in frame.columns])
        self.table.verticalHeader().setVisible(False)
        for r, (_idx, row) in enumerate(frame.iterrows()):
            for c, value in enumerate(row):
                text = (
                    ""
                    if pd.isna(value)
                    else (f"{value:.2f}" if isinstance(value, float) else str(value))
                )
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.plot = pg.PlotWidget(background="#ffffff")
        item = self.plot.getPlotItem()
        for name in ("left", "bottom", "top", "right"):
            item.showAxis(name)
            ax = item.getAxis(name)
            ax.setPen(pg.mkPen("#000000"))
            ax.setTextPen(pg.mkPen("#000000"))
            ax.setStyle(tickLength=-6)
        item.getAxis("top").setStyle(showValues=False)
        item.getAxis("right").setStyle(showValues=False)
        item.setLabel("left", "Atomic concentration (%)", color="#000000")
        item.setLabel("bottom", "Sample", color="#000000")
        item.addLegend(offset=(-10, 10), labelTextColor="#000000")
        x = frame["index"].to_numpy(dtype=float)
        item.getAxis("bottom").setTicks([[(float(i), str(s)) for i, s in zip(x, frame["sample"])]])
        self.curves = []
        for k, el in enumerate(series_elements(frame)):
            color = SERIES[k % len(SERIES)]
            y = frame[f"{el} at%"].to_numpy(dtype=float)
            ok = np.isfinite(y)
            curve = item.plot(
                x[ok],
                y[ok],
                pen=pg.mkPen(color, width=1.5),
                symbol="o",
                symbolSize=7,
                symbolPen=pg.mkPen(color, width=1.2),
                symbolBrush=pg.mkBrush("#ffffff"),
                name=el,
            )
            self.curves.append(curve)
            if f"{el} err" in frame.columns:
                err = frame[f"{el} err"].to_numpy(dtype=float)
                good = ok & np.isfinite(err)
                if good.any():
                    item.addItem(
                        pg.ErrorBarItem(
                            x=x[good],
                            y=y[good],
                            height=2 * err[good],
                            beam=0.15,
                            pen=pg.mkPen(color, width=1),
                        )
                    )
        # half a step of room on both sides so the first and last sample names show,
        # and atomic percent from zero
        if x.size:
            item.setXRange(float(x.min()) - 0.5, float(x.max()) + 0.5, padding=0.0)
            shares = [frame[c].to_numpy(dtype=float) for c in frame.columns if c.endswith(" at%")]
            top = max((float(np.nanmax(v)) for v in shares if np.isfinite(v).any()), default=100.0)
            item.setYRange(0.0, min(100.0, top * 1.12 + 1.0), padding=0.0)
        lay = QVBoxLayout(self)
        lay.addWidget(self.plot, 3)
        lay.addWidget(self.table, 2)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        if export is not None:
            to_csv = QPushButton("Export CSV…")
            to_csv.clicked.connect(lambda: export(False))
            to_origin = QPushButton("Export for Origin…")
            to_origin.clicked.connect(lambda: export(True))
            buttons.addButton(to_csv, QDialogButtonBox.ButtonRole.ActionRole)
            buttons.addButton(to_origin, QDialogButtonBox.ButtonRole.ActionRole)
        lay.addWidget(buttons)
