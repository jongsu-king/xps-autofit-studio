"""Publication-style fit figures (PNG / SVG / PDF via Matplotlib).

Binding energy increases to the left, as is conventional for XPS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from ..core.fitting import FitResult  # noqa: E402

# Colour-vision-safe categorical order; components take slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"


def plot_fit(
    result: FitResult,
    path: str | Path | None = None,
    title: str = "",
    dpi: int = 200,
    figsize: tuple[float, float] = (6.4, 5.4),
    show_background: bool = True,
    annotate: bool = True,
) -> Figure:
    """Draw raw data, background, components, envelope and residual."""
    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=figsize, sharex=True, gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05}
    )
    fig.patch.set_facecolor(SURFACE)
    for a in (ax, axr):
        a.set_facecolor(SURFACE)
        a.grid(True, color=GRID, linewidth=0.6)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        a.tick_params(colors=INK_SECONDARY, labelsize=8)

    x = result.x
    bg = result.background_total
    ax.plot(x, result.y, "o", ms=2.5, mfc="none", mec=MUTED, mew=0.7, label="Raw", zorder=2)
    if show_background and (
        result.background.spec.type != "none" or result.settings.refine_linear_background
    ):
        label = f"Background ({result.background.spec.type}"
        label += " + linear)" if result.settings.refine_linear_background else ")"
        ax.plot(x, bg, "--", color=MUTED, lw=1.0, label=label, zorder=3)

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
            ax.fill_between(x, bg, y, color=color, alpha=0.18, lw=0, zorder=3)
            ax.plot(x, y, color=color, lw=1.2, label=c.label, zorder=4)
            if annotate:
                ax.annotate(
                    f"{c.center:.2f}",
                    (c.center, c.height + bg[int(np.argmin(np.abs(x - c.center)))]),
                    textcoords="offset points",
                    xytext=(0, 4),
                    ha="center",
                    fontsize=7,
                    color=INK_SECONDARY,
                )
    ax.plot(x, result.model, color=INK, lw=1.4, label="Envelope", zorder=5)
    ax.set_ylabel(f"Intensity ({_unit_label(result)})", fontsize=9, color=INK)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    if title:
        ax.set_title(title, fontsize=10, color=INK, loc="left")
    stats = result.stats
    ax.text(
        0.99,
        0.98,
        f"reduced chi-sq = {stats.redchi:.3g}\nAICc = {stats.aicc:.1f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=7,
        color=INK_SECONDARY,
    )

    axr.axhline(0, color=MUTED, lw=0.8)
    if result.sigma is not None:
        axr.fill_between(x, -result.sigma, result.sigma, color=GRID, lw=0, label="±1σ")
    axr.plot(x, result.residual, color=INK_SECONDARY, lw=0.9)
    axr.set_ylabel("Residual", fontsize=8, color=INK)
    axr.set_xlabel("Binding energy (eV)", fontsize=9, color=INK)
    axr.invert_xaxis()
    fig.align_ylabels([ax, axr])
    if path is not None:
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=SURFACE)
        plt.close(fig)
    return fig


def _unit_label(result: FitResult) -> str:
    return "counts" if result.stats.weighted else "a.u."


def plot_candidates(selection: Any, path: str | Path | None = None, dpi: int = 150) -> Figure:
    """Information criterion versus component count."""
    fig, ax = plt.subplots(figsize=(4.2, 2.8))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ns = [c.n_components for c in selection.candidates]
    vals = [c.criterion_value for c in selection.candidates]
    ok = [c.physical_ok for c in selection.candidates]
    ax.plot(ns, vals, "-", color=MUTED, lw=1)
    for n, v, good in zip(ns, vals, ok):
        ax.plot(n, v, "o", color=SERIES[0] if good else SERIES[7], ms=6)
    if selection.best is not None:
        ax.plot(
            selection.best.n_components,
            selection.best.criterion_value,
            "o",
            mfc="none",
            mec=INK,
            ms=11,
            mew=1.2,
        )
    ax.set_xlabel("Number of components", fontsize=9)
    ax.set_ylabel(
        selection.candidates[0].criterion.upper() if selection.candidates else "criterion",
        fontsize=9,
    )
    ax.set_xticks(ns)
    ax.grid(True, color=GRID, lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if path is not None:
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=SURFACE)
        plt.close(fig)
    return fig
