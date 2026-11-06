"""Bootstrap uncertainties as a complement to covariance-based standard errors.

Covariance errors assume the model is right and the noise is as weighted.  Bootstrap
replicates expose how much the result moves under realistic noise, which matters most
for overlapping peaks whose widths and areas trade off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .fitting import FitError, FitResult, FitSettings, fit_peaks, specs_from_result
from .spectrum import Spectrum


@dataclass
class BootstrapResult:
    n_requested: int
    n_succeeded: int
    mode: str
    #: ``{component label: {attribute: {"std": ..., "p2.5": ..., "p50": ..., "p97.5": ...}}}``
    summary: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_requested": self.n_requested,
            "n_succeeded": self.n_succeeded,
            "mode": self.mode,
            "summary": self.summary,
        }


_ATTRS = ("area", "center", "fwhm")


def bootstrap(
    spectrum: Spectrum,
    result: FitResult,
    n: int = 100,
    seed: int = 0,
    mode: str = "auto",
    settings: FitSettings | None = None,
) -> BootstrapResult:
    """Refit ``n`` synthetic replicates of the data around the fitted model.

    ``mode="poisson"`` draws Poisson counts from the model (background + envelope) and
    requires counts; ``mode="residual"`` adds randomly re-sampled residuals;
    ``"auto"`` picks Poisson when the spectrum is in counts.
    """
    settings = settings or result.settings
    if mode == "auto":
        mode = "poisson" if spectrum.intensity_unit == "counts" else "residual"
    rng = np.random.default_rng(seed)
    model_total = result.model
    specs0 = specs_from_result(result)
    samples: dict[str, dict[str, list[float]]] = {}
    ok = 0
    for _ in range(n):
        if mode == "poisson":
            y = rng.poisson(np.maximum(model_total, 0.0)).astype(float)
        elif mode == "residual":
            y = model_total + rng.choice(result.residual, size=result.residual.size, replace=True)
        else:
            raise ValueError("mode must be 'auto', 'poisson' or 'residual'")
        rep = spectrum.copy()
        rep.intensity = y
        try:
            r = fit_peaks(rep, specs0, settings)
        except FitError:
            continue
        ok += 1
        for c in r.components:
            d = samples.setdefault(c.label, {a: [] for a in _ATTRS})
            for a in _ATTRS:
                d[a].append(float(getattr(c, a)))
    summary: dict[str, dict[str, dict[str, float]]] = {}
    for label, attrs in samples.items():
        summary[label] = {}
        for a, vals in attrs.items():
            arr = np.asarray(vals)
            if arr.size == 0:
                continue
            summary[label][a] = {
                "std": float(np.std(arr, ddof=1)) if arr.size > 1 else float("nan"),
                "p2.5": float(np.percentile(arr, 2.5)),
                "p50": float(np.percentile(arr, 50)),
                "p97.5": float(np.percentile(arr, 97.5)),
            }
    return BootstrapResult(n, ok, mode, summary)
