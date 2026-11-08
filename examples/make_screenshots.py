"""Render the documentation screenshots of the desktop application offscreen.

Usage::

    QT_QPA_PLATFORM=offscreen python examples/make_screenshots.py docs/images

The synthetic example data set is written to a temporary folder, fitted with the
built-in recipes exactly as a user would do it in the window, and the window (or a
panel of it) is grabbed to PNG.  No display is needed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.panels import DiagnosticsPanel, ModelTable  # noqa: E402
from xps_autofit.gui.theme import apply_theme  # noqa: E402
from xps_autofit.synthetic import example_dataset  # noqa: E402


def _grab_standalone(widget: QWidget, width: int, height: int, path: Path) -> None:
    """Show a panel on its own at a legible size and grab it."""
    widget.resize(width, height)
    widget.show()
    QApplication.processEvents()
    widget.grab().save(str(path))
    widget.close()


def main(out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        example_dataset(data, seed=5)
        win = MainWindow(synchronous_jobs=True)
        win.resize(1700, 980)
        win.show()
        app.processEvents()

        # 1. Cu 2p3/2 with satellites: the full window after AUTO FIT
        keys = win.load_files([str(data / "cu2o_Cu2p3.txt"), str(data / "p3ht_aged_S2p.csv")])
        win.use_recipe("cu2o")
        win.select_key(keys[0])
        win.auto_fit()
        app.processEvents()
        win.tabs.setCurrentWidget(win.components)
        app.processEvents()
        p = out / "gui_main_cu2p.png"
        win.grab().save(str(p))
        written.append(p)

        # 2. Diagnostics readout (with bootstrap) and the candidate-model table of
        #    the same fit, rendered on their own so the text is legible.
        win.run_uncertainty(60)
        app.processEvents()
        state = win.session.results[keys[0]]
        diag = DiagnosticsPanel()
        diag.display(state.result, state.selection, state.status, state.bootstrap)
        p = out / "gui_diagnostics.png"
        _grab_standalone(diag, 1040, 440, p)
        written.append(p)
        models = ModelTable()
        models.show_selection(state.selection)
        models.resizeColumnsToContents()
        p = out / "gui_models.png"
        _grab_standalone(models, 1040, 200, p)
        written.append(p)

        # 3. S 2p: automatic two-doublet fit, then a manual refit after a drag
        win.use_recipe("p3ht")
        win.select_key(keys[1])
        win.auto_fit()
        app.processEvents()
        line = win.plot._lines["sulfonate/sulfate"]
        line.setValue(line.value() + 0.25)
        line.sigPositionChangeFinished.emit(line)
        app.processEvents()
        win.tabs.setCurrentWidget(win.components)
        app.processEvents()
        p = out / "gui_s2p_manual.png"
        win.grab().save(str(p))
        written.append(p)

        # 4. Survey with the identified element lines marked (IDENTIFY)
        keys = win.load_files([str(data / "cu2o_survey.csv")])
        win.select_key(keys[-1])
        win.identify_current()
        app.processEvents()
        p = out / "gui_survey_identify.png"
        win.grab().save(str(p))
        written.append(p)

        # 5. Composition tab: both regions of the multi-region VAMAS file (FIT ALL)
        keys = win.load_files([str(data / "p3ht_aged_multi.vms")])
        win.use_recipe("p3ht")
        win.select_key(keys[0])
        win.fit_all(keys)
        app.processEvents()
        for k in keys:
            win.select_key(k)
            win.run_uncertainty(40)
            app.processEvents()
        win.select_key(keys[1])
        win.tabs.setCurrentWidget(win.composition)
        app.processEvents()
        p = out / "gui_composition.png"
        win.grab().save(str(p))
        written.append(p)

        # 6. Comparison view: fresh and aged S 2p, normalised to the maximum, stacked
        #    (the aged file is already loaded, so collect both keys from the session)
        win.load_files([str(data / "p3ht_fresh_S2p.csv")])
        wanted = ("p3ht_fresh_S2p.csv", "p3ht_aged_S2p.csv")
        keys = [k for k in win.session.order if win.session.items[k].path.name in wanted]
        win.act_norm_max.setChecked(True)
        win.act_stack.setChecked(True)
        win.tree.select_keys(keys)
        app.processEvents()
        win.tabs.setCurrentWidget(win.diagnostics)
        app.processEvents()
        p = out / "gui_compare.png"
        win.grab().save(str(p))
        written.append(p)
        win.close()
        app.processEvents()
    return written


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "docs/images"
    for path in main(target):
        print(path)
