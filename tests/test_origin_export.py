"""Origin export: label rows, columns, batch format, finding and opening Origin."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from xps_autofit.automation.batch_fitting import RunOptions, fit_file
from xps_autofit.automation.model_selection import select_model
from xps_autofit.export.origin import (
    ORIGIN_ENV,
    component_columns,
    find_origin_executable,
    fit_columns,
    open_in_origin,
    overlay_columns,
    write_origin_csv,
)
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import example_dataset, p3ht_s2p, synthesize


@pytest.fixture(scope="module")
def s2p_fit():
    spec, _ = synthesize(p3ht_s2p(True), seed=2, name="P3HT aged S 2p")
    sel = select_model(spec, load_recipe("p3ht").region("S 2p"))
    return spec, sel.best.result


def _read(path: Path) -> tuple[list[list[str]], np.ndarray]:
    lines = path.read_text(encoding="utf-8").splitlines()
    labels = [ln.split(",") for ln in lines[:3]]
    data = np.genfromtxt(lines[3:], delimiter=",")
    return labels, np.atleast_2d(data)


def test_fit_curves_carry_origin_label_rows(s2p_fit, tmp_path):
    _spec, result = s2p_fit
    path = write_origin_csv(tmp_path / "s2p_origin.csv", fit_columns(result))
    (long_names, units, comments), data = _read(path)
    majors = [c.label for c in result.majors()]
    assert long_names[:4] == ["Binding Energy", "Raw", "Background", "Envelope"]
    assert long_names[-1] == "Residual"
    assert all(m in long_names for m in majors)
    assert units[0] == "eV" and set(units[1:]) == {"counts"}
    assert comments[0] == "X" and "shirley" in comments[2]
    first = long_names.index(majors[0])
    assert "eV; FWHM" in comments[first] and "%" in comments[first]
    assert data.shape == (result.x.size, len(long_names))
    assert np.allclose(data[:, 0], result.x)
    assert np.allclose(data[:, 1], result.y)
    assert np.allclose(data[:, 3], result.model, rtol=1e-9)
    comp = result.components[0]
    assert np.allclose(data[:, 4], comp.values + result.background_total, rtol=1e-9)
    # label rows are plain ASCII without separators that would split a cell
    text = path.read_text(encoding="utf-8")
    assert text.isascii()
    assert all(len(row) == len(long_names) for row in (units, comments))


def test_component_table_and_overlay_pairs(s2p_fit, tmp_path):
    spec, result = s2p_fit
    path = write_origin_csv(tmp_path / "table.csv", component_columns(result))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Component,Centre,Centre error,FWHM,Area")
    assert lines[1].split(",")[1] == "eV"
    assert len(lines) == 3 + len(result.components)
    assert lines[3].split(",")[0] == result.components[0].label.replace(",", ";")
    short = spec.crop(161.0, 166.0)
    path = write_origin_csv(
        tmp_path / "overlay.csv", overlay_columns([("aged", spec), ("short, cropped", short)])
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Binding Energy,aged,Binding Energy,short; cropped"
    assert lines[2].split(",")[0] == "X of aged"
    assert len(lines) == 3 + spec.n
    assert lines[-1].endswith(",,"), "the shorter pair is padded with empty cells"
    with pytest.raises(ValueError):
        write_origin_csv(tmp_path / "none.csv", [])


def test_batch_origin_format(tmp_path):
    data = tmp_path / "data"
    example_dataset(data, seed=6)
    rep = fit_file(
        data / "p3ht_aged_S2p.csv",
        load_recipe("p3ht"),
        RunOptions(tmp_path / "out", formats=("origin",)),
    )
    outputs = rep.regions[0].outputs
    curves, table = Path(outputs["origin"]), Path(outputs["origin_components"])
    assert curves.name == "p3ht_aged_S2p__S_2p_origin.csv" and curves.exists()
    assert table.name == "p3ht_aged_S2p__S_2p_origin_components.csv" and table.exists()
    assert curves.read_text(encoding="utf-8").startswith("Binding Energy,Raw,Background")


def test_finding_and_opening_origin(tmp_path, monkeypatch):
    # explicit path wins on any platform
    exe = tmp_path / "Origin64.exe"
    exe.write_text("")
    assert find_origin_executable({ORIGIN_ENV: str(exe)}, "darwin") == exe
    assert find_origin_executable({ORIGIN_ENV: str(tmp_path / "missing.exe")}, "win32") is None
    # Origin runs on Windows only
    assert find_origin_executable({}, "linux") is None
    # newest installation under Program Files\OriginLab
    pf = tmp_path / "Program Files"
    for version in ("Origin2023", "Origin2025b"):
        d = pf / "OriginLab" / version
        d.mkdir(parents=True)
        (d / "Origin64.exe").write_text("")
        (d / "OriginPro.chm").write_text("")
    found = find_origin_executable({"ProgramFiles": str(pf)}, "win32")
    assert found == pf / "OriginLab" / "Origin2025b" / "Origin64.exe"
    assert find_origin_executable({"ProgramFiles": str(tmp_path / "nothing")}, "win32") is None
    # opening: Origin when found, else the default program
    calls: list[object] = []
    data = tmp_path / "x_origin.csv"
    data.write_text("Binding Energy\n")
    assert open_in_origin(data, executable=found, launcher=calls.append) == "origin"
    assert calls[-1] == [str(found), str(data)]
    monkeypatch.delenv(ORIGIN_ENV, raising=False)
    monkeypatch.setattr("xps_autofit.export.origin.sys.platform", "linux")
    assert open_in_origin(data, launcher=calls.append, fallback=calls.append) == "default"
    assert calls[-1] == data
    assert os.path.exists(data)


def test_pyside_linux_311_combination_is_recognised():
    pytest.importorskip("PySide6")
    from xps_autofit.gui.compat import pyside_refcount_warning

    assert "PySide6<6.12" in pyside_refcount_warning("linux", (3, 11), "6.12.0")
    assert pyside_refcount_warning("linux", (3, 11), "6.13.1") is not None
    assert pyside_refcount_warning("linux", (3, 11), "6.11.3") is None
    assert pyside_refcount_warning("linux", (3, 12), "6.12.0") is None
    assert pyside_refcount_warning("darwin", (3, 11), "6.12.0") is None
    assert pyside_refcount_warning("win32", (3, 11), "6.12.0") is None
    assert pyside_refcount_warning("linux", (3, 11), "dev") is None
    # the package's own markers keep pip away from that combination
    import tomllib

    from packaging.requirements import Requirement

    root = Path(__file__).resolve().parents[1]
    gui = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["gui"]
    linux311 = [
        Requirement(r)
        for r in gui
        if Requirement(r).name == "PySide6"
        and Requirement(r).marker.evaluate({"sys_platform": "linux", "python_version": "3.11"})
    ]
    assert len(linux311) == 1 and not linux311[0].specifier.contains("6.12.0")
