from pathlib import Path

import pytest

from xps_autofit.cli import main
from xps_autofit.core.quantification import NOT_CALCULABLE, atomic_percent, auger_parameter
from xps_autofit.database import SCOFIELD_AL_KALPHA, get_rsf, spin_orbit, suggest_assignments
from xps_autofit.recipes import builtin_recipe_names, load_recipe, save_recipe


def test_cli_end_to_end(tmp_path, capsys):
    data = tmp_path / "data"
    assert main(["synth", "--out", str(data)]) == 0
    assert (data / "truth.json").exists()
    assert main(["info", str(data / "p3ht_aged_multi.vms")]) == 0
    out = capsys.readouterr().out
    assert "2 spectrum/spectra" in out
    res = tmp_path / "res"
    rc = main(
        [
            "fit",
            str(data / "p3ht_aged_S2p.csv"),
            "--recipe",
            "p3ht",
            "--output",
            str(res),
            "--formats",
            "csv,json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "thiophene C-S-C" in out and "[          ok] S 2p  n=2" in out
    project = res / "p3ht_aged_S2p__S_2p.json"
    assert project.exists()
    assert main(["verify", str(project)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_adhoc_region_and_batch(tmp_path, capsys):
    data = tmp_path / "data"
    main(["synth", "--out", str(data)])
    res = tmp_path / "adhoc"
    rc = main(
        [
            "fit",
            str(data / "p3ht_fresh_S2p.csv"),
            "--range",
            "160",
            "172",
            "--doublet",
            "1.18",
            "0.5",
            "--max-components",
            "2",
            "--element",
            "S",
            "--line",
            "2p",
            "--output",
            str(res),
            "--formats",
            "csv",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "n=1" in out
    rc = main(
        [
            "batch",
            str(data),
            "--recipe",
            "p3ht",
            "--region",
            "S 2p",
            "--output",
            str(tmp_path / "batch"),
            "--formats",
            "csv",
        ]
    )
    assert rc == 0
    assert (tmp_path / "batch" / "summary_components.csv").exists()


def test_cli_recipes_and_gui(capsys):
    assert main(["recipes"]) == 0
    assert "p3ht" in capsys.readouterr().out
    assert main(["recipes", "--show", "cu2o"]) == 0
    assert "Cu LMM" in capsys.readouterr().out


def test_cli_gui_command_delegates_to_the_app(monkeypatch):
    pytest.importorskip("PySide6")
    import xps_autofit.gui as gui

    monkeypatch.setattr(gui, "run", lambda argv: 0)
    assert main(["gui"]) == 0


def test_recipe_save_and_reload(tmp_path):
    r = load_recipe("cbo")
    p = save_recipe(r, tmp_path / "cbo_copy.yaml")
    r2 = load_recipe(p)
    assert [x.name for x in r2.regions] == [x.name for x in r.regions]
    assert r2.region("Bi 4f").doublet.area_ratio == pytest.approx(0.75)
    assert r2.region("Bi 4f").rsf is None
    with pytest.raises(FileNotFoundError):
        load_recipe("does_not_exist")
    assert set(builtin_recipe_names()) >= {"p3ht", "cu2o", "cbo", "sam_2pacz"}


def test_database_helpers():
    assert spin_orbit("S", "2p") == (1.18, 0.5)
    assert spin_orbit("Cu", "2p3/2") == (19.75, 0.5)
    assert spin_orbit("C", "1s") is None
    hits = suggest_assignments("S", "2p", 164.05)
    assert hits and hits[0]["species"].startswith("thiophene")
    assert suggest_assignments("Cu", "2p3/2", 933.7)[0]["species"] == "Cu(II) CuO"
    assert suggest_assignments(None, None, 1.0) == []
    assert get_rsf("C", "1s") == 1.0 and get_rsf("Bi", "4f") is None
    assert SCOFIELD_AL_KALPHA["O 1s"] == pytest.approx(2.93)


def test_quantification():
    q = atomic_percent([("C 1s", "C", "1s", 1000.0, 1.0), ("O 1s", "O", "1s", 2930.0, 2.93)])
    assert q.status == "OK"
    assert [round(e.atomic_percent, 6) for e in q.entries] == [50.0, 50.0]
    q2 = atomic_percent([("C 1s", "C", "1s", 1000.0, 1.0), ("Bi 4f", "Bi", "4f", 5.0, None)])
    assert q2.status == NOT_CALCULABLE and q2.missing == ["Bi 4f"]
    assert atomic_percent([]).status == NOT_CALCULABLE
    assert auger_parameter(932.4, 916.8) == pytest.approx(1849.2)


def test_examples_folder_is_regenerable(tmp_path):
    from xps_autofit.synthetic import example_dataset

    paths = example_dataset(tmp_path)
    assert {p.suffix for p in paths} >= {".csv", ".txt", ".vms", ".json"}
    assert all(Path(p).exists() for p in paths)
