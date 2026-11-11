"""Survey quantification and the composition series (engine, command line, batch)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xps_autofit.automation.batch_fitting import RunOptions, run_batch
from xps_autofit.automation.identify import identify_elements
from xps_autofit.automation.series import (
    composition_series,
    natural_key,
    series_elements,
    series_origin_columns,
)
from xps_autofit.automation.survey_quant import quantify_survey
from xps_autofit.cli import main
from xps_autofit.core.quantification import QuantCorrection, QuantEntry, QuantResult
from xps_autofit.export.origin import write_origin_csv
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import example_dataset, synthesize_survey

SURVEYS = [
    ({"Cu": 1.0, "O": 1.4, "C": 2.5, "N": 0.15}, 7),
    ({"Au": 1.0, "C": 2.0, "O": 0.8}, 3),
    ({"Si": 1.0, "O": 2.0, "C": 0.6}, 5),
    ({"Ti": 1.0, "O": 2.0, "C": 1.0, "N": 0.3}, 11),
]


@pytest.mark.parametrize(("composition", "seed"), SURVEYS)
def test_survey_composition_recovers_the_synthetic_truth(composition, seed):
    """The synthetic survey places every line with area = amount x relative intensity,
    so the procedure (window, Shirley background, sensitivity) must give the amounts
    back.  This checks the arithmetic, not the accuracy of real sensitivity factors."""
    survey, _ = synthesize_survey(composition, seed=seed)
    quant = quantify_survey(survey, identify_elements(survey))
    assert quant.status == "OK" and not quant.skipped
    total = sum(composition.values())
    got = quant.composition()
    assert set(got) == set(composition)
    assert sum(got.values()) == pytest.approx(100.0)
    for element, amount in composition.items():
        true = 100.0 * amount / total
        assert got[element] == pytest.approx(true, rel=0.08), element
    for q in quant.lines:
        assert q.area_err is not None and q.area_err > 0
        assert q.atomic_percent_err is not None and 0 < q.atomic_percent_err < 1.0
        assert q.window[0] < q.peak_eV < q.window[1]
    result = quant.to_quant_result()
    assert result.status == "OK" and len(result.entries) == len(quant.lines)
    assert all(e.label.endswith("(survey)") for e in result.entries)
    assert "survey estimate" in quant.note


def test_survey_composition_options_and_edge_cases():
    survey, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=7)
    ident = identify_elements(survey)
    plain = quantify_survey(survey, ident).composition()
    # a KE^(-0.5) correction favours lines at high kinetic energy (low binding energy)
    corrected = quantify_survey(
        survey, ident, correction=QuantCorrection(imfp_exponent=-0.5)
    ).composition()
    assert corrected["C"] > plain["C"] and corrected["Cu"] < plain["Cu"]
    # a charged sample: the windows follow the measured peaks
    shifted = survey.shift(3.0, "charging")
    q = quantify_survey(shifted, identify_elements(shifted, charge_shift=3.0))
    assert q.composition()["O"] == pytest.approx(plain["O"], rel=0.05)
    # an intensity scale without counting statistics has no errors
    arbitrary = survey.copy()
    arbitrary.intensity_unit = "arbitrary"
    q = quantify_survey(arbitrary, ident)
    assert all(line.area_err is None and line.atomic_percent_err is None for line in q.lines)
    # nothing confident enough
    q = quantify_survey(survey, ident, min_confidence=1.01)
    assert q.status == "NOT_CALCULABLE" and q.lines == [] and set(q.skipped) == {"Cu", "O", "C"}


def test_identify_quantify_command(tmp_path, capsys):
    survey, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=8)
    path = tmp_path / "survey.csv"
    path.write_text(
        "Binding Energy (eV),Counts\n"
        + "\n".join(f"{e:.2f},{int(i)}" for e, i in zip(survey.energy, survey.intensity)),
        encoding="utf-8",
    )
    assert main(["identify", str(path), "--quantify"]) == 0
    out = capsys.readouterr().out
    assert "survey composition (OK):" in out and "from 2p3/2" in out and "survey estimate" in out
    assert main(["identify", str(path), "--quantify", "--json"]) == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert data["quantification"]["status"] == "OK"
    assert {line["element"] for line in data["quantification"]["lines"]} == {"Cu", "O", "C"}


def _quant(values: dict[str, float], std: float | None = None) -> QuantResult:
    entries = []
    for label, pct in values.items():
        e = QuantEntry(label, label.split()[0], None, 1.0, 1.0)
        e.atomic_percent = pct
        e.atomic_percent_std = std
        entries.append(e)
    return QuantResult("OK", entries, [], "")


def test_composition_series_table():
    assert natural_key("cycle10") > natural_key("cycle2")
    items = [
        ("cycle10", _quant({"C 1s": 20.0, "Cu 2p": 50.0, "O 1s": 30.0}, std=0.5)),
        ("cycle2", _quant({"C 1s": 60.0, "Cu 2p": 15.0, "O 1s": 25.0}, std=0.5)),
        ("cycle1", _quant({"C 1s": 70.0, "Cu 2p3/2": 6.0, "Cu 2p1/2": 4.0, "O 1s": 20.0})),
        ("cycle3", None),
    ]
    frame = composition_series(items)
    assert list(frame["sample"]) == ["cycle1", "cycle2", "cycle3", "cycle10"]
    assert list(frame["index"]) == [1, 2, 3, 4]
    assert list(frame["status"]) == ["OK", "OK", "no fit", "OK"]
    assert series_elements(frame) == ["C", "Cu", "O"]  # by mean share
    assert frame.loc[0, "Cu at%"] == pytest.approx(10.0), "regions of one element are summed"
    assert math.isnan(frame.loc[2, "C at%"])
    assert math.isnan(frame.loc[0, "C err"]) and frame.loc[1, "C err"] == pytest.approx(0.5)
    given = composition_series(items, order="given")
    assert list(given["sample"]) == ["cycle10", "cycle2", "cycle1", "cycle3"]
    with pytest.raises(ValueError):
        composition_series(items, order="random")


def test_series_for_origin(tmp_path):
    frame = composition_series(
        [
            ("a", _quant({"C 1s": 60.0, "O 1s": 40.0}, 1.0)),
            ("b", _quant({"C 1s": 55.0, "O 1s": 45.0}, 1.0)),
        ]
    )
    path = write_origin_csv(tmp_path / "series.csv", series_origin_columns(frame))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Sample index,C,C error,O,O error,Sample"
    assert lines[1] == ",at.%,at.%,at.%,at.%,"
    assert lines[3].startswith("1,60,1,40,1,a")


def test_batch_writes_the_composition_series(tmp_path):
    data = tmp_path / "data"
    example_dataset(data, seed=4)
    files = [data / "p3ht_aged_multi.vms", data / "p3ht_aged_multi.xlsx"]
    out = tmp_path / "out"
    batch = run_batch(files, load_recipe("p3ht"), RunOptions(out, formats=("csv", "png", "origin")))
    assert all(
        f.quantification is not None and f.quantification.status == "OK" for f in batch.files
    )
    series = pd.read_csv(out / "summary_series.csv")
    assert list(series["sample"]) == ["p3ht_aged_multi", "p3ht_aged_multi"]
    assert {"C at%", "S at%"} <= set(series.columns)
    assert np.allclose(series["C at%"] + series["S at%"], 100.0)
    # the same two regions in two formats give the same composition
    assert series.loc[0, "S at%"] == pytest.approx(series.loc[1, "S at%"], abs=0.5)
    assert (out / "composition_series.png").stat().st_size > 5000
    assert (
        (out / "summary_series_origin.csv").read_text(encoding="utf-8").startswith("Sample index,")
    )
    assert Path(batch.summary_paths["summary_series"]).exists()
