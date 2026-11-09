"""Session files of the desktop application (``.xpsession``, JSON).

A session file records what is open and what has been fitted: the spectrum files
with each spectrum's title and charge shift, the recipe in use, and for every fitted
spectrum a project dictionary (the same content as an exported project file: the
fitted data, settings, start values and parameters).  Restoring re-reads the
spectrum files, re-applies titles and shifts, and rebuilds each result by re-running
the stored fit from its stored start, which reproduces the parameters without a new
model selection.  The candidate-model table and bootstrap replicates are not stored;
AUTO FIT and UNCERTAINTY recreate them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..automation.model_selection import Candidate, SelectionResult
from ..core.preprocessing import estimate_noise
from ..core.region import RegionSpec
from ..export.project import load_project, project_dict, refit_from_project, save_project
from .session import Session

SESSION_FORMAT = 1
SESSION_SUFFIX = ".xpsession"


def spectrum_shift(history: list[dict[str, Any]]) -> float:
    """Total energy shift recorded in a spectrum's history (charge corrections)."""
    return float(sum(float(h.get("delta_eV", 0.0)) for h in history if h.get("step") == "shift"))


def session_dict(session: Session) -> dict[str, Any]:
    """Everything needed to restore ``session`` later."""
    spectra: list[dict[str, Any]] = []
    for key in session.order:
        item = session.items[key]
        spec = item.spectrum
        entry: dict[str, Any] = {
            "path": str(item.path),
            "index": item.index,
            "name": spec.name,
            "shift_eV": spectrum_shift(spec.history),
        }
        st = session.results.get(key)
        if st is not None and st.result is not None:
            sel = st.as_selection()
            if sel is not None:
                entry["result"] = {
                    "status": st.status,
                    "notes": list(st.notes),
                    "manual": st.manual is not None,
                    "project": project_dict(
                        sel, {"path": str(item.path), "spectrum_name": spec.name}, spec
                    ),
                }
        spectra.append(entry)
    recipe = session.recipe
    return {
        "format": SESSION_FORMAT,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "xps_autofit": __version__,
        "recipe": {"name": recipe.name, "source": recipe.source} if recipe else None,
        "spectra": spectra,
    }


def save_session(path: str | Path, session: Session) -> Path:
    p = Path(path)
    if p.suffix.lower() != SESSION_SUFFIX:
        p = p.with_suffix(p.suffix + SESSION_SUFFIX) if p.suffix else p.with_suffix(SESSION_SUFFIX)
    return save_project(p, session_dict(session))


@dataclass
class RestoreReport:
    keys: list[str] = field(default_factory=list)
    """Spectra present after the restore, in file order."""
    restored: list[str] = field(default_factory=list)
    """Spectra whose fit was rebuilt."""
    recipe: dict[str, Any] | None = None
    messages: list[str] = field(default_factory=list)


def _selection_from_project(
    project: dict[str, Any], status: str, notes: list[str]
) -> SelectionResult:
    spectrum, fit = refit_from_project(project)
    sel_d = project["selection"]
    region = RegionSpec.from_dict(sel_d["region"])
    criterion = region.criterion
    cand = Candidate(
        n_components=len(fit.majors()),
        result=fit,
        violations=[],
        warnings=[],
        criterion=criterion,
        criterion_value=float(getattr(fit.stats, criterion)),
        background_type=fit.background.spec.type,
        shape=fit.settings.shape,
        background_mode=str(fit.background.info.get("mode", "static")),
    )
    return SelectionResult(
        region=region,
        spectrum=spectrum,
        background=fit.background,
        noise=estimate_noise(spectrum.energy, spectrum.intensity),
        detected=[],
        candidates=[cand],
        best=cand,
        status=status,
        seed=int(sel_d.get("seed", 0)),
        notes=list(notes) + ["restored from a session file (candidate models not stored)"],
    )


def restore_session(
    path: str | Path, session: Session, log: Callable[[str], None] | None = None
) -> RestoreReport:
    """Load the files of a session into ``session`` and rebuild its fits.

    Files that are already open keep their place; missing files and spectra are
    reported, not fatal.
    """
    data = load_project(path)
    report = RestoreReport(recipe=data.get("recipe"))
    if int(data.get("format", 0)) != SESSION_FORMAT:
        raise ValueError(f"{Path(path).name}: not a session file (format {data.get('format')!r})")
    entries = list(data.get("spectra", []))
    for file_path in dict.fromkeys(e["path"] for e in entries):
        if not Path(file_path).is_file():
            report.messages.append(f"missing file: {file_path}")
            continue
        wanted = [e for e in entries if e["path"] == file_path]
        if any(f"{file_path}#{e['index']}" not in session.items for e in wanted):
            session.load_paths([file_path])
    for e in entries:
        key = f"{e['path']}#{e['index']}"
        item = session.items.get(key)
        if item is None:
            if Path(e["path"]).is_file():
                report.messages.append(f"spectrum {e['index'] + 1} not found in {e['path']}")
            continue
        report.keys.append(key)
        name = e.get("name") or ""
        if name and item.spectrum.name != name:
            session.rename_spectrum(key, name)
        wanted_shift = float(e.get("shift_eV", 0.0))
        have_shift = spectrum_shift(item.spectrum.history)
        if abs(wanted_shift - have_shift) > 1e-9:
            item.spectrum = item.spectrum.shift(wanted_shift - have_shift, "session restore")
        result = e.get("result")
        if not result:
            continue
        try:
            selection = _selection_from_project(
                result["project"], str(result.get("status", "ok")), list(result.get("notes", []))
            )
        except Exception as exc:  # a corrupt entry must not lose the others
            report.messages.append(f"{item.display_name}: fit not restored ({exc})")
            continue
        session.set_selection(key, selection)
        st = session.state(key)
        st.status = str(result.get("status", selection.status))
        report.restored.append(key)
    if log is not None:
        for m in report.messages:
            log(m)
    session.spectraChanged.emit()
    return report
