"""Publication-style fit figures (PNG / SVG / PDF via Matplotlib).

Binding energy increases to the left, as is conventional for XPS.  Two figure styles
exist: ``"origin"`` (default) draws the graph the way OriginLab does: white canvas, a
black frame on all four sides with inward ticks, Arial-type labels, no grid, open
black data symbols, a red envelope and a boxed legend, matching the desktop
application's Origin-style plot; ``"classic"`` is the earlier look with a soft grid
and open left/bottom axes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import AutoMinorLocator  # noqa: E402

from ..core.fitting import FitResult  # noqa: E402

if TYPE_CHECKING:
    from ..automation.valence_band import VBEdge
    from ..core.spectrum import Spectrum

# Colour-vision-safe categorical order; components take slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

FIGURE_STYLES = ("origin", "classic")
DEFAULT_FIGURE_STYLE = "origin"
# Arial where it exists (Windows, macOS, Office installs), metric-compatible
# Liberation Sans on Linux, DejaVu Sans as the last resort so no font warning is
# raised.
ORIGIN_FONTS = ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]

ORIGIN_RC: dict[str, Any] = {
    "font.family": "sans-serif",
    "font.sans-serif": ORIGIN_FONTS,
    "mathtext.fontset": "dejavusans",
    "axes.linewidth": 0.8,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.top": True,
    "ytick.right": True,
    "xtick.minor.visible": True,
    "ytick.minor.visible": True,
    "xtick.major.size": 4.0,
    "ytick.major.size": 4.0,
    "xtick.minor.size": 2.0,
    "ytick.minor.size": 2.0,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "legend.frameon": True,
    "legend.fancybox": False,
    "legend.edgecolor": "black",
    "legend.framealpha": 1.0,
}


@dataclass(frozen=True)
class _Look:
    surface: str
    raw: str
    background: str
    envelope: str
    residual: str
    sigma: str
    text: str
    fill_alpha: float


_ORIGIN = _Look(
    surface="#ffffff",
    raw="#000000",
    background="#7f7f7f",
    envelope="#d62728",
    residual="#000000",
    sigma="#d9d9d9",
    text="#000000",
    fill_alpha=0.25,
)
_CLASSIC = _Look(
    surface=SURFACE,
    raw=MUTED,
    background=MUTED,
    envelope=INK,
    residual=INK_SECONDARY,
    sigma=GRID,
    text=INK_SECONDARY,
    fill_alpha=0.18,
)


@lru_cache(maxsize=1)
def origin_font_family() -> str:
    """The first of :data:`ORIGIN_FONTS` installed here (``DejaVu Sans`` at worst).

    Resolved once so that artists can be given a single existing family: a list on
    an artist makes Matplotlib log a warning for every family it skips.
    """
    for name in ORIGIN_FONTS:
        try:
            fm.findfont(fm.FontProperties(family=name), fallback_to_default=False)
        except ValueError:
            continue
        return name
    return "DejaVu Sans"


def _rc(style: str) -> Any:
    """rcParams overrides for a style (typed loosely: Matplotlib's keys are literals)."""
    if style != "origin":
        return {}
    return {**ORIGIN_RC, "font.sans-serif": [origin_font_family(), *ORIGIN_FONTS]}


def _check_style(style: str) -> str:
    if style not in FIGURE_STYLES:
        raise ValueError(f"figure style must be one of {FIGURE_STYLES}, got {style!r}")
    return style


def _style_axes(ax: Any, style: str, surface: str) -> None:
    ax.set_facecolor(surface)
    if style == "origin":
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("black")
            spine.set_linewidth(0.8)
        ax.tick_params(which="both", direction="in", top=True, right=True, colors="black")
        ax.tick_params(which="major", labelsize=9, length=4, width=0.8)
        ax.tick_params(which="minor", length=2, width=0.6)
        ax.minorticks_on()
        ax.grid(False)
    else:
        ax.grid(True, color=GRID, linewidth=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=INK_SECONDARY, labelsize=8)


def plot_fit(
    result: FitResult,
    path: str | Path | None = None,
    title: str = "",
    dpi: int = 200,
    figsize: tuple[float, float] = (6.4, 5.4),
    show_background: bool = True,
    annotate: bool = True,
    style: str = DEFAULT_FIGURE_STYLE,
) -> Figure:
    """Draw raw data, background, components, envelope and residual.

    ``style`` is ``"origin"`` (publication look, default) or ``"classic"``.
    """
    _check_style(style)
    with plt.rc_context(_rc(style)):
        return _plot_fit(result, path, title, dpi, figsize, show_background, annotate, style)


def _plot_fit(
    result: FitResult,
    path: str | Path | None,
    title: str,
    dpi: int,
    figsize: tuple[float, float],
    show_background: bool,
    annotate: bool,
    style: str,
) -> Figure:
    look = _ORIGIN if style == "origin" else _CLASSIC
    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=figsize, sharex=True, gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05}
    )
    fig.patch.set_facecolor(look.surface)
    draw_fit(fig, ax, axr, result, title, show_background, annotate, style)
    if path is not None:
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=look.surface)
        plt.close(fig)
    return fig


def draw_fit(
    fig: Figure,
    ax: Any,
    axr: Any,
    result: FitResult,
    title: str = "",
    show_background: bool = True,
    annotate: bool = True,
    style: str = DEFAULT_FIGURE_STYLE,
) -> None:
    """Draw a fit into existing axes (``ax`` data, ``axr`` residual, sharing x)."""
    look = _ORIGIN if style == "origin" else _CLASSIC
    # Fonts are set on the artists too, not only through rcParams: a figure returned
    # without saving is drawn after the rc context has ended.
    family = origin_font_family() if style == "origin" else None
    font: dict[str, Any] = {"fontfamily": family} if family else {}
    for a in (ax, axr):
        _style_axes(a, style, look.surface)
        if family:
            a.tick_params(labelfontfamily=family)

    x = result.x
    bg = result.background_total
    ax.plot(
        x,
        result.y,
        "o",
        ms=3.0 if style == "origin" else 2.5,
        mfc="none",
        mec=look.raw,
        mew=0.7,
        label="Raw",
        zorder=2,
    )
    if show_background and (
        result.background.spec.type != "none" or result.settings.refine_linear_background
    ):
        label = f"Background ({result.background.spec.type}"
        label += " + linear)" if result.settings.refine_linear_background else ")"
        ax.plot(x, bg, "--", color=look.background, lw=1.0, label=label, zorder=3)

    majors = result.majors()
    for c in result.components:
        parent_index = next(j for j, m in enumerate(majors) if m.parent == c.parent)
        color = SERIES[parent_index % len(SERIES)]
        if c.values is None:
            continue
        y = c.values + bg
        if c.is_minor:
            ax.plot(x, y, color=color, lw=1.0, ls=":", zorder=4)
        else:
            ax.fill_between(x, bg, y, color=color, alpha=look.fill_alpha, lw=0, zorder=3)
            ax.plot(x, y, color=color, lw=1.2, label=c.label, zorder=4)
            if annotate:
                ax.annotate(
                    f"{c.center:.2f}",
                    (c.center, c.height + bg[int(np.argmin(np.abs(x - c.center)))]),
                    textcoords="offset points",
                    xytext=(0, 4),
                    ha="center",
                    fontsize=7,
                    color=look.text,
                    **font,
                )
    ax.plot(x, result.model, color=look.envelope, lw=1.4, label="Envelope", zorder=5)
    ax.set_ylabel(f"Intensity ({_unit_label(result)})", fontsize=9, color=look.text, **font)
    legend_kwargs: dict[str, Any] = {"loc": "upper left"}
    if style == "origin":
        legend_kwargs.update(
            frameon=True,
            edgecolor="black",
            framealpha=1.0,
            fancybox=False,
            prop={"family": family, "size": 7},
        )
    else:
        legend_kwargs.update(frameon=False, fontsize=7)
    ax.legend(**legend_kwargs)
    if title:
        ax.set_title(title, fontsize=10, color=look.text, loc="left", **font)
    stats = result.stats
    ax.text(
        0.99,
        0.98,
        f"reduced chi-sq = {stats.redchi:.3g}\nAICc = {stats.aicc:.1f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=7,
        color=look.text,
        **font,
    )

    axr.axhline(0, color=look.background, lw=0.8)
    if result.sigma is not None:
        axr.fill_between(x, -result.sigma, result.sigma, color=look.sigma, lw=0, label="±1σ")
    axr.plot(x, result.residual, color=look.residual, lw=0.9)
    axr.set_ylabel("Residual", fontsize=8, color=look.text, **font)
    axr.set_xlabel("Binding energy (eV)", fontsize=9, color=look.text, **font)
    axr.invert_xaxis()
    fig.align_ylabels([ax, axr])


def _unit_label(result: FitResult) -> str:
    return "counts" if result.stats.weighted else "a.u."


def plot_candidates(
    selection: Any,
    path: str | Path | None = None,
    dpi: int = 150,
    style: str = DEFAULT_FIGURE_STYLE,
) -> Figure:
    """Information criterion versus component count."""
    _check_style(style)
    look = _ORIGIN if style == "origin" else _CLASSIC
    with plt.rc_context(_rc(style)):
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        fig.patch.set_facecolor(look.surface)
        _style_axes(ax, style, look.surface)
        ns = [c.n_components for c in selection.candidates]
        vals = [c.criterion_value for c in selection.candidates]
        ok = [c.physical_ok for c in selection.candidates]
        ax.plot(ns, vals, "-", color=look.background, lw=1)
        for n, v, good in zip(ns, vals, ok):
            ax.plot(n, v, "o", color=SERIES[0] if good else SERIES[7], ms=6)
        if selection.best is not None:
            ax.plot(
                selection.best.n_components,
                selection.best.criterion_value,
                "o",
                mfc="none",
                mec=look.text,
                ms=11,
                mew=1.2,
            )
        ax.set_xlabel("Number of components", fontsize=9)
        ax.set_ylabel(
            selection.candidates[0].criterion.upper() if selection.candidates else "criterion",
            fontsize=9,
        )
        ax.set_xticks(ns)
        if style == "origin":
            ax.minorticks_off()
        if path is not None:
            fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=look.surface)
            plt.close(fig)
        return fig


def plot_series(
    frame: Any,
    path: str | Path | None = None,
    title: str = "",
    dpi: int = 200,
    style: str = DEFAULT_FIGURE_STYLE,
) -> Figure:
    """Atomic percent of every element against the sample order (a depth profile or a
    series), from :func:`xps_autofit.automation.series.composition_series`."""
    from ..automation.series import series_elements

    _check_style(style)
    look = _ORIGIN if style == "origin" else _CLASSIC
    family = origin_font_family() if style == "origin" else None
    font: dict[str, Any] = {"fontfamily": family} if family else {}
    with plt.rc_context(_rc(style)):
        n = len(frame.index)
        fig, ax = plt.subplots(figsize=(max(4.8, 0.55 * n + 2.5), 3.8))
        fig.patch.set_facecolor(look.surface)
        _style_axes(ax, style, look.surface)
        if family:
            ax.tick_params(labelfontfamily=family)
        x = frame["index"].to_numpy(dtype=float)
        for k, el in enumerate(series_elements(frame)):
            y = frame[f"{el} at%"].to_numpy(dtype=float)
            err = frame[f"{el} err"].to_numpy(dtype=float) if f"{el} err" in frame else None
            color = SERIES[k % len(SERIES)]
            ax.errorbar(
                x,
                y,
                yerr=err,
                color=color,
                marker="o",
                ms=5,
                mfc="white" if style == "origin" else color,
                lw=1.2,
                capsize=2.5,
                label=el,
            )
        ax.set_xticks(x)
        labels = [str(s) for s in frame["sample"]]
        rotate = max((len(s) for s in labels), default=0) * n > 60
        ax.set_xticklabels(labels, rotation=45 if rotate else 0, ha="right" if rotate else "center")
        ax.set_xlabel("Sample", fontsize=9, color=look.text, **font)
        ax.set_ylabel("Atomic concentration (%)", fontsize=9, color=look.text, **font)
        ax.set_ylim(bottom=0)
        if style == "origin":
            ax.minorticks_off()
            ax.tick_params(axis="y", which="minor", left=True, right=True)
            ax.yaxis.set_minor_locator(AutoMinorLocator())
        legend_kwargs: dict[str, Any] = {"loc": "best"}
        if style == "origin":
            legend_kwargs.update(
                frameon=True, edgecolor="black", fancybox=False, prop={"family": family, "size": 8}
            )
        else:
            legend_kwargs.update(frameon=False, fontsize=8)
        ax.legend(**legend_kwargs)
        if title:
            ax.set_title(title, fontsize=10, color=look.text, loc="left", **font)
        fig.tight_layout()
        if path is not None:
            fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=look.surface)
            plt.close(fig)
        return fig


def plot_vb_edge(
    spectrum: Spectrum,
    edge: VBEdge,
    path: str | Path | None = None,
    title: str = "",
    dpi: int = 200,
    style: str = DEFAULT_FIGURE_STYLE,
) -> Figure:
    """A valence-band spectrum with the edge and baseline lines of
    :func:`xps_autofit.automation.valence_band.find_vb_edge` and the VBM marked."""
    _check_style(style)
    look = _ORIGIN if style == "origin" else _CLASSIC
    with plt.rc_context(_rc(style)):
        fig, ax = plt.subplots(figsize=(5.2, 3.8))
        draw_vb_edge(fig, ax, spectrum, edge, title, style)
        fig.tight_layout()
        if path is not None:
            fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=look.surface)
            plt.close(fig)
        return fig


def draw_vb_edge(
    fig: Figure,
    ax: Any,
    spectrum: Spectrum,
    edge: VBEdge,
    title: str = "",
    style: str = DEFAULT_FIGURE_STYLE,
) -> None:
    """Draw the valence-band figure into ``ax`` (used by :func:`plot_vb_edge` and the
    PDF report)."""
    _check_style(style)
    look = _ORIGIN if style == "origin" else _CLASSIC
    family = origin_font_family() if style == "origin" else None
    font: dict[str, Any] = {"fontfamily": family} if family else {}
    x = np.asarray(spectrum.energy, dtype=float)
    y = np.asarray(spectrum.intensity, dtype=float)
    fig.patch.set_facecolor(look.surface)
    _style_axes(ax, style, look.surface)
    if family:
        ax.tick_params(labelfontfamily=family)
    ax.plot(
        x,
        y,
        "o",
        ms=2.6,
        mfc="none" if style == "origin" else look.raw,
        mec=look.raw,
        mew=0.6,
        label="Raw",
    )
    lo = min(edge.baseline.lo, edge.vbm) - 0.3
    hi = edge.edge.hi + 0.6
    xb = np.linspace(min(edge.baseline.lo, lo), edge.vbm + 0.8, 50)
    xe = np.linspace(edge.vbm - 0.1, hi, 50)
    ax.plot(xb, edge.baseline(xb), color=SERIES[1], lw=1.3, label="Baseline")
    ax.plot(xe, edge.edge(xe), color=SERIES[0], lw=1.3, label="Leading edge")
    err = f" ± {edge.vbm_err:.2f}" if edge.vbm_err is not None else ""
    ax.axvline(edge.vbm, color=look.text, lw=0.8, ls="--")
    ax.annotate(
        f"VBM {edge.vbm:.2f}{err} eV",
        (edge.vbm, float(edge.baseline(edge.vbm))),
        xytext=(8, 40),
        textcoords="offset points",
        fontsize=8,
        color=look.text,
        arrowprops={"arrowstyle": "-", "color": look.text, "lw": 0.6},
        **font,
    )
    ax.set_xlim(float(x.max()), float(x.min()))  # binding energy decreasing to the right
    span = float(np.max(y) - np.min(y))
    ax.set_ylim(float(np.min(y)) - 0.05 * span, float(np.max(y)) + 0.08 * span)
    ax.set_xlabel("Binding energy (eV)", fontsize=9, color=look.text, **font)
    unit = spectrum.intensity_unit or "counts"
    ax.set_ylabel(f"Intensity ({unit})", fontsize=9, color=look.text, **font)
    if style == "origin":
        ax.xaxis.set_minor_locator(AutoMinorLocator())
        ax.yaxis.set_minor_locator(AutoMinorLocator())
    legend_kwargs: dict[str, Any] = {"loc": "upper right"}
    if style == "origin":
        legend_kwargs.update(
            frameon=True, edgecolor="black", fancybox=False, prop={"family": family, "size": 8}
        )
    else:
        legend_kwargs.update(frameon=False, fontsize=8)
    ax.legend(**legend_kwargs)
    if title:
        ax.set_title(title, fontsize=10, color=look.text, loc="left", **font)
