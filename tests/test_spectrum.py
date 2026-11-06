import numpy as np
import pytest

from xps_autofit.core.preprocessing import (
    C1S_REFERENCE_WARNING,
    charge_correct,
    check_axis,
    estimate_noise,
)
from xps_autofit.core.spectrum import Spectrum, SpectrumError


def test_descending_axis_is_sorted_and_recorded():
    e = np.arange(10.0, 0.0, -0.5)
    i = np.arange(e.size, dtype=float)
    s = Spectrum(e, i)
    assert np.all(np.diff(s.energy) > 0)
    assert s.intensity[0] == i[-1]
    assert s.history[0] == {"step": "sort_ascending", "input_order": "descending"}
    assert check_axis(s).input_order == "descending"


def test_duplicates_are_averaged_and_nonfinite_dropped():
    e = np.array([1.0, 2.0, 2.0, 3.0, 4.0, 5.0, np.nan])
    i = np.array([1.0, 2.0, 4.0, 3.0, 4.0, 5.0, 6.0])
    s = Spectrum(e, i)
    assert s.n == 5
    assert s.intensity[1] == pytest.approx(3.0)
    steps = [h["step"] for h in s.history]
    assert "drop_nonfinite" in steps and "merge_duplicate_energies" in steps


def test_too_short_or_mismatched_rejected():
    with pytest.raises(SpectrumError):
        Spectrum(np.arange(3.0), np.arange(3.0))
    with pytest.raises(SpectrumError):
        Spectrum(np.arange(6.0), np.arange(5.0))
    with pytest.raises(SpectrumError):
        Spectrum(np.arange(6.0), np.arange(6.0), axis="wavelength")


def test_sigma_depends_on_unit():
    e = np.arange(10.0)
    counts = Spectrum(e, np.full(10, 400.0), intensity_unit="counts")
    assert np.allclose(counts.sigma, 20.0)
    arbitrary = Spectrum(e, np.full(10, 400.0), intensity_unit="arbitrary")
    assert arbitrary.sigma is None
    cps_unknown = Spectrum(e, np.full(10, 400.0), intensity_unit="cps")
    assert cps_unknown.sigma is None
    cps = Spectrum(e, np.full(10, 400.0), intensity_unit="cps", dwell_time_s=0.5, n_scans=2)
    assert np.allclose(cps.sigma, np.sqrt(400.0 * 1.0) / 1.0)


def test_kinetic_to_binding_conversion_and_crop():
    ke = np.arange(1300.0, 1330.0, 0.5)
    s = Spectrum(ke, np.ones(ke.size), axis="kinetic", photon_energy=1486.6)
    b = s.to_binding()
    assert b.axis == "binding"
    assert b.energy[0] == pytest.approx(1486.6 - 1329.5)
    assert np.all(np.diff(b.energy) > 0)
    c = b.crop(160, 170)
    assert c.energy[0] >= 160 and c.energy[-1] <= 170
    with pytest.raises(SpectrumError):
        b.crop(0, 1)


def test_shift_and_charge_correction_record_history():
    s = Spectrum(np.arange(280.0, 292.0, 0.1), np.ones(120))
    s2, record = charge_correct(s, 285.1, 284.8, "C 1s C-C")
    assert s2.energy[0] == pytest.approx(279.7)
    assert record["delta_eV"] == pytest.approx(-0.3)
    assert record["warning"] == C1S_REFERENCE_WARNING
    assert s2.history[-1]["step"] == "shift"


def test_noise_estimate_matches_poisson(rng):
    x = np.arange(0.0, 20.0, 0.05)
    y = rng.poisson(10000.0, x.size).astype(float)
    rep = estimate_noise(x, y, fwhm_hint=1.0)
    assert rep.sigma == pytest.approx(100.0, rel=0.2)
    assert rep.method == "mad_of_savgol_residual"


def test_roundtrip_dict():
    s = Spectrum(
        np.arange(5.0, 15.0, 0.5), np.arange(20.0), name="x", metadata={"a": np.float64(1.5)}
    )
    d = s.to_dict()
    assert d["metadata"]["a"] == 1.5
    s2 = Spectrum.from_dict(d)
    assert np.allclose(s2.energy, s.energy) and s2.sha256() == s.sha256()
