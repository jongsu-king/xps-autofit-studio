"""Bootstrap uncertainties as a complement to covariance-based standard errors.

Covariance errors assume the model is right and the noise is as weighted.  Bootstrap
replicates expose how much the result moves under realistic noise, which matters most
for overlapping peaks whose widths and areas trade off.  The replicate areas are kept
so that uncertainties can be propagated to fractions and, across regions, to atomic
percentages (:func:`xps_autofit.core.quantification.atomic_percent_samples`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .fitting import (
    FitError,
    FitResult,
    FitSettings,
    fit_peaks,
    minor_label,
    specs_from_result,
)
from .spectrum import Spectrum


@dataclass
class BootstrapResult:
    n_requested: int
    n_succeeded: int
    mode: str
    #: ``{component label: {attribute: {"std": ..., "p2.5": ..., "p50": ..., "p97.5": ...}}}``
    summary: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    #: Replicate areas per component label (``n_succeeded`` values each).
    area_samples: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    #: Replicate total area (all lines) and major-line area of the region.
    total_area_samples: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)
    major_area_samples: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_requested": self.n_requested,
            "n_succeeded": self.n_succeeded,
            "mode": self.mode,
            "summary": self.summary,
        }

    def renamed(self, old: str, new: str) -> BootstrapResult:
        """The same replicates with component *old* (and its minor line) called *new*;
        the counterpart of :func:`xps_autofit.core.fitting.rename_component`."""
        mapping = {old: new, minor_label(old): minor_label(new)}

        def key(label: str) -> str:
            return mapping.get(label, label)

        return BootstrapResult(
            n_requested=self.n_requested,
            n_succeeded=self.n_succeeded,
            mode=self.mode,
            summary={key(k): v for k, v in self.summary.items()},
            area_samples={key(k): v for k, v in self.area_samples.items()},
            total_area_samples=self.total_area_samples,
            major_area_samples=self.major_area_samples,
        )


_ATTRS = ("area", "center", "fwhm", "fraction", "component_fraction")


def _summarise(arr: np.ndarray) -> dict[str, float]:
    return {
        "std": float(np.std(arr, ddof=1)) if arr.size > 1 else float("nan"),
        "p2.5": float(np.percentile(arr, 2.5)),
        "p50": float(np.percentile(arr, 50)),
        "p97.5": float(np.percentile(arr, 97.5)),
    }


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
    ``"auto"`` picks Poisson when the spectrum is in counts.  Replicates start from
    the fitted values and use a local optimiser whatever the original settings.
    """
    settings = settings or result.settings
    if settings.optimizer != "leastsq":
        from dataclasses import replace

        settings = replace(settings, optimizer="leastsq")
    if mode == "auto":
        mode = "poisson" if spectrum.intensity_unit == "counts" else "residual"
    rng = np.random.default_rng(seed)
    model_total = result.model
    specs0 = specs_from_result(result)
    samples: dict[str, dict[str, list[float]]] = {}
    totals: list[float] = []
    majors: list[float] = []
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
            r = fit_peaks(rep, specs0, settings, background=result.background)
        except FitError:
            continue
        ok += 1
        totals.append(r.total_area)
        majors.append(sum(c.area for c in r.majors()))
        for c in r.components:
            d = samples.setdefault(c.label, {a: [] for a in _ATTRS})
            for a in _ATTRS:
                v = getattr(c, a)
                if v is not None:
                    d[a].append(float(v))
    summary: dict[str, dict[str, dict[str, float]]] = {}
    area_samples: dict[str, np.ndarray] = {}
    for label, attrs in samples.items():
        summary[label] = {}
        for a, vals in attrs.items():
            arr = np.asarray(vals, dtype=float)
            if arr.size == 0:
                continue
            summary[label][a] = _summarise(arr)
            if a == "area":
                area_samples[label] = arr
    return BootstrapResult(
        n,
        ok,
        mode,
        summary,
        area_samples,
        np.asarray(totals, dtype=float),
        np.asarray(majors, dtype=float),
    )
