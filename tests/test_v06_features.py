"""Origin-style figures, recipe suggestion from a survey (engine and CLI)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest
import yaml

from xps_autofit.automation.identify import identify_elements
from xps_autofit.automation.model_selection import select_model
from xps_autofit.automation.suggest import suggest_recipe, suggest_regions
from xps_autofit.cli import main
from xps_autofit.export.plots import (
    FIGURE_STYLES,
    ORIGIN_FONTS,
    origin_font_family,
    plot_candidates,
    plot_fit,
)
from xps_autofit.recipes import load_recipe, save_recipe
from xps_autofit.synthetic import p3ht_s2p, synthesize, synthesize_survey


@pytest.fixture(scope="module")
def s2p_selection(tmp_path_factory):
    spec, _truth = synthesize(p3ht_s2p(True), seed=2)
    recipe = load_recipe("p3ht")
    region = recipe.region("S 2p")
    assert region is not None
    return select_model(spec, region)


@pytest.fixture(scope="module")
def survey_ident():
    survey, truth = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5, "N": 0.15}, seed=7)
    return survey, identify_elements(survey)


def test_origin_figure_has_box_axes_and_inward_ticks(s2p_selection, tmp_path):
    result = s2p_selection.best.result
    for style in FIGURE_STYLES:
        fig = plot_fit(result, tmp_path / f"{style}.png", title="S 2p", style=style)
        assert (tmp_path / f"{style}.png").stat().st_size > 10_000
        plt.close(fig)
    fig = plot_fit(result, style="origin")
    ax, axr = fig.axes
    assert ax.spines["top"].get_visible() and ax.spines["right"].get_visible()
    assert ax.xaxis.get_tick_params(which="major")["direction"] == "in"
    assert axr.yaxis.get_tick_params(which="major")["direction"] == "in"
    assert ax.get_facecolor() == (1.0, 1.0, 1.0, 1.0)
    legend = ax.get_legend()
    assert legend is not None and legend.get_frame_on()
    envelope = next(line for line in ax.get_lines() if line.get_label() == "Envelope")
    assert envelope.get_color() == "#d62728"
    raw = next(line for line in ax.get_lines() if line.get_label() == "Raw")
    assert raw.get_markeredgecolor() == "#000000" and raw.get_markerfacecolor() == "none"
    assert not any(gl.get_visible() for gl in ax.get_xgridlines())
    # fonts live on the artists, so the returned figure keeps them outside rc_context
    family = origin_font_family()
    assert family in ORIGIN_FONTS
    assert ax.yaxis.get_label().get_fontfamily()[0] == family
    assert ax.get_yticklabels()[0].get_fontfamily()[0] == family
    plt.close(fig)
    fig = plot_fit(result, style="classic")
    ax = fig.axes[0]
    assert not ax.spines["top"].get_visible()
    assert any(gl.get_visible() for gl in ax.get_xgridlines())
    plt.close(fig)
    with pytest.raises(ValueError):
        plot_fit(result, style="excel")
    fig = plot_candidates(s2p_selection, tmp_path / "models.png", style="origin")
    assert fig.axes[0].spines["top"].get_visible()
    plt.close(fig)


def test_recipe_suggested_from_survey(survey_ident, tmp_path):
    survey, ident = survey_ident
    found = {c.element for c in ident.candidates}
    assert {"Cu", "O", "C"} <= found
    regions = suggest_regions(ident, min_confidence=0.5)
    names = {r.name: r for r in regions}
    assert {"Cu 2p3/2", "O 1s", "C 1s"} <= set(names)
    cu = names["Cu 2p3/2"]
    assert cu.doublet is None, "a listed spin-orbit component is fitted on its own"
    assert cu.rsf == pytest.approx(16.73) and cu.element == "Cu" and cu.line == "2p3/2"
    assert cu.range is not None and cu.range[0] < 933.0 < cu.range[1]
    assert cu.range[1] - cu.range[0] == pytest.approx(16.0)
    o1s = names["O 1s"]
    assert o1s.range is not None and abs((o1s.range[0] + o1s.range[1]) / 2 - 531.5) < 2.0
    assert all(r.range[1] % 0.5 == 0 and r.range[0] % 0.5 == 0 for r in regions if r.range)
    assert all("suggested from survey" in r.notes for r in regions)

    recipe = suggest_recipe(ident, name="cu_survey")
    assert recipe.charge_reference is not None
    assert recipe.charge_reference.region == "C 1s"
    assert recipe.charge_reference.value == pytest.approx(284.8)
    assert recipe.photon_energy == pytest.approx(ident.photon_energy)
    path = save_recipe(recipe, tmp_path / "cu_survey.yaml")
    loaded = load_recipe(path)
    assert [r.name for r in loaded.regions] == [r.name for r in recipe.regions]
    assert loaded.region("Cu 2p3/2").rsf == pytest.approx(16.73)
    with pytest.raises(ValueError):
        suggest_recipe(ident, min_confidence=1.01)
    # a charged sample: the ranges follow the measured peaks
    shifted = survey.shift(2.0, "simulated charging")
    ident2 = identify_elements(shifted, charge_shift=2.0)
    regions2 = {r.name: r for r in suggest_regions(ident2)}
    assert regions2["O 1s"].range[0] == pytest.approx(o1s.range[0] + 2.0, abs=0.5)


def test_suggest_cli_writes_a_usable_recipe(tmp_path, capsys):
    survey, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=8)
    lines = ["Binding Energy (eV),Counts"] + [
        f"{e:.2f},{int(i)}" for e, i in zip(survey.energy, survey.intensity)
    ]
    csv = tmp_path / "survey.csv"
    csv.write_text("\n".join(lines), encoding="utf-8")
    out = tmp_path / "survey_recipe.yaml"
    assert main(["suggest", str(csv), "-o", str(out), "--name", "from-survey"]) == 0
    text = capsys.readouterr().out
    assert "Cu 2p3/2" in text and "charge reference: C 1s" in text and "recipe written" in text
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["name"] == "from-survey" and data["source"] == "survey"
    recipe = load_recipe(out)
    assert recipe.region("O 1s") is not None
    # the recipe matches the high-resolution regions by energy range
    from xps_autofit.automation.batch_fitting import match_regions

    o1s_spec = survey.crop(*recipe.region("O 1s").range)
    pairs = match_regions([o1s_spec], recipe)
    assert [r.name for _s, r in pairs] == ["O 1s"]
    assert main(["suggest", str(csv), "--min-confidence", "1.01"]) == 1
    assert main(["suggest", str(csv)]) == 0
    assert "regions:" in capsys.readouterr().out
    assert np.isfinite(recipe.photon_energy)
