"""Known problems of the Qt binding on particular platforms."""

from __future__ import annotations

import sys

PYSIDE_LINUX_311_WARNING = (
    "PySide6 {version} on Linux with Python {python} has a reference-count bug: every "
    "event Qt hands to Python lowers the count of None, and Python 3.11 aborts "
    "('none_dealloc') once it reaches zero - after a few hundred redraws. Install "
    "PySide6 6.11 (pip install 'PySide6<6.12') or use Python 3.12 or newer."
)


def pyside_refcount_warning(
    platform: str | None = None,
    python: tuple[int, int] | None = None,
    pyside_version: str | None = None,
) -> str | None:
    """A warning when this interpreter and PySide6 form the crashing combination.

    PySide6 6.12.0's Linux build decrements the reference count of ``None`` on each
    event it dispatches; Python 3.12+ makes ``None`` immortal and the macOS and
    Windows builds are not affected (measured on 6.9.3, 6.10.3, 6.11.3, 6.12.0).
    The package's dependency markers avoid the combination; this catches a manual
    installation.
    """
    platform = sys.platform if platform is None else platform
    python = (sys.version_info.major, sys.version_info.minor) if python is None else python
    if pyside_version is None:
        try:
            import PySide6

            pyside_version = PySide6.__version__
        except ImportError:  # pragma: no cover - the GUI needs PySide6 anyway
            return None
    if not platform.startswith("linux") or python >= (3, 12):
        return None
    try:
        major, minor = (int(x) for x in pyside_version.split(".")[:2])
    except ValueError:
        return None
    if (major, minor) < (6, 12):
        return None
    return PYSIDE_LINUX_311_WARNING.format(
        version=pyside_version, python=f"{python[0]}.{python[1]}"
    )
