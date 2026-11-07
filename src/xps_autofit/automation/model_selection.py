"""Choose the number of components (and, on request, background and line shape)
with statistics *and* physics.

For each variant (background type x shape) and each component count ``n`` in the
allowed range, several initial guesses are fitted and the best (lowest chi-square) is
kept.  Models are then ranked by AICc (or BIC) *among those that pass the physical
checks* in :func:`check_physical`, with a parsimony margin.  If no model passes, the
statistically best one is returned with status ``needs_review``; if another valid
model lies within the margin the status is ``ambiguous``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ..core.background import BackgroundResult, compute_background
from ..core.constraints import Violation, check_physical
from ..core.fitting import ComponentSpec, FitError, FitResult, fit_peaks, specs_from_result
from ..core.peak_shapes import GL_SHAPES, SHAPES, area_from_height, evaluate
from ..core.preprocessing import NoiseReport, estimate_noise, smooth_for_detection
from ..core.region import CandidateLine, RegionSpec, Variant
from ..core.spectrum import Spectrum
from .peak_detection import PeakGuess, detect_peaks, pair_doublets, residual_peak


@dataclass
class Candidate:
    n_components: int
    result: FitResult
    violations: list[Violation]
    warnings: list[Violation]
    criterion: str
    criterion_value: float
    background_type: str = "shirley"
    shape: str = "voigt"
    background_mode: str = "static"

    @property
    def physical_ok(self) -> bool:
        return not self.violations

    @property
    def structured_residual(self) -> bool:
        return any(w.code == "structured_residual" for w in self.warnings)

    @property
    def variant(self) -> str:
        return Variant(self.background_type, self.shape, self.background_mode).label

    def to_dict(self, include_arrays: bool = False) -> dict[str, Any]:
        return {
            "n_components": self.n_components,
            "background_type": self.background_type,
            "background_mode": self.background_mode,
            "shape": self.shape,
            "criterion": self.criterion,
            "criterion_value": self.criterion_value,
            "physical_ok": self.physical_ok,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [v.to_dict() for v in self.warnings],
            "fit": self.result.to_dict(include_arrays=include_arrays),
        }


@dataclass
class SelectionResult:
    region: RegionSpec
    spectrum: Spectrum
    background: BackgroundResult
    noise: NoiseReport
    detected: list[PeakGuess]
    candidates: list[Candidate]
    best: Candidate | None
    status: str
    seed: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self, include_arrays: bool = False) -> dict[str, Any]:
        return {
            "region": self.region.to_dict(),
            "spectrum": self.spectrum.to_dict(include_data=include_arrays),
            "background": self.background.to_dict(include_values=include_arrays),
            "noise": self.noise.to_dict(),
            "detected": [g.to_dict() for g in self.detected],
            "candidates": [c.to_dict(include_arrays=False) for c in self.candidates],
            "best_n": self.best.n_components if self.best else None,
            "best_variant": self.best.variant if self.best else None,
            "best": self.best.to_dict(include_arrays=include_arrays) if self.best else None,
            "status": self.status,
            "seed": self.seed,
            "notes": self.notes,
        }


def derive_seed(spectrum_hash: str, region_name: str, user_seed: int | None) -> int:
    """Deterministic seed from the data and region so batch and single runs agree."""
    h = hashlib.sha256(f"{spectrum_hash}|{region_name}|{user_seed}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def fwhm_hint_for(region: RegionSpec, shape: str | None = None) -> float:
    c = region.constraints
    shp = shape or region.shape
    if shp in GL_SHAPES or shp == "auto":
        lo, hi = c.fwhm_g
    else:
        lo, hi = c.fwhm
    return float(min(max(np.sqrt(lo * hi), 0.4), 2.5))


def _initial_widths(region: RegionSpec, fwhm_guess: float, shape: str) -> dict[str, float]:
    c = region.constraints
    if shape in GL_SHAPES:
        fl = float(np.clip(0.2, *c.fwhm_l))
        fg = float(np.clip(0.9 * fwhm_guess, *c.fwhm_g))
        widths = {"fwhm_g": fg, "fwhm_l": fl}
        if shape == "doniach_sunjic":
            widths["asym"] = float(np.clip(0.05, *c.asym))
        return widths
    if shape == "pseudo_voigt":
        return {"fwhm": float(np.clip(fwhm_guess, *c.fwhm)), "eta": float(np.clip(0.3, *c.eta))}
    return {"fwhm": float(np.clip(fwhm_guess, *c.fwhm))}


def assign_candidates(
    centers: list[float], candidates: list[CandidateLine]
) -> list[CandidateLine | None]:
    """Greedy one-to-one match of guessed centres to candidate windows."""
    pairs = []
    for i, c in enumerate(centers):
        for cand in candidates:
            if cand.bounds[0] <= c <= cand.bounds[1]:
                pairs.append((abs(c - cand.center), i, cand))
    pairs.sort(key=lambda t: t[0])
    out: list[CandidateLine | None] = [None] * len(centers)
    used: set[str] = set()
    for _d, i, cand in pairs:
        if out[i] is None and cand.label not in used:
            out[i] = cand
            used.add(cand.label)
    return out


def specs_from_guesses(
    guesses: list[PeakGuess], region: RegionSpec, shape: str
) -> list[ComponentSpec]:
    assigned = assign_candidates([g.center for g in guesses], region.candidates)
    specs: list[ComponentSpec] = []
    generic = 0
    for g, cand in zip(guesses, assigned):
        widths = _initial_widths(region, g.fwhm, shape)
        if cand is not None and cand.fwhm_g is not None and "fwhm_g" in widths:
            widths["fwhm_g"] = float(np.clip(widths["fwhm_g"], *cand.fwhm_g))
        area = area_from_height(shape, max(g.height, 1e-9), **widths)
        if cand is not None:
            label, cb, fgb = cand.label, cand.bounds, cand.fwhm_g
        else:
            generic += 1
            label, cb, fgb = f"{region.name} #{generic}", None, None
        spec = ComponentSpec(
            label=label,
            center=g.center,
            area=area,
            center_bounds=cb,
            fwhm_g_bounds=fgb,
            doublet=region.doublet,
        )
        for w, v in widths.items():
            setattr(spec, w, v)
        specs.append(spec)
    return _unique_labels(specs)


def _unique_labels(specs: list[ComponentSpec]) -> list[ComponentSpec]:
    seen: dict[str, int] = {}
    for s in specs:
        n = seen.get(s.label, 0) + 1
        seen[s.label] = n
        if n > 1:
            s.label = f"{s.label} ({n})"
    return specs


def _approx_net(
    x: np.ndarray, guesses: list[PeakGuess], region: RegionSpec, shape: str
) -> np.ndarray:
    total = np.zeros_like(x)
    for g in guesses:
        widths = _initial_widths(region, g.fwhm, shape)
        area = area_from_height(shape, max(g.height, 1e-9), **widths)
        total += evaluate(shape, x, area, g.center, **widths)
        if region.doublet is not None:
            d = region.doublet
            total += evaluate(shape, x, area * d.area_ratio, g.center + d.splitting, **widths)
    return total


def _jitter(
    specs: list[ComponentSpec],
    rng: np.random.Generator,
    fwhm_hint: float,
    region: RegionSpec,
    shape: str,
) -> list[ComponentSpec]:
    c = region.constraints
    lo, hi = region.range if region.range else (-np.inf, np.inf)
    out: list[ComponentSpec] = []
    for s in specs:
        new = ComponentSpec(**{**s.__dict__})
        cb = s.center_bounds or (lo + c.edge_margin, hi - c.edge_margin)
        new.center = float(np.clip(s.center + rng.uniform(-0.3, 0.3) * fwhm_hint, cb[0], cb[1]))
        new.area = float(s.area * rng.uniform(0.7, 1.3))
        for w in SHAPES[shape].params:
            if w in ("eta", "asym"):
                continue
            bounds = s.fwhm_g_bounds if (w == "fwhm_g" and s.fwhm_g_bounds) else c.bounds(w)
            setattr(new, w, float(np.clip(getattr(s, w) * rng.uniform(0.8, 1.25), *bounds)))
        out.append(new)
    return out


def candidate_start(
    n: int, region: RegionSpec, x: np.ndarray, y_net: np.ndarray, fwhm_hint: float, shape: str
) -> list[ComponentSpec] | None:
    """Start with components at the ``n`` candidate positions carrying the most signal.

    This is the analyst's prior ('put the peaks where the chemistry says') and
    rescues cases where detected maxima merge overlapping states.
    """
    if len(region.candidates) < n:
        return None
    xu, ys = smooth_for_detection(x, y_net, fwhm_hint)
    scored = []
    for cand in region.candidates:
        if not (x[0] <= cand.center <= x[-1]):
            continue
        h = float(np.interp(cand.center, xu, ys))
        scored.append((h, cand))
    if len(scored) < n:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    guesses = [PeakGuess(c.center, max(h, 1e-9) * 0.7, fwhm_hint, h) for h, c in scored[:n]]
    return specs_from_guesses(guesses, region, shape)


def relabel_generic(result: FitResult, region: RegionSpec) -> None:
    """Rename generic components that ended inside an unused candidate window."""
    if not region.candidates:
        return
    used = {s.label for s in result.specs if any(s.label == c.label for c in region.candidates)}
    for s, m in zip(result.specs, result.majors()):
        if s.label in used or s.center_bounds is not None:
            continue
        for cand in region.candidates:
            if cand.label not in used and cand.bounds[0] <= m.center <= cand.bounds[1]:
                old = s.label
                s.label = cand.label
                used.add(cand.label)
                for comp in result.components:
                    if comp.parent == old:
                        comp.parent = cand.label
                        comp.label = f"{cand.label} (minor)" if comp.is_minor else cand.label
                break


def make_starts(
    n: int,
    majors: list[PeakGuess],
    prev: FitResult | None,
    x: np.ndarray,
    y_net: np.ndarray,
    region: RegionSpec,
    fwhm_hint: float,
    rng: np.random.Generator,
    n_starts: int,
    shape: str | None = None,
) -> list[list[ComponentSpec]]:
    """Initial component sets for an ``n``-component model."""
    shape = shape or region.shape
    c = region.constraints
    base = list(majors[:n])
    if len(base) < n:
        resid = y_net - _approx_net(x, base, region, shape)
        while len(base) < n:
            g = residual_peak(
                x, resid, fwhm_hint, [b.center for b in base], c.min_separation, c.edge_margin
            )
            if g is None:
                # Spread remaining components evenly over the interior of the region.
                pos = x[0] + (x[-1] - x[0]) * (len(base) + 1) / (n + 1)
                g = PeakGuess(float(pos), float(max(np.max(y_net), 1e-9)) * 0.1, fwhm_hint, 0.0)
            base.append(g)
            resid = y_net - _approx_net(x, base, region, shape)
    starts = [specs_from_guesses(base, region, shape)]
    cand_start = candidate_start(n, region, x, y_net, fwhm_hint, shape)
    if cand_start is not None:
        starts.append(cand_start)
    if prev is not None and len(prev.majors()) == n - 1:
        g = residual_peak(
            x,
            prev.residual,
            fwhm_hint,
            [m.center for m in prev.majors()],
            c.min_separation,
            c.edge_margin,
        )
        if g is not None:
            widths = _initial_widths(region, fwhm_hint, shape)
            extra_guess = PeakGuess(g.center, g.height, fwhm_hint, g.prominence)
            extra = specs_from_guesses([extra_guess], region, shape)[0]
            extra.area = area_from_height(shape, max(g.height, 1e-9), **widths)
            combined = specs_from_result(prev) + [extra]
            # Re-assign labels so candidate windows stay one-to-one.
            relabelled = specs_from_guesses(
                [PeakGuess(s.center, 1.0, fwhm_hint, 0.0) for s in combined], region, shape
            )
            for s_new, s_old in zip(relabelled, combined):
                s_new.area = s_old.area
                for w in SHAPES[shape].params:
                    setattr(s_new, w, getattr(s_old, w))
            starts.append(relabelled)
    while len(starts) < n_starts:
        starts.append(_jitter(starts[0], rng, fwhm_hint, region, shape))
    return starts


def _fit_variant(
    spec: Spectrum,
    region: RegionSpec,
    variant: Variant,
    base_seed: int,
    n_values: list[int],
    n_starts: int,
    crit: str,
    notes: list[str],
) -> tuple[list[Candidate], BackgroundResult, NoiseReport, list[PeakGuess]]:
    bg_type, shape = variant.background_type, variant.shape
    settings = region.fit_settings(bg_type, shape, variant.background_mode)
    bg = compute_background(spec.energy, spec.intensity, settings.background)
    y_net = spec.intensity - bg.values
    fwhm_hint = fwhm_hint_for(region, shape)
    noise = estimate_noise(spec.energy, y_net, fwhm_hint)
    tag = variant.label
    for w in bg.warnings:
        notes.append(f"{tag}: {w}")

    n_detect = region.max_components * (2 if region.doublet else 1) + 2
    detected = detect_peaks(
        spec.energy,
        y_net,
        noise.sigma,
        fwhm_hint,
        region.constraints.min_separation,
        n_detect,
        sigma=spec.sigma,
    )
    if region.doublet is not None:
        d = region.doublet
        tol = max(0.25, 3.0 * spec.step, d.splitting_tolerance)
        majors = pair_doublets(detected, d.splitting, d.area_ratio, tol)
    else:
        majors = list(detected)

    candidates: list[Candidate] = []
    prev: FitResult | None = None
    for n in n_values:
        rng = np.random.default_rng(base_seed + n)
        starts = make_starts(
            n, majors, prev, spec.energy, y_net, region, fwhm_hint, rng, n_starts, shape
        )
        best: FitResult | None = None
        failures = 0
        for i, specs in enumerate(starts):
            use = settings
            if settings.optimizer == "global" and i == 0:
                use = replace(settings, seed=base_seed + n)
            else:
                use = replace(settings, optimizer="leastsq")
            try:
                r = fit_peaks(spec, specs, use, background=bg)
            except FitError:
                failures += 1
                continue
            if best is None or r.stats.chisqr < best.stats.chisqr:
                best = r
        if best is None:
            notes.append(f"{tag} n={n}: all {len(starts)} starts failed")
            continue
        if failures:
            notes.append(f"{tag} n={n}: {failures}/{len(starts)} starts failed")
        relabel_generic(best, region)
        violations, warnings = check_physical(
            best,
            region.constraints,
            spec.range,
            region.candidate_windows or None,
            region.require_assignment,
            noise_sigma=noise.sigma,
        )
        candidates.append(
            Candidate(
                n,
                best,
                violations,
                warnings,
                crit,
                float(getattr(best.stats, crit)),
                bg_type,
                shape,
                variant.background_mode,
            )
        )
        prev = best
    return candidates, bg, noise, detected


def select_model(
    spectrum: Spectrum,
    region: RegionSpec,
    *,
    n_starts: int | None = None,
    criterion: str | None = None,
    seed: int | None = None,
    fixed_n: int | None = None,
) -> SelectionResult:
    """Automatic fit of one region with model selection.

    Parameters
    ----------
    spectrum
        Binding-energy spectrum; cropped to ``region.range`` when given.
    fixed_n
        Skip selection and fit exactly this many components.
    """
    if spectrum.axis != "binding":
        raise FitError("select_model requires a binding-energy axis")
    spec = spectrum.crop(*region.range) if region.range else spectrum
    crit = criterion or region.criterion
    n_starts = n_starts or region.n_starts
    base_seed = derive_seed(spec.sha256(), region.name, seed)
    notes: list[str] = []
    n_values = (
        [fixed_n] if fixed_n else list(range(region.min_components, region.max_components + 1))
    )

    candidates: list[Candidate] = []
    per_variant: dict[str, tuple[BackgroundResult, NoiseReport, list[PeakGuess]]] = {}
    for variant in region.variants():
        cands, bg, noise, detected = _fit_variant(
            spec, region, variant, base_seed, n_values, n_starts, crit, notes
        )
        candidates.extend(cands)
        per_variant[variant.label] = (bg, noise, detected)

    first = next(iter(per_variant.values()))
    if not candidates:
        return SelectionResult(
            region, spec, first[0], first[1], first[2], [], None, "failed", base_seed, notes
        )

    best_c, status, why = choose(candidates, region.min_improvement)
    notes.extend(why)
    bg, noise, detected = per_variant[best_c.variant]
    return SelectionResult(
        region, spec, bg, noise, detected, candidates, best_c, status, base_seed, notes
    )


def choose(candidates: list[Candidate], min_improvement: float) -> tuple[Candidate, str, list[str]]:
    """Parsimonious choice among physically valid candidates.

    For each component count the best variant (background/shape) is taken.  Starting
    from the simplest valid model, a more complex one is adopted only when it lowers
    the criterion by at least ``min_improvement``.  Within that margin the residual
    decides: a model whose residual is white replaces one whose residual is
    structured (Durbin-Watson warning) when it also has the lower criterion.  The
    result is ``ambiguous`` when another valid model with a different number of
    components lies within the margin and the residual does not separate them;
    variants within the margin are reported in the notes.
    """
    notes: list[str] = []
    valid = [c for c in candidates if c.physical_ok]
    if not valid:
        best = min(candidates, key=lambda c: c.criterion_value)
        notes.append(
            "no candidate model passed the physical checks; best statistical model returned"
        )
        return best, "needs_review", notes
    by_n: dict[int, Candidate] = {}
    for c in sorted(valid, key=lambda c: (c.n_components, c.criterion_value)):
        by_n.setdefault(c.n_components, c)
    ordered = [by_n[n] for n in sorted(by_n)]
    chosen = ordered[0]
    for cand in ordered[1:]:
        if cand.criterion_value <= chosen.criterion_value - min_improvement:
            chosen = cand
        elif (
            cand.criterion_value < chosen.criterion_value
            and chosen.structured_residual
            and not cand.structured_residual
        ):
            notes.append(
                f"n={cand.n_components} adopted over n={chosen.n_components}: the criterion "
                f"gap is below {min_improvement:g} but the simpler model leaves a structured "
                f"residual (Durbin-Watson {chosen.result.stats.durbin_watson:.2f}) and the "
                f"richer one does not ({cand.result.stats.durbin_watson:.2f})"
            )
            chosen = cand
    crit = chosen.criterion.upper()
    close_n = [
        c
        for c in ordered
        if c is not chosen and abs(c.criterion_value - chosen.criterion_value) < min_improvement
    ]
    close_variants = [
        c
        for c in valid
        if c.n_components == chosen.n_components
        and c is not chosen
        and abs(c.criterion_value - chosen.criterion_value) < min_improvement
    ]
    for c in close_variants:
        notes.append(
            f"{c.variant} is within {abs(c.criterion_value - chosen.criterion_value):.2f} {crit} "
            f"of {chosen.variant} at n={chosen.n_components}; {chosen.variant} is reported"
        )
    # A close model whose residual is structured while the chosen one is white is not a
    # real alternative; it does not make the result ambiguous.
    close_n = [c for c in close_n if not (c.structured_residual and not chosen.structured_residual)]
    if close_n:
        other = min(close_n, key=lambda c: c.criterion_value)
        notes.append(
            f"{crit} difference between n={chosen.n_components} and n={other.n_components} is "
            f"{abs(other.criterion_value - chosen.criterion_value):.2f} (< {min_improvement:g}); "
            f"n={chosen.n_components} is reported"
        )
        return chosen, "ambiguous", notes
    rejected = [
        c for c in candidates if not c.physical_ok and c.criterion_value < chosen.criterion_value
    ]
    for c in rejected:
        notes.append(
            f"n={c.n_components} ({c.variant}) has lower {crit} ({c.criterion_value:.1f}) but "
            "fails: " + "; ".join(v.message for v in c.violations)
        )
    return chosen, "ok", notes
