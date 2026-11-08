"""Engine additions of 0.5: scatter window of the active background, GL product shape in
model selection, energy-dependent quantification correction, recipe round trip."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from xps_autofit.automation.model_selection import select_model
from xps_autofit.core.background import BackgroundSpec
from xps_autofit.core.fitting import ComponentSpec, FitSettings, fit_peaks
from xps_autofit.core.quantification import (
    NOT_CALCULABLE,
    QuantCorrection,
    atomic_percent,
    atomic_percent_samples,
)
from xps_autofit.core.region import RegionSpec
from xps_autofit.recipes import Recipe, load_recipe, recipe_from_dict
from xps_autofit.synthetic import p3ht_c1s, p3ht_s2p, synthesize

S2P = p3ht_s2p(True).components[0].doublet


def _aged():
    return synthesize(p3ht_s2p(True), seed=2)


# ---------------------------------------------------------------- scatter window
def test_scatter_window_bounds_k_and_records_the_start():
    spec, _ = _aged()
    specs = [
        ComponentSpec("t", 164.1, 15000, 1.0, 0.2, doublet=S2P),
        ComponentSpec("o", 168.3, 2000, 1.2, 0.2, doublet=S2P),
    ]
    r = fit_peaks(spec, specs, FitSettings(background=BackgroundSpec("shirley", mode="active")))
    info = r.background.info
    assert info["scatter_window"] == 0.3
    k0 = info["scatter_start"]
    assert k0 > 0 and k0 / 1.3 <= info["scatter"] <= k0 * 1.3
    assert r.params["bg_scatter"]["min"] == pytest.approx(k0 / 1.3)
    assert r.params["bg_scatter"]["max"] == pytest.approx(k0 * 1.3)
    assert not any("edge of its window" in w for w in r.warnings)

    free = fit_peaks(
        spec,
        specs,
        FitSettings(background=BackgroundSpec("shirley", mode="active", scatter_window=None)),
    )
    assert free.background.info["scatter_window"] is None
    upper = free.params["bg_scatter"]["max"]
    assert upper is None or not np.isfinite(upper)
    # Well-behaved data: the window does not bind, so both fits agree.
    assert free.background.info["scatter"] == pytest.approx(info["scatter"], rel=1e-3)


def test_tight_scatter_window_warns_when_k_hits_the_bound():
    spec, _ = _aged()
    specs = [ComponentSpec("t", 164.1, 15000, 1.0, 0.2, doublet=S2P)]
    r = fit_peaks(
        spec,
        specs,
        FitSettings(background=BackgroundSpec("shirley", mode="active", scatter_window=0.001)),
    )
    k0 = r.background.info["scatter_start"]
    assert r.background.info["scatter"] == pytest.approx(k0, rel=2e-3)
    assert any("edge of its window" in w for w in r.warnings)


def test_scatter_window_survives_region_fit_settings_and_dicts():
    region = load_recipe("p3ht").region("C 1s")
    assert region is not None
    active = replace(
        region, background=replace(region.background, mode="active", scatter_window=0.2)
    )
    settings = active.fit_settings()
    assert settings.background.scatter_window == 0.2
    again = RegionSpec.from_dict(active.to_dict())
    assert again.background.scatter_window == 0.2
    free = BackgroundSpec.from_dict({"type": "shirley", "mode": "active", "scatter_window": None})
    assert free.scatter_window is None
    with pytest.raises(ValueError):
        BackgroundSpec("shirley", mode="active", scatter_window=-0.1)


def test_windowed_active_c1s_stays_near_the_endpoint_estimate():
    """The case that motivated the window: seed 3 of the synthetic C 1s drove k to 1.55 k0
    without it; with the default window the fit stays inside and is closer to the truth."""
    spec, truth = synthesize(p3ht_c1s(), seed=3)
    region = load_recipe("p3ht").region("C 1s")
    assert region is not None
    truth_area = {c["label"]: c["area"] for c in truth["components"]}

    def worst(sel):
        best = sel.best
        assert best is not None
        errs = []
        for c in best.result.majors():
            ta = truth_area.get(c.parent)
            if ta is None:
                near = min(truth["components"], key=lambda t: abs(t["center"] - c.center))
                ta = near["area"]
            errs.append(abs(c.area - ta) / ta)
        return max(errs), best.result.background.info

    free_err, free_info = worst(
        select_model(
            spec,
            replace(
                region, background=replace(region.background, mode="active", scatter_window=None)
            ),
        )
    )
    win_err, win_info = worst(
        select_model(spec, replace(region, background=replace(region.background, mode="active")))
    )
    assert free_info["scatter"] / free_info["scatter_start"] > 1.4
    assert win_info["scatter"] / win_info["scatter_start"] <= 1.3 + 1e-6
    assert win_err < free_err


# ------------------------------------------------------------- GL product in selection
def test_gl_product_region_fits_in_model_selection():
    spec, truth = _aged()
    region = load_recipe("p3ht").region("S 2p")
    assert region is not None
    region = replace(
        region, shape="gl_product", constraints=replace(region.constraints, fwhm=(0.5, 2.5))
    )
    sel = select_model(spec, region)
    assert sel.best is not None and sel.best.n_components == 2
    assert sel.best.variant.endswith("gl_product")
    truth_area = {c["label"]: c["area"] for c in truth["components"]}
    for c in sel.best.result.majors():
        assert abs(c.area - truth_area[c.parent]) / truth_area[c.parent] < 0.05
        assert c.eta is not None and 0.0 <= c.eta <= 1.0


# ------------------------------------------------------------ quantification correction
def test_quant_correction_divides_by_kinetic_energy_power():
    items = [("C 1s", "C", "1s", 1000.0, 1.0), ("O 1s", "O", "1s", 2930.0, 2.93)]
    plain = atomic_percent(items)
    assert plain.status == "OK"
    assert [round(e.atomic_percent, 6) for e in plain.entries] == [50.0, 50.0]
    assert "no transmission" in plain.note

    corr = QuantCorrection(imfp_exponent=0.6, transmission_exponent=-1.0)
    assert corr.exponent == pytest.approx(-0.4)
    ke = {"C 1s": 1486.6 - 284.8, "O 1s": 1486.6 - 532.0}
    fixed = atomic_percent(items, corr, ke)
    assert fixed.status == "OK"
    c, o = fixed.entries
    assert c.kinetic_energy == pytest.approx(ke["C 1s"]) and o.correction_factor == pytest.approx(
        ke["O 1s"] ** -0.4
    )
    # Net exponent -0.4: the faster C 1s electrons get the smaller factor KE**-0.4,
    # dividing by it raises their corrected area -> larger share than the plain 50 %.
    expected_c = (1000 / (1.0 * ke["C 1s"] ** -0.4)) / (
        1000 / (1.0 * ke["C 1s"] ** -0.4) + 2930 / (2.93 * ke["O 1s"] ** -0.4)
    )
    assert c.atomic_percent == pytest.approx(100 * expected_c)
    assert c.atomic_percent > 50 > o.atomic_percent
    assert "KE^(0.6 + -1)" in fixed.note

    missing = atomic_percent(items, corr, {"C 1s": 1200.0})
    assert missing.status == NOT_CALCULABLE and missing.missing == ["O 1s"]

    # bootstrap replicates use the same divisor
    rng = np.random.default_rng(1)
    samples = {"C 1s": 1000 + rng.normal(0, 30, 50), "O 1s": 2930 + rng.normal(0, 60, 50)}
    n = atomic_percent_samples(fixed, samples)
    assert n == 50 and c.atomic_percent_std is not None and c.atomic_percent_std < 2.0
    assert c.atomic_percent_p2_5 < c.atomic_percent < c.atomic_percent_p97_5


def test_quant_correction_round_trips_through_the_recipe():
    base = load_recipe("cu2o")
    assert not base.quantification.active
    d = base.to_dict()
    d["quantification"] = {"imfp_exponent": 0.7, "transmission_exponent": 0.0}
    rec = recipe_from_dict(d, source="test")
    assert isinstance(rec, Recipe) and rec.quantification.exponent == pytest.approx(0.7)
    assert rec.to_dict()["quantification"] == {"imfp_exponent": 0.7, "transmission_exponent": 0.0}
    with pytest.raises(ValueError):
        rec.quantification.factor(0.0)
