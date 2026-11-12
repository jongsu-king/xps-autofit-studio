"""Desktop features added in 0.3: diagnostics readout, bootstrap action, drag-and-drop,
recent files, copyable tables, model picking by row, background mode in the panel."""

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
from xps_autofit.gui.panels import diagnostics_text  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_data2")
    example_dataset(d, seed=9)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    win.settings_store.setValue("recent_files", [])
    win.show()
    app.processEvents()
    yield win
    dispose_window(win)
    app.processEvents()


def _fitted(window, app, data_dir, name="p3ht_aged_S2p.csv", recipe="p3ht"):
    keys = window.load_files([str(data_dir / name)])
    window.use_recipe(recipe)
    window.select_key(keys[0])
    assert window.auto_fit()
    app.processEvents()
    return keys[0]


def test_diagnostics_readout_and_model_rows(window, app, data_dir):
    key = _fitted(window, app, data_dir)
    text = window.diagnostics.toPlainText()
    assert "Durbin-Watson" in text and "MODEL" in text and "shirley/voigt" in text
    assert "CONVERGED" in text
    # the Models tab lists the variant and the Durbin-Watson value per candidate
    headers = [window.models.horizontalHeaderItem(c).text() for c in range(7)]
    assert headers[1] == "Model" and headers[4] == "DW"
    assert window.models.item(0, 1).text() == "shirley/voigt"
    # clicking a non-selected candidate shows it without changing the stored result
    state = window.session.results[key]
    best_n = state.result.majors()
    other = next(
        i for i, c in enumerate(state.selection.candidates) if c.result is not state.result
    )
    window.models.cellClicked.emit(other, 0)
    app.processEvents()
    assert "candidate" in window.diagnostics.toPlainText() or window.components.rowCount() > 0
    assert state.result.majors() == best_n


def test_bootstrap_action_fills_the_readout(window, app, data_dir):
    key = _fitted(window, app, data_dir)
    assert window.run_uncertainty(8)
    app.processEvents()
    boot = window.session.results[key].bootstrap
    assert boot is not None and boot.n_succeeded == 8
    text = window.diagnostics.toPlainText()
    assert "BOOTSTRAP" in text and "8/8 replicates" in text
    assert window.tabs.currentWidget() is window.diagnostics
    # a manual refit clears the bootstrap, since it belongs to the previous model
    window.add_component()
    app.processEvents()
    assert window.session.results[key].bootstrap is None


def test_drop_folder_and_recent_files(window, app, data_dir):
    keys = window.load_dropped([str(data_dir)])
    assert len(keys) >= 5
    recent = window.recent_files()
    assert recent and all(Path(p).exists() for p in recent)
    assert window.menu_recent.isEnabled()
    assert window.load_dropped([str(data_dir / "truth.json")]) == []
    assert "no supported" in window.log_panel.toPlainText()


def test_copy_table_to_clipboard(window, app, data_dir):
    _fitted(window, app, data_dir)
    text = window.components.copy_to_clipboard(selected_only=False)
    lines = text.splitlines()
    assert lines[0].startswith("Component\tCentre (eV)")
    assert len(lines) == window.components.rowCount() + 1
    assert "thiophene C-S-C" in text
    assert QApplication.clipboard().text() == text


def test_cursor_readout_and_reset_view(window, app, data_dir):
    _fitted(window, app, data_dir)
    window.plot.cursorMoved.emit(164.25, 12345.0)
    app.processEvents()
    assert "164.250" in window.cursor_label.text()
    window.plot.reset_view()  # must not raise with a result displayed


def test_background_mode_and_shape_round_trip_in_panel(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_fresh_S2p.csv")])
    window.select_key(keys[0])
    window.settings.element.setCurrentText("S")
    window.settings.line.setCurrentText("2p")
    window.settings.bg_mode.setCurrentText("active")
    window.settings.shape.setCurrentText("doniach_sunjic")
    assert window.settings.asym_hi.isEnabled()
    window.settings.asym_hi.setValue(0.2)
    region = window.settings.region_spec(window.session.items[keys[0]].spectrum)
    assert region.background.mode == "active" and region.shape == "doniach_sunjic"
    assert region.constraints.asym == (0.0, 0.2)
    window.settings.load_region(region)
    assert window.settings.bg_mode.currentText() == "active"
    window.settings.shape.setCurrentText("voigt")
    assert not window.settings.asym_hi.isEnabled()
    window.settings.max_n.setValue(1)
    assert window.auto_fit()
    app.processEvents()
    state = window.session.results[keys[0]]
    assert state.result.background.info["mode"] == "active"
    assert "active" in window.diagnostics.toPlainText()


def test_remove_spectrum_and_save_plot(window, app, data_dir, tmp_path):
    key = _fitted(window, app, data_dir)
    out = window.save_plot(tmp_path / "plot.png")
    assert out.exists() and out.stat().st_size > 1000
    window.remove_current_spectrum()
    app.processEvents()
    assert key not in window.session.items
    assert window.diagnostics.toPlainText().startswith("No fit yet")


def test_diagnostics_text_without_result():
    assert diagnostics_text(None, None).startswith("No fit yet")


def test_valence_band_edge_in_the_app(window, app, tmp_path):
    from xps_autofit.synthetic import synthesize_valence_band

    spec, truth = synthesize_valence_band(vbm=1.5, seed=2)
    path = tmp_path / "vb.csv"
    rows = [f"{a:.3f},{int(b)}" for a, b in zip(spec.energy, spec.intensity)]
    path.write_text("Binding Energy (eV),Counts\n" + "\n".join(rows) + "\n", encoding="utf-8")
    assert window.valence_band_edge() is None  # nothing selected
    keys = window.load_files([str(path)])
    window.select_key(keys[0])
    figure = tmp_path / "vb_vbm.png"
    edge = window.valence_band_edge(figure=figure)
    app.processEvents()
    assert edge is not None and abs(edge.vbm - truth["vbm"]) < 0.05
    assert window.vb_edges[keys[0]] is edge
    assert figure.stat().st_size > 10_000
    log = window.log_panel.toPlainText()
    assert f"VBM {edge.vbm:.3f}" in log and "first band maximum" in log
    names = [item.name() for item in window.plot.main.listDataItems()]
    assert names == ["Raw", "Baseline", "Leading edge"]
    assert window.act_vbm.shortcut().toString() == "Ctrl+Shift+V"
    # the PDF report of the file carries the valence band (summary + one page)
    pdf = window.export_report(tmp_path / "vb_report.pdf")
    raw = pdf.read_bytes()
    assert raw.count(b"/Type /Page") - raw.count(b"/Type /Pages") == 2
    assert "1 valence band(s)" in window.log_panel.toPlainText()
    # a spectrum without a fit does not keep the last fit's residual scale
    assert window.plot.resid.getViewBox().viewRange()[1] == pytest.approx([-1.0, 1.0])
    # a spectrum without an edge is reported, not drawn
    window.plot.show_spectrum(spec, "")
    flat = tmp_path / "flat.csv"
    flat.write_text(
        "Binding Energy (eV),Counts\n" + "\n".join(f"{e:.3f},50" for e in spec.energy) + "\n",
        encoding="utf-8",
    )
    k2 = window.load_files([str(flat)])
    window.select_key(k2[0])
    assert window.valence_band_edge() is None
    assert "no valence-band edge" in window.log_panel.toPlainText()
    # a recipe's report: vbm region gives the range and the edge window
    import yaml

    recipe_path = tmp_path / "oxide_vb.yaml"
    recipe_path.write_text(
        yaml.safe_dump(
            {
                "name": "oxide_vb",
                "regions": [
                    {
                        "name": "VB",
                        "range": [-2.0, 10.0],
                        "fit": False,
                        "report": "vbm",
                        "vbm_edge_window": [0.3, 0.7],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    window.use_recipe_file(recipe_path)
    window.select_key(keys[0])
    edge = window.valence_band_edge()
    assert edge is not None and edge.edge_window == (0.3, 0.7)
    assert edge.baseline.lo >= -2.0 and abs(edge.vbm - truth["vbm"]) < 0.05
    assert "recipe region 'VB'" in window.log_panel.toPlainText()
    # removing the spectrum forgets its edge
    window.remove_current_spectrum()
    assert keys[0] not in window.vb_edges
