"""Desktop application tests (offscreen).  Skipped when PySide6 is not installed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.qt_helpers import dispose_window  # noqa: E402
from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.gui.workers import JobRunner  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_data")
    example_dataset(d, seed=5)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    win.show()
    app.processEvents()
    yield win
    # Release the Qt objects while the interpreter is healthy: windows that survive
    # until interpreter exit are freed in an arbitrary order and can abort the process
    # after the tests have passed.
    dispose_window(win)
    app.processEvents()


def test_load_select_and_auto_fit(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    assert len(keys) == 1
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    app.processEvents()
    assert window.settings.region_combo.currentText() == "S 2p"
    assert window.settings.doublet.isChecked()
    assert window.auto_fit()
    app.processEvents()
    state = window.session.results[keys[0]]
    assert state.status == "ok"
    assert len(state.result.majors()) == 2
    assert window.components.rowCount() == 4
    assert window.models.rowCount() == 3
    assert set(window.plot.line_positions()) == {"thiophene C-S-C", "sulfonate/sulfate"}
    assert window.lamp.label.text() == "CONVERGED"


def test_drag_edit_add_remove_and_export(window, app, data_dir, tmp_path):
    keys = window.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    window.auto_fit()
    app.processEvents()
    line = window.plot._lines["sulfonate/sulfate"]
    line.setValue(line.value() + 0.3)
    line.sigPositionChangeFinished.emit(line)
    app.processEvents()
    state = window.session.results[keys[0]]
    assert state.status == "manual"
    ox = next(m for m in state.result.majors() if m.label == "sulfonate/sulfate")
    assert abs(ox.center - 168.4) < 0.1  # the refit pulls it back to the data

    window.add_component()
    app.processEvents()
    assert len(window.session.results[keys[0]].result.majors()) == 3
    window.components.selectRow(window.components.rowCount() - 1)
    window.remove_component()
    app.processEvents()
    assert len(window.session.results[keys[0]].result.majors()) == 2

    assert window.export_current(tmp_path, ("csv", "json"))
    app.processEvents()
    assert (tmp_path / "p3ht_aged_S2p__S_2p.json").exists()
    assert (tmp_path / "p3ht_aged_S2p__S_2p_components.csv").exists()


def test_batch_from_gui(window, app, data_dir, tmp_path):
    assert window.run_batch([str(data_dir)], "p3ht", tmp_path, ("csv",), True, ["S 2p"])
    app.processEvents()
    frame, folder = window._last_batch
    assert folder == tmp_path and len(frame.index) >= 4
    assert (tmp_path / "summary_regions.csv").exists()


def test_adhoc_settings_without_recipe(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_fresh_S2p.csv")])
    window.select_key(keys[0])
    window.settings.element.setCurrentText("S")
    window.settings.line.setCurrentText("2p")
    assert window.settings.doublet.isChecked() and abs(window.settings.split.value() - 1.18) < 1e-9
    window.settings.max_n.setValue(2)
    region = window.settings.region_spec(window.session.items[keys[0]].spectrum)
    assert region.doublet is not None and region.candidates == []
    assert window.auto_fit()
    app.processEvents()
    assert len(window.session.results[keys[0]].result.majors()) == 1


def test_unreadable_file_is_reported_not_fatal(window, app, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("nothing numeric here\n")
    assert window.load_files([str(bad)]) == []
    assert "cannot read" in window.log_panel.toPlainText()


def test_threaded_runner_cleans_up(app):
    runner = JobRunner(synchronous=False)
    results: list[object] = []
    runner.start(lambda: 42, results.append, lambda e: results.append(("error", e)), "x")
    for _ in range(200):
        app.processEvents()
        if results:
            break
        import time

        time.sleep(0.01)
    assert results == [42]
    assert not runner.busy

    errors: list[str] = []

    def boom() -> None:
        raise RuntimeError("boom")

    runner.start(boom, results.append, errors.append, "y")
    for _ in range(200):
        app.processEvents()
        if errors:
            break
        import time

        time.sleep(0.01)
    assert errors and "boom" in errors[0]
    assert not runner.busy


def test_screenshot_can_be_grabbed(window, app, data_dir, tmp_path):
    keys = window.load_files([str(data_dir / "cu2o_Cu2p3.txt")])
    window.use_recipe("cu2o")
    window.select_key(keys[0])
    window.auto_fit()
    app.processEvents()
    img = window.grab()
    assert img.width() > 800 and img.height() > 500
    assert img.save(str(tmp_path / "shot.png"))


def test_run_entry_point_starts_and_quits(app):
    from PySide6.QtCore import QTimer

    from xps_autofit.gui import run

    QTimer.singleShot(200, app.quit)
    assert run([]) == 0
