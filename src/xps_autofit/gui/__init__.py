"""Desktop application (PySide6 + PyQtGraph).

Qt is imported lazily so the analysis engine never depends on it.  Start with
``xps-autofit gui`` or ``python -m xps_autofit.gui``.
"""

from __future__ import annotations

import sys
from typing import cast

GUI_INSTALL_HINT = (
    "The desktop application needs PySide6 and pyqtgraph. "
    "Install them with:  pip install 'xps-autofit[gui]'"
)


def run(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(f"{GUI_INSTALL_HINT}\n({exc})") from exc
    from PySide6.QtCore import QSettings

    from .main_window import MainWindow
    from .theme import DEFAULT_THEME, THEMES, apply_theme

    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    theme = str(QSettings("xps-autofit", "studio").value("ui/theme", DEFAULT_THEME))
    apply_theme(cast(QApplication, app), theme if theme in THEMES else DEFAULT_THEME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
