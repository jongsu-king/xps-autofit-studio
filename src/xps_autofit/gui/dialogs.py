"""Export and batch dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

FORMATS = ("csv", "xlsx", "json", "png", "svg", "pdf")


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
