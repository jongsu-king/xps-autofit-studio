"""Valence-band maximum by linear extrapolation of the leading edge."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from xps_autofit.automation.valence_band import VBEdgeError, find_vb_edge
from xps_autofit.cli import main
from xps_autofit.core.spectrum import Spectrum
from xps_autofit.synthetic import synthesize_valence_band


def _csv(path: Path, spec: Spectrum) -> Path:
    rows = [f"{a:.3f},{int(b)}" for a, b in zip(spec.energy, spec.intensity)]
    path.write_text("Binding Energy (eV),Counts\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("vbm", [0.8, 1.5, 2.6])
def test_vbm_is_recovered(vbm):
    for seed in (1, 2, 3):
        spec, truth = synthesize_valence_band(vbm=vbm, seed=seed, resolution_fwhm=0.5)
        edge = find_vb_edge(spec)
        assert edge.vbm == pytest.approx(truth["vbm"], abs=0.04)
        assert edge.vbm_err is not None and 0.005 < edge.vbm_err < 0.05
        assert abs(edge.vbm - vbm) < 3 * edge.vbm_err + 0.02
        assert edge.window_spread is not None and edge.window_spread < 0.05
        assert edge.edge.lo > vbm and edge.edge.hi < edge.band_maximum
        assert edge.baseline.hi < vbm and edge.baseline.n >= 5
        assert not edge.notes


def test_broad_resolution_reads_low_and_explicit_windows():
    # a 0.9 eV resolution rounds the foot into the default window: the extrapolation
    # lands a few hundredths of an eV low (documented in algorithm.md)
    lows = []
    for seed in (1, 2, 3):
        spec, truth = synthesize_valence_band(vbm=1.5, seed=seed, resolution_fwhm=0.9)
        lows.append(truth["vbm"] - find_vb_edge(spec).vbm)
    assert all(0.0 < d < 0.12 for d in lows)
    # explicit energy windows replace the automatic ones (no window spread then)
    spec, _ = synthesize_valence_band(vbm=1.5, seed=1)
    edge = find_vb_edge(spec, edge=(2.0, 2.8), baseline=(-2.5, 0.8))
    assert (edge.edge.lo, edge.edge.hi) == (2.0, 2.8)
    assert (edge.baseline.lo, edge.baseline.hi) == (-2.5, 0.8)
    assert edge.window_spread is None and edge.edge_window is None
    assert edge.vbm == pytest.approx(1.5, abs=0.05)
    d = edge.to_dict()
    assert d["vbm_eV"] == edge.vbm and d["edge"]["range_eV"] == [2.0, 2.8]


def test_vbm_errors_and_fallbacks():
    spec, _ = synthesize_valence_band(vbm=1.5, seed=1)
    with pytest.raises(VBEdgeError, match="binding"):
        find_vb_edge(Spectrum(1486.6 - spec.energy, spec.intensity, axis="kinetic"))
    with pytest.raises(VBEdgeError, match="starts on the edge"):
        find_vb_edge(spec, energy_range=(2.6, 12.0))  # cropped past the foot
    with pytest.raises(VBEdgeError, match="too few"):
        find_vb_edge(spec, energy_range=(0.0, 0.5))
    with pytest.raises(VBEdgeError, match="edge_window"):
        find_vb_edge(spec, edge_window=(0.6, 0.2))
    flat = Spectrum(spec.energy, np.full_like(spec.energy, 100.0), name="flat")
    with pytest.raises(VBEdgeError):
        find_vb_edge(flat)
    # a baseline too short for a line falls back to a flat one and says so
    short = find_vb_edge(spec, energy_range=(1.1, 12.0))
    assert any("flat baseline" in n for n in short.notes)
    assert short.baseline.slope == 0.0
    assert short.vbm == pytest.approx(1.5, abs=0.1)


def test_vbm_command_line(tmp_path, capsys):
    spec, _ = synthesize_valence_band(vbm=1.2, seed=4)
    f = _csv(tmp_path / "vb.csv", spec)
    assert main(["vbm", str(f), "--plot", str(tmp_path / "fig")]) == 0
    out = capsys.readouterr().out
    import re

    vbm = float(re.search(r"VBM (\d+\.\d+)", out).group(1))
    assert vbm == pytest.approx(1.2, abs=0.05) and "first band maximum" in out
    assert (tmp_path / "fig" / "vb_vbm.png").stat().st_size > 10_000
    assert main(["vbm", str(f), "--json", "--edge-window", "0.3", "0.7"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["vbm_eV"] == pytest.approx(1.2, abs=0.05)
    assert data[0]["edge_window"] == [0.3, 0.7]
    # a file without an edge reports and returns 1
    g = _csv(tmp_path / "flat.csv", Spectrum(spec.energy, np.full_like(spec.energy, 50.0)))
    assert main(["vbm", str(g)]) == 1
    assert "flat.csv" in capsys.readouterr().out


def test_vbm_figure_styles(tmp_path):
    from xps_autofit.export.plots import plot_vb_edge

    spec, _ = synthesize_valence_band(vbm=1.5, seed=2)
    edge = find_vb_edge(spec)
    for style in ("origin", "classic"):
        fig = plot_vb_edge(spec, edge, title="VB", style=style)
        ax = fig.axes[0]
        assert ax.get_xlim()[0] > ax.get_xlim()[1]  # binding energy decreasing to the right
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert labels == ["Raw", "Baseline", "Leading edge"]
        assert any("VBM 1.4" in t.get_text() or "VBM 1.5" in t.get_text() for t in ax.texts)
        import matplotlib.pyplot as plt

        plt.close(fig)
    path = tmp_path / "vb.svg"
    plot_vb_edge(spec, edge, path)
    assert path.read_text().startswith("<?xml")


def test_vbm_region_in_a_batch(tmp_path):
    import pandas as pd

    from xps_autofit.automation.batch_fitting import RunOptions, run_batch
    from xps_autofit.core.region import RegionSpec
    from xps_autofit.recipes import recipe_from_dict

    data = tmp_path / "vb"
    data.mkdir()
    truths = {}
    for i, vbm in enumerate((1.1, 1.6, 2.2), start=1):
        spec, truth = synthesize_valence_band(vbm=vbm, seed=i)
        _csv(data / f"film_{i}.csv", spec)
        truths[f"film_{i}"] = truth["vbm"]
    _csv(data / "film_flat.csv", Spectrum(spec.energy, np.full_like(spec.energy, 40.0)))
    recipe = recipe_from_dict(
        {
            "name": "oxide_vb",
            "regions": [
                {
                    "name": "VB",
                    "range": [-3.0, 12.0],
                    "fit": False,
                    "report": "vbm",
                    "vbm_edge_window": [0.2, 0.6],
                    "notes": "VBM by linear extrapolation",
                }
            ],
        }
    )
    region = recipe.region("VB")
    assert region.to_dict()["vbm_edge_window"] == [0.2, 0.6]
    assert RegionSpec.from_dict(region.to_dict()) == region
    out = tmp_path / "out"
    batch = run_batch([data], recipe, RunOptions(out, formats=("csv", "png")))
    rows = pd.read_csv(out / "summary_regions.csv").set_index("sample")
    for stem, vbm in truths.items():
        assert rows.loc[stem, "status"] == "reported"
        assert abs(rows.loc[stem, "vbm_eV"] - vbm) < 0.05
        assert 0 < rows.loc[stem, "vbm_err"] < 0.05
        assert (out / f"{stem}__VB_vbm.png").exists()
    assert rows.loc["film_flat", "status"] == "failed"
    assert "no valence-band edge" in rows.loc["film_flat", "messages"]
    reports = {f.sample: f for f in batch.files}
    assert reports["film_1"].regions[0].vbm["edge_window"] == [0.2, 0.6]
    # recipe errors
    for bad in ({"report": "vbm"}, {"report": "vbm_max", "fit": False}):
        with pytest.raises(ValueError):
            RegionSpec.from_dict({"name": "VB", "range": [-3, 12], **bad})
    with pytest.raises(ValueError, match="vbm_edge_window"):
        RegionSpec.from_dict(
            {"name": "VB", "fit": False, "report": "vbm", "vbm_edge_window": [0.7, 0.3]}
        )
