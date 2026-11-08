import numpy as np
import pytest
from scipy.integrate import quad

from xps_autofit.core import peak_shapes as ps


@pytest.mark.parametrize(
    "shape,widths",
    [
        ("gaussian", {"fwhm": 1.3}),
        ("lorentzian", {"fwhm": 0.8}),
        ("voigt", {"fwhm_g": 1.0, "fwhm_l": 0.4}),
        ("pseudo_voigt", {"fwhm": 1.2, "eta": 0.35}),
        ("gl_product", {"fwhm": 1.2, "eta": 0.35}),
        ("gl_product", {"fwhm": 0.9, "eta": 0.9}),
        ("gl_product", {"fwhm": 1.5, "eta": 0.02}),
    ],
)
def test_shapes_integrate_to_area(shape, widths):
    def f(t: float) -> float:
        return float(ps.evaluate(shape, np.array([t]), 123.0, 1.5, **widths)[0])

    area, _ = quad(f, -np.inf, np.inf, points=None, limit=400)
    assert area == pytest.approx(123.0, rel=1e-4)


@pytest.mark.parametrize(
    "shape,widths,expected",
    [
        ("gaussian", {"fwhm": 1.3}, 1.3),
        ("lorentzian", {"fwhm": 0.8}, 0.8),
        ("pseudo_voigt", {"fwhm": 1.2, "eta": 0.35}, 1.2),
        ("voigt", {"fwhm_g": 1.0, "fwhm_l": 0.4}, ps.voigt_fwhm(1.0, 0.4)),
        ("gl_product", {"fwhm": 1.2, "eta": 0.5}, ps.gl_product_fwhm(1.2, 0.5)),
        ("gl_product", {"fwhm": 1.2, "eta": 0.0}, 1.2),
        ("gl_product", {"fwhm": 1.2, "eta": 1.0}, 1.2),
    ],
)
def test_fwhm_matches_definition(shape, widths, expected):
    x = np.linspace(-6, 6, 240001)
    y = ps.evaluate(shape, x, 1.0, 0.0, **widths)
    half = y.max() / 2
    above = x[y >= half]
    measured = above[-1] - above[0]
    assert measured == pytest.approx(expected, abs=2e-3)
    assert ps.total_fwhm(shape, **widths) == pytest.approx(expected, rel=1e-3)


def test_voigt_limits_reduce_to_gaussian_and_lorentzian():
    x = np.linspace(-5, 5, 2001)
    g = ps.voigt(x, 1.0, 0.0, 1.0, 1e-9)
    assert np.allclose(g, ps.gaussian(x, 1.0, 0.0, 1.0), atol=1e-6)
    lo = ps.voigt(x, 1.0, 0.0, 1e-9, 1.0)
    assert np.allclose(lo, ps.lorentzian(x, 1.0, 0.0, 1.0), atol=1e-6)


def test_gl_product_limits_and_width():
    x = np.linspace(-5, 5, 2001)
    assert np.allclose(ps.gl_product(x, 1.0, 0.0, 1.0, 0.0), ps.gaussian(x, 1.0, 0.0, 1.0))
    assert np.allclose(ps.gl_product(x, 1.0, 0.0, 1.0, 1.0), ps.lorentzian(x, 1.0, 0.0, 1.0))
    # The product of two unit-height factors of width F is narrower than F in between:
    # at most about 6 % (eta near 0.5), never wider.
    widths = [ps.gl_product_fwhm(1.0, eta) for eta in np.linspace(0, 1, 21)]
    assert min(widths) > 0.94 and max(widths) <= 1.0 + 1e-9
    assert ps.gl_product_fwhm(1.0, 0.5) == pytest.approx(0.956, abs=2e-3)
    # The closed-form integral agrees with quadrature at small eta, where the naive
    # exp(a/b) * erfc(...) product would overflow.
    f = lambda t: float(np.exp(-4 * np.log(2) * 0.99 * t * t) / (1 + 4 * 0.01 * t * t))  # noqa: E731
    assert ps.gl_product_integral(1.0, 0.01) == pytest.approx(quad(f, -np.inf, np.inf)[0], rel=1e-6)


def test_fit_recovers_a_gl_product_line():
    from xps_autofit.core.background import BackgroundSpec
    from xps_autofit.core.fitting import ComponentSpec, FitSettings, fit_peaks
    from xps_autofit.core.spectrum import Spectrum

    x = np.arange(280.0, 292.0, 0.05)
    truth = ps.gl_product(x, 50000.0, 285.0, 1.3, 0.3) + 400.0
    y = np.random.default_rng(3).poisson(truth).astype(float)
    r = fit_peaks(
        Spectrum(x, y, intensity_unit="counts"),
        [ComponentSpec("c", 285.2, 40000.0, fwhm=1.0, eta=0.5)],
        FitSettings(shape="gl_product", background=BackgroundSpec("linear")),
    )
    c = r.majors()[0]
    assert c.area == pytest.approx(50000.0, rel=0.01)
    assert c.center == pytest.approx(285.0, abs=0.01)
    assert c.eta == pytest.approx(0.3, abs=0.03)
    assert r.params["c0_fwhm"]["value"] == pytest.approx(1.3, abs=0.02)
    assert c.fwhm == pytest.approx(ps.gl_product_fwhm(1.3, 0.3), rel=0.02), "measured width"
    assert r.stats.redchi < 1.6


def test_height_and_area_from_height_are_inverse():
    h = ps.height("voigt", 50.0, fwhm_g=1.0, fwhm_l=0.2)
    assert ps.area_from_height("voigt", h, fwhm_g=1.0, fwhm_l=0.2) == pytest.approx(50.0)


def test_unknown_shape_rejected():
    with pytest.raises(ValueError):
        ps.get_shape("doniach")
