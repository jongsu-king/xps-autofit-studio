"""Region specification: everything needed to fit one core level automatically."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .background import BACKGROUND_TYPES, BackgroundSpec
from .constraints import DoubletSpec, PeakConstraints
from .peak_shapes import SHAPES

AUTO = "auto"
AUTO_BACKGROUNDS = ("shirley", "tougaard", "linear")
AUTO_SHAPES = ("voigt", "pseudo_voigt")
OPTIMIZERS = ("leastsq", "global")


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

    @property
    def bounds(self) -> tuple[float, float]:
        return (self.center - self.window, self.center + self.window)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"label": self.label, "center": self.center, "window": self.window}
        if self.fwhm_g is not None:
            d["fwhm_g"] = list(self.fwhm_g)
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CandidateLine:
        fw = d.get("fwhm_g")
        return cls(
            label=str(d["label"]),
            center=float(d["center"]),
            window=float(d.get("window", 0.5)),
            fwhm_g=(float(fw[0]), float(fw[1])) if fw else None,
            note=str(d.get("note", "")),
        )


@dataclass
class RegionSpec:
    """Fit recipe for one spectral region.

    ``background.type`` and ``shape`` may be ``"auto"``: every combination of
    :data:`AUTO_BACKGROUNDS` and :data:`AUTO_SHAPES` is then fitted and the choice is
    made with the same criterion and physical checks as the number of components.
    ``optimizer="global"`` adds a differential-evolution search before the
    Levenberg-Marquardt polish for the first start of every model.
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
    require_assignment: bool = False
    fit: bool = True
    """``False`` for report-only regions (e.g. an Auger line whose maximum is used for
    the Auger parameter)."""
    report: str | None = None
    """``"auger_max"``: report the kinetic energy of the maximum (for Auger parameters)."""
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
        if self.optimizer not in OPTIMIZERS:
            raise ValueError(f"optimizer must be one of {OPTIMIZERS}")

    @property
    def candidate_windows(self) -> list[tuple[str, float, float]]:
        return [(c.label, *c.bounds) for c in self.candidates]

    def variants(self) -> list[tuple[str, str]]:
        """``(background type, shape)`` combinations to try."""
        bgs = AUTO_BACKGROUNDS if self.background.type == AUTO else (self.background.type,)
        shapes = AUTO_SHAPES if self.shape == AUTO else (self.shape,)
        return [(b, s) for b in bgs for s in shapes]

    def fit_settings(self, background_type: str | None = None, shape: str | None = None) -> Any:
        """Concrete :class:`FitSettings`; ``"auto"`` entries need explicit choices."""
        from .fitting import FitSettings

        bg_type = background_type or self.background.type
        shp = shape or self.shape
        if bg_type == AUTO or shp == AUTO:
            raise ValueError("fit_settings() needs a concrete background type and shape")
        bg = BackgroundSpec(
            type=bg_type,
            endpoint_points=self.background.endpoint_points,
            max_iterations=self.background.max_iterations,
            tolerance=self.background.tolerance,
            tougaard_B=self.background.tougaard_B,
            tougaard_C=self.background.tougaard_C,
        )
        return FitSettings(
            shape=shp,
            background=bg,
            constraints=self.constraints,
            weighting=self.weighting,
            refine_linear_background=self.refine_background,
            optimizer=self.optimizer,
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
            "require_assignment": self.require_assignment,
            "fit": self.fit,
            "report": self.report,
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
            require_assignment=bool(d.get("require_assignment", False)),
            fit=bool(d.get("fit", True)),
            report=d.get("report"),
            auger_pair=d.get("auger_pair"),
            notes=str(d.get("notes", "")),
        )
