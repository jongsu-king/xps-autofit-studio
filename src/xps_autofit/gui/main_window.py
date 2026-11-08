"""Main window: sample tree | live plot | fit settings and tables, with a status lamp."""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtCore import QDateTime, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .. import __version__
from ..automation.batch_fitting import RunOptions, run_batch, write_region_outputs
from ..automation.identify import Identification, identify_elements
from ..automation.model_selection import select_model
from ..automation.peak_detection import residual_peak
from ..core.constraints import check_physical
from ..core.fitting import ComponentSpec, FitResult, fit_peaks, specs_from_result
from ..core.preprocessing import C1S_REFERENCE_WARNING
from ..core.uncertainty import BootstrapResult, bootstrap
from ..readers import supported_extensions
from ..recipes import builtin_recipe_names, load_recipe
from ..update_check import (
    RELEASES_URL,
    Fetcher,
    UpdateInfo,
    check_for_update,
    disabled_by_environment,
)
from .dialogs import BatchDialog, ExportDialog, TableDialog
from .panels import (
    ComponentsTable,
    CompositionPanel,
    DiagnosticsPanel,
    FitSettingsPanel,
    LogPanel,
    ModelTable,
    SampleTree,
    StatusLamp,
)
from .plot_widget import SpectrumPlot
from .session import RegionState, Session
from .workers import JobRunner

MAX_RECENT = 12
UPDATE_CHECK_INTERVAL_H = 24
UPDATE_CHECK_DELAY_MS = 1500


class UpdateCheckThread(QThread):
    """Runs the release check off the GUI thread; emits the result or ``None``."""

    done = Signal(object)

    def __init__(self, fetch: Fetcher | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self._fetch = fetch

    def run(self) -> None:
        try:
            info: UpdateInfo | None = check_for_update(fetch=self._fetch)
        except Exception:  # offline, rate limit, odd answer: nothing to show
            info = None
        self.done.emit(info)


class MainWindow(QMainWindow):
    def __init__(
        self, synchronous_jobs: bool = False, auto_update_check: bool | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"XPS AutoFit Studio  {__version__}")
        self.resize(1480, 900)
        self.setAcceptDrops(True)
        self.session = Session()
        self.runner = JobRunner(self, synchronous=synchronous_jobs)
        self.settings_store = QSettings("xps-autofit", "studio")
        self._current_key: str | None = None
        self._compare_keys: list[str] = []
        """Spectra shown together in the comparison view (empty: normal view)."""
        self._update_thread: UpdateCheckThread | None = None
        self.last_update_info: UpdateInfo | None = None
        self.last_identification: Identification | None = None

        # ---- central plot
        self.plot = SpectrumPlot()
        self.setCentralWidget(self.plot)

        # ---- left dock: samples
        self.tree = SampleTree()
        self._dock("SAMPLES", self.tree, Qt.DockWidgetArea.LeftDockWidgetArea, 420)

        # ---- right dock: settings + tables
        self.settings = FitSettingsPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.settings)
        self.components = ComponentsTable()
        self.models = ModelTable()
        self.diagnostics = DiagnosticsPanel()
        tabs = QTabWidget()
        tabs.addTab(self.components, "Components")
        tabs.addTab(self.models, "Models")
        tabs.addTab(self.diagnostics, "Diagnostics")
        self.composition = CompositionPanel()
        tabs.addTab(self.composition, "Composition")
        self.tabs = tabs
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(scroll)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 380])
        self._dock("FIT SETTINGS", splitter, Qt.DockWidgetArea.RightDockWidgetArea, 430)

        # ---- bottom dock: log
        self.log_panel = LogPanel()
        self._dock("LOG", self.log_panel, Qt.DockWidgetArea.BottomDockWidgetArea, 0, height=120)

        # ---- toolbar, menus, status bar
        self._build_toolbar()
        self._build_menus()
        self.lamp = StatusLamp()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(140)
        self.status_text = QLabel("Open a spectrum to begin")
        self.cursor_label = QLabel("")
        self.cursor_label.setObjectName("cursor")
        self.cursor_label.setMinimumWidth(230)
        self.update_label = QLabel("")
        self.update_label.setObjectName("update")
        self.update_label.setOpenExternalLinks(True)
        self.update_label.setVisible(False)
        self.statusBar().addWidget(self.lamp)
        self.statusBar().addWidget(self.status_text, 1)
        self.statusBar().addPermanentWidget(self.update_label)
        self.statusBar().addPermanentWidget(self.cursor_label)
        self.statusBar().addPermanentWidget(self.progress)

        # ---- wiring
        self.session.spectraChanged.connect(self._refresh_tree)
        self.session.resultChanged.connect(self._on_result_changed)
        self.session.message.connect(self.log)
        self.tree.spectrumSelected.connect(self.select_key)
        self.tree.spectrumRenamed.connect(self.rename_spectrum)
        self.tree.selectionKeysChanged.connect(self._on_tree_selection)
        self.plot.centerDragged.connect(self._on_center_dragged)
        self.plot.cursorMoved.connect(self._on_cursor_moved)
        self.components.componentEdited.connect(self._on_component_edited)
        self.components.componentRenamed.connect(self.rename_component)
        self.models.modelPicked.connect(self._show_model)
        self.settings.recipe_combo.currentIndexChanged.connect(self._on_recipe_combo)
        self.runner.started.connect(self._job_started)
        self.runner.stopped.connect(self._job_stopped)
        self.settings.set_recipes(builtin_recipe_names())
        self.diagnostics.display(None)
        self._rebuild_recent_menu()
        self.log(
            f"XPS AutoFit Studio {__version__} ready. Formats: {', '.join(supported_extensions())}"
        )
        if auto_update_check is None:
            auto_update_check = not synchronous_jobs
        if auto_update_check and self.update_check_due():
            QTimer.singleShot(UPDATE_CHECK_DELAY_MS, lambda: self.check_for_updates(manual=False))

    # ------------------------------------------------------------------ layout
    def _dock(
        self, title: str, widget: QWidget, area: Qt.DockWidgetArea, width: int, height: int = 0
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(widget)
        if width:
            widget.setMinimumWidth(width)
        if height:
            widget.setMinimumHeight(height)
        self.addDockWidget(area, dock)
        return dock

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)
        self.act_open = QAction("Open files…", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.open_files_dialog)
        self.act_open_folder = QAction("Open folder…", self)
        self.act_open_folder.triggered.connect(self.open_folder_dialog)
        self.act_fit = QAction("AUTO FIT", self)
        self.act_fit.setShortcut("F5")
        self.act_fit.triggered.connect(lambda: self.auto_fit())
        self.act_fit_all = QAction("FIT ALL", self)
        self.act_fit_all.setShortcut("Shift+F5")
        self.act_fit_all.setToolTip(
            "Queue an automatic fit for every loaded spectrum (recipe region by energy "
            "range; the panel settings for the selected one)"
        )
        self.act_fit_all.triggered.connect(lambda: self.fit_all())
        self.act_align = QAction("ALIGN", self)
        self.act_align.setShortcut("Ctrl+Shift+A")
        self.act_align.setToolTip(
            "Charge correction: shift every spectrum of this file so the selected "
            "component sits at the reference energy, then refit them"
        )
        self.act_align.triggered.connect(self.align_charge_dialog)
        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.triggered.connect(lambda: self.undo())
        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.triggered.connect(lambda: self.redo())
        self.act_refit = QAction("REFIT", self)
        self.act_refit.setShortcut("F6")
        self.act_refit.triggered.connect(lambda: self.refit())
        self.act_add = QAction("+ Component", self)
        self.act_add.triggered.connect(self.add_component)
        self.act_remove = QAction("- Component", self)
        self.act_remove.triggered.connect(self.remove_component)
        self.act_uncertainty = QAction("UNCERTAINTY", self)
        self.act_uncertainty.setShortcut("F7")
        self.act_uncertainty.setToolTip(
            "Bootstrap the displayed fit: standard deviations and 95 % intervals"
        )
        self.act_uncertainty.triggered.connect(lambda: self.run_uncertainty())
        self.act_batch = QAction("BATCH", self)
        self.act_batch.setShortcut("Ctrl+B")
        self.act_batch.triggered.connect(self.batch_dialog)
        self.act_export = QAction("EXPORT", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self.export_dialog)
        self.act_reset_view = QAction("Reset view", self)
        self.act_reset_view.setShortcut("Home")
        self.act_reset_view.triggered.connect(self.plot.reset_view)
        self.act_save_plot = QAction("Save plot image…", self)
        self.act_save_plot.setShortcut("Ctrl+Shift+S")
        self.act_save_plot.triggered.connect(self.save_plot_dialog)
        self.act_remove_spectrum = QAction("Remove spectrum", self)
        self.act_remove_spectrum.setShortcut(QKeySequence.StandardKey.Delete)
        self.act_remove_spectrum.triggered.connect(self.remove_current_spectrum)
        self.act_copy_table = QAction("Copy table", self)
        self.act_copy_table.setShortcut("Ctrl+Shift+C")
        self.act_copy_table.triggered.connect(self.copy_current_table)
        self.act_identify = QAction("IDENTIFY", self)
        self.act_identify.setShortcut("F8")
        self.act_identify.setToolTip(
            "Survey: list the elements whose lines explain the peaks and mark them"
        )
        self.act_identify.triggered.connect(lambda: self.identify_current())
        self.act_rename_spectrum = QAction("Rename spectrum…", self)
        self.act_rename_spectrum.setShortcut("F2")
        self.act_rename_spectrum.setToolTip(
            "Title of the selected spectrum: tree, plot, exported figure and project file"
        )
        self.act_rename_spectrum.triggered.connect(self.rename_current_spectrum_dialog)
        self.act_rename_component = QAction("Rename component…", self)
        self.act_rename_component.setShortcut("Shift+F2")
        self.act_rename_component.setToolTip(
            "Name of the selected component (its doublet partner follows); no refit"
        )
        self.act_rename_component.triggered.connect(self.rename_component_dialog)
        for a in (self.act_open, self.act_open_folder):
            bar.addAction(a)
        bar.addSeparator()
        for a in (
            self.act_fit,
            self.act_fit_all,
            self.act_refit,
            self.act_add,
            self.act_remove,
            self.act_uncertainty,
            self.act_identify,
            self.act_align,
        ):
            bar.addAction(a)
        bar.addSeparator()
        for a in (self.act_batch, self.act_export):
            bar.addAction(a)
        for a in (self.act_fit, self.act_batch):
            w = bar.widgetForAction(a)
            if w is not None:
                w.setObjectName("primary")
        self.toolbar = bar

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_open_folder)
        self.menu_recent = m_file.addMenu("Recent files")
        m_file.addAction(self.act_remove_spectrum)
        m_file.addSeparator()
        m_file.addAction(self.act_export)
        m_file.addAction(self.act_save_plot)
        m_file.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        m_file.addAction(quit_action)
        m_edit = self.menuBar().addMenu("&Edit")
        for a in (self.act_undo, self.act_redo):
            m_edit.addAction(a)
        m_edit.addSeparator()
        for a in (self.act_rename_spectrum, self.act_rename_component, self.act_remove_spectrum):
            m_edit.addAction(a)
        m_an = self.menuBar().addMenu("&Analysis")
        for a in (
            self.act_fit,
            self.act_fit_all,
            self.act_refit,
            self.act_add,
            self.act_remove,
            self.act_uncertainty,
            self.act_identify,
            self.act_align,
            self.act_batch,
        ):
            m_an.addAction(a)
        m_view = self.menuBar().addMenu("&View")
        m_view.addAction(self.act_reset_view)
        m_view.addAction(self.act_copy_table)
        m_view.addSeparator()
        # Comparison view (two or more spectra selected in SAMPLES)
        self.compare_group = QActionGroup(self)
        self.act_norm_none = QAction("Compare: raw intensities", self)
        self.act_norm_max = QAction("Compare: normalise to maximum", self)
        self.act_norm_area = QAction("Compare: normalise to area", self)
        for a in (self.act_norm_none, self.act_norm_max, self.act_norm_area):
            a.setCheckable(True)
            self.compare_group.addAction(a)
            m_view.addAction(a)
            a.triggered.connect(lambda _c=False: self._redraw_compare())
        self.act_norm_none.setChecked(True)
        self.act_stack = QAction("Compare: stack with offset", self)
        self.act_stack.setCheckable(True)
        self.act_stack.setToolTip("Waterfall: each spectrum offset by half the largest range")
        self.act_stack.toggled.connect(lambda _on: self._redraw_compare())
        m_view.addAction(self.act_stack)
        m_help = self.menuBar().addMenu("&Help")
        self.act_check_updates = QAction("Check for updates…", self)
        self.act_check_updates.triggered.connect(lambda: self.check_for_updates(manual=True))
        m_help.addAction(self.act_check_updates)
        self.act_auto_updates = QAction("Check for updates at startup", self)
        self.act_auto_updates.setCheckable(True)
        self.act_auto_updates.setChecked(self.update_check_enabled())
        self.act_auto_updates.toggled.connect(
            lambda on: self.settings_store.setValue("update_check/enabled", bool(on))
        )
        m_help.addAction(self.act_auto_updates)
        releases = QAction("Release notes and installers", self)
        releases.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        m_help.addAction(releases)
        m_help.addSeparator()
        about = QAction("About", self)
        about.triggered.connect(
            lambda: QMessageBox.about(
                self,
                "XPS AutoFit Studio",
                f"XPS AutoFit Studio {__version__}\nAutomated, reproducible XPS peak fitting.\n"
                "Engine: NumPy, SciPy, lmfit. Interface: PySide6, PyQtGraph.",
            )
        )
        m_help.addAction(about)

    # ------------------------------------------------------------------ logging
    def log(self, text: str) -> None:
        self.log_panel.log(text)
        self.status_text.setText(text.splitlines()[0][:160])

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self.plot.shutdown()
        thread = self._update_thread
        if thread is not None and thread.isRunning():
            thread.wait(2000)
        super().closeEvent(event)

    # ------------------------------------------------------------- update check
    def update_check_enabled(self) -> bool:
        raw = self.settings_store.value("update_check/enabled", True)
        if isinstance(raw, str):
            return raw.lower() not in ("false", "0", "")
        return bool(raw)

    def update_check_due(self) -> bool:
        """Startup check wanted, not disabled by the environment, and not done recently."""
        if disabled_by_environment() or not self.update_check_enabled():
            return False
        last = self.settings_store.value("update_check/last", "")
        if isinstance(last, str) and last:
            then = QDateTime.fromString(last, Qt.DateFormat.ISODate)
            if then.isValid():
                hours = then.secsTo(QDateTime.currentDateTimeUtc()) / 3600.0
                return hours >= UPDATE_CHECK_INTERVAL_H
        return True

    def check_for_updates(self, manual: bool = True, fetch: Fetcher | None = None) -> bool:
        """Ask GitHub for the latest release; the result arrives in ``_update_checked``."""
        if self.runner.synchronous:
            try:
                info: UpdateInfo | None = check_for_update(fetch=fetch)
            except Exception:
                info = None
            self._update_checked(info, manual)
            return True
        if self._update_thread is not None and self._update_thread.isRunning():
            return False
        thread = UpdateCheckThread(fetch, self)
        thread.done.connect(lambda info, m=manual: self._update_checked(info, m))
        thread.finished.connect(self._update_thread_finished)
        self._update_thread = thread
        if manual:
            self.log("checking GitHub for a newer release…")
        thread.start()
        return True

    def _update_thread_finished(self) -> None:
        thread, self._update_thread = self._update_thread, None
        if thread is not None:
            thread.deleteLater()

    def _update_checked(self, info: UpdateInfo | None, manual: bool) -> None:
        self.last_update_info = info
        if info is None:
            if manual:
                QMessageBox.information(
                    self,
                    "Check for updates",
                    "The release information could not be retrieved (offline, or GitHub "
                    f"did not answer).\n\nReleases: {RELEASES_URL}",
                )
            else:
                self.log("update check: GitHub not reachable; will try again later")
            return
        self.settings_store.setValue(
            "update_check/last", QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate)
        )
        skipped = str(self.settings_store.value("update_check/skip_version", ""))
        if not info.is_newer:
            self.update_label.setVisible(False)
            if manual:
                QMessageBox.information(
                    self,
                    "Check for updates",
                    f"XPS AutoFit Studio {info.current} is up to date "
                    f"(latest release {info.latest}).",
                )
            else:
                self.log(f"update check: {info.current} is the latest release")
            return
        if not manual and skipped == info.latest:
            self.log(f"update check: {info.latest} available (skipped by you)")
            return
        self.show_update(info)
        if manual:
            self._update_dialog(info)

    def show_update(self, info: UpdateInfo) -> None:
        """Put a clickable notice in the status bar and a line in the log."""
        asset = info.platform_asset
        url = asset[1] if asset else info.url
        self.update_label.setText(
            f'<a href="{url}" style="color:#e0b35a;text-decoration:none">'
            f"↑ Update {info.latest} available</a>"
        )
        self.update_label.setToolTip(
            f"You have {info.current}. Click to open " + (asset[0] if asset else "the release page")
        )
        self.update_label.setVisible(True)
        self.log(f"update available: {info.latest} (installed {info.current}) - {info.url}")

    def _update_dialog(self, info: UpdateInfo) -> None:
        asset = info.platform_asset
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Update available")
        box.setText(f"XPS AutoFit Studio {info.latest} is available (you have {info.current}).")
        detail = f"Release page: {info.url}"
        if asset:
            detail += f"\nInstaller for this computer: {asset[0]}"
        else:
            detail += '\nUpgrade with: pip install -U "xps-autofit[gui]"'
        if info.notes:
            detail += "\n\n" + info.notes[:1500]
        box.setDetailedText(detail)
        download = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is download:
            QDesktopServices.openUrl(QUrl(asset[1] if asset else info.url))
        elif clicked is skip:
            self.settings_store.setValue("update_check/skip_version", info.latest)
            self.update_label.setVisible(False)
            self.log(f"update check: {info.latest} will not be announced again")

    def _job_actions(self) -> tuple[QAction, ...]:
        return (
            self.act_fit,
            self.act_refit,
            self.act_batch,
            self.act_export,
            self.act_uncertainty,
            self.act_identify,
            self.act_rename_spectrum,
            self.act_rename_component,
            self.act_fit_all,
            self.act_align,
            self.act_undo,
            self.act_redo,
        )

    def _job_started(self, label: str) -> None:
        self.progress.setVisible(True)
        self.lamp.set_state("running", f"RUNNING: {label.upper()}")
        for a in self._job_actions():
            a.setEnabled(False)

    def _job_stopped(self) -> None:
        self.progress.setVisible(False)
        for a in self._job_actions():
            a.setEnabled(True)
        if self.lamp.state == "running":
            self.lamp.set_state("idle")

    def _on_cursor_moved(self, energy: float, intensity: float) -> None:
        self.cursor_label.setText(f"E {energy:9.3f} eV   I {intensity:12.1f}")

    def _error(self, text: str) -> None:
        self.lamp.set_state("error")
        self.log("error: " + text.strip().splitlines()[-1])
        self.log_panel.log(text)

    # ------------------------------------------------------------------ files
    def open_files_dialog(self) -> None:
        pats = " ".join(f"*{e}" for e in supported_extensions())
        start = self.settings_store.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open spectra", str(start), f"Spectra ({pats});;All files (*)"
        )
        if paths:
            self.settings_store.setValue("last_dir", str(Path(paths[0]).parent))
            self.load_files(paths)

    def open_folder_dialog(self) -> None:
        start = self.settings_store.value("last_dir", str(Path.home()))
        d = QFileDialog.getExistingDirectory(self, "Open folder with spectra", str(start))
        if d:
            self.settings_store.setValue("last_dir", d)
            exts = set(supported_extensions())
            self.load_files([str(p) for p in sorted(Path(d).iterdir()) if p.suffix.lower() in exts])

    def load_files(self, paths: Sequence[str | Path]) -> list[str]:
        keys = self.session.load_paths(list(paths))
        if keys:
            self._remember_recent([str(p) for p in paths])
        if keys and self._current_key is None:
            self.tree.select_key(keys[0])
        return keys

    def load_dropped(self, paths: Sequence[str | Path]) -> list[str]:
        """Files and folders dropped on the window; folders expand to supported files."""
        exts = set(supported_extensions())
        files: list[Path] = []
        skipped: list[str] = []
        for p in map(Path, paths):
            if p.is_dir():
                files.extend(q for q in sorted(p.iterdir()) if q.suffix.lower() in exts)
            elif p.is_file() and p.suffix.lower() in exts:
                files.append(p)
            elif p.is_file():
                skipped.append(p.name)
        if skipped:
            self.log(
                f"drop: skipped {len(skipped)} file(s) with unsupported extension: "
                + ", ".join(skipped[:5])
            )
        if not files:
            self.log("drop: no supported spectrum files")
            return []
        return self.load_files(files)

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.load_dropped(paths)

    # ------------------------------------------------------------- recent files
    def recent_files(self) -> list[str]:
        raw = self.settings_store.value("recent_files", [])
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, (list, tuple)):
            return [str(p) for p in raw]
        return []

    def _remember_recent(self, paths: list[str]) -> None:
        recent = [p for p in self.recent_files() if p not in paths]
        recent = [*paths, *recent][:MAX_RECENT]
        self.settings_store.setValue("recent_files", recent)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.menu_recent.clear()
        recent = self.recent_files()
        for p in recent:
            act = QAction(p, self)
            act.triggered.connect(lambda _checked=False, path=p: self.load_files([path]))
            self.menu_recent.addAction(act)
        if recent:
            self.menu_recent.addSeparator()
            clear = QAction("Clear list", self)
            clear.triggered.connect(self._clear_recent)
            self.menu_recent.addAction(clear)
        self.menu_recent.setEnabled(bool(recent))

    def _clear_recent(self) -> None:
        self.settings_store.setValue("recent_files", [])
        self._rebuild_recent_menu()

    def remove_current_spectrum(self) -> None:
        cur = self.current()
        if cur is None:
            return
        key, item = cur
        self.session.remove(key)
        self._current_key = None
        self.plot.show_spectrum(item.spectrum, "")
        self.components.show_result(None)
        self.models.show_selection(None)
        self.diagnostics.display(None)
        self.lamp.set_state("idle")
        self.log(f"removed {item.display_name}")
        if self.session.order:
            self.tree.select_key(self.session.order[0])

    def _refresh_tree(self) -> None:
        items = [self.session.items[k] for k in self.session.order]
        status = {k: st.status for k, st in self.session.results.items()}
        self.tree.populate(items, status)

    # ------------------------------------------------------------------ renaming
    def rename_current_spectrum_dialog(self) -> None:
        """F2 / File > Rename spectrum: inline editor in the tree when it has the
        focus, otherwise a text dialog."""
        cur = self.current()
        if cur is None:
            self.log("select a spectrum to rename")
            return
        if self.tree.hasFocus() and self.tree.edit_current_title():
            return
        if self.runner.synchronous:  # headless: the dialog would block
            return
        name, ok = QInputDialog.getText(self, "Rename spectrum", "Title:", text=cur[1].display_name)
        if ok:
            self.rename_spectrum(cur[0], name)

    def rename_spectrum(self, key: str, name: str) -> bool:
        """Set the spectrum's title; it appears in the tree, the plot title, the
        exported figure and the project file.  File names are unchanged."""
        item = self.session.items.get(key)
        if item is None:
            return False
        old = item.display_name
        if not self.session.rename_spectrum(key, name):
            self._refresh_tree()  # an empty or unchanged edit: show the old title again
            return False
        self._refresh_title(key)
        self.log(f"renamed spectrum {old!r} to {item.display_name!r}")
        return True

    def rename_component_dialog(self) -> None:
        """Shift+F2 / Analysis > Rename component: inline editor in the Components
        table when it has the focus, otherwise a text dialog."""
        cur = self.current()
        label = self.components.selected_parent()
        if cur is None or label is None:
            self.log("select a component row to rename")
            return
        if self.components.hasFocus() and self.components.edit_selected_name():
            return
        if self.runner.synchronous:
            return
        name, ok = QInputDialog.getText(self, "Rename component", "Name:", text=label)
        if ok:
            self.rename_component(label, name)

    def rename_component(self, old: str, new: str) -> bool:
        """Rename a component of the displayed fit (and its minor doublet line) in the
        tables, the plot, the diagnostics, a bootstrap and the exports.  No refit; the
        fit status does not change.  A rejected name is logged and the table shows the
        old one again."""
        cur = self.current()
        if cur is None:
            return False
        key = cur[0]
        try:
            self.session.rename_component(key, old, new)
        except ValueError as exc:
            self.log(f"rename: {exc}")
            state = self.session.results.get(key)
            if state is not None and state.result is not None:
                self._display_state(key, state)
            return False
        if new.strip() != old:
            self.log(f"renamed component {old!r} to {new.strip()!r}")
        return True

    def _title_for(self, item: Any, state: RegionState | None) -> str:
        if state is None or state.result is None:
            return str(item.display_name)
        sel = state.selection
        n = len(state.result.majors())
        return f"{item.display_name} - {sel.region.name if sel else ''} (n={n}, {state.status})"

    def _refresh_title(self, key: str) -> None:
        if key != self._current_key:
            return
        item = self.session.items[key]
        self.plot.set_title(self._title_for(item, self.session.results.get(key)))

    # ------------------------------------------------------------------ undo / redo
    def undo(self) -> bool:
        cur = self.current()
        if cur is None or not self.session.undo(cur[0]):
            self.log("nothing to undo")
            return False
        self.log("undo")
        return True

    def redo(self) -> bool:
        cur = self.current()
        if cur is None or not self.session.redo(cur[0]):
            self.log("nothing to redo")
            return False
        self.log("redo")
        return True

    # ------------------------------------------------------------- comparison view
    def _on_tree_selection(self, keys: list[str]) -> None:
        keys = [k for k in keys if k in self.session.items]
        if len(keys) >= 2:
            self.compare(keys)
        elif len(keys) == 1 and self._compare_keys:
            self._compare_keys = []
            self.select_key(keys[0])

    def compare_options(self) -> tuple[str, float]:
        """``(normalise, stack)`` from the View menu."""
        if self.act_norm_max.isChecked():
            normalise = "max"
        elif self.act_norm_area.isChecked():
            normalise = "area"
        else:
            normalise = "none"
        return normalise, 0.5 if self.act_stack.isChecked() else 0.0

    def compare(self, keys: list[str]) -> int:
        """Overlay the selected spectra (raw data) in one plot; sample series or depth
        profiles are read side by side, normalised or stacked from the View menu."""
        items = [self.session.items[k] for k in keys if k in self.session.items]
        if len(items) < 2:
            return 0
        self._compare_keys = [k for k in keys if k in self.session.items]
        normalise, stack = self.compare_options()
        entries = [(it.display_name, it.spectrum) for it in items]
        n = self.plot.show_overlay(
            entries, normalise, stack, title=f"Comparison of {len(items)} spectra"
        )
        self.components.show_result(None)
        self.models.show_selection(None)
        self.diagnostics.setPlainText(
            "COMPARE     "
            + "\n            ".join(
                f"{it.display_name:<32} {it.spectrum.n} points  "
                f"{it.spectrum.range[0]:.1f} - {it.spectrum.range[1]:.1f} eV  "
                f"max {float(it.spectrum.intensity.max()):.0f}"
                for it in items
            )
            + f"\n\n{normalise} normalisation; {'stacked' if stack else 'overlaid'}.  "
            "Select a single spectrum to return to its fit."
        )
        self.lamp.set_state("idle", "COMPARE")
        self.log(
            f"comparison view: {n} spectra ({normalise}, {'stacked' if stack else 'overlaid'})"
        )
        return n

    def _redraw_compare(self) -> None:
        if self._compare_keys:
            self.compare(self._compare_keys)

    # ------------------------------------------------------------- batch of fits
    def fit_all(self, keys: Sequence[str] | None = None) -> int:
        """Queue an automatic fit for every loaded spectrum (or *keys*).  Recipe
        regions are matched by energy range; the selected spectrum uses the panel
        settings as AUTO FIT does.  Returns the number of fits queued."""
        targets = list(keys) if keys is not None else list(self.session.order)
        n = 0
        for key in targets:
            item = self.session.items.get(key)
            if item is None:
                continue
            spectrum = item.spectrum
            region = (
                self.settings.region_spec(spectrum)
                if key == self._current_key
                else (self.settings.region_for(spectrum) or self.settings.region_spec(spectrum))
            )

            def job(spec: Any = spectrum, reg: Any = region) -> Any:
                return select_model(spec, reg)

            def done(sel: Any, k: str = key, name: str = item.display_name) -> None:
                self.session.set_selection(k, sel)
                count = sel.best.n_components if sel.best else 0
                self.log(f"{name}: {sel.status}, n={count}")

            self.runner.queue(job, done, self._error, label=f"fit {region.name}")
            n += 1
        if n:
            self.log(f"queued {n} automatic fit(s)")
        return n

    # ---------------------------------------------------------- charge correction
    def align_charge_dialog(self) -> None:
        cur = self.current()
        label = self._reference_component_label()
        if cur is None or label is None:
            self.log("fit the reference region (usually C 1s) and select its component first")
            return
        if self.runner.synchronous:
            return
        default = 284.8
        recipe = self.session.recipe
        if recipe is not None and recipe.charge_reference is not None:
            default = recipe.charge_reference.value
        value, ok = QInputDialog.getDouble(
            self,
            "Charge alignment",
            f"Reference binding energy for {label!r} (eV):",
            default,
            0.0,
            5000.0,
            2,
        )
        if ok:
            self.align_charge(value, label)

    def _reference_component_label(self) -> str | None:
        """The component to align: the table selection, else the recipe's reference
        component when it belongs to the displayed region, else the largest line."""
        cur = self.current()
        if cur is None:
            return None
        state = self.session.results.get(cur[0])
        if state is None or state.result is None:
            return None
        majors = state.result.majors()
        selected = self.components.selected_parent()
        if selected and any(c.label == selected for c in majors):
            return selected
        recipe = self.session.recipe
        if recipe is not None and recipe.charge_reference is not None and state.selection:
            ref = recipe.charge_reference
            if ref.component and state.selection.region.name.lower() == ref.region.lower():
                for c in majors:
                    if c.label.lower() == ref.component.lower():
                        return c.label
        return max(majors, key=lambda c: c.area).label if majors else None

    def align_charge(self, reference: float, component: str | None = None) -> bool:
        """Shift every spectrum of the current file so that *component* (of the
        displayed fit) sits at *reference* eV, then refit the regions that had a fit.
        The shift is recorded in each spectrum's history and in the project files."""
        cur = self.current()
        if cur is None:
            return False
        key, item = cur
        state = self.session.results.get(key)
        if state is None or state.result is None:
            self.log("fit the reference region first")
            return False
        label = component or self._reference_component_label()
        comp = next((c for c in state.result.majors() if c.label == label), None)
        if comp is None:
            self.log(f"no component called {label!r} in the displayed fit")
            return False
        label = comp.label
        delta = float(reference - comp.center)
        if abs(delta) < 0.005:  # below any energy step: nothing worth refitting
            self.log(f"{label} already at {reference:.2f} eV; nothing to align")
            return False
        reason = f"charge correction: {label} {comp.center:.3f} -> {reference:.3f} eV"
        refit = self.session.shift_file(key, delta, reason)
        self.log(
            f"charge alignment {delta:+.3f} eV applied to {len(self.session.siblings(key))} "
            f"spectrum/spectra of {item.path.name} ({reason})"
        )
        if abs(reference - 284.8) < 0.05 or label.lower().startswith("c 1s"):
            self.log(C1S_REFERENCE_WARNING)
        self.select_key(key)
        self.fit_all(refit)
        return True

    # ------------------------------------------------------------------ selection
    def select_key(self, key: str) -> None:
        item = self.session.items.get(key)
        if item is None:
            return
        self._current_key = key
        self._compare_keys = []
        spectrum = item.spectrum
        self.settings.set_range(*spectrum.range)
        self.settings.select_region_for(spectrum)
        state = self.session.results.get(key)
        if state is not None and state.result is not None:
            self._display_state(key, state)
        else:
            self.plot.show_spectrum(spectrum, item.display_name)
            self.components.show_result(None)
            self.models.show_selection(None)
            self.diagnostics.display(None)
            self._refresh_composition()
            self.lamp.set_state("idle")
        self.tree.select_key(key)

    def current(self) -> tuple[str, Any] | None:
        if self._current_key is None:
            return None
        item = self.session.items.get(self._current_key)
        return (self._current_key, item) if item is not None else None

    def _on_recipe_combo(self, _index: int) -> None:
        name = self.settings.recipe_combo.currentData()
        recipe = load_recipe(str(name)) if name else None
        self.session.recipe = recipe
        self.settings.set_recipe(recipe)
        cur = self.current()
        if cur is not None:
            self.settings.select_region_for(cur[1].spectrum)
        self.log(f"recipe: {recipe.name if recipe else 'manual settings'}")

    def use_recipe(self, name: str) -> None:
        idx = self.settings.recipe_combo.findData(name)
        if idx >= 0:
            self.settings.recipe_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------ fitting
    def auto_fit(self) -> bool:
        cur = self.current()
        if cur is None:
            self.log("select a spectrum first")
            return False
        key, item = cur
        region = self.settings.region_spec(item.spectrum)
        spectrum = item.spectrum

        def job() -> Any:
            return select_model(spectrum, region)

        def done(sel: Any) -> None:
            self.session.set_selection(key, sel)
            n = sel.best.n_components if sel.best else 0
            self.log(f"{item.display_name}: {sel.status}, n={n}, " + "; ".join(sel.notes[:2]))

        return self.runner.start(job, done, self._error, label=f"auto fit {region.name}")

    def _manual_specs(self, key: str) -> tuple[RegionState, list[ComponentSpec]] | None:
        state = self.session.results.get(key)
        if state is None or state.result is None or state.selection is None:
            self.log("run AUTO FIT first; manual edits refine an automatic result")
            return None
        return state, specs_from_result(state.result)

    def refit(self, specs: list[ComponentSpec] | None = None) -> bool:
        cur = self.current()
        if cur is None:
            return False
        key, item = cur
        pair = self._manual_specs(key)
        if pair is None:
            return False
        state, current_specs = pair
        specs = specs or current_specs
        sel = state.selection
        assert sel is not None
        settings = (
            replace(sel.best.result.settings, optimizer="leastsq")
            if sel.best
            else sel.region.fit_settings()
        )
        for s in specs:  # widen centre windows to include dragged positions
            if s.center_bounds is not None and not (
                s.center_bounds[0] <= s.center <= s.center_bounds[1]
            ):
                s.center_bounds = (
                    min(s.center_bounds[0], s.center - 0.3),
                    max(s.center_bounds[1], s.center + 0.3),
                )

        background = sel.best.result.background if sel.best else sel.background

        def job() -> FitResult:
            return fit_peaks(sel.spectrum, specs, settings, background=background)

        def done(result: FitResult) -> None:
            violations, warnings = check_physical(
                result,
                sel.region.constraints,
                sel.spectrum.range,
                sel.region.candidate_windows or None,
                False,
                sel.noise.sigma,
            )
            notes = [v.message for v in violations + warnings]
            self.session.set_manual(key, result, notes)
            st = result.stats
            self.log(
                f"manual refit: reduced chi-sq {st.redchi:.3g}, AICc {st.aicc:.1f}"
                + (f"; {notes[0]}" if notes else "")
            )

        return self.runner.start(job, done, self._error, label="refit")

    def _on_center_dragged(self, label: str, energy: float) -> None:
        cur = self.current()
        if cur is None:
            return
        pair = self._manual_specs(cur[0])
        if pair is None:
            return
        _state, specs = pair
        for s in specs:
            if s.label == label:
                s.center = energy
        self.log(f"{label}: centre moved to {energy:.3f} eV")
        if self.settings.auto_refit.isChecked():
            self.refit(specs)

    def _on_component_edited(self, label: str, field: str, value: float) -> None:
        cur = self.current()
        if cur is None:
            return
        pair = self._manual_specs(cur[0])
        if pair is None:
            return
        _state, specs = pair
        for s in specs:
            if s.label == label:
                setattr(s, field, value)
        self.refit(specs)

    def add_component(self) -> None:
        cur = self.current()
        if cur is None:
            return
        pair = self._manual_specs(cur[0])
        if pair is None:
            return
        state, specs = pair
        result = state.result
        sel = state.selection
        assert result is not None and sel is not None
        c = sel.region.constraints
        guess = residual_peak(
            result.x,
            result.residual,
            1.0,
            [s.center for s in specs],
            c.min_separation,
            c.edge_margin,
        )
        center = guess.center if guess is not None else float(result.x[len(result.x) // 2])
        n = len(specs) + 1
        new = ComponentSpec(
            label=f"{sel.region.name} #{n}",
            center=center,
            area=max(result.y_net.max(), 1.0) * 0.1,
            doublet=sel.region.doublet,
        )
        new.fwhm_g = float(sum(s.fwhm_g for s in specs) / len(specs))
        new.fwhm_l = specs[0].fwhm_l
        self.log(f"added component at {center:.2f} eV")
        self.refit(specs + [new])

    def remove_component(self) -> None:
        cur = self.current()
        if cur is None:
            return
        pair = self._manual_specs(cur[0])
        if pair is None:
            return
        _state, specs = pair
        label = self.components.selected_parent()
        if label is None or len(specs) < 2:
            self.log("select a component row to remove (at least one must remain)")
            return
        specs = [s for s in specs if s.label != label]
        self.log(f"removed {label}")
        self.refit(specs)

    def _show_model(self, index: int) -> None:
        cur = self.current()
        if cur is None:
            return
        state = self.session.results.get(cur[0])
        if state is None or state.selection is None:
            return
        cands = state.selection.candidates
        if not 0 <= index < len(cands):
            return
        cand = cands[index]
        if cand.result is state.result:
            self._display_state(cur[0], state)
            return
        title = f"{cur[1].display_name} - candidate n={cand.n_components} ({cand.variant})"
        self.plot.show_result(cand.result, title, draggable=False)
        self.components.show_result(cand.result)
        status = "ok" if cand.physical_ok else "needs_review"
        self.diagnostics.display(cand.result, state.selection, status)

    # ------------------------------------------------------------- identification
    def identify_current(self, tolerance: float = 1.5, min_confidence: float = 0.3) -> bool:
        """Identify the elements in the selected spectrum (meant for surveys)."""
        cur = self.current()
        if cur is None:
            self.log("select a survey spectrum first")
            return False
        key, item = cur
        spectrum = item.spectrum
        lo, hi = spectrum.range
        if hi - lo < 100:
            self.log(
                f"{item.display_name}: {hi - lo:.0f} eV wide; identification is meant for "
                "surveys but runs anyway"
            )

        def job() -> Identification:
            return identify_elements(spectrum, tolerance=tolerance, min_confidence=min_confidence)

        def done(ident: Identification) -> None:
            self.last_identification = ident
            found = ", ".join(f"{c.element} ({c.confidence:.2f})" for c in ident.candidates)
            self.log(
                f"{item.display_name}: {len(ident.peaks)} peaks; elements: "
                + (found or "none above the confidence threshold")
            )
            for n in ident.notes:
                self.log(f"  {n}")
            marks: list[tuple[str, float]] = []
            for c in ident.candidates:
                for m in c.matched:
                    if m.peak is not None and m.line.kind == "photoelectron":
                        marks.append((m.label, m.peak.energy))
            if key == self._current_key:
                self.plot.show_spectrum(spectrum, f"{item.display_name} - identified elements")
                self.plot.mark_lines(marks[:24])
            self.lamp.set_state("ok", "IDENTIFIED")
            if not self.runner.synchronous:
                TableDialog(
                    f"Elements in {item.display_name}", pd.DataFrame(ident.rows()), None, self
                ).exec()

        return self.runner.start(job, done, self._error, label="identify elements")

    # ------------------------------------------------------------- uncertainty
    def run_uncertainty(self, n: int | None = None) -> bool:
        cur = self.current()
        if cur is None:
            self.log("select a fitted spectrum first")
            return False
        key, item = cur
        state = self.session.results.get(key)
        if state is None or state.result is None or state.selection is None:
            self.log("run AUTO FIT first; the bootstrap resamples a fitted model")
            return False
        if n is None:
            n, ok = QInputDialog.getInt(
                self, "Bootstrap uncertainties", "Replicates (Poisson or residual):", 100, 8, 5000
            )
            if not ok:
                return False
        sel = state.selection
        result = state.result
        count = int(n)

        def job() -> BootstrapResult:
            return bootstrap(sel.spectrum, result, n=count, seed=sel.seed)

        def done(boot: BootstrapResult) -> None:
            self.session.set_bootstrap(key, boot)
            self.tabs.setCurrentWidget(self.diagnostics)
            worst = max(
                (
                    (v["area"]["std"] / max(abs(v["area"]["p50"]), 1e-9), label)
                    for label, v in boot.summary.items()
                    if "area" in v
                ),
                default=(0.0, ""),
            )
            self.log(
                f"bootstrap {boot.n_succeeded}/{boot.n_requested} ({boot.mode}): largest relative "
                f"area spread {100 * worst[0]:.1f} % ({worst[1]})"
            )

        return self.runner.start(job, done, self._error, label="bootstrap")

    def copy_current_table(self) -> None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, (ComponentsTable, ModelTable, CompositionPanel)):
            text = widget.copy_to_clipboard(selected_only=False)
            self.log(f"copied {len(text.splitlines()) - 1} rows to the clipboard")
        else:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(self.diagnostics.toPlainText())
            self.log("copied the diagnostics readout to the clipboard")

    def save_plot_dialog(self) -> None:
        cur = self.current()
        if cur is None:
            return
        default = str(Path(str(self.settings_store.value("last_dir", str(Path.home())))))
        name = Path(default) / f"{Path(cur[1].path).stem}_plot.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save plot image", str(name), "PNG (*.png)")
        if path:
            self.save_plot(path)

    def save_plot(self, path: str | Path) -> Path:
        p = Path(path)
        self.plot.export_png(str(p))
        self.log(f"saved plot image: {p}")
        return p

    # ------------------------------------------------------------------ display
    def _on_result_changed(self, key: str) -> None:
        state = self.session.results[key]
        self.tree.set_status(key, state.status)
        if key == self._current_key:
            self._display_state(key, state)
        elif self._current_key is not None and key in self.session.siblings(self._current_key):
            self._refresh_composition()

    def _refresh_composition(self) -> None:
        """Composition of the current file from every fitted region in it."""
        cur = self.current()
        if cur is None:
            self.composition.show_result(None, "")
            return
        key, item = cur
        self.composition.show_result(
            self.session.composition(key),
            f"{item.path.name}: {len(self.session.siblings(key))} spectrum/spectra",
        )

    def _display_state(self, key: str, state: RegionState) -> None:
        item = self.session.items[key]
        result = state.result
        if result is None:
            return
        sel = state.selection
        self.plot.show_result(result, self._title_for(item, state))
        self.components.show_result(result)
        self.models.show_selection(sel)
        self.diagnostics.display(result, sel, state.status, state.bootstrap)
        self._refresh_composition()
        self.lamp.set_state(state.status)

    # ------------------------------------------------------------------ export / batch
    def export_dialog(self) -> None:
        cur = self.current()
        if cur is None:
            self.log("nothing to export")
            return
        fallback = str(cur[1].path.parent / "xps_autofit_results")
        default = Path(str(self.settings_store.value("export_dir", fallback)))
        dlg = ExportDialog(default, self)
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        self.settings_store.setValue("export_dir", str(v["output_dir"]))
        self.export_current(v["output_dir"], v["formats"], v["bootstrap"])

    def export_current(
        self, output_dir: Path, formats: tuple[str, ...], bootstrap: int = 0
    ) -> bool:
        cur = self.current()
        if cur is None:
            return False
        key, item = cur
        state = self.session.results.get(key)
        sel = state.as_selection() if state is not None else None
        if sel is None or sel.best is None:
            self.log("fit the spectrum before exporting")
            return False
        best = sel.best
        options = RunOptions(Path(output_dir), formats=tuple(formats), bootstrap=bootstrap)
        spectrum = item.spectrum
        path = item.path

        def job() -> dict[str, str]:
            extra: dict[str, Any] = {"status": sel.status}
            if bootstrap > 0:
                from ..core.uncertainty import bootstrap as run_bootstrap

                extra["bootstrap"] = run_bootstrap(
                    sel.spectrum, best.result, n=bootstrap, seed=sel.seed
                ).to_dict()
            return write_region_outputs(path, spectrum, sel, options, extra)

        def done(outputs: dict[str, str]) -> None:
            for fmt, p in outputs.items():
                self.log(f"exported {fmt}: {p}")
            self.lamp.set_state(state.status if state else "ok")

        return self.runner.start(job, done, self._error, label="export")

    def batch_dialog(self) -> None:
        default = Path(str(self.settings_store.value("last_dir", str(Path.home()))))
        dlg = BatchDialog(default, self)
        dlg.add_paths(sorted({str(it.path) for it in self.session.items.values()}))
        if self.session.recipe is not None:
            idx = dlg.recipe.findData(self.session.recipe.name)
            if idx >= 0:
                dlg.recipe.setCurrentIndex(idx)
        if dlg.exec() != BatchDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        self.run_batch(
            v["paths"],
            v["recipe"],
            v["output_dir"],
            v["formats"],
            v["charge_correct"],
            v["regions"],
        )

    def run_batch(
        self,
        paths: list[str],
        recipe_name: str,
        output_dir: Path,
        formats: tuple[str, ...],
        charge_correct: bool = True,
        regions: list[str] | None = None,
    ) -> bool:
        try:
            recipe = load_recipe(recipe_name)
        except Exception:
            self._error(traceback.format_exc())
            return False
        options = RunOptions(
            Path(output_dir),
            formats=tuple(formats),
            charge_correct=charge_correct,
            region_filter=regions,
        )

        def job() -> Any:
            return run_batch(paths, recipe, options)

        def done(batch: Any) -> None:
            n_regions = sum(len(f.regions) for f in batch.files)
            self.log(
                f"batch: {len(batch.files)} files, {n_regions} regions, "
                f"{batch.n_ok} ok -> {output_dir}"
            )
            summary = batch.summary_paths.get("summary_regions")
            frame = pd.read_csv(summary) if summary and Path(summary).exists() else pd.DataFrame()
            self.lamp.set_state("ok", "BATCH DONE")
            self._last_batch = (frame, Path(output_dir))
            if not self.runner.synchronous:
                TableDialog("Batch summary", frame, Path(output_dir), self).exec()

        return self.runner.start(job, done, self._error, label=f"batch ({len(paths)} inputs)")
