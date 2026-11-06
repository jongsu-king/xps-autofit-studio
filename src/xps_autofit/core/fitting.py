"""Non-linear least-squares peak fitting on top of :mod:`lmfit`.

Model
-----
``I(E) = B(E) + sum_i A_i P_i(E; mu_i, widths_i)`` where ``B`` is computed first
(:mod:`.background`) and subtracted, ``P_i`` are area-normalised shapes and ``A_i``
are areas.  Doublets add a *minor* line tied to its major by expressions
(``center + split``, ``area * ratio``, shared widths), so a doublet is one chemical
component with one set of free parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import lmfit
import numpy as np

from .background import BackgroundResult, BackgroundSpec, compute_background
from .constraints import DoubletSpec, PeakConstraints
from .peak_shapes import SHAPES, evaluate, get_shape, total_fwhm
from .peak_shapes import height as shape_height
from .spectrum import Spectrum


class FitError(RuntimeError):
    """Raised when a fit cannot be set up or the optimiser fails outright."""


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
    """Add a free offset and slope to absorb small background misestimates."""
    optimizer: str = "leastsq"
    """``"leastsq"``: Levenberg-Marquardt from the initial values.  ``"global"``: a
    differential-evolution search inside the parameter bounds first, then
    Levenberg-Marquardt from the best point found (slower, robust to local minima)."""
    global_max_nfev: int = 20000
    global_popsize: int = 12
    seed: int | None = None
    """Seed of the differential-evolution search (``None``: 0, deterministic)."""

    def __post_init__(self) -> None:
        get_shape(self.shape)
        if self.weighting not in ("auto", "poisson", "none"):
            raise ValueError("weighting must be 'auto', 'poisson' or 'none'")
        if self.optimizer not in ("leastsq", "global"):
            raise ValueError("optimizer must be 'leastsq' or 'global'")

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
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FitSettings:
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

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in self.__dict__.items()}


@dataclass
class FitResult:
    """Everything a fit produced.

    ``background.values`` is the fixed background (Shirley etc.); ``bg_adjust`` is the
    optional linear refinement; ``envelope`` is the sum of the peak components only.
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
        }
        if include_arrays:
            d["x"] = self.x.tolist()
            d["y"] = self.y.tolist()
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


def build_parameters(
    specs: list[ComponentSpec], settings: FitSettings, x: np.ndarray
) -> lmfit.Parameters:
    """Translate component specs and constraints into an :class:`lmfit.Parameters`."""
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
    if settings.refine_linear_background:
        params.add("bg_offset", value=0.0)
        params.add("bg_slope", value=0.0)
    return params


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
    total = np.zeros_like(x, dtype=float)
    for comp in evaluate_components(values, specs, shape, x):
        total += comp
    if refine_bg:
        total = total + values["bg_offset"] + values["bg_slope"] * (x - x_center)
    return total


def _residual(
    params: lmfit.Parameters,
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray | None,
    specs: list[ComponentSpec],
    shape: str,
    refine_bg: bool,
    x_center: float,
) -> np.ndarray:
    r = evaluate_total(params.valuesdict(), specs, shape, x, refine_bg, x_center) - y
    return r * w if w is not None else r


# ---------------------------------------------------------------------------- fitting
def fit_peaks(
    spectrum: Spectrum,
    specs: list[ComponentSpec],
    settings: FitSettings | None = None,
    background: BackgroundResult | None = None,
) -> FitResult:
    """Fit ``specs`` to ``spectrum`` (already cropped to the region of interest)."""
    settings = settings or FitSettings()
    if spectrum.axis != "binding":
        raise FitError("fit requires a binding-energy axis; call Spectrum.to_binding() first")
    x = spectrum.energy
    y = spectrum.intensity
    if background is None:
        background = compute_background(x, y, settings.background)
    y_net = y - background.values

    sigma = spectrum.sigma if settings.weighting in ("auto", "poisson") else None
    if settings.weighting == "poisson" and sigma is None:
        raise FitError(
            "Poisson weighting requested but the spectrum carries no counting statistics"
        )
    w = (1.0 / sigma) if sigma is not None else None
    scale_covar = settings.scale_covar if settings.scale_covar is not None else (w is None)
    x_center = 0.5 * float(x[0] + x[-1])

    params = build_parameters(specs, settings, x)
    args = (x, y_net, w, specs, settings.shape, settings.refine_linear_background, x_center)
    try:
        if settings.optimizer == "global":
            params = _global_search(params, args, settings, x, y_net)
        res = lmfit.minimize(
            _residual,
            params,
            args=args,
            method=settings.method,
            max_nfev=settings.max_nfev,
            scale_covar=scale_covar,
            nan_policy="raise",
        )
    except Exception as exc:  # lmfit raises a variety of exception types
        raise FitError(f"optimiser failed: {exc}") from exc
    return _build_result(res, spectrum, specs, settings, background, y_net, sigma, w, x_center)


def _global_search(
    params: lmfit.Parameters,
    args: tuple[Any, ...],
    settings: FitSettings,
    x: np.ndarray,
    y_net: np.ndarray,
) -> lmfit.Parameters:
    """Differential evolution inside finite bounds; returns the best point as a start.

    Areas and the optional linear background term have no natural upper bound, so
    generous data-driven bounds are set for the search only.
    """
    span = float(x[-1] - x[0])
    peak = float(max(np.max(np.abs(y_net)), 1e-9))
    area_max = 4.0 * peak * span
    search = params.copy()
    for name, par in search.items():
        if not par.vary:
            continue
        if name.endswith("_area"):
            par.set(min=0.0, max=area_max)
        elif name == "bg_offset":
            par.set(min=-peak, max=peak)
        elif name == "bg_slope":
            par.set(min=-peak / span, max=peak / span)
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


def _build_result(
    res: Any,
    spectrum: Spectrum,
    specs: list[ComponentSpec],
    settings: FitSettings,
    background: BackgroundResult,
    y_net: np.ndarray,
    sigma: np.ndarray | None,
    w: np.ndarray | None,
    x_center: float,
) -> FitResult:
    x = spectrum.energy
    shape = settings.shape
    names = SHAPES[shape].params
    values = res.params.valuesdict()
    comp_values = evaluate_components(values, specs, shape, x)
    envelope = np.zeros_like(x, dtype=float)
    for cv in comp_values:
        envelope += cv
    if settings.refine_linear_background:
        bg_adjust = values["bg_offset"] + values["bg_slope"] * (x - x_center)
    else:
        bg_adjust = np.zeros_like(x, dtype=float)
    residual = y_net - bg_adjust - envelope
    warnings: list[str] = list(background.warnings)

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
        else:
            fw_err = _stderr(p[f"{key}_fwhm"])
        comp = Component(
            label=f"{s.label} (minor)" if minor else s.label,
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
            values=vals,
        )
        components.append(comp)
    total = sum(c.area for c in components)
    for c in components:
        c.fraction = 100.0 * c.area / total if total > 0 else None
        if not c.is_minor and total > 0:
            parent_area = sum(d.area for d in components if d.parent == c.parent)
            c.component_fraction = 100.0 * parent_area / total

    n = int(x.size)
    k = int(res.nvarys)
    rss = float(np.sum(residual**2))
    weighted = w is not None
    if weighted:
        chisqr = float(np.sum((residual * w) ** 2))
        loglike_term = chisqr
    else:
        chisqr = rss
        loglike_term = n * math.log(max(rss, 1e-300) / n)
    aic = loglike_term + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1)) if n - k - 1 > 0 else float("inf")
    bic = loglike_term + k * math.log(n)
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
        y=spectrum.intensity,
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
        if result.settings.shape != "voigt":
            new.fwhm = c.fwhm
        if c.eta is not None:
            new.eta = c.eta
        out.append(new)
    return out
