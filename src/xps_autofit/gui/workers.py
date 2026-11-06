"""Background jobs on a QThread, with the clean-up order that avoids a double free.

The worker never deletes itself from inside its thread.  When it reports
``finished`` or ``failed`` the GUI thread stops the thread, waits for it, and only
then drops both references.  (Deleting the worker from the thread while the GUI
releases its last reference crashes in Shiboken's destructor.)
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot


class FitWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, job: Callable[[], Any]) -> None:
        super().__init__()
        self._job = job

    @Slot()
    def run(self) -> None:
        try:
            result = self._job()
        except Exception:  # report everything; the GUI decides what to show
            self.failed.emit(traceback.format_exc())
            return
        self.finished.emit(result)


class JobRunner(QObject):
    """Runs one job at a time.  ``synchronous=True`` executes inline (tests)."""

    started = Signal(str)
    stopped = Signal()

    def __init__(self, parent: QObject | None = None, synchronous: bool = False) -> None:
        super().__init__(parent)
        self.synchronous = synchronous
        self._thread: QThread | None = None
        self._worker: FitWorker | None = None
        self._on_done: Callable[[Any], None] | None = None
        self._on_error: Callable[[str], None] | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(
        self,
        job: Callable[[], Any],
        on_done: Callable[[Any], None],
        on_error: Callable[[str], None],
        label: str = "job",
    ) -> bool:
        if self.busy:
            return False
        if self.synchronous:
            self.started.emit(label)
            try:
                result = job()
            except Exception:
                on_error(traceback.format_exc())
            else:
                on_done(result)
            finally:
                self.stopped.emit()
            return True
        self._on_done, self._on_error = on_done, on_error
        self._worker = FitWorker(job)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._finished)
        self._worker.failed.connect(self._failed)
        self.started.emit(label)
        self._thread.start()
        return True

    def _teardown(self) -> None:
        thread, self._thread = self._thread, None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait()
        self.stopped.emit()

    @Slot(object)
    def _finished(self, result: Any) -> None:
        cb = self._on_done
        self._teardown()
        if cb is not None:
            cb(result)

    @Slot(str)
    def _failed(self, text: str) -> None:
        cb = self._on_error
        self._teardown()
        if cb is not None:
            cb(text)
