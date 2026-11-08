"""Element identification in survey spectra."""

from __future__ import annotations

import json

import numpy as np
import pytest

from xps_autofit.automation.identify import (
    find_survey_peaks,
    identify_elements,
    nearest_lines,
)
from xps_autofit.cli import main
from xps_autofit.database.survey_lines import ELEMENTS_COVERED, SURVEY_LINES, lines_of
from xps_autofit.synthetic import example_dataset, synthesize_survey


def _found(ident) -> dict[str, float]:
    return {c.element: c.confidence for c in ident.candidates}


def test_survey_table_is_consistent():
    keys = [(ln.element, ln.line) for ln in SURVEY_LINES]
    assert len(keys) == len(set(keys)), "duplicate (element, line) entries"
    for ln in SURVEY_LINES:
        assert 0 < ln.energy < 1400
        assert ln.intensity > 0
        assert ln.kind in ("photoelectron", "auger")
    for el in ELEMENTS_COVERED:
        assert any(ln.kind == "photoelectron" for ln in lines_of(el))
    assert {"C", "N", "O", "Si", "Cu", "Fe", "Au", "Pb"} <= set(ELEMENTS_COVERED)
    assert len(ELEMENTS_COVERED) >= 60


def test_survey_peaks_found_above_noise():
    spec, truth = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=5)
    peaks, sigma = find_survey_peaks(spec)
    assert sigma > 0
    energies = np.array([p.energy for p in peaks])
    for line in truth["lines"]:
        if line["area"] > 5000:
            assert np.min(np.abs(energies - line["energy"])) < 0.6, line
    assert all(p.snr >= 5 for p in peaks)


def test_identify_cu_o_c_n_survey():
    spec, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5, "N": 0.15}, seed=5)
    ident = identify_elements(spec)
    found = _found(ident)
    assert set(found) == {"Cu", "O", "C", "N"}
    assert min(found["Cu"], found["O"], found["C"]) >= 0.9
    assert found["N"] >= 0.5
    cu = next(c for c in ident.candidates if c.element == "Cu")
    labels = {m.label for m in cu.matched}
    assert {"Cu 2p3/2", "Cu 2p1/2", "Cu LMM"} <= labels
    assert cu.main_line is not None and cu.main_line.label == "Cu 2p3/2"
    offset = cu.main_line.offset_eV
    assert offset is not None and abs(offset) < 0.6
    assert not ident.unassigned


@pytest.mark.parametrize(
    "composition",
    [
        {"Si": 1.0, "O": 2.0, "C": 0.8, "F": 0.3, "Na": 0.1},
        {"Ti": 1.0, "O": 2.2, "C": 1.0, "Au": 0.3},
        {"Pb": 1.0, "I": 3.0, "C": 2.0, "N": 0.8, "O": 0.4},
        {"Fe": 1.0, "Ni": 0.5, "Cr": 0.3, "O": 2.0, "C": 1.0},
        {"Mg": 1.0, "O": 1.0, "C": 0.5},
    ],
)
def test_identify_has_no_false_elements(composition):
    spec, _ = synthesize_survey(composition, seed=11)
    ident = identify_elements(spec)
    found = _found(ident)
    assert set(found) == set(composition), found
    assert all(v >= 0.3 for v in found.values())


def test_identify_marks_genuine_overlap_as_ambiguous():
    spec, _ = synthesize_survey({"Bi": 1.0, "S": 1.0, "C": 1.0, "O": 1.0}, seed=9)
    ident = identify_elements(spec)
    found = _found(ident)
    assert {"Bi", "S", "C", "O"} == set(found)
    s = next(c for c in ident.candidates if c.element == "S")
    assert s.ambiguous_with == ["Bi"]
    assert found["Bi"] > found["S"]


def test_identify_with_charge_shift():
    spec, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=5)
    shifted = spec.shift(2.6, "charging")
    plain = _found(identify_elements(shifted))
    assert not {"Cu", "O", "C"} <= set(plain)
    corrected = _found(identify_elements(shifted, charge_shift=2.6))
    assert {"Cu", "O", "C"} <= set(corrected)
    wide = _found(identify_elements(shifted, tolerance=3.0))
    assert {"Cu", "O", "C"} <= set(wide)


def test_identify_restricts_to_requested_elements_and_serialises():
    spec, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=5)
    ident = identify_elements(spec, elements=["Cu", "Fe"])
    assert ident.elements() == ["Cu"]
    assert ident.unassigned, "the O and C peaks are now unexplained"
    rows = ident.rows()
    assert rows[0]["element"] == "Cu" and rows[0]["main_line"] == "Cu 2p3/2"
    d = json.loads(json.dumps(ident.to_dict()))
    assert d["candidates"][0]["element"] == "Cu"
    assert d["unassigned"]
    hints = nearest_lines(531.5)
    assert hints[0].startswith("O 1s")


def test_identify_on_kinetic_axis_and_narrow_range():
    spec, _ = synthesize_survey({"Cu": 1.0, "O": 1.4, "C": 2.5}, seed=5)
    kinetic = spec.copy()
    kinetic.energy = 1486.6 - spec.energy
    kinetic.axis = "kinetic"
    from xps_autofit.core.spectrum import Spectrum

    kin = Spectrum(**{k: v for k, v in kinetic.__dict__.items()})
    ident = identify_elements(kin)
    assert {"Cu", "O", "C"} <= set(_found(ident))
    narrow = identify_elements(spec.crop(520, 560))
    assert any("narrow" in n for n in narrow.notes)
    assert _found(narrow).get("O", 0) > 0


def test_cli_identify(tmp_path, capsys):
    example_dataset(tmp_path, seed=3)
    rc = main(["identify", str(tmp_path / "cu2o_survey.csv")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cu  confidence" in out and "Cu 2p3/2" in out and "O 1s" in out
    rc = main(["identify", str(tmp_path / "cu2o_survey.csv"), "--json", "--elements", "Cu,O"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and [c["element"] for c in data["candidates"]] == ["Cu", "O"]
