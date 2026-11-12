"""Links between components: centre offsets, area ratios and shared widths."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from xps_autofit.automation.model_selection import select_model
from xps_autofit.core.background import BackgroundSpec
from xps_autofit.core.constraints import PeakConstraints
from xps_autofit.core.fitting import (
    ComponentLink,
    ComponentSpec,
    FitError,
    FitSettings,
    build_parameters,
    check_link_cycles,
    fit_peaks,
    rename_component,
)
from xps_autofit.core.peak_shapes import evaluate
from xps_autofit.core.region import CandidateLine, RegionSpec
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.recipes import load_recipe, recipe_from_dict
from xps_autofit.synthetic import p3ht_c1s, synthesize


def _main_and_satellite(seed: int = 3) -> Spectrum:
    """C 1s-like main line with a shake-up satellite 6.5 eV above it (5 % of its area)."""
    rng = np.random.default_rng(seed)
    x = np.arange(280.0, 296.0, 0.05)
    clean = (
        200.0
        + evaluate("voigt", x, 40000.0, 284.8, fwhm_g=1.0, fwhm_l=0.2)
        + evaluate("voigt", x, 2000.0, 291.3, fwhm_g=1.0, fwhm_l=0.2)
    )
    return Spectrum(x, rng.poisson(clean).astype(float), name="satellite")


SETTINGS = FitSettings(shape="voigt", background=BackgroundSpec(type="linear"))


def test_linked_satellite_follows_its_main_line():
    spec = _main_and_satellite()
    main = ComponentSpec("C-C", 284.7, 30000.0, fwhm_g=1.1, fwhm_l=0.2)
    sat = ComponentSpec(
        "shake-up",
        291.0,
        1000.0,
        fwhm_g=1.5,
        fwhm_l=0.3,
        center_link=ComponentLink("C-C", 6.5),
        area_link=ComponentLink("C-C", 0.05, 0.02),
        width_link=ComponentLink("C-C"),
    )
    params = build_parameters([main, sat], SETTINGS, spec.energy)
    assert params["c1_center"].expr == "c0_center + c1_link_center"
    assert not params["c1_link_center"].vary  # no tolerance: fixed offset
    assert (params["c1_link_area"].min, params["c1_link_area"].max) == pytest.approx((0.03, 0.07))
    assert params["c1_fwhm_g"].expr == "c0_fwhm_g" and params["c1_fwhm_l"].expr == "c0_fwhm_l"
    result = fit_peaks(spec, [main, sat], SETTINGS)
    c, s = result.majors()
    assert s.center - c.center == pytest.approx(6.5, abs=1e-9)
    assert (s.fwhm_g, s.fwhm_l) == pytest.approx((c.fwhm_g, c.fwhm_l))
    assert s.area / c.area == pytest.approx(0.05, abs=0.005)
    assert s.center_err is not None and s.area_err is not None  # propagated errors
    unlinked = replace(sat, center_link=None, area_link=None, width_link=None)
    free = fit_peaks(spec, [main, unlinked], SETTINGS)
    # linked: the main line's centre, area, fwhm_g, fwhm_l and the ratio; free: the
    # satellite adds its centre, area and fwhm_g (fwhm_l is shared by default)
    assert (result.stats.nvarys, free.stats.nvarys) == (5, 7)
    assert result.specs[1].links().keys() == {"center", "area", "width"}
    # the component table says what follows what
    from xps_autofit.export.tables import components_table

    table = components_table(result).set_index("label")
    assert table.loc["C-C", "links"] == ""
    assert table.loc["shake-up", "links"] == (
        "center = C-C + 6.500 eV; area = C-C x 0.05 (+/- 0.02); width = widths of C-C"
    )


def test_links_round_trip_and_rename():
    spec = ComponentSpec(
        "b",
        286.0,
        center_link=ComponentLink("a", 1.2, 0.1),
        area_link=ComponentLink("a", 0.5),
        width_link=ComponentLink("a"),
    )
    d = spec.to_dict()
    assert d["links"] == {"center": ["a", 1.2, 0.1], "area": ["a", 0.5], "width": "a"}
    back = ComponentSpec.from_dict(d)
    assert back.links() == spec.links()
    assert "links" not in ComponentSpec("a", 285.0).to_dict()  # old projects stay the same
    assert ComponentSpec.from_dict(ComponentSpec("a", 285.0).to_dict()).links() == {}
    # renaming the target carries the links along
    x = _main_and_satellite()
    result = fit_peaks(
        x,
        [
            ComponentSpec("C-C", 284.7, 30000.0, fwhm_g=1.1),
            ComponentSpec("sat", 291.0, 1000.0, center_link=ComponentLink("C-C", 6.5)),
        ],
        SETTINGS,
    )
    renamed = rename_component(result, "C-C", "graphitic")
    assert renamed.specs[1].center_link == ComponentLink("graphitic", 6.5)
    assert result.specs[1].center_link == ComponentLink("C-C", 6.5)  # the original is untouched


def test_a_centre_tied_closer_than_min_separation_is_not_too_close():
    from xps_autofit.core.constraints import check_physical

    x = _main_and_satellite()
    specs = [
        ComponentSpec("C-C", 284.7, 30000.0, fwhm_g=1.1),
        ComponentSpec("sat", 291.3, 1000.0),
        ComponentSpec("near", 285.1, 3000.0, center_link=ComponentLink("C-C", 0.3)),
    ]
    result = fit_peaks(x, specs, SETTINGS)
    constraints = PeakConstraints(min_separation=0.6)
    violations, _ = check_physical(result, constraints, (280.0, 296.0))
    assert not any(v.code == "too_close" for v in violations)
    free = fit_peaks(x, [specs[0], specs[1], replace(specs[2], center_link=None)], SETTINGS)
    near = next(c for c in free.majors() if c.label == "near")
    cc = next(c for c in free.majors() if c.label == "C-C")
    violations, _ = check_physical(free, constraints, (280.0, 296.0))
    assert (abs(near.center - cc.center) < 0.6) == any(v.code == "too_close" for v in violations)


def test_link_validation():
    for kind, raw in (
        ("center", "a"),  # a centre link needs an offset
        ("area", ["a", 0.0]),
        ("area", ["a", 0.5, 0.6]),  # the ratio could reach 0
        ("center", ["a", 1.0, -0.1]),
        ("center", ["", 1.0]),
        ("center", ["b", "x"]),
        ("shape", "a"),
    ):
        with pytest.raises(FitError):
            ComponentLink.parse(kind, raw, owner="b")
    with pytest.raises(FitError, match="itself"):
        ComponentLink.parse("width", "b", owner="b")
    assert ComponentLink.parse("area", {"target": "a", "value": 0.5}) == ComponentLink("a", 0.5)
    cyclic = [
        ComponentSpec("a", 1.0, area_link=ComponentLink("b", 2.0)),
        ComponentSpec("b", 2.0, area_link=ComponentLink("a", 0.5)),
    ]
    with pytest.raises(FitError, match="circular area link"):
        check_link_cycles(cyclic)
    # a link whose target is not in the model is ignored with a warning
    x = _main_and_satellite()
    r = fit_peaks(
        x,
        [
            ComponentSpec("C-C", 284.7, 30000.0, fwhm_g=1.1),
            ComponentSpec("sat", 291.3, 1000.0, area_link=ComponentLink("C-O", 0.1)),
        ],
        SETTINGS,
    )
    assert any("area link to 'C-O' ignored" in w for w in r.warnings)
    # a width link against the direction of a shared width is not a cycle
    shared = replace(SETTINGS, constraints=PeakConstraints(share_fwhm_l=True))
    specs = [
        ComponentSpec("C-C", 284.7, 30000.0, fwhm_g=1.1, width_link=ComponentLink("sat")),
        ComponentSpec("sat", 291.3, 1000.0, fwhm_g=1.0),
    ]
    params = build_parameters(specs, shared, x.energy)
    assert params["c1_fwhm_l"].expr == "c0_fwhm_l" and params["c0_fwhm_l"].expr is None
    assert params["c0_fwhm_g"].expr == "c1_fwhm_g"
    fit_peaks(x, specs, shared)


def test_recipe_links_and_model_selection():
    base = load_recipe("p3ht").to_dict()
    c1s = next(r for r in base["regions"] if r["name"] == "C 1s")
    for cand in c1s["candidates"]:
        if cand["label"] in ("C-S/C-N", "C-O"):
            cand["links"] = {"width": "C-C/C-H"}
    recipe = recipe_from_dict(base)
    region = recipe.region("C 1s")
    cands = {c.label: c for c in region.candidates}
    assert cands["C-O"].links == {"width": ComponentLink("C-C/C-H")}
    assert CandidateLine.from_dict(cands["C-O"].to_dict()) == cands["C-O"]
    spec, truth = synthesize(p3ht_c1s(), seed=3)
    sel = select_model(spec, region)
    assert sel.best is not None and sel.best.n_components == 4
    got = {c.label: c for c in sel.best.result.majors()}
    assert got["C-O"].fwhm_g == pytest.approx(got["C-C/C-H"].fwhm_g)
    assert got["C-S/C-N"].fwhm_g == pytest.approx(got["C-C/C-H"].fwhm_g)
    assert got["O-C=O"].fwhm_g != pytest.approx(got["C-C/C-H"].fwhm_g)
    # recipe errors: unknown target, cycle
    bad = load_recipe("p3ht").region("C 1s").to_dict()
    bad["candidates"][1]["links"] = {"area": ["graphite", 0.3]}
    with pytest.raises(ValueError, match="not a candidate"):
        RegionSpec.from_dict(bad)
    bad["candidates"][1]["links"] = {"area": ["C-C/C-H", 0.3]}
    bad["candidates"][0]["links"] = {"area": ["C-S/C-N", 3.0]}
    with pytest.raises(ValueError, match="circular area link"):
        RegionSpec.from_dict(bad)
