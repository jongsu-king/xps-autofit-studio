import numpy as np
import pytest

from xps_autofit.automation.model_selection import select_model
from xps_autofit.automation.peak_detection import PeakGuess, detect_peaks, pair_doublets
from xps_autofit.core.fitting import FitError
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import (
    cu2p3_mixed,
    p3ht_c1s,
    p3ht_s2p,
    synthesize,
)

from .conftest import assert_close


def test_fresh_p3ht_selects_one_doublet(fresh_s2p, s2p_region):
    spec, truth = fresh_s2p
    sel = select_model(spec, s2p_region)
    assert sel.status == "ok"
    assert sel.best.n_components == 1
    c = sel.best.result.majors()[0]
    assert c.label == "thiophene C-S-C"
    assert_close(c.center, 164.0, abs_=0.03)
    assert_close(c.area, 20000.0, rel=0.03)
    assert sel.best.result.stats.redchi < 1.5


def test_aged_p3ht_selects_two_doublets(aged_s2p, s2p_region):
    spec, truth = aged_s2p
    sel = select_model(spec, s2p_region)
    assert sel.status == "ok"
    assert sel.best.n_components == 2
    labels = {c.label for c in sel.best.result.majors()}
    assert labels == {"thiophene C-S-C", "sulfonate/sulfate"}
    ox = next(c for c in sel.best.result.majors() if c.label.startswith("sulfonate"))
    assert_close(ox.center, 168.4, abs_=0.05)
    assert_close(ox.area, 3000.0, rel=0.1)
    # the rejected 3-component model must be in the candidate list with its reasons
    n3 = next(c for c in sel.candidates if c.n_components == 3)
    assert not n3.physical_ok or n3.criterion_value > sel.best.criterion_value


def test_c1s_four_overlapping_components(c1s_region):
    spec, truth = synthesize(p3ht_c1s(), seed=21)
    sel = select_model(spec, c1s_region)
    assert sel.best.n_components == 4
    got = {c.label: c for c in sel.best.result.majors()}
    for t in truth["components"]:
        c = got[t["label"]]
        assert_close(c.center, t["center"], abs_=0.08)
        assert_close(c.area, t["area"], rel=0.15)
    assert sel.best.result.stats.redchi < 1.5


def test_cu2p_with_broad_satellites():
    spec, truth = synthesize(cu2p3_mixed(), seed=22)
    region = load_recipe("cu2o").region("Cu 2p3/2")
    sel = select_model(spec, region)
    assert sel.status == "ok"
    assert sel.best.n_components == 4
    got = {c.label: c for c in sel.best.result.majors()}
    for t in truth["components"]:
        assert_close(got[t["label"]].center, t["center"], abs_=0.1)
        # Cu(II) sits 1.3 eV from a line five times larger; a 15 % area trade-off is
        # the realistic limit for free widths.
        assert_close(got[t["label"]].area, t["area"], rel=0.15)
    assert_close(got["Cu(0)/Cu(I)"].area, 80000.0, rel=0.05)
    n5 = next(c for c in sel.candidates if c.n_components == 5)
    assert not n5.physical_ok


@pytest.mark.parametrize("seed", [7, 8, 9])
def test_low_snr_does_not_overfit(s2p_region, seed):
    region = p3ht_s2p(False)
    for comp in region.components:
        comp.area /= 40.0  # ~500 counts in the main line
    region.background_lo, region.background_hi = 20.0, 35.0
    spec, _ = synthesize(region, seed=seed)
    sel = select_model(spec, s2p_region)
    assert sel.best is not None
    assert sel.best.n_components == 1
    assert sel.status in ("ok", "ambiguous")
    c = sel.best.result.majors()[0]
    assert abs(c.center - 164.0) < 0.15
    assert c.area_err is not None and c.area_err / c.area > 0.005  # errors grow with noise


@pytest.mark.parametrize("seed", [1, 2, 3, 11])
def test_fresh_p3ht_never_gains_components(s2p_region, seed):
    spec, _ = synthesize(p3ht_s2p(False), seed=seed)
    sel = select_model(spec, s2p_region)
    assert sel.best.n_components == 1
    extra = [c for c in sel.candidates if c.n_components > 1]
    assert all(
        (not c.physical_ok) or c.criterion_value > sel.best.criterion_value - 2 for c in extra
    )


def test_fixed_n_bypasses_selection(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    sel = select_model(spec, s2p_region, fixed_n=1)
    assert [c.n_components for c in sel.candidates] == [1]
    assert sel.best.n_components == 1


def test_noiseless_data_still_works(s2p_region):
    spec, _ = synthesize(p3ht_s2p(True), noise="none")
    sel = select_model(spec, s2p_region)
    assert sel.best.n_components == 2
    assert sel.best.result.stats.redchi < 1e-2


def test_results_are_deterministic(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    a = select_model(spec, s2p_region)
    b = select_model(spec, s2p_region)
    assert a.seed == b.seed
    for ca, cb in zip(a.best.result.components, b.best.result.components):
        assert ca.center == cb.center and ca.area == cb.area


def test_seed_changes_starts_but_not_truth(aged_s2p, s2p_region):
    spec, _ = aged_s2p
    a = select_model(spec, s2p_region, seed=1)
    b = select_model(spec, s2p_region, seed=2)
    assert a.seed != b.seed
    assert a.best.n_components == b.best.n_components == 2
    assert abs(a.best.result.majors()[0].center - b.best.result.majors()[0].center) < 1e-3


def test_kinetic_axis_rejected(fresh_s2p, s2p_region):
    spec, _ = fresh_s2p
    ke = Spectrum(1486.6 - spec.energy, spec.intensity, axis="kinetic", photon_energy=1486.6)
    with pytest.raises(FitError):
        select_model(ke, s2p_region)


def test_needs_review_when_nothing_is_physical():
    # A single sharp spike narrower than the allowed widths: centre at edge of region
    x = np.arange(100.0, 110.0, 0.05)
    y = 50.0 + 2000.0 * np.exp(-0.5 * ((x - 100.3) / 0.1) ** 2)
    spec = Spectrum(x, np.random.default_rng(1).poisson(y).astype(float))
    region = load_recipe("p3ht").region("C 1s")
    region.range = (100.0, 110.0)
    region.candidates = []
    sel = select_model(spec, region)
    assert sel.status in ("needs_review", "ambiguous", "ok")
    if sel.status == "needs_review":
        assert sel.best is not None and sel.best.violations


def test_detect_and_pair_doublets(aged_s2p):
    spec, _ = aged_s2p
    y = spec.intensity - spec.intensity.min()
    guesses = detect_peaks(
        spec.energy, y, noise_sigma=25.0, fwhm_hint=1.0, min_separation=0.5, max_peaks=8
    )
    centers = sorted(g.center for g in guesses)
    assert any(abs(c - 164.0) < 0.1 for c in centers)
    assert any(abs(c - 165.18) < 0.15 for c in centers)
    majors = pair_doublets(guesses, 1.18, 0.5, 0.25)
    major_centers = sorted(g.center for g in majors)
    assert not any(abs(c - 165.18) < 0.15 for c in major_centers)
    assert any(abs(c - 164.0) < 0.1 for c in major_centers)


def test_pair_doublets_keeps_unpaired():
    g = [PeakGuess(10.0, 100.0, 1.0, 100.0), PeakGuess(12.0, 90.0, 1.0, 90.0)]
    assert len(pair_doublets(g, 1.18, 0.5, 0.2)) == 2


def test_a_degenerate_lowest_start_does_not_discard_the_component_count():
    """C 1s seed 6: the lowest chi-square start of n=4 slides C-C and C-S 0.56 eV
    apart (< 0.6) while the other starts end at the truth; n=4 must survive."""
    spec, truth = synthesize(p3ht_c1s(), seed=6)
    sel = select_model(spec, load_recipe("p3ht").region("C 1s"))
    assert sel.status == "ok" and sel.best.n_components == 4
    assert sel.best.result.stats.redchi < 1.3
    got = {c.label: c for c in sel.best.result.majors()}
    for t in truth["components"]:
        assert_close(got[t["label"]].center, t["center"], abs_=0.1)
    assert any("kept the best start that passes" in n for n in sel.notes)


def test_pick_start_rules():
    from types import SimpleNamespace

    from xps_autofit.automation.model_selection import pick_start
    from xps_autofit.core.constraints import Violation

    def fit(chisqr, errorbars=True, bad=False):
        result = SimpleNamespace(stats=SimpleNamespace(chisqr=chisqr, errorbars=errorbars))
        return (result, [Violation("too_close", "x")] if bad else [], [])

    low_ok, other_ok = fit(10.0), fit(11.0)
    assert pick_start([other_ok, low_ok]) is low_ok
    low_bad, rescue, unchecked = fit(9.0, bad=True), fit(12.0), fit(10.5, errorbars=False)
    assert pick_start([low_bad, unchecked, rescue]) is rescue
    # passing only because no covariance was available is not a rescue
    assert pick_start([low_bad, unchecked]) is low_bad
    # an admissible lowest start is kept even without error bars (unchanged behaviour)
    low_unchecked = fit(8.0, errorbars=False)
    assert pick_start([low_unchecked, rescue]) is low_unchecked
