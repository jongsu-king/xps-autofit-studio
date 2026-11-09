"""Desktop features added in 0.4: element identification, update notice, quality grade
column and readout, robustness settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.qt_helpers import dispose_window  # noqa: E402
from xps_autofit.core.region import RegionSpec  # noqa: E402
from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402

NEWER = {
    "tag_name": "v9.9.9",
    "html_url": "https://example.invalid/releases/v9.9.9",
    "assets": [
        {"name": "XPS-AutoFit-Studio-9.9.9-macOS-arm64.dmg", "browser_download_url": "m"},
        {"name": "XPS-AutoFit-Studio-9.9.9-Windows-x64-Setup.exe", "browser_download_url": "w"},
        {"name": "xps-autofit-studio_9.9.9_amd64.deb", "browser_download_url": "d"},
    ],
}


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_data4")
    example_dataset(d, seed=9)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    win.settings_store.remove("update_check")
    win.show()
    app.processEvents()
    yield win
    win.settings_store.remove("update_check")
    dispose_window(win)
    app.processEvents()


def test_identify_action_marks_lines(window, app, data_dir):
    keys = window.load_files([str(data_dir / "cu2o_survey.csv")])
    window.select_key(keys[0])
    assert window.identify_current()
    app.processEvents()
    ident = window.last_identification
    assert ident is not None
    assert {"Cu", "O", "C"} <= set(ident.elements())
    assert window.plot._marks, "identified lines are marked on the plot"
    assert window.lamp.label.text() == "IDENTIFIED"
    assert "elements:" in window.log_panel.toPlainText()


def test_identify_needs_a_spectrum(window):
    assert not window.identify_current()


def test_update_notice_skip_and_older(window, app):
    assert window.update_check_due()
    window.check_for_updates(manual=False, fetch=lambda u, t: NEWER)
    app.processEvents()
    assert window.update_label.isVisible()
    assert "9.9.9" in window.update_label.text()
    assert window.last_update_info is not None and window.last_update_info.is_newer
    assert not window.update_check_due(), "checked a moment ago"

    window.settings_store.setValue("update_check/skip_version", "9.9.9")
    window.update_label.setVisible(False)
    window.check_for_updates(manual=False, fetch=lambda u, t: NEWER)
    assert not window.update_label.isVisible()

    window.check_for_updates(manual=False, fetch=lambda u, t: {"tag_name": "v0.0.1"})
    assert not window.update_label.isVisible()
    assert window.last_update_info is not None and not window.last_update_info.is_newer

    def broken(url: str, timeout: float) -> dict:
        raise OSError("offline")

    window.check_for_updates(manual=False, fetch=broken)
    assert window.last_update_info is None
    assert "not reachable" in window.log_panel.toPlainText()


def test_update_check_switches(window, monkeypatch):
    window.act_auto_updates.setChecked(False)
    assert not window.update_check_enabled()
    assert not window.update_check_due()
    window.act_auto_updates.setChecked(True)
    assert window.update_check_due()
    monkeypatch.setenv("XPS_AUTOFIT_NO_UPDATE_CHECK", "1")
    assert not window.update_check_due()


def test_grade_column_and_readout(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    assert window.auto_fit()
    app.processEvents()
    headers = [
        window.models.horizontalHeaderItem(i).text() for i in range(window.models.columnCount())
    ]
    assert "Grade" in headers
    col = headers.index("Grade")
    grades = {window.models.item(r, col).text() for r in range(window.models.rowCount())}
    assert grades <= {"A", "B", "C", "D", "E"}
    state = window.session.results[keys[0]]
    assert state.selection is not None and state.selection.best is not None
    best = state.selection.best
    assert best.grade is not None and best.grade.letter == "A"
    text = window.diagnostics.toPlainText()
    assert "QUALITY     grade A" in text
    assert "PARAMETERS  max cross-component |r|" in text


def test_robustness_settings_round_trip(window):
    panel = window.settings
    panel.loss.setCurrentText("soft_l1")
    assert panel.loss_scale.isEnabled()
    panel.loss_scale.setValue(2.5)
    panel.mask_spikes.setChecked(True)
    panel.spike_sigma.setValue(7.0)
    from xps_autofit.synthetic import p3ht_s2p, synthesize

    spec, _ = synthesize(p3ht_s2p(False), seed=1)
    region = panel.region_spec(spec)
    assert (region.loss, region.loss_scale, region.spike_sigma) == ("soft_l1", 2.5, 7.0)
    panel.load_region(RegionSpec(name="r", range=(1.0, 2.0)))
    assert panel.loss.currentText() == "linear"
    assert not panel.mask_spikes.isChecked()
    assert not panel.loss_scale.isEnabled()
    panel.load_region(RegionSpec(name="r", range=(1.0, 2.0), loss="cauchy", spike_sigma=5.0))
    assert panel.loss.currentText() == "cauchy" and panel.spike_sigma.value() == 5.0
