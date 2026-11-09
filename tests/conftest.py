from __future__ import annotations

import os
import sys

import numpy as np
import pytest

from xps_autofit.core.constraints import DoubletSpec
from xps_autofit.core.region import CandidateLine, RegionSpec
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import SynthComponent, SynthRegion, p3ht_s2p, synthesize

S2P = DoubletSpec(splitting=1.18, area_ratio=0.5)


@pytest.fixture
def s2p_region() -> RegionSpec:
    return load_recipe("p3ht").region("S 2p")


@pytest.fixture
def c1s_region() -> RegionSpec:
    return load_recipe("p3ht").region("C 1s")


@pytest.fixture
def fresh_s2p() -> tuple[Spectrum, dict]:
    return synthesize(p3ht_s2p(False), seed=11)


@pytest.fixture
def aged_s2p() -> tuple[Spectrum, dict]:
    return synthesize(p3ht_s2p(True), seed=12)


def single_voigt_region(
    area: float = 30000.0, fwhm_g: float = 1.0, fwhm_l: float = 0.3
) -> SynthRegion:
    return SynthRegion(
        "single",
        95.0,
        110.0,
        0.05,
        [SynthComponent("single", 102.3, area, fwhm_g, fwhm_l)],
        200.0,
        400.0,
    )


@pytest.fixture
def single_voigt() -> tuple[Spectrum, dict]:
    return synthesize(single_voigt_region(), seed=5)


@pytest.fixture
def plain_region() -> RegionSpec:
    return RegionSpec(
        name="single",
        range=(95.0, 110.0),
        candidates=[CandidateLine("single", 102.3, 1.0)],
        min_components=1,
        max_components=3,
    )


def assert_close(
    actual: float, expected: float, rel: float | None = None, abs_: float | None = None
) -> None:
    if rel is not None:
        assert abs(actual - expected) <= rel * abs(expected), f"{actual} vs {expected} (rel {rel})"
    if abs_ is not None:
        assert abs(actual - expected) <= abs_, f"{actual} vs {expected} (abs {abs_})"


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(0)


# ------------------------------------------------------------ clean process exit
_EXIT_STATUS = 0


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """End the test process without the interpreter's finalisation when Qt was used.

    PySide6/Shiboken objects collected while the interpreter shuts down have aborted
    the process on Linux / Python 3.11 after every test had passed ("Fatal Python
    error: bool_dealloc", exit code 134).  The GUI tests delete their windows while
    the interpreter is healthy (``tests/qt_helpers.dispose_window``); by the time this
    hook runs everything has been reported (terminal summary, coverage, cache), so
    the streams are flushed and the process ends with pytest's own exit status - the
    same idea as ``pyqtgraph.exit()`` for applications.

    Qt objects are deliberately not touched here: forcing the deferred deletion of
    the widgets left over at this point (panels and dialogs some tests create without
    a parent) crashed the process now and then (exit 139).
    """
    if "PySide6.QtWidgets" not in sys.modules:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_EXIT_STATUS)
