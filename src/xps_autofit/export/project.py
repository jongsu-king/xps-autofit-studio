"""Reproducible project files.

A project JSON stores the data actually fitted, every setting, the initial values of
the chosen start, the fitted parameters and the software versions.  Loading a project
and re-running :func:`xps_autofit.core.fitting.fit_peaks` from the stored start must
reproduce the stored parameters; :func:`verify_project` checks that.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lmfit
import numpy as np
import scipy

from .. import __version__
from ..automation.model_selection import SelectionResult
from ..core.fitting import ComponentSpec, FitResult, FitSettings, fit_peaks
from ..core.spectrum import Spectrum

PROJECT_FORMAT = 1


def environment() -> dict[str, str]:
    return {
        "xps_autofit": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "lmfit": lmfit.__version__,
    }


def project_dict(
    selection: SelectionResult,
    source: dict[str, Any] | None = None,
    original: Spectrum | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "format": PROJECT_FORMAT,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": environment(),
        "source": source or {},
        "selection": selection.to_dict(include_arrays=True),
    }
    if original is not None:
        d["original_spectrum"] = original.to_dict(include_data=False)
    if extra:
        d.update(extra)
    return d


def save_project(path: str | Path, data: dict[str, Any]) -> Path:
    path = Path(path)
    path.write_text(json.dumps(data, indent=1, allow_nan=False, default=_default), encoding="utf-8")
    return path


def _default(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        v = obj.item()
        return v if np.isfinite(v) else None
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serialisable: {type(obj)}")


def load_project(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class VerifyReport:
    ok: bool
    max_param_rel_diff: float
    max_envelope_abs_diff: float
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def refit_from_project(data: dict[str, Any]) -> tuple[Spectrum, FitResult]:
    """Rebuild the fitted spectrum and re-run the fit from the stored start."""
    sel = data["selection"]
    best = sel["best"]
    if best is None:
        raise ValueError("project has no selected model to reproduce")
    spectrum = Spectrum.from_dict(sel["spectrum"])
    fit = best["fit"]
    settings = FitSettings.from_dict(fit["settings"])
    specs = [ComponentSpec.from_dict(s) for s in fit["specs"]]
    return spectrum, fit_peaks(spectrum, specs, settings)


def verify_project(
    path: str | Path, rtol: float = 1e-6, atol_envelope: float | None = None
) -> VerifyReport:
    """Re-run the stored fit and compare parameters and envelope with the file."""
    data = load_project(path)
    spectrum, result = refit_from_project(data)
    stored_fit = data["selection"]["best"]["fit"]
    messages: list[str] = []
    max_rel = 0.0
    for name, p in stored_fit["params"].items():
        if name not in result.params:
            messages.append(f"parameter {name} missing after refit")
            continue
        a = float(p["value"])
        b = float(result.params[name]["value"])
        scale = max(abs(a), abs(b), 1e-12)
        rel = abs(a - b) / scale
        max_rel = max(max_rel, rel)
        if rel > rtol:
            messages.append(f"{name}: stored {a:.6g} vs refit {b:.6g} (rel {rel:.2e})")
    stored_env = np.asarray(stored_fit["envelope"], dtype=float)
    env_diff = (
        float(np.max(np.abs(stored_env - result.envelope)))
        if stored_env.size == result.envelope.size
        else float("inf")
    )
    if atol_envelope is None:
        atol_envelope = (
            1e-6 * max(1.0, float(np.max(np.abs(stored_env)))) if stored_env.size else 1e-6
        )
    if env_diff > atol_envelope:
        messages.append(f"envelope differs by up to {env_diff:.3g}")
    env = data.get("environment", {})
    now = environment()
    for key in ("xps_autofit", "numpy", "scipy", "lmfit"):
        if env.get(key) != now.get(key):
            messages.append(f"note: {key} version {env.get(key)} (file) vs {now.get(key)} (now)")
    ok = max_rel <= rtol and env_diff <= atol_envelope
    return VerifyReport(ok, max_rel, env_diff, messages)
