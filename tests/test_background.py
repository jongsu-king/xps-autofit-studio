import numpy as np
import pytest

from xps_autofit.core.background import (
    BackgroundError,
    BackgroundSpec,
    compute_background,
    linear_background,
    shirley_background,
    tougaard_background,
)
from xps_autofit.core.peak_shapes import voigt
from xps_autofit.synthetic import shirley_like_background


@pytest.fixture
def peak_on_step():
    x = np.arange(160.0, 172.0, 0.05)
    signal = voigt(x, 20000.0, 164.0, 0.9, 0.2) + voigt(x, 10000.0, 165.18, 0.9, 0.2)
    bg = shirley_like_background(x, signal, 300.0, 600.0)
    return x, signal, bg


@pytest.fixture
def gaussian_peak_on_step():
    """Gaussian-dominated doublet: no tails reach the endpoints."""
    x = np.arange(158.0, 172.0, 0.05)
    signal = voigt(x, 20000.0, 164.0, 0.9, 1e-6) + voigt(x, 10000.0, 165.18, 0.9, 1e-6)
    bg = shirley_like_background(x, signal, 300.0, 600.0)
    return x, signal, bg


def test_linear_background_hits_endpoints():
    x = np.linspace(0, 10, 101)
    y = 5.0 + 2.0 * x
    bg = linear_background(x, y, endpoint_points=1)
    assert np.allclose(bg, y)


def test_shirley_recovers_shirley_type_background(gaussian_peak_on_step):
    x, signal, bg_true = gaussian_peak_on_step
    bg, info = shirley_background(x, signal + bg_true, endpoint_points=1)
    assert info["converged"]
    assert np.max(np.abs(bg - bg_true)) < 1e-3 * 300.0


def test_shirley_endpoint_bias_from_lorentzian_tails(peak_on_step):
    """Lorentzian tails raise the endpoints; the bias is what the linear refinement
    in the fit absorbs.  Documented here so the magnitude is visible."""
    x, signal, bg_true = peak_on_step
    bg, info = shirley_background(x, signal + bg_true, endpoint_points=1)
    assert info["converged"]
    bias = bg - bg_true
    assert 40 < bias[0] < 60 and 10 < bias[-1] < 25
    assert bias[0] == pytest.approx(signal[0], abs=1e-6)


def test_shirley_background_is_monotonic_for_positive_signal(gaussian_peak_on_step):
    x, signal, bg_true = gaussian_peak_on_step
    bg, _ = shirley_background(x, signal + bg_true)
    assert np.all(np.diff(bg) >= -1e-9)
    assert bg[0] == pytest.approx(np.mean((signal + bg_true)[:3]))
    assert bg[-1] == pytest.approx(np.mean((signal + bg_true)[-3:]))


def test_shirley_flat_endpoints_gives_constant():
    x = np.linspace(0, 10, 201)
    y = 100.0 + voigt(x, 500.0, 5.0, 1.0, 1e-9)
    bg, info = shirley_background(x, y, endpoint_points=2)
    assert info["iterations"] == 0
    assert np.allclose(bg, 100.0, atol=1e-6)


def test_tougaard_meets_endpoints_and_rises_towards_high_be(gaussian_peak_on_step):
    x, signal, bg_true = gaussian_peak_on_step
    y = signal + bg_true
    bg, info = tougaard_background(x, y, endpoint_points=3)
    assert bg[0] == pytest.approx(np.mean(y[:3]))
    assert np.mean(bg[-3:]) == pytest.approx(np.mean(y[-3:]), rel=1e-6)
    assert np.all(np.diff(bg) >= -1e-6 * 300.0)
    assert bg[-1] - bg[0] > 0.9 * 300.0
    assert info["B"] > 0


def test_compute_background_dispatch_and_warning(peak_on_step):
    x, signal, bg_true = peak_on_step
    y = signal + bg_true
    for kind in ("none", "linear", "shirley", "tougaard"):
        res = compute_background(x, y, BackgroundSpec(type=kind))
        assert res.values.shape == y.shape
    reversed_step = compute_background(x, y[::-1], BackgroundSpec(type="shirley"))
    assert any("high-BE endpoint" in w for w in reversed_step.warnings)


def test_background_rejects_bad_axis():
    x = np.array([1.0, 2.0, 2.0, 3.0, 4.0])
    with pytest.raises(BackgroundError):
        shirley_background(x, np.ones(5))
    with pytest.raises(BackgroundError):
        BackgroundSpec(type="polynomial")
