"""Live spectrum view: raw data, background, components, envelope, residual.

Major components carry a draggable centre line; releasing it emits
``centerDragged(label, energy)`` so the main window can refit.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core.fitting import FitResult
from ..core.spectrum import Spectrum
from .theme import GRID, INK, INK_SECONDARY, MUTED, SERIES_DARK


def _rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


class SpectrumPlot(QWidget):
    centerDragged = Signal(str, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = pg.GraphicsLayoutWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.main = self.view.addPlot(row=0, col=0)
        self.resid = self.view.addPlot(row=1, col=0)
        self.view.ci.layout.setRowStretchFactor(0, 4)
        self.view.ci.layout.setRowStretchFactor(1, 1)
        for p in (self.main, self.resid):
            p.invertX(True)
            p.showGrid(x=True, y=True, alpha=0.15)
            p.getAxis("left").setPen(pg.mkPen(GRID))
            p.getAxis("bottom").setPen(pg.mkPen(GRID))
            p.getAxis("left").setTextPen(pg.mkPen(INK_SECONDARY))
            p.getAxis("bottom").setTextPen(pg.mkPen(INK_SECONDARY))
        self.resid.setXLink(self.main)
        self.main.setLabel("left", "Intensity")
        self.resid.setLabel("left", "Residual")
        self.resid.setLabel("bottom", "Binding energy (eV)")
        self.main.getAxis("bottom").setStyle(showValues=False)
        # Legend outside the data area (own column, both rows) so it never hides a peak.
        self.legend = pg.LegendItem(labelTextColor=INK_SECONDARY, brush=pg.mkBrush(19, 19, 18, 0))
        self.view.addItem(self.legend, row=0, col=1, rowspan=2)
        self.view.ci.layout.setColumnFixedWidth(1, 200)
        self.main.legend = self.legend
        self.title_item = pg.TextItem("", color=INK_SECONDARY, anchor=(0, 1))
        self._lines: dict[str, pg.InfiniteLine] = {}
        self._spectrum: Spectrum | None = None

    # ------------------------------------------------------------------ helpers
    def _reset(self) -> None:
        self.main.clear()
        self.resid.clear()
        self.legend.clear()
        self._lines.clear()

    def show_spectrum(self, spectrum: Spectrum, title: str = "") -> None:
        self._reset()
        self._spectrum = spectrum
        self._draw_raw(spectrum.energy, spectrum.intensity)
        self.main.setTitle(title, color=INK_SECONDARY, size="11pt")
        self.main.setLabel("left", f"Intensity ({spectrum.intensity_unit})")
        self._fit_view(spectrum.energy)

    def _draw_raw(self, x: np.ndarray, y: np.ndarray) -> None:
        self.main.plot(
            x,
            y,
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolPen=pg.mkPen(MUTED, width=0.8),
            symbolBrush=None,
            name="Raw",
        )

    def show_result(self, result: FitResult, title: str = "", draggable: bool = True) -> None:
        self._reset()
        x = result.x
        bg = result.background_total
        self._draw_raw(x, result.y)
        bg_label = "Background"
        if result.settings.refine_linear_background:
            bg_label += f" ({result.background.spec.type} + linear)"
        else:
            bg_label += f" ({result.background.spec.type})"
        bg_curve = self.main.plot(
            x, bg, pen=pg.mkPen(MUTED, width=1, style=Qt.PenStyle.DashLine), name=bg_label
        )
        majors = result.majors()
        order = sorted(range(len(majors)), key=lambda j: -majors[j].center)
        slot = {majors[j].parent: k for k, j in enumerate(order)}
        for comp in result.components:
            if comp.values is None:
                continue
            idx = next(j for j, m in enumerate(majors) if m.parent == comp.parent)
            color = SERIES_DARK[idx % len(SERIES_DARK)]
            y = comp.values + bg
            if comp.is_minor:
                self.main.plot(x, y, pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DotLine))
                continue
            curve = self.main.plot(x, y, pen=pg.mkPen(color, width=1.5), name=comp.label)
            fill = pg.FillBetweenItem(bg_curve, curve, brush=pg.mkBrush(*_rgba(color, 45)))
            self.main.addItem(fill)
            if draggable:
                line = pg.InfiniteLine(
                    pos=comp.center,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashDotLine),
                    hoverPen=pg.mkPen(color, width=2),
                    label=f"{comp.label}\n{{value:.2f}} eV",
                    labelOpts={
                        "position": 0.95 - 0.08 * (slot[comp.parent] % 5),
                        "color": color,
                        "fill": (20, 20, 19, 190),
                    },
                )
                line.setBounds((float(x[0]), float(x[-1])))
                line.sigPositionChangeFinished.connect(
                    lambda ln=line, lab=comp.parent: self.centerDragged.emit(lab, float(ln.value()))
                )
                self.main.addItem(line)
                self._lines[comp.parent] = line
        self.main.plot(x, result.model, pen=pg.mkPen(INK, width=2), name="Envelope")

        if result.sigma is not None:
            upper = self.resid.plot(x, result.sigma, pen=None)
            lower = self.resid.plot(x, -result.sigma, pen=None)
            self.resid.addItem(
                pg.FillBetweenItem(lower, upper, brush=pg.mkBrush(*_rgba(GRID, 160)))
            )
        self.resid.addLine(y=0, pen=pg.mkPen(MUTED, width=0.8))
        self.resid.plot(x, result.residual, pen=pg.mkPen(INK_SECONDARY, width=1))
        self.main.setTitle(title, color=INK_SECONDARY, size="11pt")
        self._fit_view(x)

    def _fit_view(self, x: np.ndarray) -> None:
        """Fix the x range from the data and auto-scale y; pyqtgraph's deferred
        auto-range otherwise alternates with the empty range left by ``clear()``."""
        lo, hi = float(np.min(x)), float(np.max(x))
        for p in (self.main, self.resid):
            vb = p.getViewBox()
            vb.autoRange(padding=0.04)
            vb.setXRange(lo, hi, padding=0.02)

    def line_positions(self) -> dict[str, float]:
        return {label: float(line.value()) for label, line in self._lines.items()}

    def export_png(self, path: str) -> None:
        from pyqtgraph.exporters import ImageExporter

        exporter = ImageExporter(self.view.scene())
        exporter.export(path)
