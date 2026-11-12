"""Editing enhancements: parameter locks, plot options, saving the settings as a recipe."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import pyqtgraph as pg  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.qt_helpers import dispose_window  # noqa: E402
from xps_autofit.core.fitting import ComponentSpec, build_parameters, fit_peaks  # noqa: E402
from xps_autofit.gui.dialogs import PlotOptionsDialog  # noqa: E402
from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.panels import LOCK_COLUMNS  # noqa: E402
from xps_autofit.gui.plot_widget import PlotOptions  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.recipes import load_recipe  # noqa: E402
from xps_autofit.synthetic import example_dataset, p3ht_s2p, synthesize  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_editing")
    example_dataset(d, seed=19)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    saved = win.settings_store.value("ui/plot_options")
    win.show()
    app.processEvents()
    yield win
    if saved is None:
        win.settings_store.remove("ui/plot_options")
    else:
        win.settings_store.setValue("ui/plot_options", saved)
    dispose_window(win)


def _fitted(win, app, data_dir):
    keys = win.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    win.use_recipe("p3ht")
    win.select_key(keys[0])
    assert win.auto_fit()
    app.processEvents()
    return keys[0]


def test_width_lock_fixes_the_width_parameters():
    spec, _ = synthesize(p3ht_s2p(False), seed=4)
    region = load_recipe("p3ht").region("S 2p")
    settings = region.fit_settings()
    specs = [
        ComponentSpec("a", 164.0, area=5e4, fwhm_g=0.9, fwhm_l=0.3, doublet=region.doublet),
        ComponentSpec(
            "b", 165.3, area=5e3, fwhm_g=0.9, fwhm_l=0.3, doublet=region.doublet, vary_width=False
        ),
    ]
    params = build_parameters(specs, settings, spec.energy)
    assert params["c0_fwhm_g"].vary and not params["c1_fwhm_g"].vary
    assert not params["c1_fwhm_l"].vary or params["c1_fwhm_l"].expr  # shared L follows c0
    result = fit_peaks(spec, specs, settings)
    b = next(c for c in result.majors() if c.label == "b")
    assert b.fwhm_g == pytest.approx(0.9)
    assert result.specs[1].vary_width is False
    assert ComponentSpec.from_dict(specs[1].to_dict()).vary_width is False


def test_locks_from_the_components_table(window, app, data_dir):
    key = _fitted(window, app, data_dir)
    state = window.session.state(key)
    label = state.result.majors()[0].label
    before = {c.label: (c.center, c.fwhm_g) for c in state.result.majors()}
    # the table shows free parameters as unticked boxes
    row = next(
        r
        for r in range(window.components.rowCount())
        if window.components.item(r, 0).data(Qt.ItemDataRole.UserRole) == label
    )
    for col in LOCK_COLUMNS:
        assert window.components.item(row, col).checkState() == Qt.CheckState.Unchecked
    # ticking "Fix W" refits with the widths of that component fixed
    assert window.components.set_lock(label, "vary_width", True)
    app.processEvents()
    state = window.session.state(key)
    spec = next(s for s in state.result.specs if s.label == label)
    assert spec.vary_width is False and state.status == "manual"
    comp = next(c for c in state.result.majors() if c.label == label)
    assert comp.fwhm_g == pytest.approx(before[label][1], abs=1e-9)
    assert window.components.item(row, 11).checkState() == Qt.CheckState.Checked
    assert "widths fixed" in window.log_panel.toPlainText()
    # fixing the centre keeps a dragged centre exactly where it was put
    window._on_component_locked(label, "vary_center", False)
    app.processEvents()
    window._on_center_dragged(label, before[label][0] + 0.3)
    app.processEvents()
    comp = next(c for c in window.session.state(key).result.majors() if c.label == label)
    assert comp.center == pytest.approx(before[label][0] + 0.3, abs=1e-9)
    # unlocking frees it again
    assert window.components.set_lock(label, "vary_center", False)
    app.processEvents()
    spec = next(s for s in window.session.state(key).result.specs if s.label == label)
    assert spec.vary_center is True
    assert window.session.can_undo(key)


def test_plot_options_apply_and_persist(window, app, data_dir):
    _fitted(window, app, data_dir)
    plot = window.plot
    n_fills = sum(isinstance(i, pg.FillBetweenItem) for i in plot.main.items)
    assert n_fills == 2 and plot.legend.isVisible()
    options = PlotOptions(
        title="My title",
        x_label="BE / eV",
        y_label="Counts",
        tick_font_pt=14,
        label_font_pt=16,
        symbol_size=8,
        envelope_width=3.0,
        fill_alpha=50,
        show_legend=False,
        show_fills=False,
        show_center_labels=False,
        x_range=(160.0, 170.0),
        y_range=(0.0, 25000.0),
    )
    window.apply_plot_options(options)
    app.processEvents()
    assert plot.options == options
    assert "My title" in plot.main.titleLabel.text
    assert "BE / eV" in plot.resid.getAxis("bottom").labelText
    assert "Counts" in plot.main.getAxis("left").labelText
    assert not plot.legend.isVisible()
    assert sum(isinstance(i, pg.FillBetweenItem) for i in plot.main.items) == 0
    assert plot.main.getAxis("left").style["tickFont"].pointSize() == 14
    assert plot._eff.symbol_size == 8 and plot._eff.envelope_width == 3.0
    assert plot._eff.fill_alpha == round(50 * 2.55)
    xr = plot.main.getViewBox().viewRange()[0]
    assert xr[0] == pytest.approx(160.0, abs=1e-6) and xr[1] == pytest.approx(170.0, abs=1e-6)
    yr = plot.main.getViewBox().viewRange()[1]
    assert yr[1] == pytest.approx(25000.0, abs=1e-6)
    assert all(getattr(line, "label", None) is None for line in plot._lines.values())
    stored = json.loads(str(window.settings_store.value("ui/plot_options")))
    assert PlotOptions.from_dict(stored) == options
    # a new window picks the options up again
    other = MainWindow(synchronous_jobs=True)
    assert other.plot.options == options
    dispose_window(other)
    # the dialog reproduces and resets them
    dlg = PlotOptionsDialog(options)
    assert dlg.values() == options
    dlg.restore_defaults()
    assert dlg.values() == PlotOptions()
    window.apply_plot_options(PlotOptions())
    app.processEvents()
    assert plot.legend.isVisible()
    assert sum(isinstance(i, pg.FillBetweenItem) for i in plot.main.items) == 2
    assert "My title" not in plot.main.titleLabel.text


def test_settings_saved_as_recipe(window, app, data_dir, tmp_path):
    key = _fitted(window, app, data_dir)
    window.settings.max_n.setValue(4)
    recipe = window.save_recipe_file(tmp_path / "my_sample.yaml", include_components=True)
    assert recipe is not None
    loaded = load_recipe(tmp_path / "my_sample.yaml")
    names = [r.name for r in loaded.regions]
    assert "S 2p" in names and "C 1s" in names, "the other regions of the base recipe are kept"
    s2p = loaded.region("S 2p")
    majors = window.session.state(key).result.majors()
    assert [c.label for c in s2p.candidates] == [m.label for m in majors]
    assert s2p.min_components == s2p.max_components == len(majors)
    assert s2p.candidates[0].center == pytest.approx(majors[0].center)
    assert loaded.charge_reference is not None and loaded.photon_energy is not None
    assert "based on p3ht" in loaded.description
    assert window.session.recipe is not None
    assert window.session.recipe.source == str(tmp_path / "my_sample.yaml")
    assert "my_sample (file)" in window.settings.recipe_combo.currentText()
    # without components the panel values alone are written (base recipe p3ht again)
    window.use_recipe("p3ht")
    window.settings.max_n.setValue(4)
    plain = window.save_recipe_file(tmp_path / "plain.yaml")
    assert (
        plain is not None
        and plain.region("S 2p").candidates == load_recipe("p3ht").region("S 2p").candidates
    )
    assert plain.region("S 2p").max_components == 4
    assert np.isfinite(plain.photon_energy)


def test_redraws_release_the_centre_lines(window, app, data_dir):
    """Every redraw used to leak its draggable centre lines and their labels: the drag
    callback was a lambda holding the line, a cycle through the C++ connection that
    the garbage collector cannot see.  Leaked Qt graphics objects were later freed in
    an arbitrary order."""
    import gc

    key = _fitted(window, app, data_dir)
    result = window.session.state(key).result
    for _ in range(3):
        window.plot.show_result(result, "t")
        app.processEvents()
    gc.collect()
    before = sum(isinstance(o, pg.InfiniteLine) for o in gc.get_objects())
    for _ in range(15):
        window.plot.show_result(result, "t")
        app.processEvents()
    gc.collect()
    after = sum(isinstance(o, pg.InfiniteLine) for o in gc.get_objects())
    assert after == before
    # dragging still refits through the bound slot
    label = result.majors()[0].label
    line = window.plot._lines[label]
    line.setValue(line.value() + 0.2)
    line.sigPositionChangeFinished.emit(line)
    app.processEvents()
    assert window.session.state(key).status == "manual"


def test_export_for_origin_from_the_app(window, app, data_dir, tmp_path):
    from xps_autofit.export.origin import ORIGIN_COMPONENTS_SUFFIX

    keys = window.load_files([str(data_dir / "p3ht_fresh_S2p.csv")])
    window.select_key(keys[0])
    # a spectrum without a fit: energy and intensity
    raw = window.export_for_origin(tmp_path / "raw")
    assert [p.name for p in raw] == ["raw.csv"]
    assert raw[0].read_text(encoding="utf-8").splitlines()[1].startswith("eV,counts")
    # the fit: curves and the component table, then opened (opener is stubbed)
    key = _fitted(window, app, data_dir)
    opened: list[Path] = []
    files = window.export_for_origin(
        tmp_path / "s2p_origin.csv",
        open_after=True,
        opener=lambda p: (opened.append(p), "default")[1],
    )
    assert [p.name for p in files] == ["s2p_origin.csv", f"s2p{ORIGIN_COMPONENTS_SUFFIX}"]
    assert opened == [files[0]]
    header = files[0].read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header[:2] == ["Binding Energy", "Raw"]
    assert window.session.state(key).result.majors()[0].label.replace(",", ";") in header
    assert "drag the file into Origin" in window.log_panel.toPlainText()
    # the comparison view: X/Y pairs
    window.tree.select_keys(list(window.session.order))
    app.processEvents()
    assert len(window._compare_keys) == 2
    pairs = window.export_for_origin(tmp_path / "compare_origin.csv")
    first = pairs[0].read_text(encoding="utf-8").splitlines()[0].split(",")
    assert first[0] == "Binding Energy" and first[2] == "Binding Energy" and len(first) == 4


def test_survey_composition_and_series_in_the_app(window, app, data_dir, tmp_path):
    import pandas as pd

    # IDENTIFY on a survey fills the Composition tab with the survey estimate
    keys = window.load_files([str(data_dir / "cu2o_survey.csv")])
    survey_key = keys[0]
    window.select_key(survey_key)
    assert window.identify_current()
    app.processEvents()
    quant = window.survey_quant[survey_key]
    assert quant.status == "OK" and {"Cu", "O", "C"} <= set(quant.composition())
    shown = window.composition.result
    assert shown is not None and all(e.label.endswith("(survey)") for e in shown.entries)
    assert "survey estimate" in window.composition.status.text()
    assert "survey composition (rough)" in window.log_panel.toPlainText()
    # two fitted multi-region files plus the survey make a series of three
    multi = window.load_files(
        [str(data_dir / "p3ht_aged_multi.vms"), str(data_dir / "p3ht_aged_multi.xlsx")]
    )
    window.use_recipe("p3ht")
    window.select_key(multi[0])
    window.fit_all(multi)
    app.processEvents()
    frame = window.composition_series_frame()
    assert list(frame["sample"]) == ["cu2o_survey", "p3ht_aged_multi", "p3ht_aged_multi"]
    assert list(frame["status"]) == ["OK", "OK", "OK"]
    assert frame.loc[1, "S at%"] == pytest.approx(frame.loc[2, "S at%"], abs=0.5)
    dlg = window.composition_series_dialog()
    assert dlg is not None and dlg.table.rowCount() == 3
    assert len(dlg.curves) == len([c for c in frame.columns if c.endswith(" at%")])
    dlg.close()
    dlg.deleteLater()
    plain = window.export_series(tmp_path / "series.csv")
    assert pd.read_csv(plain)["sample"].tolist() == frame["sample"].tolist()
    opened: list[Path] = []
    origin = window.export_series(
        tmp_path / "series_origin.csv",
        origin=True,
        open_after=True,
        opener=lambda p: (opened.append(p), "default")[1],
    )
    assert opened == [origin]
    assert origin.read_text(encoding="utf-8").splitlines()[0].startswith("Sample index,")


def test_assignment_column_and_rsf_library_in_the_app(window, app, data_dir, tmp_path):
    from xps_autofit.gui.panels import ASSIGNMENT_COLUMN, COMPONENT_HEADERS

    assert COMPONENT_HEADERS[ASSIGNMENT_COLUMN] == "Assignment"
    key = _fitted(window, app, data_dir)  # P3HT S 2p: thiophene and oxidised sulfur
    table = window.components
    texts = [table.item(r, ASSIGNMENT_COLUMN).text() for r in range(table.rowCount())]
    assert any("thiophene" in t for t in texts)
    first = next(
        r for r in range(table.rowCount()) if "thiophene" in table.item(r, ASSIGNMENT_COLUMN).text()
    )
    assert "not an assignment" in table.item(first, ASSIGNMENT_COLUMN).toolTip()
    minor_rows = [r for r in range(table.rowCount()) if table.item(r, 0).text().startswith("    ")]
    assert minor_rows and all(table.item(r, ASSIGNMENT_COLUMN).text() == "" for r in minor_rows)
    # an RSF library replaces the recipe factor in the Composition tab
    saved = window.settings_store.value("quant/rsf_library")
    try:
        lib = tmp_path / "inst.csv"
        lib.write_text("element,line,rsf\nS,2p,2.0\n")
        before = window.session.composition(key)
        assert before is not None and before.entries[0].rsf_source == "recipe"
        assert window.load_rsf_library_file(lib) is not None
        after = window.session.composition(key)
        s2p = next(e for e in after.entries if e.element == "S")
        assert s2p.rsf == 2.0 and s2p.rsf_source == "library inst"
        assert "RSF library inst" in after.note
        assert window.settings_store.value("quant/rsf_library") == str(lib)
        assert window.load_rsf_library_file(tmp_path / "missing.csv") is None
        assert "RSF library not loaded" in window.log_panel.toPlainText()
        window.clear_rsf_library()
        assert window.session.rsf_library is None
        assert window.session.composition(key).entries[0].rsf_source == "recipe"
    finally:
        if saved is None:
            window.settings_store.remove("quant/rsf_library")
        else:
            window.settings_store.setValue("quant/rsf_library", saved)


def test_report_and_tougaard_selector_in_the_app(window, app, data_dir, tmp_path):
    panel = window.settings
    assert not panel.tougaard_cs.isEnabled()
    panel.background.setCurrentText("tougaard")
    assert panel.tougaard_cs.isEnabled()
    panel.tougaard_cs.setCurrentText("polymer")
    from xps_autofit.synthetic import p3ht_s2p, synthesize

    spec, _ = synthesize(p3ht_s2p(False), seed=1)
    bg = panel.region_spec(spec).background
    assert (bg.tougaard_C, bg.tougaard_D) == (551.0, 436.0)
    # a recipe's own constants show as "custom" and survive the round trip
    from dataclasses import replace

    from xps_autofit.core.background import BackgroundSpec

    custom = replace(
        panel.region_spec(spec),
        background=BackgroundSpec(type="tougaard", tougaard_C=800.0, tougaard_D=100.0),
    )
    panel.load_region(custom)
    assert panel.tougaard_cs.currentText() == "custom"
    again = panel.region_spec(spec).background
    assert (again.tougaard_C, again.tougaard_D) == (800.0, 100.0)
    panel.background.setCurrentText("shirley")
    # nothing loaded or fitted: no report
    assert window.export_report(tmp_path / "none.pdf") is None
    assert not (tmp_path / "none.pdf").exists()
    keys = window.load_files([str(data_dir / "p3ht_aged_multi.vms")])
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    window.fit_all(keys)
    app.processEvents()
    path = window.export_report(tmp_path / "report")
    assert path is not None and path.suffix == ".pdf" and path.exists()
    raw = path.read_bytes()
    assert raw.count(b"/Type /Page") - raw.count(b"/Type /Pages") == 3
    assert "report:" in window.log_panel.toPlainText()
