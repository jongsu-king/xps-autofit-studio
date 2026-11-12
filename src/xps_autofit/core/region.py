"""Region specification: everything needed to fit one core level automatically."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from .background import ACTIVE_TYPES, BACKGROUND_MODES, BACKGROUND_TYPES, BackgroundSpec
from .constraints import DoubletSpec, PeakConstraints
from .peak_shapes import SHAPES

if TYPE_CHECKING:
    from .fitting import ComponentLink

AUTO = "auto"
AUTO_BACKGROUNDS = ("shirley", "tougaard", "linear")
AUTO_SHAPES = ("voigt", "pseudo_voigt")
OPTIMIZERS = ("leastsq", "global")
REPORTS = (None, "auger_max", "vbm")
"""What a report-only region (``fit: false``) reports."""


@dataclass(frozen=True)
class Variant:
    """One concrete background / shape combination tried by model selection."""

    background_type: str
    shape: str
    background_mode: str = "static"

    @property
    def active(self) -> bool:
        return self.background_mode == "active" and self.background_type in ACTIVE_TYPES

    @property
    def background_label(self) -> str:
        return f"{self.background_type}(active)" if self.active else self.background_type

    @property
    def label(self) -> str:
        return f"{self.background_label}/{self.shape}"

    def __iter__(self):  # (background_type, shape) unpacking stays valid
        yield self.background_type
        yield self.shape


@dataclass
class CandidateLine:
    """A literature-based candidate chemical state within a region."""

    label: str
    center: float
    window: float = 0.5
    """Half-width (eV) of the window in which the centre may lie."""
    fwhm_g: tuple[float, float] | None = None
    """Optional per-candidate Gaussian width bounds (e.g. broad satellites)."""
    note: str = ""
    links: dict[str, ComponentLink] = field(default_factory=dict)
    """Ties to other candidates of the region (``center`` / ``area`` / ``width``,
    see :class:`~xps_autofit.core.fitting.ComponentLink`); applied whenever the target
    is part of the model, ignored otherwise."""

    @property
    def bounds(self) -> tuple[float, float]:
        return (self.center - self.window, self.center + self.window)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"label": self.label, "center": self.center, "window": self.window}
        if self.fwhm_g is not None:
            d["fwhm_g"] = list(self.fwhm_g)
        if self.note:
            d["note"] = self.note
        if self.links:
            d["links"] = {k: v.to_list(k) for k, v in self.links.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CandidateLine:
        from .fitting import FitError, parse_links

        fw = d.get("fwhm_g")
        label = str(d["label"])
        try:
            parsed = parse_links(d.get("links"), label)
        except FitError as exc:
            raise ValueError(str(exc)) from None
        return cls(
            label=label,
            center=float(d["center"]),
            window=float(d.get("window", 0.5)),
            fwhm_g=(float(fw[0]), float(fw[1])) if fw else None,
            note=str(d.get("note", "")),
            links=parsed,
        )


@dataclass
class RegionSpec:
    """Fit recipe for one spectral region.

    ``background.type``, ``background.mode`` and ``shape`` may be ``"auto"``: every
    combination of :data:`AUTO_BACKGROUNDS` (static and active where it exists) and
    :data:`AUTO_SHAPES` is then fitted and the choice is made with the same criterion
    and physical checks as the number of components.  ``optimizer="global"`` adds a
    differential-evolution search before the Levenberg-Marquardt polish for the
    first start of every model.
    """

    name: str
    element: str | None = None
    line: str | None = None
    range: tuple[float, float] | None = None
    background: BackgroundSpec = field(default_factory=BackgroundSpec)
    refine_background: bool = True
    """Add a free linear term to the background during the fit.  Endpoint-based
    backgrounds are biased by peak tails and noise; the refinement lets the data
    correct that instead of distorting the components."""
    shape: str = "voigt"
    constraints: PeakConstraints = field(default_factory=PeakConstraints)
    doublet: DoubletSpec | None = None
    candidates: list[CandidateLine] = field(default_factory=list)
    min_components: int = 1
    max_components: int = 3
    rsf: float | None = None
    rsf_applies_to: str = "total"
    """``"total"`` (RSF for the whole doublet) or ``"major"``."""
    weighting: str = "auto"
    n_starts: int = 4
    criterion: str = "aicc"
    min_improvement: float = 2.0
    """A model with one more component is adopted only when it lowers the criterion
    by at least this much (Burnham & Anderson: differences below 2 give the more
    complex model no real support)."""
    optimizer: str = "leastsq"
    """``"leastsq"`` (multi-start Levenberg-Marquardt) or ``"global"`` (differential
    evolution inside the bounds, then Levenberg-Marquardt)."""
    loss: str = "linear"
    """Least-squares loss: ``linear`` or a robust loss (``soft_l1``, ``huber``,
    ``cauchy``, ``arctan``) that down-weights residuals beyond ``loss_scale``."""
    loss_scale: float = 3.0
    spike_sigma: float | None = None
    """Exclude isolated points deviating from the running median by more than this
    many local standard deviations (``None``: no spike mask)."""
    require_assignment: bool = False
    fit: bool = True
    """``False`` for report-only regions (e.g. an Auger line whose maximum is used for
    the Auger parameter)."""
    report: str | None = None
    """``"auger_max"``: report the kinetic energy of the maximum (for Auger parameters);
    ``"vbm"``: report the valence-band maximum by linear extrapolation of the leading
    edge (:func:`~xps_autofit.automation.valence_band.find_vb_edge`)."""
    vbm_edge_window: tuple[float, float] = (0.2, 0.6)
    """``report: vbm``: fractions of the rise to the first band maximum fitted as the
    edge."""
    auger_pair: str | None = None
    """Name of the photoelectron region whose main line pairs with this Auger line."""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.range is not None:
            lo, hi = self.range
            self.range = (float(min(lo, hi)), float(max(lo, hi)))
        if self.min_components < 1 or self.max_components < self.min_components:
            raise ValueError("need 1 <= min_components <= max_components")
        if self.rsf_applies_to not in ("total", "major"):
            raise ValueError("rsf_applies_to must be 'total' or 'major'")
        if self.criterion not in ("aicc", "bic", "aic"):
            raise ValueError("criterion must be 'aicc', 'bic' or 'aic'")
        if self.shape != AUTO and self.shape not in SHAPES:
            raise ValueError(f"shape must be 'auto' or one of {sorted(SHAPES)}")
        if self.background.type != AUTO and self.background.type not in BACKGROUND_TYPES:
            raise ValueError(f"background type must be 'auto' or one of {BACKGROUND_TYPES}")
        if self.background.mode != AUTO and self.background.mode not in BACKGROUND_MODES:
            raise ValueError(f"background mode must be 'auto' or one of {BACKGROUND_MODES}")
        if self.optimizer not in OPTIMIZERS:
            raise ValueError(f"optimizer must be one of {OPTIMIZERS}")
        from .fitting import LOSSES, ComponentSpec, FitError, check_link_cycles

        if self.loss not in LOSSES:
            raise ValueError(f"loss must be one of {LOSSES}")
        if self.report not in REPORTS:
            raise ValueError(f"report must be one of {', '.join(r for r in REPORTS if r)}")
        if self.report == "vbm" and self.fit:
            raise ValueError(f"{self.name}: a 'report: vbm' region needs 'fit: false'")
        lo_f, hi_f = self.vbm_edge_window
        if not 0.0 <= lo_f < hi_f <= 1.0:
            raise ValueError("vbm_edge_window needs 0 <= low < high <= 1")
        labels = {c.label for c in self.candidates}
        for cand in self.candidates:
            for kind, link in cand.links.items():
                if link.target not in labels:
                    raise ValueError(
                        f"{self.name}: {cand.label}: {kind} link to {link.target!r}, which is "
                        "not a candidate of this region"
                    )
        specs = [ComponentSpec(c.label, c.center).set_links(dict(c.links)) for c in self.candidates]
        try:
            check_link_cycles(specs)
        except FitError as exc:
            raise ValueError(f"{self.name}: {exc}") from None

    @property
    def candidate_windows(self) -> list[tuple[str, float, float]]:
        return [(c.label, *c.bounds) for c in self.candidates]

    def variants(self) -> list[Variant]:
        """Background / shape combinations to try (each unpacks as ``(type, shape)``)."""
        bgs = AUTO_BACKGROUNDS if self.background.type == AUTO else (self.background.type,)
        shapes = AUTO_SHAPES if self.shape == AUTO else (self.shape,)
        modes = BACKGROUND_MODES if self.background.mode == AUTO else (self.background.mode,)
        out: list[Variant] = []
        for b in bgs:
            for m in modes:
                if m == "active" and b not in ACTIVE_TYPES:
                    continue  # linear/none have no active form; the static one covers it
                for s in shapes:
                    out.append(Variant(b, s, m))
        return out

    def fit_settings(
        self,
        background_type: str | None = None,
        shape: str | None = None,
        background_mode: str | None = None,
    ) -> Any:
        """Concrete :class:`FitSettings`; ``"auto"`` entries need explicit choices."""
        from .fitting import FitSettings

        bg_type = background_type or self.background.type
        shp = shape or self.shape
        mode = background_mode or self.background.mode
        if bg_type == AUTO or shp == AUTO or mode == AUTO:
            raise ValueError("fit_settings() needs a concrete background type, mode and shape")
        bg = replace(self.background, type=bg_type, mode=mode)
        return FitSettings(
            shape=shp,
            background=bg,
            constraints=self.constraints,
            weighting=self.weighting,
            refine_linear_background=self.refine_background,
            optimizer=self.optimizer,
            loss=self.loss,
            loss_scale=self.loss_scale,
            spike_sigma=self.spike_sigma,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "element": self.element,
            "line": self.line,
            "range": list(self.range) if self.range else None,
            "background": self.background.to_dict(),
            "refine_background": self.refine_background,
            "shape": self.shape,
            "constraints": self.constraints.to_dict(),
            "doublet": self.doublet.to_dict() if self.doublet else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "min_components": self.min_components,
            "max_components": self.max_components,
            "rsf": self.rsf,
            "rsf_applies_to": self.rsf_applies_to,
            "weighting": self.weighting,
            "n_starts": self.n_starts,
            "criterion": self.criterion,
            "min_improvement": self.min_improvement,
            "optimizer": self.optimizer,
            "loss": self.loss,
            "loss_scale": self.loss_scale,
            "spike_sigma": self.spike_sigma,
            "require_assignment": self.require_assignment,
            "fit": self.fit,
            "report": self.report,
            **({"vbm_edge_window": list(self.vbm_edge_window)} if self.report == "vbm" else {}),
            "auger_pair": self.auger_pair,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegionSpec:
        doublet_raw = d.get("doublet")
        doublet: DoubletSpec | None
        if doublet_raw in (None, False):
            doublet = None
        elif doublet_raw == "auto":
            from ..database.binding_energies import spin_orbit

            so = spin_orbit(d.get("element"), d.get("line"))
            if so is None:
                raise ValueError(
                    f"doublet: auto requested but no spin-orbit data for "
                    f"{d.get('element')} {d.get('line')}"
                )
            doublet = DoubletSpec(splitting=so[0], area_ratio=so[1], splitting_tolerance=0.02)
        else:
            doublet = DoubletSpec.from_dict(dict(doublet_raw))
        rng = d.get("range")
        return cls(
            name=str(d["name"]),
            element=d.get("element"),
            line=d.get("line"),
            range=(float(rng[0]), float(rng[1])) if rng else None,
            background=BackgroundSpec.from_dict(d.get("background")),
            refine_background=bool(d.get("refine_background", True)),
            shape=str(d.get("shape", "voigt")),
            constraints=PeakConstraints.from_dict(d.get("constraints")),
            doublet=doublet,
            candidates=[CandidateLine.from_dict(c) for c in d.get("candidates", [])],
            min_components=int(d.get("min_components", 1)),
            max_components=int(d.get("max_components", 3)),
            rsf=(float(d["rsf"]) if d.get("rsf") is not None else None),
            rsf_applies_to=str(d.get("rsf_applies_to", "total")),
            weighting=str(d.get("weighting", "auto")),
            n_starts=int(d.get("n_starts", 4)),
            criterion=str(d.get("criterion", "aicc")),
            min_improvement=float(d.get("min_improvement", 2.0)),
            optimizer=str(d.get("optimizer", "leastsq")),
            loss=str(d.get("loss", "linear")),
            loss_scale=float(d.get("loss_scale", 3.0)),
            spike_sigma=(
                float(d["spike_sigma"]) if d.get("spike_sigma") not in (None, False) else None
            ),
            require_assignment=bool(d.get("require_assignment", False)),
            fit=bool(d.get("fit", True)),
            report=d.get("report"),
            vbm_edge_window=(
                (float(d["vbm_edge_window"][0]), float(d["vbm_edge_window"][1]))
                if d.get("vbm_edge_window")
                else (0.2, 0.6)
            ),
            auger_pair=d.get("auger_pair"),
            notes=str(d.get("notes", "")),
        )
