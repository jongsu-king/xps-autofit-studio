import numpy as np
import pytest

from xps_autofit.core.background import BackgroundSpec
from xps_autofit.core.constraints import DoubletSpec, PeakConstraints
from xps_autofit.core.fitting import (
    ComponentSpec,
    FitError,
    FitSettings,
    fit_peaks,
    specs_from_result,
)
from xps_autofit.core.peak_shapes import voigt_fwhm
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.synthetic import SynthComponent, SynthRegion, synthesize

from .conftest import S2P, assert_close


def test_single_voigt_recovery(single_voigt):
    spec, truth = single_voigt
    t = truth["components"][0]
    specs = [ComponentSpec("single", 102.0, area=20000.0, fwhm_g=1.2, fwhm_l=0.2)]
    settings = FitSettings(
        shape="voigt", background=BackgroundSpec("shirley"), refine_linear_background=True
    )
    r = fit_peaks(spec, specs, settings)
    c = r.majors()[0]
    assert r.stats.success and r.stats.weighted
    assert_close(c.center, t["center"], abs_=0.01)
    assert_close(c.area, t["area"], rel=0.02)
    assert_close(c.fwhm, voigt_fwhm(t["fwhm_g"], t["fwhm_l"]), rel=0.03)
    assert r.stats.redchi < 1.5
    assert c.center_err is not None and c.center_err < 0.01
    assert c.area_err is not None and c.area / c.area_err > 50
    assert c.fwhm_err is not None


def test_doublet_constraints_are_exact(aged_s2p):
    spec, truth = aged_s2p
    d = DoubletSpec(splitting=1.18, area_ratio=0.5)
    specs = [
        ComponentSpec("thiophene", 164.1, area=15000, fwhm_g=1.0, fwhm_l=0.2, doublet=d),
        ComponentSpec("oxidised", 168.3, area=2000, fwhm_g=1.2, fwhm_l=0.2, doublet=d),
    ]
    r = fit_peaks(spec, specs, FitSettings())
    major, minor = r.components[0], r.components[1]
    assert minor.is_minor and minor.parent == "thiophene"
    assert minor.center - major.center == pytest.approx(1.18, abs=1e-9)
    assert minor.area / major.area == pytest.approx(0.5, abs=1e-9)
    assert minor.fwhm == pytest.approx(major.fwhm)
    assert_close(major.center, 164.0, abs_=0.02)
    assert_close(major.area, 20000.0, rel=0.03)
    assert_close(r.components[2].area, 3000.0, rel=0.08)
    assert major.component_fraction == pytest.approx(100 * 1.5 * major.area / r.total_area)


def test_doublet_splitting_may_vary_within_tolerance(fresh_s2p):
    spec, _ = fresh_s2p
    d = DoubletSpec(splitting=1.10, area_ratio=0.5, splitting_tolerance=0.1)
    r = fit_peaks(spec, [ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=d)], FitSettings())
    split = r.params["c0_split"]
    assert split["vary"] and 1.16 < split["value"] < 1.20


def test_shared_lorentzian_width_is_an_expression(aged_s2p):
    spec, _ = aged_s2p
    c = PeakConstraints(share_fwhm_l=True)
    specs = [
        ComponentSpec("a", 164.0, 20000, 0.9, 0.15, doublet=S2P),
        ComponentSpec("b", 168.4, 3000, 1.3, 0.15, doublet=S2P),
    ]
    r = fit_peaks(spec, specs, FitSettings(constraints=c))
    assert r.params["c1_fwhm_l"]["expr"] == "c0_fwhm_l"
    assert r.params["c0m_fwhm_g"]["expr"] == "c0_fwhm_g"
    assert r.components[0].fwhm_l == pytest.approx(r.components[2].fwhm_l)


@pytest.mark.parametrize("shape", ["gaussian", "lorentzian", "pseudo_voigt"])
def test_other_shapes_fit(shape, single_voigt):
    spec, truth = single_voigt
    r = fit_peaks(
        spec, [ComponentSpec("s", 102.0, 20000, fwhm=1.1, eta=0.3)], FitSettings(shape=shape)
    )
    assert r.stats.success
    assert_close(r.majors()[0].center, truth["components"][0]["center"], abs_=0.03)


def test_unweighted_fit_uses_rss_criteria(single_voigt):
    spec, _ = single_voigt
    arb = spec.copy()
    arb.intensity_unit = "arbitrary"
    r = fit_peaks(arb, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings())
    assert not r.stats.weighted
    assert r.stats.chisqr == pytest.approx(r.stats.rss)
    with pytest.raises(FitError):
        fit_peaks(
            arb, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings(weighting="poisson")
        )


def test_descending_and_irregular_axes_give_same_answer(single_voigt):
    spec, _ = single_voigt
    reference = fit_peaks(spec, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings())
    desc = Spectrum(spec.energy[::-1], spec.intensity[::-1])
    r_desc = fit_peaks(desc, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings())
    assert r_desc.majors()[0].center == pytest.approx(reference.majors()[0].center, abs=1e-9)
    assert r_desc.majors()[0].area == pytest.approx(reference.majors()[0].area, rel=1e-9)
    keep = np.ones(spec.n, dtype=bool)
    keep[::3] = False  # remove every third point -> non-uniform spacing
    irregular = Spectrum(spec.energy[keep], spec.intensity[keep])
    assert not irregular.is_uniform
    r_irr = fit_peaks(irregular, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings())
    assert r_irr.majors()[0].center == pytest.approx(reference.majors()[0].center, abs=0.01)
    assert r_irr.majors()[0].area == pytest.approx(reference.majors()[0].area, rel=0.03)


def test_refit_from_result_is_stable(single_voigt):
    spec, _ = single_voigt
    r1 = fit_peaks(spec, [ComponentSpec("s", 102.0, 20000, 1.2, 0.2)], FitSettings())
    r2 = fit_peaks(spec, specs_from_result(r1), r1.settings)
    assert r2.majors()[0].center == pytest.approx(r1.majors()[0].center, abs=1e-6)


def test_empty_centre_window_is_an_error(single_voigt):
    spec, _ = single_voigt
    with pytest.raises(FitError):
        fit_peaks(
            spec, [ComponentSpec("s", 102.0, 1.0, center_bounds=(150.0, 160.0))], FitSettings()
        )


def test_bad_doublet_spec_rejected():
    with pytest.raises(ValueError):
        DoubletSpec(splitting=-1.0, area_ratio=0.5)
    with pytest.raises(ValueError):
        PeakConstraints(fwhm_g=(2.0, 1.0))


def test_result_serialises_without_nan(aged_s2p):
    import json

    spec, _ = aged_s2p
    r = fit_peaks(spec, [ComponentSpec("t", 164.0, 20000, 0.9, 0.15, doublet=S2P)], FitSettings())
    text = json.dumps(r.to_dict(include_arrays=True), allow_nan=False)
    assert "c0m_center" in text


def test_low_counts_region_still_fits():
    region = SynthRegion(
        "weak", 95.0, 110.0, 0.1, [SynthComponent("w", 102.3, 300.0, 1.0, 0.2)], 20.0, 30.0
    )
    spec, _ = synthesize(region, seed=3)
    r = fit_peaks(spec, [ComponentSpec("w", 102.0, 200, 1.0, 0.2)], FitSettings())
    assert r.stats.success
    assert abs(r.majors()[0].center - 102.3) < 0.15
