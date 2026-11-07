"""Active backgrounds, the Doniach-Sunjic line, shoulder detection, residual
diagnostics and bootstrap propagation to atomic percentages."""

from __future__ import annotations

import numpy as np
import pytest

from xps_autofit.automation.model_selection import Candidate, choose, select_model
from xps_autofit.automation.peak_detection import detect_peaks
from xps_autofit.core import peak_shapes as ps
from xps_autofit.core.background import (
    BackgroundError,
    BackgroundSpec,
    compute_background,
    tougaard_kernel,
)
from xps_autofit.core.constraints import PeakConstraints, Violation, check_physical
from xps_autofit.core.fitting import (
    ComponentSpec,
    FitError,
    FitSettings,
    fit_peaks,
    residual_diagnostics,
    specs_from_result,
)
from xps_autofit.core.quantification import atomic_percent, atomic_percent_samples
from xps_autofit.core.region import RegionSpec
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.core.uncertainty import bootstrap

from .conftest import S2P, assert_close


# ------------------------------------------------------------------ Doniach-Sunjic
def test_doniach_sunjic_reduces_to_voigt_without_asymmetry():
    x = np.linspace(-8, 8, 3201)
    ds = ps.doniach_sunjic(x, 1.0, 0.0, 1.0, 0.4, 0.0)
    v = ps.voigt(x, 1.0, 0.0, 1.0, 0.4)
    # the DS area is defined inside +/- 10 FWHM, the Voigt over the whole axis
    w = ps.voigt_fwhm(1.0, 0.4)
    xx = np.linspace(-10 * w, 10 * w, 40001)
    frac = np.trapezoid(ps.voigt(xx, 1.0, 0.0, 1.0, 0.4), xx)
    assert np.max(np.abs(ds * frac - v)) < 1e-3 * v.max()
    assert ps.total_fwhm("doniach_sunjic", fwhm_g=1.0, fwhm_l=0.4, asym=0.0) == pytest.approx(
        w, rel=2e-3
    )


@pytest.mark.parametrize("alpha", [0.05, 0.15, 0.3])
def test_doniach_sunjic_area_and_tail_direction(alpha):
    fg, fl = 0.8, 0.3
    w = ps.voigt_fwhm(fg, fl)
    x = np.linspace(-12 * w, 12 * w, 60001)
    y = ps.doniach_sunjic(x, 250.0, 0.0, fg, fl, alpha)
    inside = np.abs(x) <= ps.DS_AREA_WINDOW * w
    assert np.trapezoid(y[inside], x[inside]) == pytest.approx(250.0, rel=2e-3)
    # the slow tail lies at higher binding energy (x > centre)
    ratio = np.interp(3.0, x, y) / np.interp(-3.0, x, y)
    assert ratio > (2.0 if alpha < 0.1 else 5.0)
    assert np.all(np.isfinite(y)) and np.all(y >= 0)
    # asymmetry broadens the measured width and moves the maximum to higher BE
    assert ps.total_fwhm("doniach_sunjic", fwhm_g=fg, fwhm_l=fl, asym=alpha) > w
    assert x[np.argmax(y)] > 0


def test_fit_recovers_asymmetry_of_a_metallic_line():
    x = np.arange(80.0, 92.0, 0.05)
    true = {"area": 40000.0, "center": 84.0, "fwhm_g": 0.6, "fwhm_l": 0.3, "asym": 0.12}
    signal = ps.doniach_sunjic(x, **true)
    y = np.random.default_rng(3).poisson(signal + 400.0).astype(float)
    spec = Spectrum(x, y, intensity_unit="counts")
    settings = FitSettings(
        shape="doniach_sunjic", background=BackgroundSpec("linear"), refine_linear_background=True
    )
    r = fit_peaks(spec, [ComponentSpec("Au", 84.1, 30000, 0.7, 0.25, asym=0.03)], settings)
    c = r.majors()[0]
    assert r.stats.success and c.asym is not None
    assert_close(c.center, 84.0, abs_=0.02)
    assert_close(c.asym, 0.12, abs_=0.02)
    assert_close(c.area, 40000.0, rel=0.03)
    assert r.stats.redchi < 1.5
    # a symmetric Voigt cannot follow the tail: it leaves a structured residual
    sym = fit_peaks(
        spec,
        [ComponentSpec("Au", 84.1, 30000, 0.7, 0.25)],
        FitSettings(background=BackgroundSpec("linear"), refine_linear_background=True),
    )
    assert sym.stats.redchi > 2 * r.stats.redchi
    assert sym.stats.durbin_watson is not None and r.stats.durbin_watson is not None
    assert sym.stats.durbin_watson < r.stats.durbin_watson


# ---------------------------------------------------------------- active backgrounds
def test_active_shirley_recovers_offset_and_areas(aged_s2p):
    spec, truth = aged_s2p
    specs = [
        ComponentSpec("thiophene", 164.1, 15000, 1.0, 0.2, doublet=S2P),
        ComponentSpec("oxidised", 168.3, 2000, 1.2, 0.2, doublet=S2P),
    ]
    r = fit_peaks(spec, specs, FitSettings(background=BackgroundSpec("shirley", mode="active")))
    info = r.background.info
    assert info["mode"] == "active" and info["scatter"] > 0
    assert_close(info["offset"], truth["background"]["lo"], abs_=8.0)
    assert_close(r.background.values[-1], truth["background"]["hi"], abs_=15.0)
    assert_close(r.majors()[0].area, 20000.0, rel=0.02)
    assert_close(r.components[2].area, 3000.0, rel=0.08)
    assert r.stats.redchi < 1.5
    assert "bg_scatter" in r.params and r.params["bg_scatter"]["vary"]
    assert np.allclose(r.y_net + r.background.values, r.y)
    # the project round trip keeps the mode and reproduces the fit from the result
    again = fit_peaks(spec, specs_from_result(r), FitSettings.from_dict(r.settings.to_dict()))
    assert again.settings.background.mode == "active"
    assert again.majors()[0].area == pytest.approx(r.majors()[0].area, rel=1e-4)


def test_active_tougaard_recovers_scattering_factor():
    x = np.arange(95.0, 125.0, 0.1)
    signal = ps.voigt(x, 60000.0, 102.3, 1.0, 0.3)
    B_true = 3000.0
    bg = 200.0 + B_true * (tougaard_kernel(x) @ signal)
    y = np.random.default_rng(8).poisson(signal + bg).astype(float)
    spec = Spectrum(x, y, intensity_unit="counts")
    r = fit_peaks(
        spec,
        [ComponentSpec("s", 102.0, 50000, 1.1, 0.25)],
        FitSettings(background=BackgroundSpec("tougaard", mode="active")),
    )
    assert_close(r.background.info["scatter"], B_true, rel=0.1)
    assert_close(r.background.info["offset"], 200.0, abs_=10.0)
    assert_close(r.majors()[0].area, 60000.0, rel=0.02)
    assert r.stats.redchi < 1.5


def test_active_background_with_global_optimizer(aged_s2p):
    spec, _ = aged_s2p
    specs = [ComponentSpec("t", 165.5, 1000, 1.0, 0.2, doublet=S2P)]
    r = fit_peaks(
        spec,
        specs,
        FitSettings(
            background=BackgroundSpec("shirley", mode="active"), optimizer="global", seed=1
        ),
    )
    assert_close(r.majors()[0].center, 164.0, abs_=0.05)


def test_auto_mode_tries_static_and_active(s2p_region):
    region = RegionSpec.from_dict(
        {**s2p_region.to_dict(), "background": {"type": "auto", "mode": "auto"}}
    )
    labels = [v.label for v in region.variants()]
    assert labels == [
        "shirley/voigt",
        "shirley(active)/voigt",
        "tougaard/voigt",
        "tougaard(active)/voigt",
        "linear/voigt",
    ]
    only_mode = RegionSpec.from_dict(
        {**s2p_region.to_dict(), "background": {"type": "shirley", "mode": "auto"}}
    )
    assert [v.label for v in only_mode.variants()] == ["shirley/voigt", "shirley(active)/voigt"]


def test_select_model_with_active_shirley(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    region = RegionSpec.from_dict(
        {**s2p_region.to_dict(), "background": {"type": "shirley", "mode": "active"}}
    )
    sel = select_model(spec, region)
    assert sel.best is not None and sel.best.n_components == 2
    assert sel.best.background_mode == "active" and sel.best.variant == "shirley(active)/voigt"
    assert sel.best.result.background.info["mode"] == "active"
    got = {c.label: c for c in sel.best.result.majors()}
    assert_close(got["thiophene C-S-C"].center, 164.0, abs_=0.03)
    assert_close(got["sulfonate/sulfate"].area, 3000.0, rel=0.1)
    d = sel.to_dict(include_arrays=True)
    assert d["best"]["fit"]["settings"]["background"]["mode"] == "active"
    assert d["best"]["background_mode"] == "active"


def test_auto_cannot_reach_fit_peaks(aged_s2p):
    spec, _ = aged_s2p
    with pytest.raises(FitError):
        fit_peaks(
            spec,
            [ComponentSpec("t", 164, 1, doublet=S2P)],
            FitSettings(background=BackgroundSpec("shirley", mode="auto")),
        )
    with pytest.raises(BackgroundError):
        compute_background([1.0, 2, 3, 4, 5], [1.0] * 5, BackgroundSpec("shirley", mode="odd"))


# --------------------------------------------------------------- shoulder detection
def test_second_derivative_finds_an_unresolved_shoulder():
    x = np.arange(280.0, 292.0, 0.05)
    main = ps.gaussian(x, 50000.0, 284.8, 1.0)
    shoulder = ps.gaussian(x, 9000.0, 285.8, 1.0)  # one FWHM away, no maximum of its own
    y = main + shoulder
    assert len(detect_peaks(x, y, 10.0, 1.0, 0.3, 8, shoulders=False)) == 1
    guesses = detect_peaks(x, y, 10.0, 1.0, 0.3, 8)
    kinds = [(g.center, g.kind) for g in guesses]
    assert any(abs(c - 284.8) < 0.1 and k == "maximum" for c, k in kinds)
    assert any(abs(c - 286.0) < 0.4 and k == "shoulder" for c, k in kinds)
    # shoulders rank after maxima and carry a positive starting height
    sh = next(g for g in guesses if g.kind == "shoulder")
    assert guesses[0].kind == "maximum" and 0 < sh.height < guesses[0].height


def test_shoulder_detector_is_quiet_on_a_single_noisy_peak():
    x = np.arange(95.0, 110.0, 0.05)
    clean = ps.voigt(x, 30000.0, 102.3, 1.0, 0.3) + 300.0
    raw = np.random.default_rng(4).poisson(clean).astype(float)
    for seed in range(5):
        raw = np.random.default_rng(seed).poisson(clean).astype(float)
        guesses = detect_peaks(x, raw - 300.0, 18.0, 1.0, 0.3, 8, sigma=np.sqrt(raw))
        assert sum(g.kind == "shoulder" for g in guesses) == 0, seed
        assert len(guesses) == 1


# -------------------------------------------------------------- residual diagnostics
def test_residual_diagnostics_on_white_and_structured_series(rng):
    white = rng.normal(size=2000)
    dw, z, lag1 = residual_diagnostics(white)
    assert dw == pytest.approx(2.0, abs=0.15) and abs(z) < 3 and abs(lag1) < 0.1
    t = np.linspace(0, 6 * np.pi, 2000)
    structured = np.sin(t) + 0.1 * rng.normal(size=2000)
    dw2, z2, lag2 = residual_diagnostics(structured)
    assert dw2 < 0.2 and z2 < -20 and lag2 > 0.9
    assert residual_diagnostics(np.zeros(50)) == (None, None, None)


def test_missing_component_gives_structured_residual_warning(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    one = fit_peaks(spec, [ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P)], FitSettings())
    _v, warnings = check_physical(one, s2p_region.constraints, spec.range)
    assert any(w.code == "structured_residual" for w in warnings)
    two = fit_peaks(
        spec,
        [
            ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P),
            ComponentSpec("o", 168.4, 3000, 1.3, 0.15, doublet=S2P),
        ],
        FitSettings(),
    )
    _v, warnings2 = check_physical(two, s2p_region.constraints, spec.range)
    assert not any(w.code == "structured_residual" for w in warnings2)
    assert two.stats.durbin_watson > one.stats.durbin_watson


def test_choose_prefers_white_residual_inside_the_margin(aged_s2p):
    spec, _ = aged_s2p
    one = fit_peaks(spec, [ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P)], FitSettings())
    two = fit_peaks(
        spec,
        [
            ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P),
            ComponentSpec("o", 168.4, 3000, 1.3, 0.15, doublet=S2P),
        ],
        FitSettings(),
    )
    flag = Violation("structured_residual", "structured", None, "warning")
    c1 = Candidate(1, one, [], [flag], "aicc", 100.0)
    c2 = Candidate(2, two, [], [], "aicc", 99.0)  # within the margin of 2
    chosen, status, notes = choose([c1, c2], 2.0)
    assert chosen is c2 and status == "ok"
    assert any("structured residual" in n for n in notes)
    # without the residual flag the usual parsimony rule applies and the result is ambiguous
    c1b = Candidate(1, one, [], [], "aicc", 100.0)
    chosen_b, status_b, _ = choose([c1b, c2], 2.0)
    assert chosen_b is c1b and status_b == "ambiguous"


# ------------------------------------------------------ bootstrap -> atomic percent
def test_bootstrap_keeps_samples_and_propagates_to_atomic_percent(aged_s2p, fresh_s2p):
    spec_a, _ = aged_s2p
    spec_b, _ = fresh_s2p
    ra = fit_peaks(
        spec_a,
        [
            ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P),
            ComponentSpec("o", 168.4, 3000, 1.3, 0.15, doublet=S2P),
        ],
        FitSettings(),
    )
    rb = fit_peaks(
        spec_b, [ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P)], FitSettings()
    )
    ba = bootstrap(spec_a, ra, n=12, seed=1)
    bb = bootstrap(spec_b, rb, n=12, seed=2)
    assert ba.n_succeeded == 12 and ba.total_area_samples.shape == (12,)
    assert set(ba.area_samples) == {c.label for c in ra.components}
    assert "component_fraction" in ba.summary["t"] and "fraction" in ba.summary["o (minor)"]
    assert ba.summary["t"]["area"]["std"] > 0
    quant = atomic_percent(
        [("A", "S", "2p", ra.total_area, 0.668), ("B", "S", "2p", rb.total_area, 0.668)]
    )
    used = atomic_percent_samples(quant, {"A": ba.total_area_samples, "B": bb.total_area_samples})
    assert used == 12
    stds = [e.atomic_percent_std for e in quant.entries]
    assert all(s is not None and s > 0 for s in stds)
    assert sum(e.atomic_percent for e in quant.entries) == pytest.approx(100.0)
    assert "bootstrap" in quant.note
    # nothing is propagated when a region has no replicates
    quant2 = atomic_percent([("A", "S", "2p", 1.0, 1.0), ("B", "S", "2p", 1.0, 1.0)])
    assert atomic_percent_samples(quant2, {"A": ba.total_area_samples}) == 0


def test_constraints_round_trip_with_asymmetry():
    c = PeakConstraints(asym=(0.0, 0.3), share_asym=False, residual_dw_warning=1.2)
    d = c.to_dict()
    c2 = PeakConstraints.from_dict(d)
    assert c2.asym == (0.0, 0.3) and not c2.share_asym and c2.residual_dw_warning == 1.2
    with pytest.raises(ValueError):
        PeakConstraints(asym=(0.0, 0.9))
