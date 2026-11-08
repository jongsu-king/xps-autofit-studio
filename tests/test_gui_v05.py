"""Desktop features added in 0.5: composition tab, FIT ALL and the job queue, charge
alignment, undo/redo, the comparison (overlay/stack) view, the scatter-window control."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

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
    d = tmp_path_factory.mktemp("gui_data5")
    example_dataset(d, seed=11)
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


def test_job_queue_runs_in_order():
    runner = JobRunner(synchronous=True)
    seen: list[int] = []
    for i in range(3):
        runner.queue(lambda i=i: i, seen.append, lambda e: seen.append(-1), label=f"j{i}")
    assert seen == [0, 1, 2] and runner.pending == 0
    assert runner.cancel_pending() == 0


def test_fit_all_and_composition_tab(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_aged_multi.vms")])
    assert len(keys) == 2
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    app.processEvents()
    assert window.composition.table.rowCount() == 0
    assert "no fitted region" in window.composition.status.text()

    assert window.fit_all() == 2
    app.processEvents()
    for k in keys:
        assert window.session.results[k].result is not None
    quant = window.session.composition(keys[0])
    assert quant is not None and quant.status == "OK"
    labels = {e.label: e for e in quant.entries}
    assert set(labels) == {"S 2p", "C 1s"}
    assert all(e.rsf_source == "recipe" for e in quant.entries)
    assert sum(e.atomic_percent for e in quant.entries) == pytest.approx(100.0)
    # The S 2p RSF (1.677, total doublet) against C 1s (1.0): S well below C.
    assert labels["S 2p"].atomic_percent < labels["C 1s"].atomic_percent
    assert labels["C 1s"].kinetic_energy == pytest.approx(1486.6 - 284.8, abs=1.0)
    table = window.composition.table
    assert table.rowCount() == 2
    assert "atomic % from 2 region(s)" in window.composition.status.text()
    text = window.composition.copy_to_clipboard()
    assert text.splitlines()[0].startswith("Region\tAtomic %")
    # A bootstrap on both regions adds intervals.
    for k in keys:
        window.select_key(k)
        assert window.run_uncertainty(8)
        app.processEvents()
    quant = window.session.composition(keys[0])
    assert quant is not None and quant.entries[0].atomic_percent_std is not None


def test_align_charge_shifts_the_file_and_refits(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_aged_multi.vms")])
    window.use_recipe("p3ht")
    original = {k: window.session.items[k].spectrum.energy[0] for k in keys}
    # Simulate a charged sample: every region of the file sits 1.5 eV too high.
    window.session.shift_file(keys[0], 1.5, "simulated charging")
    window.select_key(keys[0])
    window.fit_all()
    app.processEvents()
    c1s = next(k for k in keys if "C 1s" in window.session.items[k].display_name)
    s2p = next(k for k in keys if k != c1s)
    window.select_key(c1s)
    app.processEvents()
    # On charged data the recipe windows do not match, so the reference falls back to
    # the largest line, which is the C-C/C-H peak sitting near 286.3 eV.
    label = window._reference_component_label()
    assert label is not None
    cc = next(c for c in window.session.results[c1s].result.majors() if c.label == label)
    assert cc.center == pytest.approx(286.3, abs=0.05)
    assert window.align_charge(284.8)
    app.processEvents()
    delta = 284.8 - cc.center
    assert delta == pytest.approx(-1.5, abs=0.05)
    for k in keys:
        spec = window.session.items[k].spectrum
        assert spec.energy[0] == pytest.approx(original[k], abs=0.05), "back where it started"
        assert (
            spec.history[-1]["step"] == "shift"
            and "charge correction" in spec.history[-1]["reason"]
        )
        assert window.session.results[k].result is not None, "refitted after the shift"
    # After the correction the recipe windows match again and the labels return.
    moved = next(c for c in window.session.results[c1s].result.majors() if c.label == "C-C/C-H")
    assert moved.center == pytest.approx(284.8, abs=0.02)
    s_main = max(window.session.results[s2p].result.majors(), key=lambda c: c.area)
    assert s_main.center == pytest.approx(164.0, abs=0.05)
    assert "charge alignment" in window.log_panel.toPlainText()
    assert window.composition.table.rowCount() == 2
    assert not window.align_charge(moved.center), "already there: nothing to do"
    assert "nothing to align" in window.log_panel.toPlainText()


def test_undo_redo_of_manual_edits(window, app, data_dir):
    keys = window.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    window.use_recipe("p3ht")
    window.select_key(keys[0])
    window.auto_fit()
    app.processEvents()
    key = keys[0]
    assert not window.undo()
    window.add_component()
    app.processEvents()
    assert len(window.session.results[key].result.majors()) == 3
    assert window.rename_component("sulfonate/sulfate", "sulfate")
    assert window.undo()
    assert [c.label for c in window.session.results[key].result.majors()][1] == "sulfonate/sulfate"
    assert window.undo()
    state = window.session.results[key]
    assert len(state.result.majors()) == 2 and state.status == "ok"
    assert window.components.rowCount() == 4
    assert window.redo()
    assert len(window.session.results[key].result.majors()) == 3
    assert window.session.results[key].status == "manual"
    assert window.redo() and window.session.results[key].result.majors()[1].label == "sulfate"
    assert not window.redo()
    assert window.act_undo in window._job_actions()


def test_compare_view_overlays_and_stacks(window, app, data_dir):
    keys = window.load_files(
        [str(data_dir / "p3ht_fresh_S2p.csv"), str(data_dir / "p3ht_aged_S2p.csv")]
    )
    assert len(keys) == 2
    window.select_key(keys[0])
    app.processEvents()
    window.tree.select_keys(keys)
    app.processEvents()
    assert window._compare_keys == keys
    assert window.lamp.label.text() == "COMPARE"
    curves = [i for i in window.plot.main.listDataItems()]
    assert len(curves) == 2
    assert window.plot.main.titleLabel.text.startswith("Comparison of 2 spectra")
    assert "COMPARE" in window.diagnostics.toPlainText()
    window.act_norm_max.trigger()
    app.processEvents()
    ys = [c.yData for c in window.plot.main.listDataItems()]
    assert all(abs(y.max() - 1.0) < 1e-9 for y in ys)
    window.act_stack.setChecked(True)
    app.processEvents()
    ys = sorted(c.yData.min() for c in window.plot.main.listDataItems())
    assert ys[1] - ys[0] > 0.4, "second spectrum offset by half the largest range"
    assert window.compare_options() == ("max", 0.5)
    window.plot.reset_view()
    # Back to a single spectrum: the normal view returns.
    window.tree.select_keys([keys[1]])
    app.processEvents()
    assert window._compare_keys == []
    assert window.lamp.label.text() != "COMPARE"
    window.act_stack.setChecked(False)
    window.act_norm_none.trigger()


def test_scatter_window_control_round_trip(window):
    panel = window.settings
    assert not panel.scatter_window.isEnabled()
    panel.bg_mode.setCurrentText("active")
    assert panel.scatter_window.isEnabled()
    assert panel.scatter_window.value() == pytest.approx(0.3)
    from xps_autofit.synthetic import p3ht_s2p, synthesize

    spec, _ = synthesize(p3ht_s2p(False), seed=1)
    assert window.settings.region_spec(spec).background.scatter_window == pytest.approx(0.3)
    panel.scatter_window.setValue(0.0)
    assert window.settings.region_spec(spec).background.scatter_window is None
    assert panel.scatter_window.text() == "free"
