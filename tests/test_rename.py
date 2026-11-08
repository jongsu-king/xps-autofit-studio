"""Renaming spectra and components (0.4.1): engine, session and desktop application."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np
import pytest

from xps_autofit.core.fitting import (
    ComponentSpec,
    FitSettings,
    fit_peaks,
    minor_label,
    rename_component,
    specs_from_result,
)
from xps_autofit.core.uncertainty import bootstrap
from xps_autofit.synthetic import p3ht_s2p, synthesize


def _doublet_fit():
    spec, truth = synthesize(p3ht_s2p(True), seed=3)
    comps = p3ht_s2p(True).components
    specs = [
        ComponentSpec("a", 164.0, 20000.0, 0.85, 0.15, doublet=comps[0].doublet),
        ComponentSpec("b", 168.4, 3000.0, 1.4, 0.15, doublet=comps[1].doublet),
    ]
    return spec, fit_peaks(spec, specs, FitSettings())


# ------------------------------------------------------------------------- engine
def test_rename_component_renames_major_minor_and_spec():
    spec, result = _doublet_fit()
    renamed = rename_component(result, "a", " thiophene ")
    assert renamed is not result
    assert [c.label for c in renamed.components] == [
        "thiophene",
        minor_label("thiophene"),
        "b",
        minor_label("b"),
    ]
    assert {c.parent for c in renamed.components} == {"thiophene", "b"}
    assert [s.label for s in renamed.specs] == ["thiophene", "b"]
    # Nothing numerical moved and the original is untouched.
    for old, new in zip(result.components, renamed.components):
        assert (old.area, old.center, old.fwhm) == (new.area, new.center, new.fwhm)
    assert renamed.params == result.params and renamed.stats is result.stats
    assert [c.label for c in result.components][0] == "a"
    assert renamed.area_of("thiophene") == pytest.approx(result.area_of("a"))
    # A refit from the renamed result keeps the new names.
    again = fit_peaks(spec, specs_from_result(renamed), renamed.settings)
    assert [c.label for c in again.majors()] == ["thiophene", "b"]
    assert again.stats.redchi == pytest.approx(result.stats.redchi, rel=1e-6)


def test_rename_component_rejects_bad_names():
    _spec, result = _doublet_fit()
    with pytest.raises(ValueError, match="no component"):
        rename_component(result, "zzz", "x")
    with pytest.raises(ValueError, match="empty"):
        rename_component(result, "a", "   ")
    with pytest.raises(ValueError, match="already exists"):
        rename_component(result, "a", "b")
    assert rename_component(result, "a", "a") is result


def test_bootstrap_renamed_follows_the_component():
    spec, result = _doublet_fit()
    boot = bootstrap(spec, result, n=8, seed=1)
    moved = boot.renamed("a", "thiophene")
    assert set(moved.summary) == {"thiophene", minor_label("thiophene"), "b", minor_label("b")}
    assert moved.summary["thiophene"] is boot.summary["a"]
    assert set(moved.area_samples) == set(moved.summary)
    assert moved.n_succeeded == boot.n_succeeded
    assert np.array_equal(moved.total_area_samples, boot.total_area_samples)


# ------------------------------------------------------------------------ session
def test_session_rename_spectrum_and_manual_component():
    pytest.importorskip("PySide6")
    from xps_autofit.gui.session import LoadedSpectrum, Session

    spec, result = _doublet_fit()
    session = Session()
    item = LoadedSpectrum(Path("/data/sample.csv"), 0, spec)
    session.items[item.key] = item
    session.order.append(item.key)
    old = item.display_name
    assert old == spec.name and old
    changed: list[str] = []
    session.spectraChanged.connect(lambda: changed.append("tree"))
    assert session.rename_spectrum(item.key, "  Aged film, S 2p ")
    assert item.display_name == "Aged film, S 2p" and spec.name == "Aged film, S 2p"
    assert spec.history[-1] == {"step": "rename", "from": old, "to": "Aged film, S 2p"}
    assert not session.rename_spectrum(item.key, "")  # empty: nothing happens
    assert not session.rename_spectrum(item.key, "Aged film, S 2p")  # unchanged
    assert not session.rename_spectrum("nope", "x")
    assert changed == ["tree"]

    with pytest.raises(ValueError, match="AUTO FIT"):
        session.rename_component(item.key, "a", "x")
    session.set_manual(item.key, result, [])
    emitted: list[str] = []
    session.resultChanged.connect(emitted.append)
    session.rename_component(item.key, "a", "thiophene")
    st = session.state(item.key)
    assert st.status == "manual" and st.result is not None
    assert [c.label for c in st.result.majors()] == ["thiophene", "b"]
    assert emitted == [item.key]
    session.rename_component(item.key, "thiophene", "thiophene")  # no-op, no signal
    assert emitted == [item.key]


# -------------------------------------------------------------------- application
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit  # noqa: E402

from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_rename")
    example_dataset(d, seed=7)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    win.show()
    app.processEvents()
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()
    del win
    gc.collect()
    app.processEvents()


def _fitted(window, app, data_dir) -> str:
    keys = window.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    assert window.auto_fit()
    app.processEvents()
    return keys[0]


def _row_of(table, label: str) -> int:
    for r in range(table.rowCount()):
        if table.item(r, 0).text() == label:
            return r
    raise AssertionError(f"{label!r} not in the table")


def test_rename_spectrum_from_tree_and_export(window, app, data_dir, tmp_path):
    key = _fitted(window, app, data_dir)
    item = window.session.items[key]
    old = item.display_name
    # Inline editing in the tree: open the editor, type, Return.
    assert window.tree.edit_current_title()
    assert window.tree.state() == QAbstractItemView.State.EditingState
    editor = window.tree.findChild(QLineEdit)
    assert editor is not None and editor.text() == old
    editor.selectAll()
    QTest.keyClicks(editor, "Aged P3HT film")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()
    assert item.display_name == "Aged P3HT film"
    assert window.tree._items[key].text(0) == "Aged P3HT film"
    assert window.plot.main.titleLabel.text.startswith("Aged P3HT film - S 2p (n=2, ok)")
    assert f"renamed spectrum {old!r}" in window.log_panel.toPlainText()
    # The fit itself is untouched.
    assert window.session.results[key].status == "ok"
    # An empty title is refused and the tree shows the current one again.
    assert not window.rename_spectrum(key, "   ")
    assert window.tree._items[key].text(0) == "Aged P3HT film"
    # Exports carry the title; the file names keep the source stem.
    assert window.export_current(tmp_path, ("json", "png"))
    app.processEvents()
    project = json.loads((tmp_path / "p3ht_aged_S2p__S_2p.json").read_text())
    assert project["source"]["spectrum_name"] == "Aged P3HT film"
    assert project["original_spectrum"]["name"] == "Aged P3HT film"
    assert (tmp_path / "p3ht_aged_S2p__S_2p.png").exists()


def test_rename_component_from_table_keeps_the_fit(window, app, data_dir, tmp_path):
    key = _fitted(window, app, data_dir)
    state = window.session.results[key]
    before = state.result
    assert before is not None and state.status == "ok"
    row = _row_of(window.components, "sulfonate/sulfate")
    window.components.item(row, 0).setText("sulfate")  # what the inline editor commits
    app.processEvents()
    after = window.session.results[key].result
    assert after is not None and after is not before
    assert [c.label for c in after.components] == [
        "thiophene C-S-C",
        minor_label("thiophene C-S-C"),
        "sulfate",
        minor_label("sulfate"),
    ]
    assert after.majors()[1].area == before.majors()[1].area
    assert window.session.results[key].status == "ok", "a rename is not a manual refit"
    assert state.selection is not None and state.selection.best is not None
    assert state.selection.best.result is after
    assert set(window.plot.line_positions()) == {"thiophene C-S-C", "sulfate"}
    assert window.components.item(_row_of(window.components, "sulfate"), 0).text() == "sulfate"
    assert "sulfate" in window.diagnostics.toPlainText()

    # Rejected names: duplicate and empty; the table shows the current name again.
    window.components.item(_row_of(window.components, "sulfate"), 0).setText("thiophene C-S-C")
    app.processEvents()
    assert "already exists" in window.log_panel.toPlainText()
    assert [c.label for c in window.session.results[key].result.majors()] == [
        "thiophene C-S-C",
        "sulfate",
    ]
    assert not window.rename_component("sulfate", "")
    assert "cannot be empty" in window.log_panel.toPlainText()

    # A refit after dragging keeps the new name.
    line = window.plot._lines["sulfate"]
    window._on_center_dragged("sulfate", float(line.value()) + 0.2)
    app.processEvents()
    manual = window.session.results[key]
    assert manual.status == "manual"
    assert [c.label for c in manual.result.majors()] == ["thiophene C-S-C", "sulfate"]

    # A bootstrap follows a later rename, and the export uses the names.
    assert window.run_uncertainty(8)
    app.processEvents()
    assert "sulfate" in manual.bootstrap.summary
    assert window.rename_component("sulfate", "S(VI)")
    app.processEvents()
    assert "S(VI)" in manual.bootstrap.summary and "sulfate" not in manual.bootstrap.summary
    assert minor_label("S(VI)") in manual.bootstrap.summary
    assert "S(VI)" in window.diagnostics.toPlainText()
    assert window.export_current(tmp_path, ("json", "csv"))
    app.processEvents()
    project = json.loads((tmp_path / "p3ht_aged_S2p__S_2p.json").read_text())
    labels = [c["label"] for c in project["selection"]["best"]["fit"]["components"]]
    assert labels == [
        "thiophene C-S-C",
        minor_label("thiophene C-S-C"),
        "S(VI)",
        minor_label("S(VI)"),
    ]
    csv = (tmp_path / "p3ht_aged_S2p__S_2p_components.csv").read_text()
    assert "S(VI)" in csv


def test_rename_actions_without_selection_only_log(window):
    window.rename_current_spectrum_dialog()
    window.rename_component_dialog()
    text = window.log_panel.toPlainText()
    assert "select a spectrum to rename" in text
    assert "select a component row to rename" in text
    assert window.act_rename_spectrum.shortcut().toString() == "F2"
    assert window.act_rename_component in window._job_actions()
