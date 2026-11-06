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


def test_height_and_area_from_height_are_inverse():
    h = ps.height("voigt", 50.0, fwhm_g=1.0, fwhm_l=0.2)
    assert ps.area_from_height("voigt", h, fwhm_g=1.0, fwhm_l=0.2) == pytest.approx(50.0)


def test_unknown_shape_rejected():
    with pytest.raises(ValueError):
        ps.get_shape("doniach")
