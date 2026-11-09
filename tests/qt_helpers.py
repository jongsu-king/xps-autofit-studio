"""Helpers for the desktop-application tests."""

from __future__ import annotations

import gc
from typing import Any


def dispose_window(widget: Any) -> None:
    """Close a top-level widget and really delete it before the next test.

    ``deleteLater()`` only takes effect when an event loop processes deferred
    deletions; ``processEvents()`` outside a running loop does not, so a closed
    window used to stay alive for the rest of the session together with every
    widget, timer and plot item in it (and a Python wrapper kept alive by the
    lambdas connected to its actions).  Dozens of such windows kept receiving
    events and were finally freed in an arbitrary order at interpreter exit.
    Sending the posted ``DeferredDelete`` events explicitly deletes the C++ side;
    PySide then drops the connections, which breaks the Python cycles.
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    gc.collect()
