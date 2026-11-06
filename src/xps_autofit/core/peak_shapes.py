"""Area-normalised peak shapes.

Every shape integrates to ``area`` over the energy axis, so the fitted amplitude *is*
the peak area and areas of different shapes are directly comparable.

Width parameters are full widths at half maximum (eV):

* ``gaussian(x, area, center, fwhm)``
* ``lorentzian(x, area, center, fwhm)``
* ``voigt(x, area, center, fwhm_g, fwhm_l)`` - exact convolution via
  :func:`scipy.special.voigt_profile`
* ``pseudo_voigt(x, area, center, fwhm, eta)`` - ``eta * L + (1 - eta) * G`` with a
  common FWHM
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.special import voigt_profile

SQRT_2LN2 = float(np.sqrt(2.0 * np.log(2.0)))
#: ``area = height * fwhm * GAUSS_AREA_FACTOR`` for a Gaussian (about 1.0645).
GAUSS_AREA_FACTOR = float(np.sqrt(np.pi / (4.0 * np.log(2.0))))
#: ``area = height * fwhm * LORENTZ_AREA_FACTOR`` for a Lorentzian (pi / 2).
LORENTZ_AREA_FACTOR = float(np.pi / 2.0)


def gaussian(x: np.ndarray, area: float, center: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / (2.0 * SQRT_2LN2)
    return area / (sigma * np.sqrt(2.0 * np.pi)) * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentzian(x: np.ndarray, area: float, center: float, fwhm: float) -> np.ndarray:
    gamma = fwhm / 2.0
    return area / np.pi * gamma / ((x - center) ** 2 + gamma**2)


def voigt(x: np.ndarray, area: float, center: float, fwhm_g: float, fwhm_l: float) -> np.ndarray:
    sigma = fwhm_g / (2.0 * SQRT_2LN2)
    gamma = fwhm_l / 2.0
    return area * voigt_profile(x - center, sigma, gamma)


def pseudo_voigt(x: np.ndarray, area: float, center: float, fwhm: float, eta: float) -> np.ndarray:
    return eta * lorentzian(x, area, center, fwhm) + (1.0 - eta) * gaussian(x, area, center, fwhm)


def voigt_fwhm(fwhm_g: float, fwhm_l: float) -> float:
    """Total FWHM of a Voigt profile (Olivero & Longbothum 1977, error below 0.02 %)."""
    return 0.5346 * fwhm_l + np.sqrt(0.2166 * fwhm_l**2 + fwhm_g**2)


@dataclass(frozen=True)
class ShapeInfo:
    name: str
    func: Callable[..., np.ndarray]
    #: Parameter names beyond ``area`` and ``center``.
    params: tuple[str, ...]


SHAPES: dict[str, ShapeInfo] = {
    "gaussian": ShapeInfo("gaussian", gaussian, ("fwhm",)),
    "lorentzian": ShapeInfo("lorentzian", lorentzian, ("fwhm",)),
    "voigt": ShapeInfo("voigt", voigt, ("fwhm_g", "fwhm_l")),
    "pseudo_voigt": ShapeInfo("pseudo_voigt", pseudo_voigt, ("fwhm", "eta")),
}


def get_shape(name: str) -> ShapeInfo:
    try:
        return SHAPES[name]
    except KeyError as exc:
        raise ValueError(f"unknown peak shape {name!r}; choose from {sorted(SHAPES)}") from exc


def evaluate(shape: str, x: np.ndarray, area: float, center: float, **widths: float) -> np.ndarray:
    info = get_shape(shape)
    args = [widths[p] for p in info.params]
    return info.func(x, area, center, *args)


def total_fwhm(shape: str, **widths: float) -> float:
    """FWHM of the full profile for any shape."""
    if shape == "voigt":
        return float(voigt_fwhm(widths["fwhm_g"], widths["fwhm_l"]))
    return float(widths["fwhm"])


def height(shape: str, area: float, **widths: float) -> float:
    """Peak height (value at the centre)."""
    return float(evaluate(shape, np.zeros(1), area, 0.0, **widths)[0])


def area_from_height(shape: str, h: float, **widths: float) -> float:
    """Approximate area for a given height; used only for initial guesses."""
    unit = height(shape, 1.0, **widths)
    return float(h / unit) if unit > 0 else 0.0
