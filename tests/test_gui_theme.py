"""Light / dark themes and the Origin-style plot of the desktop application."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xps_autofit.export.plots import SERIES as FIGURE_SERIES  # noqa: E402
from xps_autofit.gui import theme  # noqa: E402
from xps_autofit.gui.main_window import MainWindow  # noqa: E402
from xps_autofit.gui.theme import (  # noqa: E402
    DARK,
    LIGHT,
    SERIES_LIGHT,
    apply_theme,
    build_qss,
    current,
    plot_style,
)
from xps_autofit.synthetic import example_dataset  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gui_theme")
    example_dataset(d, seed=13)
    return d


@pytest.fixture
def window(app):
    win = MainWindow(synchronous_jobs=True)
    saved = {
        "ui/theme": win.settings_store.value("ui/theme"),
        "ui/plot_style": win.settings_store.value("ui/plot_style"),
    }
    win.show()
    app.processEvents()
    yield win
    # leave the user's settings and the module theme as they were
    for key, value in saved.items():
        if value is None:
            win.settings_store.remove(key)
        else:
            win.settings_store.setValue(key, value)
    apply_theme(app)
    win.close()
    win.deleteLater()


def _fitted(win, app, data_dir):
    keys = win.load_files([str(data_dir / "p3ht_aged_S2p.csv")])
    win.use_recipe("p3ht")
    win.select_key(keys[0])
    win.auto_fit()
    app.processEvents()
    assert win.session.results[keys[0]].result is not None
    return keys[0]


def test_two_themes_share_the_stylesheet_template(app):
    dark, light = build_qss(DARK), build_qss(LIGHT)
    assert DARK.surface in dark and LIGHT.surface in light and dark != light
    assert LIGHT.panel in light and LIGHT.panel not in dark
    assert dark.count("{") == light.count("{")
    assert apply_theme(app, "light") is LIGHT and current().name == "light"
    assert LIGHT.surface in app.styleSheet()
    assert apply_theme(app, "nonsense") is DARK and current().name == "dark"
    # the plot styles: origin is fixed, instrument follows the theme
    assert plot_style("origin").canvas == "#ffffff" and plot_style("origin").box
    assert plot_style("instrument", LIGHT).canvas == LIGHT.plot_bg
    assert plot_style("instrument", DARK).series == DARK.series
    assert not plot_style("instrument", DARK).box
    # the module constants still name the dark tokens for older callers
    assert DARK.surface == theme.SURFACE and list(DARK.series) == theme.SERIES_DARK


def test_series_palette_matches_the_figures():
    assert SERIES_LIGHT == FIGURE_SERIES
    assert len(SERIES_LIGHT) == len(DARK.series) == 8


def test_origin_style_draws_a_box_with_inward_ticks(window, app, data_dir):
    _fitted(window, app, data_dir)
    plot = window.plot
    window.set_plot_style("origin", persist=False)
    app.processEvents()
    n_items = len(plot.main.listDataItems())
    assert plot.view.backgroundBrush().color().name() == "#ffffff"
    for p in (plot.main, plot.resid):
        assert p.getAxis("top").isVisible() and p.getAxis("right").isVisible()
        assert p.getAxis("left").style["tickLength"] < 0
        assert not p.getAxis("right").style["showValues"]
        assert not p.ctrl.xGridCheck.isChecked()
    raw = next(i for i in plot.main.listDataItems() if i.name() == "Raw")
    assert raw.opts["symbolPen"].color().name() == "#000000"
    envelope = next(i for i in plot.main.listDataItems() if i.name() == "Envelope")
    assert envelope.opts["pen"].color().name() == "#d62728"
    assert plot.main.getAxis("left").style["tickFont"].family() == "Arial"
    assert len(plot._lines) == 2, "draggable centre lines survive the restyle"

    window.set_plot_style("instrument", persist=False)
    app.processEvents()
    assert len(plot.main.listDataItems()) == n_items
    assert plot.view.backgroundBrush().color().name() == DARK.plot_bg
    assert not plot.main.getAxis("top").isVisible()
    assert plot.main.getAxis("left").style["tickLength"] > 0
    assert plot.main.ctrl.xGridCheck.isChecked()
    raw = next(i for i in plot.main.listDataItems() if i.name() == "Raw")
    assert raw.opts["symbolPen"].color().name() == DARK.muted
    assert window.plot_style_actions["instrument"].isChecked()


def test_theme_switch_persists_and_redraws(window, app, data_dir):
    key = _fitted(window, app, data_dir)
    plot = window.plot
    window.set_plot_style("instrument", persist=False)
    before = len(plot.main.listDataItems())
    window.set_theme("light")
    app.processEvents()
    assert window.settings_store.value("ui/theme") == "light"
    assert current().name == "light" and LIGHT.surface in app.styleSheet()
    assert window.theme_actions["light"].isChecked()
    # the instrument plot follows the theme; the fit is still drawn
    assert plot.view.backgroundBrush().color().name() == LIGHT.plot_bg
    assert len(plot.main.listDataItems()) == before
    envelope = next(i for i in plot.main.listDataItems() if i.name() == "Envelope")
    assert envelope.opts["pen"].color().name() == LIGHT.ink
    # the origin style does not change with the theme
    window.set_plot_style("origin", persist=False)
    assert plot.view.backgroundBrush().color().name() == "#ffffff"
    window.set_theme("dark")
    assert plot.view.backgroundBrush().color().name() == "#ffffff"
    assert window.settings_store.value("ui/theme") == "dark"
    with pytest.raises(ValueError):
        window.set_theme("sepia")
    with pytest.raises(ValueError):
        window.set_plot_style("matlab")
    # identified-element marks and a rename survive a style change
    window.select_key(key)
    window.plot.mark_lines([("S 2p", 164.0), ("C 1s", 285.0)])
    window.set_plot_style("instrument", persist=False)
    assert len(window.plot._marks) == 2
    window.plot.set_title("renamed")
    window.set_plot_style("origin", persist=False)
    assert window.plot._title == "renamed"


def test_persisted_theme_is_applied_at_construction(app):
    # Never create a window only to drop it: a MainWindow collected by the cyclic GC
    # deletes its Qt objects at an arbitrary later moment, which aborts the process
    # on some platforms.  Read the settings directly instead.
    settings = QSettings("xps-autofit", "studio")
    saved_theme, saved_style = settings.value("ui/theme"), settings.value("ui/plot_style")
    try:
        settings.setValue("ui/theme", "light")
        settings.setValue("ui/plot_style", "instrument")
        settings.sync()
        win = MainWindow(synchronous_jobs=True)
        assert current().name == "light"
        assert win.plot.look.name == "instrument"
        assert win.plot.view.backgroundBrush().color().name() == LIGHT.plot_bg
        assert win.theme_actions["light"].isChecked()
        assert win.plot_style_actions["instrument"].isChecked()
        win.close()
        win.deleteLater()
        app.processEvents()
    finally:
        for key, value in (("ui/theme", saved_theme), ("ui/plot_style", saved_style)):
            if value is None:
                settings.remove(key)
            else:
                settings.setValue(key, value)
        apply_theme(app)
