"""Instrument-style dark theme: flat panels, hairline borders, status lamps.

Colours follow the same validated palette as the figures (``export.plots``), with
the dark-surface steps for series so plot and panels read as one system.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

SURFACE = "#1a1a19"
PANEL = "#222221"
PANEL_RAISED = "#2a2a28"
PLOT_BG = "#131312"
BORDER = "#383835"
INK = "#f0efec"
INK_SECONDARY = "#c3c2b7"
MUTED = "#898781"
ACCENT = "#3987e5"
ACCENT_DIM = "#1c5cab"
GRID = "#2c2c2a"

SERIES_DARK = [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
]

STATUS_COLORS = {
    "idle": "#5a5955",
    "running": ACCENT,
    "ok": "#0ca30c",
    "manual": "#0ca30c",
    "reported": "#0ca30c",
    "ambiguous": "#fab219",
    "needs_review": "#ec835a",
    "failed": "#d03b3b",
    "error": "#d03b3b",
}

STATUS_TEXT = {
    "idle": "IDLE",
    "running": "FITTING",
    "ok": "CONVERGED",
    "manual": "MANUAL FIT",
    "reported": "REPORTED",
    "ambiguous": "AMBIGUOUS",
    "needs_review": "NEEDS REVIEW",
    "failed": "FAILED",
    "error": "ERROR",
}

QSS = f"""
QMainWindow, QDialog, QWidget {{
    background: {SURFACE};
    color: {INK};
    font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
}}
QToolBar {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolBar QToolButton {{
    background: {PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 6px 12px;
    color: {INK};
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QToolBar QToolButton:hover {{ border-color: {ACCENT}; }}
QToolBar QToolButton:pressed {{ background: {ACCENT_DIM}; }}
QToolBar QToolButton:disabled {{ color: {MUTED}; }}
QToolBar QToolButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    color: {INK_SECONDARY};
    font-weight: 700;
    letter-spacing: 1px;
}}
QDockWidget::title {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
    padding: 5px 10px;
    text-align: left;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    margin-top: 14px;
    padding: 8px 6px 6px 6px;
    color: {INK_SECONDARY};
    font-weight: 700;
    letter-spacing: 1px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTreeWidget, QTableWidget, QPlainTextEdit, QListWidget {{
    background: {PLOT_BG};
    border: 1px solid {BORDER};
    gridline-color: {GRID};
    alternate-background-color: {PANEL};
    selection-background-color: {ACCENT_DIM};
    selection-color: {INK};
}}
QHeaderView::section {{
    background: {PANEL};
    color: {INK_SECONDARY};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
    font-weight: 600;
}}
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    background: {PLOT_BG};
    border: 1px solid {BORDER};
    border-radius: 2px;
    padding: 3px 6px;
    color: {INK};
    selection-background-color: {ACCENT_DIM};
}}
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}
QPushButton {{
    background: {PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px 12px;
    color: {INK};
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT}; font-weight: 700; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 13px; height: 13px;
    border: 1px solid {BORDER};
    border-radius: 2px;
    background: {PLOT_BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QStatusBar {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
    color: {INK_SECONDARY};
}}
QProgressBar {{
    background: {PLOT_BG};
    border: 1px solid {BORDER};
    border-radius: 2px;
    text-align: center;
    color: {INK};
    height: 10px;
}}
QProgressBar::chunk {{ background: {ACCENT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: {PANEL}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 20px; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 12px;
    color: {INK_SECONDARY};
}}
QTabBar::tab:selected {{ background: {PANEL_RAISED}; color: {INK}; }}
QLabel#readout {{
    font-family: "SF Mono", Menlo, Consolas, monospace;
    color: {INK};
}}
QLabel#caption {{ color: {MUTED}; font-size: 11px; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item:selected {{ background: {ACCENT_DIM}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QToolTip {{ background: {PANEL_RAISED}; color: {INK}; border: 1px solid {BORDER}; }}
"""


def apply_theme(app: QApplication) -> None:
    import pyqtgraph as pg

    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    pg.setConfigOptions(background=PLOT_BG, foreground=INK_SECONDARY, antialias=True)
