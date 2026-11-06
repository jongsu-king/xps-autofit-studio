import json
from pathlib import Path

import numpy as np
import pytest

from xps_autofit.automation.batch_fitting import RunOptions, fit_file, match_regions, run_batch
from xps_autofit.core.uncertainty import bootstrap
from xps_autofit.export.project import load_project, refit_from_project, verify_project
from xps_autofit.readers import read_spectra
from xps_autofit.recipes import load_recipe, recipe_from_dict
from xps_autofit.synthetic import example_dataset


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    example_dataset(d, seed=3)
    return d


def test_batch_equals_individual(data_dir, tmp_path):
    recipe = load_recipe("p3ht")
    files = [data_dir / "p3ht_fresh_S2p.csv", data_dir / "p3ht_aged_S2p.csv"]
    batch = run_batch(files, recipe, RunOptions(tmp_path / "batch", formats=("json",)))
    for f, rep in zip(files, batch.files):
        single = fit_file(f, recipe, RunOptions(tmp_path / "single", formats=("json",)))
        for rb, rs in zip(rep.regions, single.regions):
            pb = rb.selection.best.result.params
            ps_ = rs.selection.best.result.params
            assert pb.keys() == ps_.keys()
            for k in pb:
                assert pb[k]["value"] == ps_[k]["value"]
    assert (tmp_path / "batch" / "summary_components.csv").exists()
    assert (tmp_path / "batch" / "summary_regions.csv").exists()


def test_outputs_and_project_roundtrip(data_dir, tmp_path):
    recipe = load_recipe("p3ht")
    opts = RunOptions(tmp_path, formats=("csv", "xlsx", "json", "png", "svg"))
    rep = fit_file(data_dir / "p3ht_aged_S2p.csv", recipe, opts)
    region = rep.regions[0]
    assert region.status == "ok" and region.n_components == 2
    for key in ("json", "csv", "xlsx", "png", "svg"):
        assert Path(region.outputs[key]).exists()
    assert (tmp_path / "p3ht_aged_S2p__S_2p_models.csv").exists()
    assert (tmp_path / "p3ht_aged_S2p__S_2p_fit.csv").exists()

    project = load_project(region.outputs["json"])
    assert project["format"] == 1 and project["environment"]["xps_autofit"]
    assert project["selection"]["best_n"] == 2
    assert "charge_shift_eV" in project
    spectrum, refit = refit_from_project(project)
    stored = project["selection"]["best"]["fit"]["components"]
    for a, b in zip(stored, refit.components):
        assert a["center"] == pytest.approx(b.center, abs=1e-9)
    report = verify_project(region.outputs["json"])
    assert report.ok, report.messages


def test_verify_detects_tampering(data_dir, tmp_path):
    rep = fit_file(
        data_dir / "p3ht_fresh_S2p.csv",
        load_recipe("p3ht"),
        RunOptions(tmp_path, formats=("json",)),
    )
    p = Path(rep.regions[0].outputs["json"])
    d = json.loads(p.read_text())
    d["selection"]["best"]["fit"]["params"]["c0_center"]["value"] += 0.5
    p.write_text(json.dumps(d))
    assert not verify_project(p).ok


def test_vamas_multi_region_with_charge_correction(data_dir, tmp_path):
    rep = fit_file(
        data_dir / "p3ht_aged_multi.vms",
        load_recipe("p3ht"),
        RunOptions(tmp_path, formats=("json",)),
    )
    assert rep.n_spectra == 2 and len(rep.regions) == 2
    assert rep.charge_shift_eV is not None and abs(rep.charge_shift_eV) < 0.1
    assert any("convention" in m for m in rep.messages)
    assert rep.quantification is not None and rep.quantification.status == "OK"
    total = sum(e.atomic_percent for e in rep.quantification.entries)
    assert total == pytest.approx(100.0)
    s2p = next(r for r in rep.regions if r.region == "S 2p")
    main = max(s2p.selection.best.result.majors(), key=lambda c: c.area)
    assert abs(main.center - 164.0) < 0.05
    off = fit_file(
        data_dir / "p3ht_aged_multi.vms",
        load_recipe("p3ht"),
        RunOptions(tmp_path / "off", formats=("json",), charge_correct=False),
    )
    assert off.charge_shift_eV is None


def test_missing_rsf_is_not_calculable(data_dir, tmp_path):
    recipe = load_recipe("p3ht")
    recipe.regions[1].rsf = None
    rep = fit_file(
        data_dir / "p3ht_aged_multi.vms", recipe, RunOptions(tmp_path, formats=("json",))
    )
    assert rep.quantification.status == "NOT_CALCULABLE"
    assert rep.quantification.missing == ["S 2p"]
    assert all(e.atomic_percent is None for e in rep.quantification.entries)


def test_no_matching_region_reports_message(data_dir, tmp_path):
    rep = fit_file(
        data_dir / "cu2o_Cu2p3.txt", load_recipe("p3ht"), RunOptions(tmp_path, formats=("json",))
    )
    assert rep.regions == [] and rep.messages


def test_match_regions_prefers_metadata(data_dir):
    spectra = read_spectra(data_dir / "p3ht_aged_multi.vms")
    pairs = match_regions(spectra, load_recipe("p3ht"))
    assert {r.name for _, r in pairs} == {"C 1s", "S 2p"}
    pairs = match_regions(spectra, load_recipe("p3ht"), region_filter=["s 2p"])
    assert [r.name for _, r in pairs] == ["S 2p"]


def test_auger_region_reports_parameter(tmp_path):
    from xps_autofit.core.spectrum import Spectrum
    from xps_autofit.readers.vamas_reader import write_vamas
    from xps_autofit.synthetic import cu2p3_mixed, synthesize

    cu, _ = synthesize(cu2p3_mixed(), seed=4)
    cu.metadata.update({"species": "Cu", "transition": "2p3/2"})
    be = np.arange(560.0, 578.0, 0.1)
    ke = 1486.6 - be
    y = 500.0 + 4000.0 * np.exp(-0.5 * ((ke - 916.8) / 1.2) ** 2)
    lmm = Spectrum(
        be,
        np.random.default_rng(0).poisson(y).astype(float),
        photon_energy=1486.6,
        metadata={"species": "Cu", "transition": "LMM"},
    )
    p = write_vamas(tmp_path / "cu.vms", [cu, lmm])
    rep = fit_file(p, load_recipe("cu2o"), RunOptions(tmp_path, formats=("json",)))
    aug = next(r for r in rep.regions if r.region == "Cu LMM")
    assert aug.status == "reported"
    assert aug.auger["max_kinetic_energy_eV"] == pytest.approx(916.8, abs=0.3)
    assert aug.auger["modified_auger_parameter_eV"] == pytest.approx(932.5 + 916.8, abs=0.4)


def test_bootstrap_runs(aged_s2p, s2p_region):
    from xps_autofit.automation.model_selection import select_model

    spec, _ = aged_s2p
    sel = select_model(spec, s2p_region)
    b = bootstrap(sel.spectrum, sel.best.result, n=5, seed=1)
    assert b.n_succeeded == 5 and b.mode == "poisson"
    assert "thiophene C-S-C" in b.summary and "area" in b.summary["thiophene C-S-C"]


def test_recipe_from_dict_validation():
    with pytest.raises(ValueError):
        recipe_from_dict({"name": "x", "regions": [{"name": "A"}, {"name": "A"}]})
    r = recipe_from_dict(
        {
            "name": "y",
            "regions": [{"name": "S 2p", "element": "S", "line": "2p", "doublet": "auto"}],
        }
    )
    assert r.regions[0].doublet.splitting == pytest.approx(1.18)
    with pytest.raises(ValueError):
        recipe_from_dict(
            {
                "name": "z",
                "regions": [{"name": "Q", "element": "Xx", "line": "9z", "doublet": "auto"}],
            }
        )
