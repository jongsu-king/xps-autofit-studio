"""Tabular output (CSV / XLSX) for fits and model-selection summaries."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..automation.model_selection import SelectionResult
from ..core.fitting import FitResult

COMPONENT_COLUMNS = [
    "label",
    "parent",
    "is_minor",
    "center_eV",
    "center_err",
    "fwhm_eV",
    "fwhm_err",
    "fwhm_g",
    "fwhm_g_err",
    "fwhm_l",
    "fwhm_l_err",
    "eta",
    "eta_err",
    "area",
    "area_err",
    "fraction_pct",
    "component_fraction_pct",
    "height",
]


def components_table(result: FitResult) -> pd.DataFrame:
    rows = []
    for c in result.components:
        rows.append(
            {
                "label": c.label,
                "parent": c.parent,
                "is_minor": c.is_minor,
                "center_eV": c.center,
                "center_err": c.center_err,
                "fwhm_eV": c.fwhm,
                "fwhm_err": c.fwhm_err,
                "fwhm_g": c.fwhm_g,
                "fwhm_g_err": c.fwhm_g_err,
                "fwhm_l": c.fwhm_l,
                "fwhm_l_err": c.fwhm_l_err,
                "eta": c.eta,
                "eta_err": c.eta_err,
                "area": c.area,
                "area_err": c.area_err,
                "fraction_pct": c.fraction,
                "component_fraction_pct": c.component_fraction,
                "height": c.height,
            }
        )
    return pd.DataFrame(rows, columns=COMPONENT_COLUMNS)


def fit_table(result: FitResult) -> pd.DataFrame:
    data = {
        "binding_energy_eV": result.x,
        "raw": result.y,
        "background": result.background_total,
        "background_fixed": result.background.values,
        "background_adjust": result.bg_adjust,
        "net": result.y - result.background_total,
        "envelope": result.envelope,
        "model": result.model,
        "residual": result.residual,
    }
    if result.sigma is not None:
        data["sigma"] = result.sigma
    for c in result.components:
        if c.values is not None:
            data[f"comp: {c.label}"] = c.values
    return pd.DataFrame(data)


def candidates_table(selection: SelectionResult) -> pd.DataFrame:
    rows = []
    for c in selection.candidates:
        s = c.result.stats
        rows.append(
            {
                "n_components": c.n_components,
                "background": c.background_type,
                "shape": c.shape,
                "nvarys": s.nvarys,
                "chisqr": s.chisqr,
                "redchi": s.redchi,
                "aic": s.aic,
                "aicc": s.aicc,
                "bic": s.bic,
                "physical_ok": c.physical_ok,
                "violations": "; ".join(v.message for v in c.violations),
                "warnings": "; ".join(v.message for v in c.warnings),
                "selected": selection.best is c,
            }
        )
    return pd.DataFrame(rows)


def write_xlsx(path: str | Path, sheets: dict[str, pd.DataFrame]) -> Path:
    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return path
