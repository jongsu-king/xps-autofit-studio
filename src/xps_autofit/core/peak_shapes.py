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
* ``doniach_sunjic(x, area, center, fwhm_g, fwhm_l, asym)`` - Doniach-Sunjic line
  (asymmetry ``asym`` = alpha, tail towards high binding energy) convolved with a
  Gaussian; for ``asym = 0`` it is the Voigt profile.  Its tail is not integrable,
  so *area* is defined as the integral within +/- :data:`DS_AREA_WINDOW` total
  widths of the centre.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve
from scipy.special import gamma as gamma_function
from scipy.special import voigt_profile

SQRT_2LN2 = float(np.sqrt(2.0 * np.log(2.0)))
#: Half-width (in units of the Voigt FWHM) of the window over which the area of a
#: Doniach-Sunjic line is defined.
DS_AREA_WINDOW = 10.0
#: Largest asymmetry accepted for a Doniach-Sunjic line.
DS_ASYM_MAX = 0.5
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


def _ds_core(t: np.ndarray, gamma: float, alpha: float) -> np.ndarray:
    """Doniach-Sunjic line, unit area for ``alpha = 0`` (then it is a Lorentzian).

    ``t = center - x`` on a binding-energy axis, so the slow tail (``t -> -inf``) lies
    at *higher* binding energy, where the intrinsic losses of a metal appear.
    """
    return (
        gamma_function(1.0 - alpha)
        / np.pi
        * np.cos(0.5 * np.pi * alpha + (1.0 - alpha) * np.arctan(t / gamma))
        / (t**2 + gamma**2) ** (0.5 * (1.0 - alpha))
    )


def _ds_profile(
    fwhm_g: float, fwhm_l: float, asym: float
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Unit-area DS x Gaussian profile on a fine grid ``t = x - center``.

    Returns ``(t, values, norm, half_window)``: ``norm`` is the factor that scales the
    raw DS core to unit area within ``+/- half_window``; it is reused for the
    unconvolved tail outside the grid.
    """
    fwhm_g = max(float(fwhm_g), 1e-6)
    fwhm_l = max(float(fwhm_l), 1e-6)
    alpha = float(np.clip(asym, 0.0, DS_ASYM_MAX))
    sigma = fwhm_g / (2.0 * SQRT_2LN2)
    gamma = fwhm_l / 2.0
    width = voigt_fwhm(fwhm_g, fwhm_l)
    half_window = DS_AREA_WINDOW * width
    step = max(min(fwhm_g, fwhm_l) / 16.0, width / 600.0)
    reach = half_window + 5.0 * sigma
    n = int(np.ceil(reach / step))
    t = np.arange(-n, n + 1) * step
    core = _ds_core(-t, gamma, alpha)  # t = x - center; core wants center - x
    kernel = np.exp(-0.5 * (t / sigma) ** 2)
    kernel /= kernel.sum()
    values = fftconvolve(core, kernel, mode="same")
    inside = np.abs(t) <= half_window
    norm = 1.0 / float(np.trapezoid(values[inside], t[inside]))
    return t, values * norm, norm, half_window


def doniach_sunjic(
    x: np.ndarray, area: float, center: float, fwhm_g: float, fwhm_l: float, asym: float
) -> np.ndarray:
    """Doniach-Sunjic line convolved with a Gaussian; see the module docstring."""
    x = np.asarray(x, dtype=float)
    # Always evaluated numerically (also for asym = 0) so the profile is continuous in
    # the asymmetry; the area convention differs from the plain Voigt by its tails.
    t, prof, norm, _half = _ds_profile(fwhm_g, fwhm_l, asym)
    d = x - center
    out = np.interp(d, t, prof, left=np.nan, right=np.nan)
    outside = np.isnan(out)
    if outside.any():
        gamma = max(float(fwhm_l), 1e-6) / 2.0
        alpha = float(np.clip(asym, 0.0, DS_ASYM_MAX))
        out[outside] = norm * _ds_core(-d[outside], gamma, alpha)
    return area * out


def doniach_sunjic_fwhm(fwhm_g: float, fwhm_l: float, asym: float) -> float:
    """Measured full width at half maximum of the asymmetric profile."""
    t, prof, _norm, _half = _ds_profile(fwhm_g, fwhm_l, asym)
    half = prof.max() / 2.0
    above = np.nonzero(prof >= half)[0]
    i0, i1 = int(above[0]), int(above[-1])

    def cross(i: int, j: int) -> float:
        # linear interpolation of the half-maximum crossing between grid points i, j
        y0, y1 = prof[i], prof[j]
        if y1 == y0:
            return float(t[i])
        return float(t[i] + (half - y0) * (t[j] - t[i]) / (y1 - y0))

    left = cross(i0 - 1, i0) if i0 > 0 else float(t[i0])
    right = cross(i1, i1 + 1) if i1 + 1 < t.size else float(t[i1])
    return right - left


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
    "doniach_sunjic": ShapeInfo("doniach_sunjic", doniach_sunjic, ("fwhm_g", "fwhm_l", "asym")),
}
#: Shapes whose width is parametrised as Gaussian + Lorentzian FWHM.
GL_SHAPES = ("voigt", "doniach_sunjic")


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
    if shape == "doniach_sunjic":
        return doniach_sunjic_fwhm(widths["fwhm_g"], widths["fwhm_l"], widths["asym"])
    return float(widths["fwhm"])


def height(shape: str, area: float, **widths: float) -> float:
    """Peak height (value at the centre)."""
    return float(evaluate(shape, np.zeros(1), area, 0.0, **widths)[0])


def area_from_height(shape: str, h: float, **widths: float) -> float:
    """Approximate area for a given height; used only for initial guesses."""
    unit = height(shape, 1.0, **widths)
    return float(h / unit) if unit > 0 else 0.0
