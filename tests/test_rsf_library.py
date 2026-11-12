"""Instrument RSF libraries: reading, precedence, batch runs, recipes, command line."""

from __future__ import annotations

import pandas as pd
import pytest
import yaml

from xps_autofit.automation.batch_fitting import RunOptions, fit_file, run_batch
from xps_autofit.cli import main
from xps_autofit.database.rsf_library import (
    RsfLibrary,
    RsfLibraryError,
    load_rsf_library,
    resolve_rsf,
)
from xps_autofit.recipes import load_recipe, save_recipe
from xps_autofit.synthetic import example_dataset


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("rsf_data")
    example_dataset(d, seed=4)
    return d


def test_reading_csv_and_yaml_libraries(tmp_path):
    csv = tmp_path / "althermo.csv"
    csv.write_text("element,line,rsf,note\nC,1s,1.0,\nS,2p,2.0,instrument\nCu,2p3/2,16.73,\n\n")
    lib = load_rsf_library(csv)
    assert lib.name == "althermo" and len(lib) == 3
    assert lib.get("S", "2p") == 2.0 and lib.get("s", "2P") == 2.0
    assert lib.get("Cu", "2p 3/2") == 16.73
    assert lib.get("Cu", "2p") is None, "a doublet total is a different factor"
    assert lib.get(None, "1s") is None and lib.notes["S 2p"] == "instrument"
    # semicolons, decimal commas and a label column (European exports)
    semi = tmp_path / "eu.csv"
    semi.write_text("label;RSF\nC 1s;1,000\nO 1s;2,881\n", encoding="utf-8")
    lib2 = load_rsf_library(semi)
    assert lib2.get("O", "1s") == pytest.approx(2.881)
    y = tmp_path / "lib.yaml"
    y.write_text(
        yaml.safe_dump({"name": "Nexsa", "source": "Avantage", "factors": {"C 1s": 1, "S 2p": 1.8}})
    )
    lib3 = load_rsf_library(y)
    assert lib3.name == "Nexsa" and lib3.get("S", "2p") == 1.8
    assert "Nexsa (Avantage), 2 factors" in lib3.describe()
    assert lib3.to_dict()["factors"] == {"C 1s": 1.0, "S 2p": 1.8}
    for bad, text in (
        ("norsf.csv", "element,line,value\nC,1s,1\n"),
        ("zero.csv", "element,line,rsf\nC,1s,0\n"),
        ("word.csv", "element,line,rsf\nC,1s,big\n"),
        ("label.csv", "label,rsf\nC1s,1\n"),
        ("empty.csv", "element,line,rsf\n"),
    ):
        (tmp_path / bad).write_text(text)
        with pytest.raises(RsfLibraryError):
            load_rsf_library(tmp_path / bad)
    (tmp_path / "list.yaml").write_text("- C 1s\n")
    with pytest.raises(RsfLibraryError):
        load_rsf_library(tmp_path / "list.yaml")
    with pytest.raises(RsfLibraryError):
        load_rsf_library(tmp_path / "missing.csv")


def test_precedence():
    lib = RsfLibrary("inst", {"S 2p": 2.0})
    assert resolve_rsf("S", "2p", 1.677, lib) == (2.0, "library inst")
    assert resolve_rsf("C", "1s", 1.0, lib) == (1.0, "recipe")
    assert resolve_rsf("C", "1s", None, lib) == (None, "missing")
    value, source = resolve_rsf("C", "1s", None, lib, scofield=True)
    assert source == "Scofield" and value == pytest.approx(1.0)
    assert resolve_rsf("Xx", "9z", None, None, scofield=True) == (None, "missing")


def test_batch_uses_the_library(data_dir, tmp_path):
    vms = data_dir / "p3ht_aged_multi.vms"
    recipe = load_recipe("p3ht")
    plain = fit_file(vms, recipe, RunOptions(tmp_path / "plain", formats=("json",)))
    lib = RsfLibrary("inst", {"S 2p": 2.0, "C 1s": 1.0}, source="test")
    with_lib = fit_file(
        vms, recipe, RunOptions(tmp_path / "lib", formats=("json",), rsf_library=lib)
    )
    a = {e.label: e for e in plain.quantification.entries}
    b = {e.label: e for e in with_lib.quantification.entries}
    assert a["S 2p"].rsf == pytest.approx(1.677) and a["S 2p"].rsf_source == "recipe"
    assert b["S 2p"].rsf == 2.0 and b["S 2p"].rsf_source == "library inst"
    # the S share scales with 1.677 / 2.0 (areas are the same fits)
    ratio_a = a["S 2p"].atomic_percent / a["C 1s"].atomic_percent
    ratio_b = b["S 2p"].atomic_percent / b["C 1s"].atomic_percent
    assert ratio_b == pytest.approx(ratio_a * 1.677 / 2.0, rel=1e-6)
    assert "RSF library inst (test)" in with_lib.quantification.note
    out = tmp_path / "batch"
    run_batch([vms], recipe, RunOptions(out, formats=("csv",), rsf_library=lib))
    q = pd.read_csv(out / "summary_quantification.csv")
    assert set(q["rsf_source"]) == {"library inst"}


def test_recipe_names_a_library_next_to_it(data_dir, tmp_path):
    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "inst.csv").write_text("element,line,rsf\nS,2p,2.5\n")
    recipe = load_recipe("p3ht")
    data = recipe.to_dict()
    data["rsf_library"] = "libs/inst.csv"
    path = tmp_path / "my.yaml"
    path.write_text(yaml.safe_dump(data))
    loaded = load_recipe(path)
    assert loaded.rsf_library == str(tmp_path / "libs" / "inst.csv")
    rep = fit_file(
        data_dir / "p3ht_aged_multi.vms", loaded, RunOptions(tmp_path / "o", formats=("json",))
    )
    s2p = next(e for e in rep.quantification.entries if e.label == "S 2p")
    assert s2p.rsf == 2.5 and s2p.rsf_source == "library inst"
    # saving and reading back keeps the (absolute) path
    save_recipe(loaded, tmp_path / "again.yaml")
    assert load_recipe(tmp_path / "again.yaml").rsf_library == loaded.rsf_library


def test_command_line_option(data_dir, tmp_path, capsys):
    lib = tmp_path / "inst.csv"
    lib.write_text("element,line,rsf\nS,2p,2.0\nC,1s,1.0\n")
    out = tmp_path / "cli"
    rc = main(
        [
            "fit",
            str(data_dir / "p3ht_aged_multi.vms"),
            "--recipe",
            "p3ht",
            "--output",
            str(out),
            "--formats",
            "csv",
            "--rsf-library",
            str(lib),
        ]
    )
    assert rc == 0
    q = pd.read_csv(out / "summary_quantification.csv")
    assert (q["rsf"] == q["element"].map({"S": 2.0, "C": 1.0})).all()
