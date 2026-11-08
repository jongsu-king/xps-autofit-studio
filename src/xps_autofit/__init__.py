"""XPS AutoFit: automated, reproducible XPS peak fitting with physical constraints.

The analysis engine (``xps_autofit.core``, ``xps_autofit.automation``) has no GUI
dependency, so the same code runs from the command line, from Python and from the
desktop application.
"""

from __future__ import annotations

__version__ = "0.5.0"

from .core.background import BackgroundSpec, compute_background
from .core.constraints import DoubletSpec, PeakConstraints
from .core.fitting import ComponentSpec, FitResult, FitSettings, fit_peaks
from .core.region import CandidateLine, RegionSpec
from .core.spectrum import Spectrum
from .readers import read_spectra

__all__ = [
    "BackgroundSpec",
    "CandidateLine",
    "ComponentSpec",
    "DoubletSpec",
    "FitResult",
    "FitSettings",
    "PeakConstraints",
    "RegionSpec",
    "Spectrum",
    "__version__",
    "compute_background",
    "fit_peaks",
    "read_spectra",
]
