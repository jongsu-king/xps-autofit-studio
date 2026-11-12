"""Physical constraints: doublets, width bounds, separation, and post-fit checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .fitting import Component, FitResult

#: Area ratio of the j = l - 1/2 (higher BE, minor) to the j = l + 1/2 (major) line.
ORBITAL_AREA_RATIOS: dict[str, float] = {"p": 0.5, "d": 2.0 / 3.0, "f": 0.75}


@dataclass
class DoubletSpec:
    """A spin-orbit doublet.  The *major* line is the fitted component; the *minor*
    line is tied to it.

    Parameters
    ----------
    splitting
        Minor minus major binding energy (eV).  Positive for p, d and f lines.
    splitting_tolerance
        0 fixes the splitting; otherwise it may vary within +/- tolerance.
    area_ratio
        ``area_minor / area_major`` (0.5 for p, 2/3 for d, 0.75 for f).
    ratio_tolerance
        0 fixes the ratio; otherwise it may vary within +/- tolerance.
    share_widths
        Minor line inherits every width parameter of the major line.
    """

    splitting: float
    area_ratio: float
    splitting_tolerance: float = 0.0
    ratio_tolerance: float = 0.0
    share_widths: bool = True
    label: str = ""

    def __post_init__(self) -> None:
        if self.splitting <= 0:
            raise ValueError("doublet splitting must be positive (minor line at higher BE)")
        if not 0 < self.area_ratio <= 1.5:
            raise ValueError("doublet area ratio must be in (0, 1.5]")
        if self.splitting_tolerance < 0 or self.ratio_tolerance < 0:
            raise ValueError("tolerances must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "splitting": self.splitting,
            "area_ratio": self.area_ratio,
            "splitting_tolerance": self.splitting_tolerance,
            "ratio_tolerance": self.ratio_tolerance,
            "share_widths": self.share_widths,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> DoubletSpec | None:
        if d is None:
            return None
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def for_orbital(cls, orbital: str, splitting: float, **kw: Any) -> DoubletSpec:
        letter = orbital.strip()[-1].lower()
        if letter not in ORBITAL_AREA_RATIOS:
            raise ValueError(f"no doublet for orbital {orbital!r}")
        return cls(splitting=splitting, area_ratio=ORBITAL_AREA_RATIOS[letter], **kw)


@dataclass
class PeakConstraints:
    """Bounds applied to every component of a region.

    Width bounds are ``(min, max)`` in eV.  ``share_*`` ties that parameter across all
    major components (a common choice for the Lorentzian lifetime width of one core
    level).
    """

    fwhm_g: tuple[float, float] = (0.3, 3.0)
    fwhm_l: tuple[float, float] = (0.02, 1.0)
    fwhm: tuple[float, float] = (0.3, 3.5)
    eta: tuple[float, float] = (0.0, 1.0)
    asym: tuple[float, float] = (0.0, 0.5)
    """Doniach-Sunjic asymmetry (alpha) bounds; 0.05-0.2 is typical of metals."""
    share_fwhm_g: bool = False
    share_fwhm_l: bool = True
    share_fwhm: bool = False
    share_eta: bool = True
    share_asym: bool = True
    min_separation: float = 0.3
    """Minimum distance between two major components (eV) for a model to count as
    physically distinct."""
    edge_margin: float = 0.2
    """Centres must lie at least this far (eV) inside the region."""
    significance_sigma: float = 3.0
    """A component whose area is below this many standard errors is 'insignificant'."""
    residual_dw_warning: float = 1.0
    """Warn when the Durbin-Watson statistic of the residual falls below this value
    (2 for white noise; small values mean the residual is structured)."""
    correlation_warning: float = 0.98
    """Warn when two free parameters of different components are correlated above
    this value: the data then do not determine the components independently."""
    relative_error_warning: float = 0.5
    """Warn when a component's area has a standard error above this fraction of its
    value."""

    WIDTH_NAMES = ("fwhm_g", "fwhm_l", "fwhm", "eta", "asym")

    def __post_init__(self) -> None:
        for name in self.WIDTH_NAMES:
            lo, hi = getattr(self, name)
            if not lo < hi:
                raise ValueError(f"{name} bounds must satisfy min < max, got {(lo, hi)}")
            setattr(self, name, (float(lo), float(hi)))
        if self.asym[0] < 0 or self.asym[1] > 0.5:
            raise ValueError("asym bounds must lie within [0, 0.5]")
        if self.min_separation < 0 or self.edge_margin < 0:
            raise ValueError("min_separation and edge_margin must be >= 0")

    def bounds(self, name: str) -> tuple[float, float]:
        lo, hi = getattr(self, name)
        return (float(lo), float(hi))

    def shared(self, name: str) -> bool:
        return bool(getattr(self, f"share_{name}"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fwhm_g": list(self.fwhm_g),
            "fwhm_l": list(self.fwhm_l),
            "fwhm": list(self.fwhm),
            "eta": list(self.eta),
            "asym": list(self.asym),
            "share_fwhm_g": self.share_fwhm_g,
            "share_fwhm_l": self.share_fwhm_l,
            "share_fwhm": self.share_fwhm,
            "share_eta": self.share_eta,
            "share_asym": self.share_asym,
            "min_separation": self.min_separation,
            "edge_margin": self.edge_margin,
            "significance_sigma": self.significance_sigma,
            "residual_dw_warning": self.residual_dw_warning,
            "correlation_warning": self.correlation_warning,
            "relative_error_warning": self.relative_error_warning,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PeakConstraints:
        if not d:
            return cls()
        kw: dict[str, Any] = {}
        for k, v in d.items():
            if k not in cls.__dataclass_fields__:
                continue
            kw[k] = tuple(v) if k in cls.WIDTH_NAMES else v
        return cls(**kw)


@dataclass
class Violation:
    code: str
    message: str
    component: str | None = None
    severity: str = "violation"  # "violation" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def check_physical(
    result: FitResult,
    constraints: PeakConstraints,
    x_range: tuple[float, float],
    candidate_windows: list[tuple[str, float, float]] | None = None,
    require_assignment: bool = False,
    noise_sigma: float | None = None,
) -> tuple[list[Violation], list[Violation]]:
    """Check a fit against physical expectations.

    Returns ``(violations, warnings)``.  Violations disqualify a model from automatic
    selection; warnings are reported but do not.

    ``noise_sigma`` (baseline noise of the net signal) enables the height test: a
    component whose height is below ``significance_sigma`` times the local noise is
    not a visible peak, whatever the covariance says.
    """
    violations: list[Violation] = []
    warnings: list[Violation] = []
    majors: list[Component] = [c for c in result.components if not c.is_minor]
    lo, hi = x_range
    margin = constraints.edge_margin
    k = constraints.significance_sigma

    specs = list(result.specs) + [None] * max(0, len(majors) - len(result.specs))
    for c, spec in zip(majors, specs):
        if c.area <= 0:
            violations.append(Violation("non_positive_area", f"{c.label}: area <= 0", c.label))
        elif c.area_err is not None and c.area_err > 0:
            z = c.area / c.area_err
            if z < k:
                violations.append(
                    Violation(
                        "insignificant_area",
                        f"{c.label}: area is only {z:.1f} sigma from zero (< {k:g})",
                        c.label,
                    )
                )
        if noise_sigma is not None and noise_sigma > 0:
            local = float(noise_sigma)
            if result.sigma is not None:
                idx = int(np.argmin(np.abs(result.x - c.center)))
                local = max(local, float(result.sigma[idx]))
            ratio = c.height / local
            if ratio < k:
                violations.append(
                    Violation(
                        "below_noise",
                        f"{c.label}: height {c.height:.3g} is {ratio:.1f} x the local noise "
                        f"(< {k:g})",
                        c.label,
                    )
                )
        if c.center - lo <= margin * 1.01 or hi - c.center <= margin * 1.01:
            violations.append(
                Violation(
                    "center_at_edge", f"{c.label}: centre {c.center:.2f} eV at region edge", c.label
                )
            )
        for pname in result.width_param_names():
            value = getattr(c, pname, None)
            if value is None:
                continue
            bmin, bmax = constraints.bounds(pname)
            if pname == "fwhm_g" and spec is not None and spec.fwhm_g_bounds is not None:
                bmin, bmax = spec.fwhm_g_bounds
            span = bmax - bmin
            if value - bmin <= 0.01 * span:
                if pname == "asym":
                    continue  # a symmetric line is the expected case, not a warning
                warnings.append(
                    Violation(
                        "width_at_lower_bound",
                        f"{c.label}: {pname} {value:.3f} at lower bound",
                        c.label,
                        "warning",
                    )
                )
            elif bmax - value <= 0.01 * span:
                warnings.append(
                    Violation(
                        "width_at_upper_bound",
                        f"{c.label}: {pname} {value:.3f} at upper bound",
                        c.label,
                        "warning",
                    )
                )

    centers = sorted((c.center, c.label) for c in majors)
    # a centre tied to another one at a chosen offset is not an independent line
    tied = {
        frozenset((s.label, s.center_link.target))
        for s in result.specs
        if s.center_link is not None
    }
    for (e1, l1), (e2, l2) in zip(centers[:-1], centers[1:]):
        if e2 - e1 < constraints.min_separation and frozenset((l1, l2)) not in tied:
            violations.append(
                Violation(
                    "too_close",
                    f"{l1} and {l2} are {e2 - e1:.2f} eV apart (< {constraints.min_separation:g})",
                    l2,
                )
            )

    if candidate_windows:
        for c in majors:
            inside = any(lo_w <= c.center <= hi_w for _, lo_w, hi_w in candidate_windows)
            if not inside:
                v = Violation(
                    "unassigned",
                    f"{c.label}: centre {c.center:.2f} eV matches no candidate window",
                    c.label,
                    "violation" if require_assignment else "warning",
                )
                (violations if require_assignment else warnings).append(v)

    dw = result.stats.durbin_watson
    if dw is not None and result.stats.ndata >= 30 and dw < constraints.residual_dw_warning:
        warnings.append(
            Violation(
                "structured_residual",
                f"residual is autocorrelated (Durbin-Watson {dw:.2f} < "
                f"{constraints.residual_dw_warning:g}); a component or background term "
                "may be missing",
                None,
                "warning",
            )
        )

    rmax = result.stats.max_correlation
    if rmax is not None and rmax > constraints.correlation_warning:
        warnings.append(
            Violation(
                "degenerate_parameters",
                f"parameters {result.stats.max_correlation_pair} are {100 * rmax:.1f} % "
                f"correlated (> {100 * constraints.correlation_warning:g} %); the data do not "
                "determine these components independently",
                None,
                "warning",
            )
        )

    for c in majors:
        if c.area > 0 and c.area_err is not None:
            rel = c.area_err / c.area
            if rel > constraints.relative_error_warning:
                warnings.append(
                    Violation(
                        "large_relative_error",
                        f"{c.label}: area uncertain to {100 * rel:.0f} %",
                        c.label,
                        "warning",
                    )
                )
    return violations, warnings
