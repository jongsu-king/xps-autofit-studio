"""Session files: save what is open and fitted, restore it in a fresh window."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.qt_helpers import dispose_window  # noqa: E402
from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.session_file import SESSION_FORMAT, restore_session, save_session  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_session")
    example_dataset(d, seed=17)
    return d


def _window(app):
    win = MainWindow(synchronous_jobs=True)
    win.show()
    app.processEvents()
    return win


def test_session_round_trip(app, data_dir, tmp_path):
    win = _window(app)
    try:
        keys = win.load_files(
            [str(data_dir / "p3ht_aged_multi.vms"), str(data_dir / "p3ht_fresh_S2p.csv")]
        )
        assert len(keys) == 3
        win.use_recipe("p3ht")
        win.select_key(keys[0])
        win.fit_all(keys[:2])  # both regions of the VAMAS file; the CSV stays unfitted
        app.processEvents()
        assert all(win.session.state(k).result is not None for k in keys[:2])
        # user edits that must survive: a title, a component name, a charge shift
        assert win.rename_spectrum(keys[0], "P3HT aged, sulfur")
        old_label = win.session.state(keys[0]).result.majors()[0].label
        assert win.rename_component(old_label, "thiophene (renamed)")
        win.session.shift_file(keys[2], 0.4, "simulated charge correction")
        before = {k: win.session.state(k).result.params for k in keys[:2]}
        status_before = {k: win.session.state(k).status for k in keys[:2]}
        energy_before = win.session.items[keys[2]].spectrum.energy.copy()
        path = win.save_session(tmp_path / "work")
        assert path.suffix == ".xpsession" and path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["format"] == SESSION_FORMAT and data["recipe"]["name"] == "p3ht"
        assert [e["name"] for e in data["spectra"]][0] == "P3HT aged, sulfur"
        assert data["spectra"][2]["shift_eV"] == pytest.approx(0.4)
        assert "result" in data["spectra"][0] and "result" not in data["spectra"][2]
    finally:
        dispose_window(win)

    fresh = _window(app)
    try:
        restored = fresh.open_session(path)
        assert restored == keys
        assert fresh.session.recipe is not None and fresh.session.recipe.name == "p3ht"
        assert fresh.session.items[keys[0]].display_name == "P3HT aged, sulfur"
        assert np.allclose(fresh.session.items[keys[2]].spectrum.energy, energy_before)
        for k in keys[:2]:
            st = fresh.session.state(k)
            assert st.result is not None and st.status == status_before[k]
            for name, p in before[k].items():
                assert st.result.params[name]["value"] == pytest.approx(p["value"], rel=1e-9)
            assert st.selection is not None and len(st.selection.candidates) == 1
            assert "restored from a session file" in st.notes[-1]
        labels = [c.label for c in fresh.session.state(keys[0]).result.majors()]
        assert "thiophene (renamed)" in labels
        assert fresh.session.state(keys[2]).result is None
        assert fresh._current_key == keys[0]
        assert fresh.tree.topLevelItemCount() == 2
        # the composition of the file is available again (both regions fitted)
        assert fresh.session.composition(keys[0]) is not None
        text = fresh.log_panel.toPlainText()
        assert "3 spectra, 2 fits restored" in text
    finally:
        dispose_window(fresh)


def test_session_restore_tolerates_missing_files_and_bad_input(app, data_dir, tmp_path):
    win = _window(app)
    try:
        keys = win.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
        win.use_recipe("p3ht")
        win.select_key(keys[0])
        assert win.auto_fit()
        app.processEvents()
        path = save_session(tmp_path / "one.xpsession", win.session)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["spectra"].append({"path": str(tmp_path / "gone.csv"), "index": 0, "name": "x"})
        data["spectra"].append(dict(data["spectra"][0], index=7))  # no such spectrum in the file
        (tmp_path / "edited.xpsession").write_text(json.dumps(data), encoding="utf-8")
    finally:
        dispose_window(win)

    fresh = _window(app)
    try:
        restored = fresh.open_session(tmp_path / "edited.xpsession")
        assert restored == keys
        text = fresh.log_panel.toPlainText()
        assert "missing file" in text and "spectrum 8 not found" in text
        assert fresh.session.state(keys[0]).result is not None
        # opening the same session again does not duplicate anything
        assert fresh.open_session(tmp_path / "edited.xpsession") == keys
        assert len(fresh.session.order) == 1
        # not a session file
        (tmp_path / "bad.xpsession").write_text(json.dumps({"format": 99}), encoding="utf-8")
        assert fresh.open_session(tmp_path / "bad.xpsession") == []
        assert "cannot open session" in fresh.log_panel.toPlainText()
        (tmp_path / "broken.xpsession").write_text("{", encoding="utf-8")
        assert fresh.open_session(tmp_path / "broken.xpsession") == []
        # a spectrum that already has a fit keeps it unless asked otherwise
        report = restore_session(path, fresh.session)
        assert report.keys == keys and report.kept == keys and report.restored == []
        assert any("kept the fit" in m for m in report.messages)
        report = restore_session(path, fresh.session, replace_fits=True)
        assert report.restored == keys and report.kept == []
        # an exported project file is not a session file
        project = fresh.export_current(tmp_path / "exp", ("json",))
        assert project
        project_json = next((tmp_path / "exp").glob("*.json"))
        assert fresh.open_session(project_json) == []
        assert "exported project file" in fresh.log_panel.toPlainText()
        # malformed entries are skipped, not fatal
        data = json.loads(path.read_text(encoding="utf-8"))
        data["spectra"].append({"path": 12, "index": "x"})
        data["spectra"].append("nonsense")
        (tmp_path / "odd.xpsession").write_text(json.dumps(data), encoding="utf-8")
        assert fresh.open_session(tmp_path / "odd.xpsession") == keys
        assert "malformed spectrum entry" in fresh.log_panel.toPlainText()
        data["spectra"] = {}
        (tmp_path / "odd2.xpsession").write_text(json.dumps(data), encoding="utf-8")
        assert fresh.open_session(tmp_path / "odd2.xpsession") == []
        # a recipe file that disappears does not crash the recipe box
        from xps_autofit.recipes import load_recipe, save_recipe

        yaml_path = tmp_path / "temp_recipe.yaml"
        save_recipe(load_recipe("p3ht"), yaml_path)
        fresh.use_recipe_file(yaml_path)
        assert fresh.session.recipe is not None and fresh.session.recipe.source == str(yaml_path)
        yaml_path.unlink()
        fresh.use_recipe("cu2o")
        fresh.use_recipe_file(yaml_path)
        assert fresh.session.recipe is None
        assert "cannot load recipe" in fresh.log_panel.toPlainText()
        assert fresh.settings.recipe_combo.currentIndex() == 0
    finally:
        dispose_window(fresh)
