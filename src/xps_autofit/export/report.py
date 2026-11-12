"""A PDF report of one sample: summary, composition and one page per fitted region.

Page 1 lists the file, the recipe, the software version and date, every region with
its status, component count, background / line shape, reduced chi-square and quality
grade, and the composition with the source of each sensitivity factor.  Each
following page shows the region's fit in the figure style of the exports (Origin-
style by default) above its component table and the selection notes.  The report
is generated from the same results as the other exports, so it reproduces nothing
on its own: it is the page to print, attach or file next to the project files.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from .. import __version__  # noqa: E402
from ..core.fitting import FitResult  # noqa: E402
from ..core.quantification import QuantResult  # noqa: E402
from .plots import (  # noqa: E402
    DEFAULT_FIGURE_STYLE,
    _check_style,
    _rc,
    draw_fit,
    origin_font_family,
)

A4 = (8.27, 11.69)
"""Portrait page size in inches."""


@dataclass
class ReportRegion:
    """One fitted region of the sample."""

    name: str
    result: FitResult
    status: str = "ok"
    variant: str = ""
    grade: str | None = None
    spectrum_name: str = ""
    notes: list[str] = field(default_factory=list)
    assignments: dict[str, str] = field(default_factory=dict)
    """Component label -> suggested chemical state (shown in the table)."""


def summary_rows(regions: Sequence[ReportRegion]) -> list[list[str]]:
    rows = []
    for r in regions:
        s = r.result.stats
        rows.append(
            [
                r.name,
                r.status,
                str(len(r.result.majors())),
                r.variant or f"{r.result.background.spec.type}/{r.result.settings.shape}",
                f"{s.redchi:.3g}",
                r.grade or "-",
            ]
        )
    return rows


def composition_rows(quant: QuantResult | None) -> list[list[str]]:
    if quant is None:
        return []
    rows = []
    for e in quant.entries:
        pct = "-" if e.atomic_percent is None else f"{e.atomic_percent:.2f}"
        err = "-" if e.atomic_percent_std is None else f"{e.atomic_percent_std:.2f}"
        rsf = "-" if e.rsf is None else f"{e.rsf:.4g}"
        rows.append([e.label, pct, err, rsf, e.rsf_source or "-"])
    return rows


def component_rows(region: ReportRegion) -> list[list[str]]:
    rows = []
    for c in region.result.components:
        rows.append(
            [
                ("  " if c.is_minor else "") + c.label,
                f"{c.center:.3f}",
                "-" if c.center_err is None else f"{c.center_err:.3f}",
                f"{c.fwhm:.3f}",
                f"{c.area:.4g}",
                "-" if c.area_err is None else f"{c.area_err:.3g}",
                "-"
                if c.component_fraction is None or c.is_minor
                else f"{c.component_fraction:.1f}",
                "" if c.is_minor else region.assignments.get(c.label, ""),
            ]
        )
    return rows


def _table(ax: Any, header: list[str], rows: list[list[str]], font: dict[str, Any]) -> float:
    """Draw a table at the top of ``ax``; return its lower edge in axes coordinates."""
    ax.axis("off")
    if not rows:
        ax.text(0.0, 0.9, "(none)", transform=ax.transAxes, fontsize=8, **font)
        return 0.85
    # column widths follow the longest entry, so long names are not cut
    longest = [max(len(str(v)) for v in col) for col in zip(header, *rows)]
    total = float(sum(max(n, 4) for n in longest))
    widths = [max(n, 4) / total for n in longest]
    table = ax.table(
        cellText=rows, colLabels=header, loc="upper left", cellLoc="left", colWidths=widths
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1.0, 1.25)
    for (r, _c), cell in table.get_celld().items():
        cell.set_linewidth(0.4)
        if font:
            cell.get_text().set_fontfamily(font["fontfamily"])
        if r == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#eeeeee")
    box = table.get_window_extent(ax.figure.canvas.get_renderer())
    return float(box.transformed(ax.transAxes.inverted()).y0)


def _page_title(spectrum_name: str, region: str) -> str:
    """ "<spectrum> - <region>", or the spectrum name alone when it names the region."""
    if not spectrum_name:
        return region
    if region and region.lower() in spectrum_name.lower():
        return spectrum_name
    return f"{spectrum_name} - {region}"


def _table_height(n_rows: int) -> float:
    """Figure fraction a table of ``n_rows`` (plus header) needs on an A4 page."""
    return 0.02 + 0.021 * (n_rows + 1)


def write_report(
    path: str | Path,
    regions: Sequence[ReportRegion],
    composition: QuantResult | None = None,
    sample: str = "",
    source: str = "",
    recipe: str = "",
    style: str = DEFAULT_FIGURE_STYLE,
) -> Path:
    """Write the PDF and return its path (one summary page + one page per region)."""
    _check_style(style)
    p = Path(path)
    family = origin_font_family() if style == "origin" else None
    font: dict[str, Any] = {"fontfamily": family} if family else {}
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with plt.rc_context(_rc(style)), PdfPages(p) as pdf:
        # ---- page 1: summary and composition
        fig = plt.figure(figsize=A4)
        fig.text(0.07, 0.95, sample or "XPS report", fontsize=16, weight="bold", **font)
        src = Path(source) if source else None
        folder = ""
        if src is not None and src.parent.parts:
            parts = src.parent.parts[-2:]
            folder = ("..." if len(src.parent.parts) > 2 else "") + "/".join(parts)
        lines = [
            f"File: {src.name}" + (f"  (folder {folder})" if folder else "") if src else "",
            f"Recipe: {recipe}" if recipe else "",
            f"XPS AutoFit Studio {__version__}, {stamp}",
        ]
        y = 0.925
        for line in filter(None, lines):
            fig.text(0.07, y, line, fontsize=9, **font)
            y -= 0.018
        fig.text(0.07, y - 0.012, "Regions", fontsize=11, weight="bold", **font)
        rows = summary_rows(regions)
        h = _table_height(len(rows))
        ax = fig.add_axes((0.07, y - 0.025 - h, 0.86, h))
        _table(
            ax,
            ["Region", "Status", "n", "Background / shape", "Reduced chi-sq", "Grade"],
            rows,
            font,
        )
        y2 = y - 0.025 - h - 0.04
        fig.text(0.07, y2, "Composition", fontsize=11, weight="bold", **font)
        crow = composition_rows(composition)
        h2 = _table_height(len(crow))
        ax = fig.add_axes((0.07, y2 - 0.013 - h2, 0.86, h2))
        _table(ax, ["Region", "Atomic %", "+/-", "RSF", "RSF source"], crow, font)
        if composition is not None:
            status = composition.status + (f" - {composition.note}" if composition.note else "")
            fig.text(0.07, y2 - 0.03 - h2, status[:400], fontsize=7, wrap=True, **font)
        pdf.savefig(fig)
        plt.close(fig)
        # ---- one page per region
        for r in regions:
            fig = plt.figure(figsize=A4)
            grid = fig.add_gridspec(
                4, 1, height_ratios=[4, 1, 0.45, 3.0], hspace=0.06, top=0.94, bottom=0.04
            )
            ax = fig.add_subplot(grid[0])
            axr = fig.add_subplot(grid[1], sharex=ax)
            ax.tick_params(labelbottom=False)
            title = _page_title(r.spectrum_name, r.name)
            draw_fit(
                fig,
                ax,
                axr,
                r.result,
                f"{title} (n={len(r.result.majors())}, {r.status})",
                style=style,
            )
            tab = fig.add_subplot(grid[3])
            bottom = _table(
                tab,
                ["Component", "Centre (eV)", "+/-", "FWHM", "Area", "+/-", "Comp. %", "Assignment"],
                component_rows(r),
                font,
            )
            links = [
                f"{s.label}: " + "; ".join(f"{k} = {v.describe(k)}" for k, v in s.links().items())
                for s in r.result.specs
                if s.links()
            ]
            notes = [n for n in r.notes if n][:6]
            if links:
                notes.insert(0, "Links - " + " | ".join(links))
            if notes:
                wrapped = [textwrap.fill(n, 140) for n in notes]
                tab.text(
                    0.0,
                    bottom - 0.04,
                    "Notes\n" + "\n".join(wrapped),
                    transform=tab.transAxes,
                    fontsize=6.5,
                    va="top",
                    **font,
                )
            pdf.savefig(fig)
            plt.close(fig)
        info = pdf.infodict()
        info["Title"] = f"XPS report {sample}".strip()
        info["Creator"] = f"XPS AutoFit Studio {__version__}"
    return p
