"""Non-linear least-squares peak fitting on top of :mod:`lmfit`.

Model
-----
``I(E) = B(E) + sum_i A_i P_i(E; mu_i, widths_i)`` where ``P_i`` are area-normalised
shapes and ``A_i`` are areas.  Doublets add a *minor* line tied to its major by
expressions (``center + split``, ``area * ratio``, shared widths), so a doublet is one
chemical component with one set of free parameters.

The background ``B`` is either *static* (computed first from the data, see
:mod:`.background`, and subtracted; optionally refined by a free linear term) or
*active*: ``B(E) = offset + k * S[envelope](E)`` with the Shirley running integral or
the Tougaard loss integral ``S`` applied to the fitted peak envelope itself, and
``offset`` and ``k`` as free parameters.  The active form removes the endpoint bias
of the classical algorithms and keeps background and peaks self-consistent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import lmfit
import numpy as np

from .background import (
    BackgroundResult,
    BackgroundSpec,
    compute_background,
    shirley_operator,
    tougaard_kernel,
)
from .constraints import DoubletSpec, PeakConstraints
from .peak_shapes import GL_SHAPES, SHAPES, evaluate, get_shape, total_fwhm
from .peak_shapes import height as shape_height
from .spectrum import Spectrum


class FitError(RuntimeError):
    """Raised when a fit cannot be set up or the optimiser fails outright."""


LOSSES = ("linear", "soft_l1", "huber", "cauchy", "arctan")
"""Loss functions of :func:`scipy.optimize.least_squares`.  ``linear`` is ordinary
least squares; the others down-weight residuals larger than ``loss_scale`` so that
spikes, cosmic-ray hits and misfit tails pull less on the components."""

CORRELATION_REPORT = 0.9
"""Pairs of free parameters whose correlation coefficient exceeds this value are
listed in :attr:`FitResult.correlations`."""

MAX_MASKED_FRACTION = 0.02
"""Spike masking is skipped (with a warning) when more points than this fraction of
the region would be masked: that is not a few spikes but a different problem."""

MAX_SPIKE_STEP = 0.25
"""Spike masking needs a step fine enough that a real line spans several points; it
is skipped (with a warning) above this step in eV."""


# ----------------------------------------------------------------------------- specs
@dataclass
class ComponentSpec:
    """Initial values and per-component bounds for one chemical component."""

    label: str
    center: float
    area: float = 1.0
    fwhm_g: float = 1.0
    fwhm_l: float = 0.2
    fwhm: float = 1.0
    eta: float = 0.3
    asym: float = 0.05
    center_bounds: tuple[float, float] | None = None
    vary_center: bool = True
    fwhm_g_bounds: tuple[float, float] | None = None
    doublet: DoubletSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "center": self.center,
            "area": self.area,
            "fwhm_g": self.fwhm_g,
            "fwhm_l": self.fwhm_l,
            "fwhm": self.fwhm,
            "eta": self.eta,
            "asym": self.asym,
            "center_bounds": list(self.center_bounds) if self.center_bounds else None,
            "vary_center": self.vary_center,
            "fwhm_g_bounds": list(self.fwhm_g_bounds) if self.fwhm_g_bounds else None,
            "doublet": self.doublet.to_dict() if self.doublet else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentSpec:
        cb = d.get("center_bounds")
        fb = d.get("fwhm_g_bounds")
        return cls(
            label=str(d["label"]),
            center=float(d["center"]),
            area=float(d.get("area", 1.0)),
            fwhm_g=float(d.get("fwhm_g", 1.0)),
            fwhm_l=float(d.get("fwhm_l", 0.2)),
            fwhm=float(d.get("fwhm", 1.0)),
            eta=float(d.get("eta", 0.3)),
            asym=float(d.get("asym", 0.05)),
            center_bounds=(float(cb[0]), float(cb[1])) if cb else None,
            vary_center=bool(d.get("vary_center", True)),
            fwhm_g_bounds=(float(fb[0]), float(fb[1])) if fb else None,
            doublet=DoubletSpec.from_dict(d.get("doublet")),
        )


@dataclass
class FitSettings:
    shape: str = "voigt"
    background: BackgroundSpec = field(default_factory=BackgroundSpec)
    constraints: PeakConstraints = field(default_factory=PeakConstraints)
    weighting: str = "auto"
    """``"auto"`` uses Poisson weights when the spectrum provides them, ``"poisson"``
    requires them, ``"none"`` fits unweighted."""
    method: str = "leastsq"
    max_nfev: int | None = None
    scale_covar: bool | None = None
    """``None``: rescale the covariance by reduced chi-square only for unweighted fits."""
    refine_linear_background: bool = False
    """Add a free offset and slope to absorb small background misestimates (static
    background) or a free slope on top of the active background."""
    optimizer: str = "leastsq"
    """``"leastsq"``: Levenberg-Marquardt from the initial values.  ``"global"``: a
    differential-evolution search inside the parameter bounds first, then
    Levenberg-Marquardt from the best point found (slower, robust to local minima)."""
    global_max_nfev: int = 20000
    global_popsize: int = 12
    seed: int | None = None
    """Seed of the differential-evolution search (``None``: 0, deterministic)."""
    loss: str = "linear"
    """``"linear"`` (least squares) or a robust loss of :data:`LOSSES`
    (``soft_l1``, ``huber``, ``cauchy``, ``arctan``), applied with
    :func:`scipy.optimize.least_squares`."""
    loss_scale: float = 3.0
    """Residual size (in standard deviations for weighted fits, in robust noise
    units otherwise) beyond which a robust loss starts to down-weight a point."""
    spike_sigma: float | None = None
    """When set, points deviating from a 5-point running median by more than this
    many local standard deviations are excluded from the fit (cosmic-ray hits,
    detector spikes).  ``None`` disables the mask."""

    def __post_init__(self) -> None:
        get_shape(self.shape)
        if self.weighting not in ("auto", "poisson", "none"):
            raise ValueError("weighting must be 'auto', 'poisson' or 'none'")
        if self.optimizer not in ("leastsq", "global"):
            raise ValueError("optimizer must be 'leastsq' or 'global'")
        if self.loss not in LOSSES:
            raise ValueError(f"loss must be one of {LOSSES}")
        if self.loss_scale <= 0:
            raise ValueError("loss_scale must be positive")
        if self.spike_sigma is not None and self.spike_sigma <= 0:
            raise ValueError("spike_sigma must be positive or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape,
            "background": self.background.to_dict(),
            "constraints": self.constraints.to_dict(),
            "weighting": self.weighting,
            "method": self.method,
            "max_nfev": self.max_nfev,
            "scale_covar": self.scale_covar,
            "refine_linear_background": self.refine_linear_background,
            "optimizer": self.optimizer,
            "global_max_nfev": self.global_max_nfev,
            "global_popsize": self.global_popsize,
            "seed": self.seed,
            "loss": self.loss,
            "loss_scale": self.loss_scale,
            "spike_sigma": self.spike_sigma,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FitSettings:
        spike = d.get("spike_sigma")
        return cls(
            shape=str(d.get("shape", "voigt")),
            background=BackgroundSpec.from_dict(d.get("background")),
            constraints=PeakConstraints.from_dict(d.get("constraints")),
            weighting=str(d.get("weighting", "auto")),
            method=str(d.get("method", "leastsq")),
            max_nfev=d.get("max_nfev"),
            scale_covar=d.get("scale_covar"),
            refine_linear_background=bool(d.get("refine_linear_background", False)),
            optimizer=str(d.get("optimizer", "leastsq")),
            global_max_nfev=int(d.get("global_max_nfev", 20000)),
            global_popsize=int(d.get("global_popsize", 12)),
            seed=d.get("seed"),
            loss=str(d.get("loss", "linear")),
            loss_scale=float(d.get("loss_scale", 3.0)),
            spike_sigma=float(spike) if spike is not None else None,
        )


# --------------------------------------------------------------------------- results
@dataclass
class Component:
    label: str
    shape: str
    is_minor: bool
    parent: str
    area: float
    center: float
    fwhm: float
    height: float
    area_err: float | None = None
    center_err: float | None = None
    fwhm_err: float | None = None
    fwhm_g: float | None = None
    fwhm_g_err: float | None = None
    fwhm_l: float | None = None
    fwhm_l_err: float | None = None
    eta: float | None = None
    eta_err: float | None = None
    asym: float | None = None
    asym_err: float | None = None
    fraction: float | None = None
    """Share of the total fitted area in the region (percent), this line only."""
    component_fraction: float | None = None
    """Share of the chemical component (major + minor line) in the region (percent);
    ``None`` on minor lines."""
    values: np.ndarray | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "values"}
        return {k: _clean(v) for k, v in d.items()}


@dataclass
class FitStatistics:
    ndata: int
    nvarys: int
    nfree: int
    rss: float
    chisqr: float
    redchi: float
    aic: float
    aicc: float
    bic: float
    weighted: bool
    success: bool
    message: str
    nfev: int
    errorbars: bool
    durbin_watson: float | None = None
    """``sum (r_i - r_{i-1})**2 / sum r_i**2`` of the (weighted) residual: 2 for white
    noise, towards 0 for a residual with structure (missing component or background)."""
    runs_z: float | None = None
    """Wald-Wolfowitz runs test of the residual signs; strongly negative values mean
    long runs of one sign, i.e. systematic misfit."""
    lag1_autocorr: float | None = None
    n_masked: int = 0
    """Points excluded from the fit by the spike mask."""
    max_correlation: float | None = None
    """Largest absolute correlation coefficient between free parameters of *different*
    components (or a component and the background).  Values near 1 mean the data do
    not determine those parameters separately."""
    max_correlation_pair: str | None = None
    loss: str = "linear"

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in self.__dict__.items()}


@dataclass
class FitResult:
    """Everything a fit produced.

    ``background.values`` is the background proper (static Shirley etc., or the
    fitted active background); ``bg_adjust`` is the optional linear refinement;
    ``envelope`` is the sum of the peak components only.
    ``residual = y - background_total - envelope``.
    """

    x: np.ndarray
    y: np.ndarray
    background: BackgroundResult
    bg_adjust: np.ndarray
    y_net: np.ndarray
    envelope: np.ndarray
    residual: np.ndarray
    sigma: np.ndarray | None
    components: list[Component]
    params: dict[str, dict[str, Any]]
    stats: FitStatistics
    settings: FitSettings
    specs: list[ComponentSpec]
    warnings: list[str] = field(default_factory=list)
    mask: np.ndarray | None = field(default=None, repr=False)
    """Boolean array, ``True`` where a point was excluded from the fit (spike mask)."""
    correlations: list[dict[str, Any]] = field(default_factory=list)
    """Parameter pairs with ``|r| >= CORRELATION_REPORT``: ``{"a", "b", "r",
    "same_component"}``, strongest first."""

    @property
    def background_total(self) -> np.ndarray:
        return self.background.values + self.bg_adjust

    @property
    def model(self) -> np.ndarray:
        """Full model including background, comparable with ``y``."""
        return self.background_total + self.envelope

    def width_param_names(self) -> tuple[str, ...]:
        return SHAPES[self.settings.shape].params

    def majors(self) -> list[Component]:
        return [c for c in self.components if not c.is_minor]

    @property
    def total_area(self) -> float:
        return float(sum(c.area for c in self.components))

    def area_of(self, label: str, include_minor: bool = True) -> float:
        total = 0.0
        for c in self.components:
            if c.parent == label and (include_minor or not c.is_minor):
                total += c.area
        return total

    def to_dict(self, include_arrays: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "settings": self.settings.to_dict(),
            "specs": [s.to_dict() for s in self.specs],
            "background": self.background.to_dict(include_values=include_arrays),
            "params": self.params,
            "components": [c.to_dict() for c in self.components],
            "stats": self.stats.to_dict(),
            "warnings": list(self.warnings),
            "correlations": [dict(c) for c in self.correlations],
        }
        if include_arrays:
            d["x"] = self.x.tolist()
            d["y"] = self.y.tolist()
            if self.mask is not None:
                d["mask"] = self.mask.astype(int).tolist()
            d["y_net"] = self.y_net.tolist()
            d["bg_adjust"] = self.bg_adjust.tolist()
            d["envelope"] = self.envelope.tolist()
            d["residual"] = self.residual.tolist()
            d["component_values"] = {
                c.label: (c.values.tolist() if c.values is not None else None)
                for c in self.components
            }
        return d


# ----------------------------------------------------------------------- parameters
def _keys(specs: list[ComponentSpec]):
    """Yield ``(prefix, spec, is_minor)`` for every line in model order."""
    for i, s in enumerate(specs):
        yield f"c{i}", s, False
        if s.doublet is not None:
            yield f"c{i}m", s, True


def _add_fixed_or_bounded(params: lmfit.Parameters, name: str, value: float, tol: float) -> None:
    if tol > 0:
        params.add(name, value=value, min=value - tol, max=value + tol)
    else:
        params.add(name, value=value, vary=False)


def _clip_inside(value: float, lo: float, hi: float, frac: float = 1e-3) -> float:
    pad = (hi - lo) * frac
    return float(min(max(value, lo + pad), hi - pad))


def _active_start(
    x: np.ndarray, y: np.ndarray, background: BackgroundResult | None
) -> tuple[float, float]:
    """Initial ``(offset, scatter)`` of an active background from a static estimate."""
    if background is not None and "scatter" in background.info:
        info = background.info
        offset = float(info.get("offset", info.get("I_low_BE", float(np.mean(y[:3])))))
        return offset, float(max(info["scatter"], 0.0))
    offset = float(np.mean(y[:3]))
    return offset, 0.0


def build_parameters(
    specs: list[ComponentSpec],
    settings: FitSettings,
    x: np.ndarray,
    y: np.ndarray | None = None,
    background: BackgroundResult | None = None,
) -> lmfit.Parameters:
    """Translate component specs and constraints into an :class:`lmfit.Parameters`.

    ``y`` and ``background`` are only needed to initialise an active background.
    """
    if not specs:
        raise FitError("at least one component is required")
    shape = settings.shape
    c = settings.constraints
    names = SHAPES[shape].params
    lo, hi = float(x.min()), float(x.max())
    params = lmfit.Parameters()
    first_shared: dict[str, str] = {}

    for i, s in enumerate(specs):
        p = f"c{i}"
        cb = s.center_bounds or (lo + c.edge_margin, hi - c.edge_margin)
        cb = (max(cb[0], lo), min(cb[1], hi))
        if cb[0] >= cb[1]:
            raise FitError(f"{s.label}: empty centre window {cb} inside region [{lo}, {hi}]")
        params.add(
            f"{p}_center",
            value=_clip_inside(s.center, *cb),
            min=cb[0],
            max=cb[1],
            vary=s.vary_center,
        )
        params.add(f"{p}_area", value=max(float(s.area), 1e-9), min=0.0)
        for w in names:
            bmin, bmax = c.bounds(w)
            override = w == "fwhm_g" and s.fwhm_g_bounds is not None
            if override:
                bmin, bmax = s.fwhm_g_bounds  # type: ignore[misc]
            shared = c.shared(w) and not override
            if shared and w in first_shared:
                params.add(f"{p}_{w}", expr=first_shared[w])
            else:
                params.add(
                    f"{p}_{w}", value=_clip_inside(getattr(s, w), bmin, bmax), min=bmin, max=bmax
                )
                if shared:
                    first_shared[w] = f"{p}_{w}"
        if s.doublet is not None:
            d = s.doublet
            _add_fixed_or_bounded(params, f"{p}_split", d.splitting, d.splitting_tolerance)
            _add_fixed_or_bounded(params, f"{p}_ratio", d.area_ratio, d.ratio_tolerance)
            m = f"{p}m"
            params.add(f"{m}_center", expr=f"{p}_center + {p}_split")
            params.add(f"{m}_area", expr=f"{p}_area * {p}_ratio")
            for w in names:
                if d.share_widths:
                    params.add(f"{m}_{w}", expr=f"{p}_{w}")
                else:
                    bmin, bmax = c.bounds(w)
                    params.add(
                        f"{m}_{w}",
                        value=_clip_inside(getattr(s, w), bmin, bmax),
                        min=bmin,
                        max=bmax,
                    )
    active = settings.background.is_active
    if active:
        if y is None:
            raise FitError("an active background needs the data to initialise")
        offset, scatter = _active_start(x, y, background)
        params.add("bg_offset", value=offset)
        window = settings.background.scatter_window
        if window is not None and scatter > 0:
            # Keep k near the endpoint-based estimate: without a window a weak edge
            # component and the scattering factor can compensate each other.
            params.add(
                "bg_scatter",
                value=scatter,
                min=scatter / (1.0 + window),
                max=scatter * (1.0 + window),
            )
        else:
            params.add("bg_scatter", value=scatter, min=0.0)
        if settings.refine_linear_background:
            params.add("bg_slope", value=0.0)
    elif settings.refine_linear_background:
        params.add("bg_offset", value=0.0)
        params.add("bg_slope", value=0.0)
    return params


# -------------------------------------------------------------------------- the model
@dataclass
class ModelContext:
    """Everything needed to evaluate the model for one set of parameter values."""

    x: np.ndarray
    specs: list[ComponentSpec]
    shape: str
    refine_bg: bool
    active: str | None
    """``None`` (static background), ``"shirley"`` or ``"tougaard"``."""
    x_center: float
    kernel: np.ndarray | None = None

    @classmethod
    def create(
        cls, x: np.ndarray, specs: list[ComponentSpec], settings: FitSettings
    ) -> ModelContext:
        active = settings.background.type if settings.background.is_active else None
        kernel = None
        if active == "tougaard":
            kernel = tougaard_kernel(x, settings.background.tougaard_C)
        return cls(
            x,
            specs,
            settings.shape,
            settings.refine_linear_background,
            active,
            0.5 * float(x[0] + x[-1]),
            kernel,
        )

    def components(self, values: dict[str, float]) -> list[np.ndarray]:
        return evaluate_components(values, self.specs, self.shape, self.x)

    def envelope(self, values: dict[str, float]) -> np.ndarray:
        total = np.zeros_like(self.x, dtype=float)
        for comp in self.components(values):
            total += comp
        return total

    def operator(self, envelope: np.ndarray) -> np.ndarray:
        """``S[envelope]`` of the active background (unit scattering factor)."""
        if self.active == "shirley":
            return shirley_operator(self.x, envelope)
        if self.active == "tougaard" and self.kernel is not None:
            return self.kernel @ envelope
        return np.zeros_like(envelope)

    def active_background(self, values: dict[str, float], envelope: np.ndarray) -> np.ndarray:
        """Fitted background proper (offset + scattering term); zeros when static."""
        if self.active is None:
            return np.zeros_like(self.x, dtype=float)
        return values["bg_offset"] + values["bg_scatter"] * self.operator(envelope)

    def adjust(self, values: dict[str, float]) -> np.ndarray:
        """Linear refinement term (offset + slope when static; slope only when active)."""
        out = np.zeros_like(self.x, dtype=float)
        if self.refine_bg:
            out += values["bg_slope"] * (self.x - self.x_center)
            if self.active is None:
                out += values["bg_offset"]
        return out

    def total(self, values: dict[str, float]) -> np.ndarray:
        """Model to compare with the target: ``y`` (active) or ``y_net`` (static)."""
        env = self.envelope(values)
        return env + self.active_background(values, env) + self.adjust(values)


def evaluate_components(
    values: dict[str, float], specs: list[ComponentSpec], shape: str, x: np.ndarray
) -> list[np.ndarray]:
    names = SHAPES[shape].params
    out: list[np.ndarray] = []
    for key, _s, _minor in _keys(specs):
        widths = {w: values[f"{key}_{w}"] for w in names}
        out.append(evaluate(shape, x, values[f"{key}_area"], values[f"{key}_center"], **widths))
    return out


def evaluate_total(
    values: dict[str, float],
    specs: list[ComponentSpec],
    shape: str,
    x: np.ndarray,
    refine_bg: bool,
    x_center: float,
) -> np.ndarray:
    """Peak envelope plus the static linear refinement (kept for compatibility)."""
    ctx = ModelContext(x, specs, shape, refine_bg, None, x_center)
    return ctx.total(values)


def _residual(
    params: lmfit.Parameters,
    ctx: ModelContext,
    target: np.ndarray,
    w: np.ndarray | None,
    keep: np.ndarray | None = None,
) -> np.ndarray:
    r = ctx.total(params.valuesdict()) - target
    if w is not None:
        r = r * w
    return r[keep] if keep is not None else r


def detect_spikes(
    y: np.ndarray, sigma: np.ndarray | None = None, threshold: float = 6.0
) -> np.ndarray:
    """Boolean mask of isolated outliers one or two points wide.

    A point is a spike when it lies more than ``threshold`` local standard deviations
    *above both* of its neighbours (or below both: a dropout); two adjacent points
    are a spike when both exceed the points on either side of the pair by that
    margin.  A smooth slope or a peak several points wide never satisfies this,
    whereas a cosmic-ray hit or a detector glitch does.  ``sigma`` gives the local
    standard deviation (counting statistics); without it the robust scale of the
    first differences is used.
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    mask = np.zeros(n, dtype=bool)
    if n < 7:
        return mask
    if sigma is not None:
        local = np.maximum(np.asarray(sigma, dtype=float), 1e-12)
    else:
        d = np.diff(y)
        mad = float(np.median(np.abs(d - np.median(d))))
        local = np.full(n, max(1.4826 * mad / np.sqrt(2.0), 1e-12))
    t = threshold * local
    c = y[1:-1]
    left, right = y[:-2], y[2:]
    single = (c - np.maximum(left, right) > t[1:-1]) | (np.minimum(left, right) - c > t[1:-1])
    mask[1:-1] |= single
    a, b = y[1:-2], y[2:-1]
    outer_lo, outer_hi = y[:-3], y[3:]
    pair_hi = np.minimum(a, b) - np.maximum(outer_lo, outer_hi) > np.maximum(t[1:-2], t[2:-1])
    pair_lo = np.minimum(outer_lo, outer_hi) - np.maximum(a, b) > np.maximum(t[1:-2], t[2:-1])
    pair = pair_hi | pair_lo
    mask[1:-2] |= pair
    mask[2:-1] |= pair
    return mask


# ---------------------------------------------------------------------------- fitting
def fit_peaks(
    spectrum: Spectrum,
    specs: list[ComponentSpec],
    settings: FitSettings | None = None,
    background: BackgroundResult | None = None,
) -> FitResult:
    """Fit ``specs`` to ``spectrum`` (already cropped to the region of interest).

    ``background`` may supply a precomputed static background; with an active
    background it only provides the starting values of offset and scattering factor.
    """
    settings = settings or FitSettings()
    if spectrum.axis != "binding":
        raise FitError("fit requires a binding-energy axis; call Spectrum.to_binding() first")
    if settings.background.type == "auto" or settings.background.mode == "auto":
        raise FitError("background 'auto' must be resolved by model selection before fitting")
    x = spectrum.energy
    y = spectrum.intensity
    if background is None:
        background = compute_background(x, y, settings.background)
    active = settings.background.is_active
    y_net = y - background.values

    sigma = spectrum.sigma if settings.weighting in ("auto", "poisson") else None
    if settings.weighting == "poisson" and sigma is None:
        raise FitError(
            "Poisson weighting requested but the spectrum carries no counting statistics"
        )
    w = (1.0 / sigma) if sigma is not None else None
    scale_covar = settings.scale_covar if settings.scale_covar is not None else (w is None)

    extra_warnings: list[str] = []
    mask: np.ndarray | None = None
    keep: np.ndarray | None = None
    if settings.spike_sigma is not None and spectrum.step > MAX_SPIKE_STEP:
        extra_warnings.append(
            f"spike mask skipped: step {spectrum.step:.2f} eV is too coarse to tell a spike "
            f"from a narrow line (limit {MAX_SPIKE_STEP:g} eV)"
        )
    elif settings.spike_sigma is not None:
        mask = detect_spikes(y, spectrum.sigma, settings.spike_sigma)
        n_mask = int(mask.sum())
        if n_mask > MAX_MASKED_FRACTION * y.size:
            extra_warnings.append(
                f"spike mask skipped: {n_mask} of {y.size} points exceed "
                f"{settings.spike_sigma:g} sigma; that is not a few spikes"
            )
            mask = None
        elif n_mask:
            keep = ~mask
            where = ", ".join(f"{float(e):.2f}" for e in x[mask][:6])
            extra_warnings.append(f"{n_mask} spike(s) masked at {where} eV")
        else:
            mask = None

    params = build_parameters(specs, settings, x, y, background)
    ctx = ModelContext.create(x, specs, settings)
    target = y if active else y_net
    args = (ctx, target, w, keep)
    try:
        if settings.optimizer == "global":
            params = _global_search(params, args, settings, ctx, target)
        if settings.loss == "linear":
            res = lmfit.minimize(
                _residual,
                params,
                args=args,
                method=settings.method,
                max_nfev=settings.max_nfev,
                scale_covar=scale_covar,
                nan_policy="raise",
            )
        else:
            f_scale = settings.loss_scale
            if w is None:
                r0 = _residual(params, *args)
                mad = float(np.median(np.abs(r0 - np.median(r0))))
                f_scale *= max(1.4826 * mad, 1e-9 * float(np.max(np.abs(target)) or 1.0))
            res = lmfit.minimize(
                _residual,
                params,
                args=args,
                method="least_squares",
                max_nfev=settings.max_nfev,
                scale_covar=scale_covar,
                nan_policy="raise",
                loss=settings.loss,
                f_scale=f_scale,
            )
            extra_warnings.append(
                f"robust loss {settings.loss} (scale {f_scale:.3g}): standard errors are "
                "the linearised estimate; compare with a bootstrap"
            )
    except Exception as exc:  # lmfit raises a variety of exception types
        raise FitError(f"optimiser failed: {exc}") from exc
    result = _build_result(res, spectrum, specs, settings, background, ctx, sigma, w, mask)
    result.warnings[0:0] = extra_warnings
    return result


def _global_search(
    params: lmfit.Parameters,
    args: tuple[Any, ...],
    settings: FitSettings,
    ctx: ModelContext,
    target: np.ndarray,
) -> lmfit.Parameters:
    """Differential evolution inside finite bounds; returns the best point as a start.

    Areas and the background terms have no natural upper bound, so generous
    data-driven bounds are set for the search only.
    """
    x = ctx.x
    span = float(x[-1] - x[0])
    peak = float(max(np.ptp(target), np.max(np.abs(target)), 1e-9))
    area_max = 4.0 * peak * span
    search = params.copy()
    s_max = 0.0
    if ctx.active is not None:
        s_max = float(np.max(ctx.operator(ctx.envelope(params.valuesdict()))))
    for name, par in search.items():
        if not par.vary:
            continue
        if name.endswith("_area"):
            par.set(min=0.0, max=area_max)
        elif name == "bg_offset":
            par.set(min=par.value - peak, max=par.value + peak)
        elif name == "bg_slope":
            par.set(min=-peak / span, max=peak / span)
        elif name == "bg_scatter" and not np.isfinite(par.max):
            hi = max(3.0 * peak / s_max if s_max > 0 else 0.0, 10.0 * par.value, 1e-6)
            par.set(min=0.0, max=hi)
        if not (np.isfinite(par.min) and np.isfinite(par.max)):
            raise FitError(f"global search needs finite bounds for {name}")
        par.value = float(np.clip(par.value, par.min, par.max))
    res = lmfit.minimize(
        _residual,
        search,
        args=args,
        method="differential_evolution",
        max_nfev=settings.global_max_nfev,
        popsize=settings.global_popsize,
        tol=1e-4,
        seed=int(settings.seed or 0),
        polish=False,
        calc_covar=False,
    )
    out = params.copy()
    for name, par in res.params.items():
        if out[name].vary:
            lo, hi = out[name].min, out[name].max
            out[name].value = float(np.clip(par.value, lo, hi))
    return out


def _component_of(name: str) -> str:
    """``c0_area`` -> ``c0``; ``bg_offset`` -> ``bg``; shared widths count as background."""
    return name.split("_", 1)[0]


def parameter_correlations(res: Any) -> tuple[list[dict[str, Any]], float | None, str | None]:
    """Strongly correlated free-parameter pairs from the covariance matrix.

    Returns ``(pairs, max_cross, pair_label)`` where ``pairs`` lists every pair with
    ``|r| >= CORRELATION_REPORT`` (strongest first) and ``max_cross`` is the largest
    ``|r|`` between parameters of *different* components (a width shared across
    components is attributed to the first one).  Correlations inside one component
    (its own area and width, say) are expected and not counted in ``max_cross``.
    """
    covar = getattr(res, "covar", None)
    names = list(getattr(res, "var_names", []) or [])
    if covar is None or len(names) < 2:
        return [], None, None
    covar = np.asarray(covar, dtype=float)
    d = np.sqrt(np.clip(np.diag(covar), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = covar / np.outer(d, d)
    pairs: list[dict[str, Any]] = []
    max_cross = 0.0
    label: str | None = None
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            r = float(corr[i, j])
            if not np.isfinite(r):
                continue
            same = _component_of(names[i]) == _component_of(names[j])
            if not same and abs(r) > max_cross:
                max_cross = abs(r)
                label = f"{names[i]} ~ {names[j]}"
            if abs(r) >= CORRELATION_REPORT:
                pairs.append({"a": names[i], "b": names[j], "r": r, "same_component": same})
    pairs.sort(key=lambda p: -abs(p["r"]))
    return pairs, (max_cross if label is not None else None), label


def _stderr(par: lmfit.Parameter) -> float | None:
    """Standard error, or ``None`` when it is missing or meaningless.

    A parameter resting on a bound gets a vanishing error from the bound transform;
    such values are reported as unavailable rather than as near-certainty.
    """
    e = par.stderr
    if e is None or not np.isfinite(e) or e <= 0:
        return None
    if abs(par.value) > 0 and e < 1e-9 * abs(par.value):
        return None
    return float(e)


def _clean(v: Any) -> Any:
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def residual_diagnostics(r: np.ndarray) -> tuple[float | None, float | None, float | None]:
    """``(Durbin-Watson, runs-test z, lag-1 autocorrelation)`` of a residual series."""
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 8:
        return None, None, None
    ss = float(np.sum(r**2))
    if ss <= 0:
        return None, None, None
    dw = float(np.sum(np.diff(r) ** 2) / ss)
    lag1 = float(np.sum(r[1:] * r[:-1]) / ss)
    signs = np.sign(r)
    signs = signs[signs != 0]
    n1 = int(np.sum(signs > 0))
    n2 = int(np.sum(signs < 0))
    runs_z: float | None = None
    if n1 > 0 and n2 > 0:
        runs = 1 + int(np.sum(signs[1:] != signs[:-1]))
        n = n1 + n2
        mu = 2.0 * n1 * n2 / n + 1.0
        var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n**2 * (n - 1))
        if var > 0:
            runs_z = float((runs - mu) / math.sqrt(var))
    return dw, runs_z, lag1


def _build_result(
    res: Any,
    spectrum: Spectrum,
    specs: list[ComponentSpec],
    settings: FitSettings,
    background: BackgroundResult,
    ctx: ModelContext,
    sigma: np.ndarray | None,
    w: np.ndarray | None,
    mask: np.ndarray | None = None,
) -> FitResult:
    x = spectrum.energy
    y = spectrum.intensity
    shape = settings.shape
    names = SHAPES[shape].params
    values = res.params.valuesdict()
    comp_values = ctx.components(values)
    envelope = np.zeros_like(x, dtype=float)
    for cv in comp_values:
        envelope += cv
    bg_adjust = ctx.adjust(values)
    warnings: list[str] = list(background.warnings)
    if ctx.active is not None:
        bg_values = ctx.active_background(values, envelope)
        k = res.params["bg_scatter"]
        info = {
            **background.info,
            "mode": "active",
            "offset": float(values["bg_offset"]),
            "scatter": float(values["bg_scatter"]),
            "scatter_start": float(k.init_value if k.init_value is not None else k.value),
            "scatter_window": settings.background.scatter_window,
        }
        if settings.background.scatter_window is not None and np.isfinite(k.max) and k.vary:
            at_bound = k.value <= k.min * 1.001 or k.value >= k.max * 0.999
            if at_bound:
                warnings.append(
                    f"active background: scattering factor k = {k.value:.4g} sits at the edge "
                    f"of its window [{k.min:.4g}, {k.max:.4g}] around the static estimate; "
                    "widen scatter_window (or set it to null) if the endpoints are unreliable"
                )
        background = BackgroundResult(bg_values, settings.background, info, list(warnings))
    y_net = y - background.values
    residual = y_net - bg_adjust - envelope

    uvars = None
    if getattr(res, "errorbars", False):
        try:
            uvars = res.uvars
        except Exception:  # pragma: no cover - depends on lmfit version
            uvars = None
    else:
        warnings.append("covariance unavailable; no standard errors (fit at a bound or singular)")

    components: list[Component] = []
    for (key, s, minor), vals in zip(_keys(specs), comp_values):
        p = res.params
        widths = {wn: float(p[f"{key}_{wn}"].value) for wn in names}
        fw = total_fwhm(shape, **widths)
        fw_err: float | None = None
        if shape == "voigt":
            if uvars is not None:
                try:
                    from uncertainties import umath

                    ufg, ufl = uvars[f"{key}_fwhm_g"], uvars[f"{key}_fwhm_l"]
                    fw_err = float((0.5346 * ufl + umath.sqrt(0.2166 * ufl**2 + ufg**2)).std_dev)
                except Exception:  # pragma: no cover
                    fw_err = None
        elif shape not in GL_SHAPES:
            fw_err = _stderr(p[f"{key}_fwhm"])
        comp = Component(
            label=minor_label(s.label) if minor else s.label,
            shape=shape,
            is_minor=minor,
            parent=s.label,
            area=float(p[f"{key}_area"].value),
            center=float(p[f"{key}_center"].value),
            fwhm=fw,
            height=shape_height(shape, float(p[f"{key}_area"].value), **widths),
            area_err=_stderr(p[f"{key}_area"]),
            center_err=_stderr(p[f"{key}_center"]),
            fwhm_err=fw_err,
            fwhm_g=widths.get("fwhm_g"),
            fwhm_g_err=_stderr(p[f"{key}_fwhm_g"]) if "fwhm_g" in names else None,
            fwhm_l=widths.get("fwhm_l"),
            fwhm_l_err=_stderr(p[f"{key}_fwhm_l"]) if "fwhm_l" in names else None,
            eta=widths.get("eta"),
            eta_err=_stderr(p[f"{key}_eta"]) if "eta" in names else None,
            asym=widths.get("asym"),
            asym_err=_stderr(p[f"{key}_asym"]) if "asym" in names else None,
            values=vals,
        )
        components.append(comp)
    total = sum(c.area for c in components)
    for c in components:
        c.fraction = 100.0 * c.area / total if total > 0 else None
        if not c.is_minor and total > 0:
            parent_area = sum(d.area for d in components if d.parent == c.parent)
            c.component_fraction = 100.0 * parent_area / total

    keep = ~mask if mask is not None else np.ones(x.size, dtype=bool)
    n = int(keep.sum())
    k = int(res.nvarys)
    used = residual[keep]
    rss = float(np.sum(used**2))
    weighted = w is not None
    if w is not None:
        scaled = used * w[keep]
        chisqr = float(np.sum(scaled**2))
        loglike_term = chisqr
    else:
        scaled = used
        chisqr = rss
        loglike_term = n * math.log(max(rss, 1e-300) / n)
    aic = loglike_term + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1)) if n - k - 1 > 0 else float("inf")
    bic = loglike_term + k * math.log(n)
    dw, runs_z, lag1 = residual_diagnostics(scaled)
    correlations, max_corr, corr_pair = parameter_correlations(res)
    stats = FitStatistics(
        ndata=n,
        nvarys=k,
        nfree=n - k,
        rss=rss,
        chisqr=chisqr,
        redchi=chisqr / max(n - k, 1),
        aic=aic,
        aicc=aicc,
        bic=bic,
        weighted=weighted,
        success=bool(res.success),
        message=str(res.message),
        nfev=int(res.nfev),
        errorbars=bool(getattr(res, "errorbars", False)),
        durbin_watson=dw,
        runs_z=runs_z,
        lag1_autocorr=lag1,
        n_masked=int(x.size - n),
        max_correlation=max_corr,
        max_correlation_pair=corr_pair,
        loss=settings.loss,
    )
    if not res.success:
        warnings.append(f"optimiser reported failure: {res.message}")

    params_out: dict[str, dict[str, Any]] = {}
    unreliable: list[str] = []
    for name, par in res.params.items():
        err = _stderr(par)
        if par.vary and stats.errorbars and err is None:
            unreliable.append(name)
        params_out[name] = {
            "value": _clean(float(par.value)),
            "stderr": err,
            "vary": bool(par.vary),
            "expr": par.expr,
            "min": _clean(float(par.min)),
            "max": _clean(float(par.max)),
            "init_value": _clean(par.init_value) if par.init_value is not None else None,
        }
    if unreliable:
        warnings.append(
            "standard errors unavailable for parameters at a bound: " + ", ".join(unreliable)
        )
    return FitResult(
        x=x,
        y=y,
        background=background,
        bg_adjust=bg_adjust,
        y_net=y_net,
        envelope=envelope,
        residual=residual,
        sigma=sigma,
        components=components,
        params=params_out,
        stats=stats,
        settings=settings,
        specs=specs,
        warnings=warnings,
        mask=mask,
        correlations=correlations,
    )


def specs_from_result(result: FitResult) -> list[ComponentSpec]:
    """Component specs whose initial values are the fitted values (for refits/bootstrap)."""
    out: list[ComponentSpec] = []
    majors = result.majors()
    for s, c in zip(result.specs, majors):
        new = ComponentSpec(**{**s.__dict__})
        new.center = c.center
        new.area = c.area
        if c.fwhm_g is not None:
            new.fwhm_g = c.fwhm_g
        if c.fwhm_l is not None:
            new.fwhm_l = c.fwhm_l
        if result.settings.shape not in GL_SHAPES:
            new.fwhm = c.fwhm
        if c.eta is not None:
            new.eta = c.eta
        if c.asym is not None:
            new.asym = c.asym
        out.append(new)
    return out


def minor_label(label: str) -> str:
    """Label of the minor doublet line that belongs to the major line *label*."""
    return f"{label} (minor)"


def rename_component(result: FitResult, old: str, new: str) -> FitResult:
    """A copy of *result* in which the chemical component *old* (the label of a major
    line) is called *new*.

    The major line, its minor doublet line (``"<new> (minor)"``) and the spec the
    component was fitted from are renamed together, so refits, tables, figures and the
    project file all carry the new name.  Nothing numerical changes; parameter names
    (``c0_area`` ...) stay as they are.

    Raises ``ValueError`` for an unknown component, an empty name or a name another
    component already has.
    """
    new = new.strip()
    labels = [c.label for c in result.majors()]
    if old not in labels:
        raise ValueError(f"no component called {old!r}")
    if not new:
        raise ValueError("a component name cannot be empty")
    if new == old:
        return result
    if new in labels:
        raise ValueError(f"a component called {new!r} already exists")
    components = [
        replace(c, label=minor_label(new) if c.is_minor else new, parent=new)
        if c.parent == old
        else c
        for c in result.components
    ]
    specs = [replace(s, label=new) if s.label == old else s for s in result.specs]
    return replace(result, components=components, specs=specs)
