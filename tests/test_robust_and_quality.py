"""Robust loss, spike masking, parameter correlations and the quality grade (0.4)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from xps_autofit.automation.model_selection import select_model
from xps_autofit.core.constraints import PeakConstraints, Violation, check_physical
from xps_autofit.core.fitting import (
    ComponentSpec,
    FitSettings,
    detect_spikes,
    fit_peaks,
)
from xps_autofit.core.quality import grade_fit
from xps_autofit.core.region import RegionSpec
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.export.tables import candidates_table
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import (
    SynthComponent,
    SynthRegion,
    p3ht_s2p,
    synthesize,
)


def _spiked(seed: int) -> tuple[Spectrum, dict, list[int]]:
    """Oxidised S 2p with three single-point spikes and one two-point spike."""
    spec, truth = synthesize(p3ht_s2p(True), seed=seed)
    y = spec.intensity.copy()
    rng = np.random.default_rng(seed)
    idx = sorted(rng.choice(np.arange(60, spec.n - 20), 3, replace=False).tolist())
    for i in idx:
        y[i] += 15 * np.sqrt(max(y[i], 1.0)) + 3000
    y[idx[0] + 1] += 2000
    spiky = Spectrum(spec.energy, y, name="spiky", intensity_unit="counts", photon_energy=1486.6)
    return spiky, truth, sorted(idx + [idx[0] + 1])


def test_detect_spikes_finds_injected_points_only():
    spiky, _truth, where = _spiked(4)
    mask = detect_spikes(spiky.intensity, spiky.sigma, 6.0)
    assert np.where(mask)[0].tolist() == where
    clean, _ = synthesize(p3ht_s2p(True), seed=4)
    assert not detect_spikes(clean.intensity, clean.sigma, 6.0).any()


def test_detect_spikes_without_sigma_uses_robust_scale():
    spiky, _truth, where = _spiked(5)
    mask = detect_spikes(spiky.intensity, None, 6.0)
    assert set(where) <= set(np.where(mask)[0].tolist())


@pytest.mark.parametrize("seed", [4, 5])
def test_spike_mask_restores_the_two_component_model(seed):
    spiky, truth, where = _spiked(seed)
    region = replace(load_recipe("p3ht").region("S 2p"), spike_sigma=6.0)
    sel = select_model(spiky, region)
    best = sel.best
    assert best is not None
    r = best.result
    assert r.stats.n_masked == len(where)
    assert r.mask is not None and r.mask.sum() == len(where)
    assert best.n_components == 2
    assert r.stats.redchi < 2.0
    truth_area = {c["label"]: c["area"] for c in truth["components"]}
    for c in r.majors():
        assert abs(c.area - truth_area[c.parent]) / truth_area[c.parent] < 0.03
    assert any("spike" in w for w in r.warnings)
    assert best.grade is not None and best.grade.letter == "A"


def test_robust_loss_resists_spikes_without_masking():
    spiky, truth, _where = _spiked(4)
    region = load_recipe("p3ht").region("S 2p")
    robust = select_model(spiky, replace(region, loss="soft_l1")).best
    assert robust is not None
    assert robust.n_components == 2
    assert robust.result.stats.loss == "soft_l1"
    truth_area = {c["label"]: c["area"] for c in truth["components"]}
    for c in robust.result.majors():
        assert abs(c.area - truth_area[c.parent]) / truth_area[c.parent] < 0.03
    assert any("robust loss" in w for w in robust.result.warnings)
    # Ordinary least squares is pulled towards the spikes: it fits the clean points
    # worse and the spikes better than the robust fit does.
    plain = select_model(spiky, region).best
    assert plain is not None
    spikes = detect_spikes(spiky.intensity, spiky.sigma, 6.0)
    crop = slice(np.searchsorted(spiky.energy, 160.0), None)
    spikes = spikes[crop]
    rss_clean = lambda r: float(np.sum(r.residual[~spikes] ** 2))  # noqa: E731
    rss_spikes = lambda r: float(np.sum(r.residual[spikes] ** 2))  # noqa: E731
    assert rss_clean(robust.result) <= rss_clean(plain.result)
    assert rss_spikes(robust.result) >= rss_spikes(plain.result)


def test_spike_mask_skipped_for_coarse_steps():
    reg = SynthRegion(
        "coarse", 95.0, 110.0, 0.5, [SynthComponent("c", 102.3, 30000.0, 1.2, 0.3)], 200.0, 400.0
    )
    spec, _ = synthesize(reg, seed=1)
    r = fit_peaks(
        spec, [ComponentSpec("c", 102.3, 30000.0, 1.2, 0.3)], FitSettings(spike_sigma=6.0)
    )
    assert r.stats.n_masked == 0
    assert any("too coarse" in w for w in r.warnings)


def test_masked_points_are_excluded_from_the_statistics():
    spiky, _truth, where = _spiked(5)
    specs = [
        ComponentSpec(
            "a", 164.0, 20000.0, 0.85, 0.15, doublet=p3ht_s2p(True).components[0].doublet
        ),
        ComponentSpec("b", 168.4, 3000.0, 1.4, 0.15, doublet=p3ht_s2p(True).components[1].doublet),
    ]
    masked = fit_peaks(spiky, specs, FitSettings(spike_sigma=6.0))
    plain = fit_peaks(spiky, specs, FitSettings())
    assert masked.stats.ndata == plain.stats.ndata - len(where)
    assert masked.stats.redchi < 0.1 * plain.stats.redchi


def test_parameter_correlations_flag_unresolved_components():
    close = SynthRegion(
        "close",
        95.0,
        110.0,
        0.05,
        [
            SynthComponent("p1", 102.0, 20000.0, 1.0, 0.2),
            SynthComponent("p2", 102.25, 20000.0, 1.0, 0.2),
        ],
        300.0,
        500.0,
    )
    spec, _ = synthesize(close, seed=2)
    constraints = PeakConstraints(min_separation=0.1, correlation_warning=0.9)
    specs = [
        ComponentSpec("p1", 102.0, 20000.0, 1.0, 0.2),
        ComponentSpec("p2", 102.25, 20000.0, 1.0, 0.2),
    ]
    r = fit_peaks(spec, specs, FitSettings(constraints=constraints))
    assert r.stats.max_correlation is not None and r.stats.max_correlation > 0.95
    assert r.stats.max_correlation_pair == "c0_area ~ c1_area"
    assert r.correlations and abs(r.correlations[0]["r"]) >= 0.9
    assert all({"a", "b", "r", "same_component"} <= set(p) for p in r.correlations)
    assert not r.correlations[0]["same_component"]
    _viol, warns = check_physical(r, constraints, spec.range)
    assert any(w.code == "degenerate_parameters" for w in warns)
    assert not any(
        w.code == "degenerate_parameters"
        for w in check_physical(r, PeakConstraints(min_separation=0.1), spec.range)[1]
    ), "the default threshold (0.98) is stricter"

    far = replace(
        close, components=[close.components[0], replace(close.components[1], center=106.0)]
    )
    spec2, _ = synthesize(far, seed=2)
    r2 = fit_peaks(
        spec2,
        [
            ComponentSpec("p1", 102.0, 20000.0, 1.0, 0.2),
            ComponentSpec("p2", 106.0, 20000.0, 1.0, 0.2),
        ],
        FitSettings(constraints=constraints),
    )
    assert r2.stats.max_correlation is not None and r2.stats.max_correlation < 0.8


def test_grade_reflects_checks_and_statistics(fresh_s2p, s2p_region):
    spec, _ = fresh_s2p
    sel = select_model(spec, s2p_region)
    best = sel.best
    assert best is not None and best.grade is not None
    assert best.grade.letter == "A"
    assert best.grade.score >= 90
    r = best.result
    worse = grade_fit(r, [Violation("too_close", "x", "a")], [Violation("w", "y", "a", "warning")])
    assert worse.score == pytest.approx(best.grade.score - 30)
    assert worse.letter in ("B", "C")
    assert any("violation" in reason for reason in worse.reasons)
    assert grade_fit(r).to_dict()["letter"] == best.grade.letter

    table = candidates_table(sel)
    assert {"grade", "quality_score", "max_correlation"} <= set(table.columns)
    assert table.loc[table["selected"], "grade"].iloc[0] == "A"


def test_grade_penalises_structured_residual(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    one = select_model(spec, s2p_region, fixed_n=1).best
    assert one is not None and one.grade is not None
    assert one.result.stats.durbin_watson is not None and one.result.stats.durbin_watson < 1.0
    assert one.grade.letter in ("D", "E")
    assert any("Durbin-Watson" in reason for reason in one.grade.reasons)


def test_settings_and_region_round_trip():
    s = FitSettings(loss="cauchy", loss_scale=2.5, spike_sigma=7.0)
    d = s.to_dict()
    assert d["loss"] == "cauchy" and d["spike_sigma"] == 7.0
    back = FitSettings.from_dict(d)
    assert (back.loss, back.loss_scale, back.spike_sigma) == ("cauchy", 2.5, 7.0)
    with pytest.raises(ValueError):
        FitSettings(loss="l2")
    with pytest.raises(ValueError):
        FitSettings(spike_sigma=0.0)

    region = RegionSpec.from_dict(
        {"name": "r", "range": [1, 2], "loss": "huber", "spike_sigma": 5, "loss_scale": 4}
    )
    assert (region.loss, region.loss_scale, region.spike_sigma) == ("huber", 4.0, 5.0)
    assert region.to_dict()["loss"] == "huber"
    fs = region.fit_settings()
    assert (fs.loss, fs.loss_scale, fs.spike_sigma) == ("huber", 4.0, 5.0)
    assert RegionSpec.from_dict({"name": "r", "spike_sigma": False}).spike_sigma is None
    with pytest.raises(ValueError):
        RegionSpec(name="bad", loss="absolute")

    c = PeakConstraints(correlation_warning=0.9, relative_error_warning=0.3)
    c2 = PeakConstraints.from_dict(c.to_dict())
    assert (c2.correlation_warning, c2.relative_error_warning) == (0.9, 0.3)


def test_robust_fit_reproduces_from_its_own_dict():
    spiky, _truth, _where = _spiked(5)
    specs = [
        ComponentSpec(
            "a", 164.0, 20000.0, 0.85, 0.15, doublet=p3ht_s2p(True).components[0].doublet
        ),
        ComponentSpec("b", 168.4, 3000.0, 1.4, 0.15, doublet=p3ht_s2p(True).components[1].doublet),
    ]
    settings = FitSettings(loss="soft_l1", spike_sigma=6.0)
    r1 = fit_peaks(spiky, specs, settings)
    d = r1.to_dict(include_arrays=True)
    assert d["stats"]["loss"] == "soft_l1" and sum(d["mask"]) == r1.stats.n_masked
    r2 = fit_peaks(
        spiky,
        [ComponentSpec.from_dict(s) for s in d["specs"]],
        FitSettings.from_dict(d["settings"]),
    )
    for name, p in r1.params.items():
        assert r2.params[name]["value"] == pytest.approx(p["value"], rel=1e-9)
