"""Live spectrum view: raw data, background, components, envelope, residual.

Major components carry a draggable centre line; releasing it emits
``centerDragged(label, energy)`` so the main window can refit.  The look comes from a
:class:`~xps_autofit.gui.theme.PlotStyle` (publication "origin" style or the
theme-following "instrument" style) and can be changed while a fit is shown.
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..core.fitting import FitResult
from ..core.spectrum import Spectrum
from .theme import RGBA, PlotStyle, plot_style, rgba

_AXES = ("left", "bottom", "top", "right")


def _qcolor(color: RGBA) -> QColor:
    """Colours go to pyqtgraph as QColor / QBrush, never as tuples.

    ``pyqtgraph.mkColor`` sends a tuple through ``numpy.issubdtype(tuple, ...)``, and
    ``numpy.dtype(tuple)`` (numpy 2.2-2.4) leaks a reference to ``None`` on every
    call; redraws do that thousands of times.  A QColor takes the early exit.
    """
    return QColor(*color)


def _brush(color: RGBA) -> QBrush:
    return QBrush(_qcolor(color))


@dataclass(frozen=True)
class PlotOptions:
    """User adjustments on top of a :class:`PlotStyle` (View > Plot options…).

    Empty strings, zeros and ``-1`` mean "as the style decides"; ranges of ``None``
    mean automatic.
    """

    title: str = ""
    x_label: str = ""
    y_label: str = ""
    tick_font_pt: int = 0
    label_font_pt: int = 0
    symbol_size: int = 0
    envelope_width: float = 0.0
    fill_alpha: int = -1
    """Component fill opacity in percent (0-100), -1 for the style's value."""
    show_legend: bool = True
    show_fills: bool = True
    show_center_labels: bool = True
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["x_range"] = list(self.x_range) if self.x_range else None
        d["y_range"] = list(self.y_range) if self.y_range else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PlotOptions:
        if not d:
            return cls()
        xr, yr = d.get("x_range"), d.get("y_range")
        return cls(
            title=str(d.get("title", "")),
            x_label=str(d.get("x_label", "")),
            y_label=str(d.get("y_label", "")),
            tick_font_pt=int(d.get("tick_font_pt", 0)),
            label_font_pt=int(d.get("label_font_pt", 0)),
            symbol_size=int(d.get("symbol_size", 0)),
            envelope_width=float(d.get("envelope_width", 0.0)),
            fill_alpha=int(d.get("fill_alpha", -1)),
            show_legend=bool(d.get("show_legend", True)),
            show_fills=bool(d.get("show_fills", True)),
            show_center_labels=bool(d.get("show_center_labels", True)),
            x_range=(float(xr[0]), float(xr[1])) if xr else None,
            y_range=(float(yr[0]), float(yr[1])) if yr else None,
        )

    def applied_to(self, style: PlotStyle) -> PlotStyle:
        """The style with this object's size overrides."""
        return replace(
            style,
            tick_font_pt=self.tick_font_pt or style.tick_font_pt,
            label_font_pt=self.label_font_pt or style.label_font_pt,
            symbol_size=self.symbol_size or style.symbol_size,
            envelope_width=self.envelope_width or style.envelope_width,
            fill_alpha=round(self.fill_alpha * 2.55) if self.fill_alpha >= 0 else style.fill_alpha,
        )


def background_label(result: FitResult) -> str:
    """``Background (shirley, active + linear)``-style legend text."""
    bg = result.background
    text = bg.spec.type
    if bg.info.get("mode") == "active":
        text += ", active"
    if result.settings.refine_linear_background:
        text += " + linear"
    return f"Background ({text})"


class SpectrumPlot(QWidget):
    centerDragged = Signal(str, float)
    cursorMoved = Signal(float, float)
    """Mouse position in data coordinates: (binding energy, intensity)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        style: PlotStyle | None = None,
        options: PlotOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self.look: PlotStyle = style or plot_style()
        """The active :class:`PlotStyle` (``style`` would shadow ``QWidget.style()``)."""
        self.options: PlotOptions = options or PlotOptions()
        self._eff: PlotStyle = self.options.applied_to(self.look)
        """``look`` with the options' size overrides; what the drawing code reads."""
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
        self.resid.setXLink(self.main)
        self.main.getAxis("bottom").setStyle(showValues=False)
        self._labels: dict[tuple[str, str], str] = {
            ("main", "left"): "Intensity",
            ("resid", "left"): "Residual",
            ("resid", "bottom"): "Binding energy (eV)",
        }
        self._title = ""
        # Legend outside the data area (own column, both rows) so it never hides a peak.
        self.legend = pg.LegendItem()
        self.view.addItem(self.legend, row=0, col=1, rowspan=2)
        self.view.ci.layout.setColumnFixedWidth(1, 200)
        # Keep the legend compact at the top of its column instead of letting the
        # grid layout stretch it over both rows.
        self.legend.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.view.ci.layout.setAlignment(
            self.legend, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.main.legend = self.legend
        self._lines: dict[str, pg.InfiniteLine] = {}
        self._marks: list[pg.InfiniteLine] = []
        self._mark_spec: list[tuple[str, float]] = []
        self._spectrum: Spectrum | None = None
        self._view_x: np.ndarray | None = None
        """Energy axis of the comparison view (``None`` outside it)."""
        self._last: tuple[str, tuple[Any, ...], dict[str, Any]] | None = None
        """The last ``show_*`` call, replayed when the style changes."""
        # Crosshair: a thin vertical hairline that follows the mouse in both panels.
        self._cross_main = pg.InfiniteLine(angle=90, movable=False)
        self._cross_resid = pg.InfiniteLine(angle=90, movable=False)
        for item in (self._cross_main, self._cross_resid):
            item.setZValue(-10)
            item.hide()
        self._proxy = pg.SignalProxy(
            self.main.scene().sigMouseMoved, rateLimit=40, slot=self._mouse_moved
        )
        self._apply_style()

    # ------------------------------------------------------------------- style
    def set_style(self, style: PlotStyle) -> None:
        """Switch the look and redraw whatever is shown."""
        self.look = style
        self._apply_style()
        self._replay()

    def set_options(self, options: PlotOptions) -> None:
        """Apply user adjustments (title, labels, sizes, legend, fills, ranges)."""
        self.options = options
        self._apply_style()
        self._replay()

    def _replay(self) -> None:
        if self._last is not None:
            method, args, kwargs = self._last
            marks = list(self._mark_spec)
            title = self._title  # may have been renamed after the last show_* call
            getattr(self, method)(*args, **kwargs)
            if marks:
                self.mark_lines(marks)
            self.set_title(title)

    def _apply_style(self) -> None:
        self._eff = self.options.applied_to(self.look)
        s = self._eff
        self.view.setBackground(s.canvas)
        font: QFont | None = None
        if s.font_family or s.tick_font_pt:
            font = QFont(s.font_family) if s.font_family else QFont()
            if s.tick_font_pt:
                font.setPointSize(s.tick_font_pt)
        for p in (self.main, self.resid):
            for name in _AXES:
                ax = p.getAxis(name)
                ax.setPen(pg.mkPen(s.frame, width=1))
                ax.setTextPen(pg.mkPen(s.text))
                ax.setTickFont(font)
                ax.setStyle(tickLength=-6 if s.ticks_inward else 5, tickTextOffset=6)
            if s.box:
                p.showAxis("top")
                p.showAxis("right")
                p.getAxis("top").setStyle(showValues=False)
                p.getAxis("right").setStyle(showValues=False)
            else:
                p.hideAxis("top")
                p.hideAxis("right")
            p.showGrid(x=s.grid, y=s.grid, alpha=0.15)
        for (which, axis), text in self._labels.items():
            self._set_label(which, axis, text)
        self.legend.setLabelTextColor(s.text)
        self.legend.setPen(pg.mkPen(s.legend_pen) if s.legend_pen else pg.mkPen(None))
        self.legend.setBrush(_brush(s.legend_fill))
        self.legend.setVisible(self.options.show_legend)
        self.view.ci.layout.setColumnFixedWidth(1, 200 if self.options.show_legend else 0)
        for item in (self._cross_main, self._cross_resid):
            item.setPen(pg.mkPen(s.crosshair, width=1))
        self.set_title(self._title)

    def _set_label(self, which: str, axis: str, text: str) -> None:
        """Set an axis label; the options' x / y labels override the automatic text."""
        self._labels[(which, axis)] = text
        s = self._eff
        o = self.options
        if which == "main" and axis == "left" and o.y_label:
            text = o.y_label
        elif which == "resid" and axis == "bottom" and o.x_label:
            text = o.x_label
        plot = self.main if which == "main" else self.resid
        extra: dict[str, str] = {"color": s.text}
        if s.font_family:
            extra["font-family"] = s.font_family
        if s.label_font_pt:
            extra["font-size"] = f"{s.label_font_pt}pt"
        plot.setLabel(axis, text, **extra)

    def _series_color(self, index: int) -> str:
        return self._eff.series[index % len(self._eff.series)]

    # ------------------------------------------------------------------ helpers
    def _line_released(self, line: pg.InfiniteLine) -> None:
        label = getattr(line, "xps_component", None)
        if label is not None:
            self.centerDragged.emit(str(label), float(line.value()))

    def _reset(self) -> None:
        for line in self._lines.values():
            with contextlib.suppress(RuntimeError, TypeError):  # already disconnected
                line.sigPositionChangeFinished.disconnect(self._line_released)
        self.main.clear()
        self.resid.clear()
        self.legend.clear()
        self._lines.clear()
        self._marks = []
        self._mark_spec = []
        self.main.addItem(self._cross_main, ignoreBounds=True)
        self.resid.addItem(self._cross_resid, ignoreBounds=True)

    def _mouse_moved(self, event: tuple) -> None:
        pos = event[0]
        vb = self.main.getViewBox()
        if not self.main.sceneBoundingRect().contains(pos):
            self._cross_main.hide()
            self._cross_resid.hide()
            return
        point = vb.mapSceneToView(pos)
        x = float(point.x())
        self._cross_main.setPos(x)
        self._cross_resid.setPos(x)
        self._cross_main.show()
        self._cross_resid.show()
        self.cursorMoved.emit(x, float(point.y()))

    def reset_view(self) -> None:
        if self._view_x is not None:
            self._fit_view(self._view_x)
        elif self._spectrum is not None:
            self._fit_view(self._spectrum.energy)

    def show_overlay(
        self,
        entries: list[tuple[str, Spectrum]],
        normalise: str = "none",
        stack: float = 0.0,
        title: str = "",
    ) -> int:
        """Comparison view: several raw spectra on one axis.

        ``normalise`` is ``"none"``, ``"max"`` (divide by the maximum) or ``"area"``
        (divide by the integral); ``stack`` offsets successive spectra by that
        fraction of the largest range (a waterfall for sample series or depth
        profiles).  The residual panel is empty in this view.  Returns the number of
        curves drawn.
        """
        self._last = ("show_overlay", (entries, normalise, stack, title), {})
        self._reset()
        self._spectrum = None
        if not entries:
            self._view_x = None
            return 0
        ys: list[np.ndarray] = []
        for _title, spec in entries:
            y = np.asarray(spec.intensity, dtype=float)
            if normalise == "max" and np.max(y) > 0:
                y = y / np.max(y)
            elif normalise == "area":
                area = float(np.trapezoid(y, spec.energy))
                if area > 0:
                    y = y / area
            ys.append(y)
        span = max(float(np.ptp(y)) for y in ys) or 1.0
        for i, ((name, spec), y) in enumerate(zip(entries, ys)):
            color = self._series_color(i)
            self.main.plot(
                spec.energy, y + i * stack * span, pen=pg.mkPen(color, width=1.5), name=name
            )
        unit = {"max": "normalised to maximum", "area": "normalised to area"}.get(
            normalise, entries[0][1].intensity_unit
        )
        if stack:
            unit += ", offset"
        self._set_label("main", "left", f"Intensity ({unit})")
        self.set_title(title)
        self._view_x = np.concatenate([np.asarray(s.energy, dtype=float) for _n, s in entries])
        self._fit_view(self._view_x)
        return len(entries)

    def shutdown(self) -> None:
        """Disconnect the mouse proxy so no timer or scene signal outlives the widget.

        Qt objects that are still connected when the interpreter exits are released
        in an arbitrary order; doing it here keeps the shutdown deterministic.
        """
        proxy = getattr(self, "_proxy", None)
        if proxy is not None:
            with contextlib.suppress(RuntimeError, TypeError):  # already gone
                proxy.disconnect()
            self._proxy = None

    def show_spectrum(self, spectrum: Spectrum, title: str = "") -> None:
        self._last = ("show_spectrum", (spectrum, title), {})
        self._reset()
        self._view_x = None
        self._spectrum = spectrum
        self._draw_raw(spectrum.energy, spectrum.intensity)
        self.set_title(title)
        self._set_label("main", "left", f"Intensity ({spectrum.intensity_unit})")
        self._fit_view(spectrum.energy)

    def show_vb_edge(self, spectrum: Spectrum, edge: Any, title: str = "") -> None:
        """A valence-band spectrum with the baseline and leading-edge lines of a
        :class:`~xps_autofit.automation.valence_band.VBEdge` and the VBM marked."""
        self._last = ("show_vb_edge", (spectrum, edge, title), {})
        self._reset()
        self._view_x = None
        self._spectrum = spectrum
        self._draw_raw(spectrum.energy, spectrum.intensity)
        xb = np.linspace(min(edge.baseline.lo, edge.vbm - 0.5), edge.vbm + 0.8, 60)
        xe = np.linspace(edge.vbm - 0.1, edge.edge.hi + 0.6, 60)
        self.main.plot(
            xb, edge.baseline(xb), pen=pg.mkPen(self._series_color(1), width=2), name="Baseline"
        )
        self.main.plot(
            xe, edge.edge(xe), pen=pg.mkPen(self._series_color(0), width=2), name="Leading edge"
        )
        marker = pg.InfiniteLine(
            pos=edge.vbm,
            angle=90,
            movable=False,
            pen=pg.mkPen(self._eff.text, width=1, style=Qt.PenStyle.DashLine),
            label=f"VBM {edge.vbm:.2f} eV",  # the error is in the log and the status bar
            labelOpts={
                "position": 0.5,
                "color": self._eff.text,
                "fill": _qcolor(self._eff.label_fill),
                "anchors": [(0, 0.5), (1, 0.5)],
            },
        )
        self.main.addItem(marker, ignoreBounds=True)
        self.set_title(title)
        self._set_label("main", "left", f"Intensity ({spectrum.intensity_unit})")
        self._fit_view(spectrum.energy)

    def _draw_raw(self, x: np.ndarray, y: np.ndarray) -> None:
        s = self._eff
        self.main.plot(
            x,
            y,
            pen=None,
            symbol="o",
            symbolSize=s.symbol_size,
            symbolPen=pg.mkPen(s.raw, width=1.0),
            symbolBrush=None,
            name="Raw",
        )

    def show_result(self, result: FitResult, title: str = "", draggable: bool = True) -> None:
        self._last = ("show_result", (result, title, draggable), {})
        self._reset()
        self._view_x = None
        s = self._eff
        x = result.x
        bg = result.background_total
        self._spectrum = Spectrum(x, result.y)
        self._draw_raw(x, result.y)
        bg_curve = self.main.plot(
            x,
            bg,
            pen=pg.mkPen(s.background, width=1, style=Qt.PenStyle.DashLine),
            name=background_label(result),
        )
        majors = result.majors()
        order = sorted(range(len(majors)), key=lambda j: -majors[j].center)
        slot = {majors[j].parent: k for k, j in enumerate(order)}
        for comp in result.components:
            if comp.values is None:
                continue
            idx = next(j for j, m in enumerate(majors) if m.parent == comp.parent)
            color = self._series_color(idx)
            y = comp.values + bg
            if comp.is_minor:
                self.main.plot(x, y, pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DotLine))
                continue
            curve = self.main.plot(x, y, pen=pg.mkPen(color, width=1.5), name=comp.label)
            if self.options.show_fills:
                fill = pg.FillBetweenItem(bg_curve, curve, brush=_brush(rgba(color, s.fill_alpha)))
                self.main.addItem(fill)
            if draggable:
                line = pg.InfiniteLine(
                    pos=comp.center,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashDotLine),
                    hoverPen=pg.mkPen(color, width=2),
                    label=(
                        f"{comp.label}\n{{value:.2f}} eV"
                        if self.options.show_center_labels
                        else None
                    ),
                    labelOpts={
                        "position": 0.95 - 0.08 * (slot[comp.parent] % 5),
                        "color": color,
                        "fill": _qcolor(s.label_fill),
                        # The x axis is inverted (binding energy): swap the default
                        # anchors so the label still sits on the side facing the
                        # centre of the view instead of running off the edge.
                        "anchors": [(1, 0.5), (0, 0.5)],
                    },
                )
                line.setBounds((float(x[0]), float(x[-1])))
                # A bound method, not a lambda holding the line: the lambda made a
                # cycle through the C++ connection that the garbage collector cannot
                # see, so every redraw leaked its centre lines and their labels.
                line.xps_component = comp.parent
                line.sigPositionChangeFinished.connect(self._line_released)
                self.main.addItem(line)
                self._lines[comp.parent] = line
        self.main.plot(
            x, result.model, pen=pg.mkPen(s.envelope, width=s.envelope_width), name="Envelope"
        )

        if result.sigma is not None:
            upper = self.resid.plot(x, result.sigma, pen=None)
            lower = self.resid.plot(x, -result.sigma, pen=None)
            self.resid.addItem(pg.FillBetweenItem(lower, upper, brush=_brush(s.sigma_fill)))
        self.resid.addLine(y=0, pen=pg.mkPen(s.background, width=0.8))
        self.resid.plot(x, result.residual, pen=pg.mkPen(s.residual, width=1))
        self.set_title(title)
        self._fit_view(x)

    def set_title(self, title: str) -> None:
        """Change the plot title without redrawing (after a rename); the options'
        title, when set, is shown instead."""
        self._title = title
        shown = self.options.title or title
        self.main.setTitle(shown, color=self._eff.text, size="11pt")

    def _fit_view(self, x: np.ndarray) -> None:
        """Fix the x range from the data and auto-scale y; pyqtgraph's deferred
        auto-range otherwise alternates with the empty range left by ``clear()``.
        Ranges given in the options replace the automatic ones."""
        lo, hi = float(np.min(x)), float(np.max(x))
        for p in (self.main, self.resid):
            vb = p.getViewBox()
            vb.autoRange(padding=0.04)
            vb.setXRange(lo, hi, padding=0.02)
        o = self.options
        if o.x_range is not None:
            # Linked views with different axis widths differ slightly; the one set
            # last is exact, so the main plot goes last.
            for p in (self.resid, self.main):
                p.getViewBox().setXRange(*o.x_range, padding=0.0)
        if o.y_range is not None:
            self.main.getViewBox().setYRange(*o.y_range, padding=0.0)

    def line_positions(self) -> dict[str, float]:
        return {label: float(line.value()) for label, line in self._lines.items()}

    def mark_lines(self, marks: list[tuple[str, float]], color: str | None = None) -> None:
        """Label fixed energies on the spectrum (identified element lines)."""
        for item in self._marks:
            self.main.removeItem(item)
        self._marks = []
        self._mark_spec = list(marks)
        pen_color = color or self._eff.text
        for i, (label, energy) in enumerate(marks):
            line = pg.InfiniteLine(
                pos=energy,
                angle=90,
                movable=False,
                pen=pg.mkPen(pen_color, width=1, style=Qt.PenStyle.DotLine),
                label=label,
                labelOpts={
                    "position": 0.92 - 0.06 * (i % 8),
                    "color": pen_color,
                    "fill": _qcolor(self._eff.label_fill),
                    "anchors": [(1, 0.5), (0, 0.5)],
                },
            )
            line.setZValue(-5)
            self.main.addItem(line, ignoreBounds=True)
            self._marks.append(line)

    def export_png(self, path: str) -> None:
        from pyqtgraph.exporters import ImageExporter

        exporter = ImageExporter(self.view.scene())
        exporter.export(path)
