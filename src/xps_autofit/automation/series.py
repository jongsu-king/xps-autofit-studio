"""Composition of a series of samples: depth-profile cycles, ageing times, batches.

Each sample's :class:`~xps_autofit.core.quantification.QuantResult` (from a batch run
or the desktop application) becomes one row with one atomic-percent column per
element; several regions of the same element are summed.  Samples are ordered
naturally by name ("cycle2" before "cycle10") unless the given order is kept.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..core.quantification import QuantResult
from ..export.origin import OriginColumn

SERIES_ORDERS = ("natural", "given")


def natural_key(text: str) -> list[Any]:
    """Sort key that compares the digit runs of ``text`` as numbers."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _element(entry: Any) -> str:
    return str(entry.element or entry.label)


def composition_series(
    items: Sequence[tuple[str, QuantResult | None]], order: str = "natural"
) -> pd.DataFrame:
    """One row per sample: ``index``, ``sample``, ``status``, then ``<El> at%`` and,
    where uncertainties exist, ``<El> err`` for every element seen.

    Elements are ordered by their mean share over the series (largest first).
    Samples without a calculable composition keep their row with empty values, so a
    missing cycle stays visible.
    """
    if order not in SERIES_ORDERS:
        raise ValueError(f"order must be one of {SERIES_ORDERS}, got {order!r}")
    rows: list[dict[str, Any]] = []
    errors_seen: set[str] = set()
    for sample, quant in items:
        values: dict[str, float] = {}
        variances: dict[str, float] = {}
        status = "no fit" if quant is None else quant.status
        if quant is not None and quant.status == "OK":
            for e in quant.entries:
                if e.atomic_percent is None:
                    continue
                el = _element(e)
                values[el] = values.get(el, 0.0) + float(e.atomic_percent)
                if e.atomic_percent_std is not None:
                    variances[el] = variances.get(el, 0.0) + float(e.atomic_percent_std) ** 2
                    errors_seen.add(el)
        rows.append({"sample": sample, "status": status, "values": values, "var": variances})
    if order == "natural":
        rows.sort(key=lambda r: natural_key(r["sample"]))
    totals: dict[str, list[float]] = {}
    for r in rows:
        for el, v in r["values"].items():
            totals.setdefault(el, []).append(v)
    elements = sorted(totals, key=lambda el: (-float(np.mean(totals[el])), el))
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows, start=1):
        row: dict[str, Any] = {"index": i, "sample": r["sample"], "status": r["status"]}
        for el in elements:
            row[f"{el} at%"] = r["values"].get(el, math.nan)
            if el in errors_seen:
                var = r["var"].get(el)
                row[f"{el} err"] = math.sqrt(var) if var is not None else math.nan
        out.append(row)
    columns = ["index", "sample", "status"]
    for el in elements:
        columns.append(f"{el} at%")
        if el in errors_seen:
            columns.append(f"{el} err")
    return pd.DataFrame(out, columns=columns)


def series_elements(frame: pd.DataFrame) -> list[str]:
    return [c[: -len(" at%")] for c in frame.columns if c.endswith(" at%")]


def series_origin_columns(frame: pd.DataFrame) -> list[OriginColumn]:
    """The series for Origin: sample index (X), one column per element and its error,
    and the sample names as a text column at the end."""
    cols = [OriginColumn("Sample index", "", "X; sample order", frame["index"].to_numpy())]
    for el in series_elements(frame):
        cols.append(OriginColumn(el, "at.%", "atomic percent", frame[f"{el} at%"].to_numpy()))
        if f"{el} err" in frame.columns:
            cols.append(
                OriginColumn(f"{el} error", "at.%", "1 sigma", frame[f"{el} err"].to_numpy())
            )
    cols.append(OriginColumn("Sample", "", "name", [str(s) for s in frame["sample"]]))
    return cols
