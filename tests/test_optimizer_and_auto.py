"""Global optimiser and automatic background / shape selection."""

from __future__ import annotations

import pytest

from xps_autofit.automation.model_selection import select_model
from xps_autofit.core.background import BackgroundError, BackgroundSpec, compute_background
from xps_autofit.core.fitting import ComponentSpec, FitSettings, fit_peaks
from xps_autofit.core.region import RegionSpec
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import p3ht_s2p, synthesize

from .conftest import S2P, assert_close


def test_global_fit_recovers_from_a_bad_start(aged_s2p):
    spec, _ = aged_s2p
    # Deliberately wrong start: both components on the wrong side of the region.
    bad = [
        ComponentSpec(
            "thiophene", 161.0, 500.0, 1.0, 0.2, center_bounds=(160.5, 166.0), doublet=S2P
        ),
        ComponentSpec(
            "oxidised", 170.5, 500.0, 1.0, 0.2, center_bounds=(166.0, 171.5), doublet=S2P
        ),
    ]
    local = fit_peaks(spec, bad, FitSettings(optimizer="leastsq"))
    glob = fit_peaks(spec, bad, FitSettings(optimizer="global", seed=3))
    assert glob.stats.chisqr <= local.stats.chisqr
    centers = sorted(c.center for c in glob.majors())
    assert_close(centers[0], 164.0, abs_=0.05)
    assert_close(centers[1], 168.4, abs_=0.1)
    assert glob.settings.optimizer == "global" and glob.stats.errorbars


def test_global_fit_is_deterministic(aged_s2p):
    spec, _ = aged_s2p
    specs = [ComponentSpec("t", 164.5, 15000, 1.0, 0.2, doublet=S2P)]
    a = fit_peaks(spec, specs, FitSettings(optimizer="global", seed=7))
    b = fit_peaks(spec, specs, FitSettings(optimizer="global", seed=7))
    assert a.majors()[0].center == b.majors()[0].center
    assert a.majors()[0].area == b.majors()[0].area


def test_select_model_with_global_optimizer(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    region = RegionSpec.from_dict({**s2p_region.to_dict(), "optimizer": "global"})
    sel = select_model(spec, region)
    assert sel.best.n_components == 2
    # the global start only ever lowers the best chi-square; a local start may tie
    assert sel.region.optimizer == "global"
    assert sel.status == "ok"
    got = {c.label: c for c in sel.best.result.majors()}
    assert_close(got["thiophene C-S-C"].center, 164.0, abs_=0.03)
    assert_close(got["sulfonate/sulfate"].area, 3000.0, rel=0.1)


def test_auto_background_and_shape(s2p_region):
    spec, _ = synthesize(p3ht_s2p(False), seed=31)
    region = RegionSpec.from_dict(
        {
            **s2p_region.to_dict(),
            "background": {"type": "auto"},
            "shape": "auto",
            "max_components": 2,
        }
    )
    assert len(region.variants()) == 6
    sel = select_model(spec, region)
    assert sel.best is not None and sel.best.n_components == 1
    variants = {c.variant for c in sel.candidates}
    assert variants == {
        f"{b}/{s}" for b in ("shirley", "tougaard", "linear") for s in ("voigt", "pseudo_voigt")
    }
    assert sel.best.background_type in ("shirley", "tougaard", "linear")
    assert sel.background.spec.type == sel.best.background_type
    assert sel.best.result.settings.shape == sel.best.shape
    assert_close(sel.best.result.majors()[0].center, 164.0, abs_=0.03)
    # the project round trip must carry the concrete choice
    d = sel.to_dict(include_arrays=True)
    assert d["best_variant"] == sel.best.variant
    assert d["best"]["fit"]["settings"]["background"]["type"] == sel.best.background_type


def test_auto_entries_are_rejected_where_they_cannot_be_resolved():
    region = RegionSpec(name="x", background=BackgroundSpec(type="auto"))
    with pytest.raises(ValueError):
        region.fit_settings()
    with pytest.raises(BackgroundError):
        compute_background([1.0, 2.0, 3.0, 4.0, 5.0], [1.0] * 5, BackgroundSpec(type="auto"))
    with pytest.raises(ValueError):
        FitSettings(optimizer="annealing")
    with pytest.raises(ValueError):
        RegionSpec(name="y", optimizer="annealing")


def test_recipe_round_trip_keeps_optimizer():
    r = load_recipe("p3ht")
    region = r.region("S 2p")
    region.optimizer = "global"
    d = region.to_dict()
    assert RegionSpec.from_dict(d).optimizer == "global"
