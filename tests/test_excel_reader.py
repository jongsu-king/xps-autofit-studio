"""Excel workbook input: the layouts instrument software and people produce."""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from openpyxl import Workbook

from xps_autofit.automation.batch_fitting import match_regions
from xps_autofit.cli import main
from xps_autofit.readers import read_spectra, supported_extensions
from xps_autofit.readers.excel_reader import ExcelReadError, read_excel, write_excel
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import example_dataset, p3ht_c1s, p3ht_s2p, synthesize


@pytest.fixture
def s2p():
    return synthesize(p3ht_s2p(True), seed=2)[0]


@pytest.fixture
def c1s():
    return synthesize(p3ht_c1s(), seed=3)[0]


def _book(path, rows, title="Sheet1"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


def test_sheet_per_region_with_metadata_rows(tmp_path, s2p, c1s):
    a, b = s2p.copy(), c1s.copy()
    a.name, b.name = "S 2p", "C1s Scan"
    a.dwell_time_s, a.n_scans = 0.1, 10
    p = write_excel(tmp_path / "regions.xlsx", [a, b], layout="sheets", metadata=True)
    spectra = read_spectra(p)
    assert [s.name for s in spectra] == ["S 2p", "C1s Scan"]
    s, c = spectra
    assert np.allclose(s.energy, s2p.energy) and np.allclose(s.intensity, s2p.intensity)
    assert s.intensity_unit == "counts" and s.photon_energy == pytest.approx(1486.6)
    assert s.dwell_time_s == pytest.approx(0.1) and s.n_scans == 10
    assert s.metadata["species"] == "S" and s.metadata["transition"] == "2p"
    assert c.metadata["species"] == "C" and c.metadata["transition"] == "1s"
    assert s.metadata["format"] == "Excel" and s.metadata["excel_columns"] == "A/B"
    assert s.metadata["header_row"] == 5 and s.metadata["first_row"] == 6
    assert c.metadata["sheet"] == "C1s Scan" and c.n_scans is None
    # a lone spectrum is named after the file
    q = write_excel(tmp_path / "single.xlsx", [a])
    only = read_spectra(q)
    assert len(only) == 1 and only[0].name == "single"
    assert ".xlsx" in supported_extensions() and ".xlsm" in supported_extensions()


def test_shared_axis_series_columns(tmp_path, s2p):
    series = []
    for k, seed in enumerate((4, 5, 6)):
        s = synthesize(p3ht_s2p(k % 2 == 1), seed=seed)[0]
        s.name = ("fresh", "aged", "cycle 3")[k]
        series.append(s)
    p = write_excel(tmp_path / "series.xlsx", series, layout="columns")
    spectra = read_excel(p)
    assert [s.name for s in spectra] == ["fresh", "aged", "cycle 3"]
    for got, want in zip(spectra, series):
        assert np.allclose(got.energy, want.energy) and np.allclose(got.intensity, want.intensity)
    assert spectra[2].metadata["excel_columns"] == "A/D"
    # a header that reads like an energy axis is rewritten so the column stays a series
    series[1].name = "Energy loss"
    spectra = read_excel(write_excel(tmp_path / "s2.xlsx", series, layout="columns"))
    assert len(spectra) == 3 and spectra[1].name == "Counts (Energy loss)"
    with pytest.raises(ValueError):
        write_excel(tmp_path / "bad.xlsx", [series[0], series[0].crop(161, 170)], layout="columns")


def test_side_by_side_pairs_with_different_lengths(tmp_path, s2p, c1s):
    short = s2p.crop(161.0, 168.0)
    short.name, c1s.name = "P3HT S 2p", "P3HT C 1s"
    p = write_excel(tmp_path / "pairs.xlsx", [short, c1s], layout="pairs", descending=True)
    spectra = read_excel(p)
    assert [s.name for s in spectra] == ["P3HT S 2p", "P3HT C 1s"]
    assert spectra[0].n == short.n and spectra[1].n == c1s.n
    assert np.allclose(spectra[0].energy, short.energy)
    assert np.allclose(spectra[1].intensity, c1s.intensity)
    assert spectra[0].history[0]["input_order"] == "descending"
    assert not any(h["step"] == "drop_nonfinite" for s in spectra for h in s.history)
    assert spectra[1].metadata["excel_columns"] == "C/D"


def test_vendor_export_keeps_only_the_measured_column(tmp_path, c1s):
    rows = [
        ["C1s Scan"],
        ["Pass energy (eV)", 20],
        [
            "Binding Energy (E)",
            "Counts / s",
            "Background",
            "Envelope",
            "C-C",
            "C-O",
            "Counts / s (Resid.)",
        ],
    ]
    for e, i in zip(c1s.energy[::-1], c1s.intensity[::-1]):
        rows.append([e, i / 0.1, 100.0, i / 0.1, i / 0.2, i / 0.3, 1.0])
    p = _book(tmp_path / "avantage.xlsx", rows, title="Sheet1")
    spectra = read_spectra(p)
    assert len(spectra) == 1
    s = spectra[0]
    assert s.metadata["intensity_column"] == "Counts / s" and s.intensity_unit == "cps"
    assert s.metadata["table_title"] == "C1s Scan"
    assert s.metadata["species"] == "C" and s.metadata["transition"] == "1s"
    assert np.allclose(s.intensity, c1s.intensity / 0.1)
    # a vendor column can still be read on request
    env = read_excel(p, intensity_col="Envelope")[0]
    assert np.allclose(env.intensity, c1s.intensity / 0.1)
    bg = read_excel(p, intensity_col="C")[0]  # Excel letter
    assert np.allclose(bg.intensity, 100.0)


def test_no_header_decimal_commas_and_kinetic_axis(tmp_path, s2p):
    rows = [
        [f"{e:.2f}".replace(".", ","), f"{i + 0.5:.1f}".replace(".", ",")]
        for e, i in zip(s2p.energy, s2p.intensity)
    ]
    p = _book(tmp_path / "plain.xlsx", rows)
    s = read_spectra(p)[0]
    assert s.n == s2p.n and s.intensity_unit == "arbitrary"
    assert s.energy[0] == pytest.approx(s2p.energy[0], abs=0.01)
    assert s.metadata["header"] is None and s.metadata["energy_column"] == "column A"
    # kinetic energy with the photon energy stated in the sheet
    ke = 1253.6 - s2p.energy
    rows = [["Excitation energy", 1253.6], [], ["Kinetic Energy (eV)", "Intensity"]]
    rows += [[e, i] for e, i in zip(ke, s2p.intensity)]
    s = read_spectra(_book(tmp_path / "ke.xlsx", rows))[0]
    assert s.axis == "binding" and np.allclose(s.energy, s2p.energy, atol=1e-6)
    assert s.photon_energy == pytest.approx(1253.6)
    assert not any(h["step"] == "assumed_photon_energy" for h in s.history)
    # without it Al K-alpha is assumed, and --photon-energy wins over both
    rows = [["KE", "Counts"]] + [[e, i] for e, i in zip(ke, s2p.intensity)]
    q = _book(tmp_path / "ke2.xlsx", rows)
    s = read_spectra(q)[0]
    assert any(h["step"] == "assumed_photon_energy" for h in s.history)
    s = read_spectra(q, photon_energy=1253.6)[0]
    assert np.allclose(s.energy, s2p.energy, atol=1e-6)


def test_two_tables_in_one_sheet_named_by_their_titles(tmp_path, s2p, c1s):
    rows = [["Region S 2p"], ["BE", "Counts"]]
    rows += [[e, i] for e, i in zip(s2p.energy, s2p.intensity)]
    rows += [[], ["Region C 1s"], ["BE", "Counts"]]
    rows += [[e, i] for e, i in zip(c1s.energy, c1s.intensity)]
    rows += [[], ["Range", 160, 172]]  # a short numeric row is not a table
    spectra = read_spectra(_book(tmp_path / "two.xlsx", rows))
    assert [s.name for s in spectra] == ["Region S 2p", "Region C 1s"]
    assert spectra[0].metadata["block_index"] == 0 and spectra[1].metadata["block_index"] == 1
    assert spectra[1].metadata["species"] == "C"
    assert np.allclose(spectra[1].energy, c1s.energy)


def test_sheet_and_column_overrides_and_errors(tmp_path, s2p, c1s):
    a, b = s2p.copy(), c1s.copy()
    a.name, b.name = "S 2p", "C 1s"
    p = write_excel(tmp_path / "two_sheets.xlsx", [a, b], layout="sheets")
    assert read_excel(p, sheet="c 1s")[0].name == "two_sheets"
    assert read_excel(p, sheet=1)[0].metadata["sheet"] == "C 1s"
    with pytest.raises(ExcelReadError):
        read_excel(p, sheet=5)
    with pytest.raises(ExcelReadError):
        read_excel(p, sheet="O 1s")
    with pytest.raises(ExcelReadError):
        read_excel(p, intensity_col="nope")
    with pytest.raises(ExcelReadError):
        read_excel(p, energy_col=0, intensity_col=0)
    # explicit columns by index, letter and header
    rows = [["x", "y", "z"]] + [[e, i, i // 2] for e, i in zip(s2p.energy, s2p.intensity)]
    q = _book(tmp_path / "xyz.xlsx", rows)
    assert read_excel(q, intensity_col="z")[0].intensity[0] == s2p.intensity[0] // 2
    assert read_excel(q, intensity_col=2)[0].intensity[0] == s2p.intensity[0] // 2
    assert read_excel(q, energy_col="A", intensity_col="C")[0].intensity[0] == s2p.intensity[0] // 2
    # like the text reader, a plain x/y/z table yields y; a sheet of named samples
    # yields every column
    assert [s.metadata["intensity_column"] for s in read_excel(q)] == ["y"]
    rows = [["BE", "sample A", "sample B", "sample C"]]
    rows += [[e, i, i + 1, i + 2] for e, i in zip(s2p.energy, s2p.intensity)]
    names = [s.name for s in read_excel(_book(tmp_path / "samples.xlsx", rows))]
    assert names == ["sample A", "sample B", "sample C"]
    with pytest.raises(ExcelReadError):
        read_spectra(_book(tmp_path / "empty.xlsx", [["only", "text"], ["a", "b"]]))
    with pytest.raises(ExcelReadError):
        read_spectra(_book(tmp_path / "short.xlsx", [["BE", "I"], [1, 2], [2, 3], [3, 4]]))
    # content sniffing: a workbook without its extension
    noext = tmp_path / "workbook_without_extension"
    shutil.copy(p, noext)
    assert len(read_spectra(noext)) == 2
    bad = tmp_path / "not_a_book.xlsx"
    bad.write_text("Binding Energy,Counts\n1,2\n")
    with pytest.raises(ExcelReadError):
        read_spectra(bad)


def test_example_workbook_matches_recipe_regions_and_cli_info(tmp_path, capsys):
    paths = example_dataset(tmp_path / "data", seed=4)
    xlsx = [p for p in paths if p.suffix == ".xlsx"]
    assert len(xlsx) == 1 and xlsx[0].name == "p3ht_aged_multi.xlsx"
    spectra = read_spectra(xlsx[0])
    assert [s.name for s in spectra] == ["S 2p", "C 1s"]
    assert all(s.photon_energy == pytest.approx(1486.6) for s in spectra)
    pairs = match_regions(spectra, load_recipe("p3ht"))
    assert sorted((s.name, r.name) for s, r in pairs) == [("C 1s", "C 1s"), ("S 2p", "S 2p")]
    vms = read_spectra(tmp_path / "data" / "p3ht_aged_multi.vms")
    for a, b in zip(spectra, vms):
        assert np.allclose(a.energy, b.energy, atol=1e-5) and np.allclose(a.intensity, b.intensity)
    assert main(["info", str(xlsx[0]), "--sheet", "C 1s"]) == 0
    out = capsys.readouterr().out
    assert "1 spectrum/spectra" in out and "'p3ht_aged_multi'" in out
    assert main(["info", str(xlsx[0])]) == 0
    assert "2 spectrum/spectra" in capsys.readouterr().out
