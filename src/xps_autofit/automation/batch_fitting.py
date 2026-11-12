"""Apply one recipe to one or many files and write every output.

:func:`fit_file` is the single-file worker; :func:`run_batch` calls it for each file
and adds cross-sample summary tables.  Because every random choice is seeded from the
data and the region name, batch and single runs give identical numbers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..core.preprocessing import C1S_REFERENCE_WARNING, charge_correct, smooth_for_detection
from ..core.quantification import (
    QuantResult,
    atomic_percent,
    atomic_percent_samples,
    auger_parameter,
)
from ..core.region import RegionSpec
from ..core.spectrum import AL_KALPHA_EV, Spectrum
from ..core.uncertainty import bootstrap
from ..database.binding_energies import suggest_assignments
from ..database.rsf_library import RsfLibrary, load_rsf_library, resolve_rsf
from ..export.origin import write_origin_csv
from ..export.plots import plot_candidates, plot_fit, plot_series
from ..export.project import project_dict, save_project
from ..export.tables import candidates_table, components_table, fit_table, write_xlsx
from ..readers import read_spectra
from ..recipes import Recipe
from .model_selection import SelectionResult, select_model
from .series import composition_series, series_origin_columns


@dataclass
class RunOptions:
    output_dir: Path
    formats: tuple[str, ...] = ("csv", "json", "png")
    charge_correct: bool = True
    seed: int | None = None
    n_starts: int | None = None
    criterion: str | None = None
    photon_energy: float | None = None
    region_filter: list[str] | None = None
    fixed_n: int | None = None
    bootstrap: int = 0
    plot_dpi: int = 200
    figure_style: str = "origin"
    """``"origin"`` (publication look) or ``"classic"`` for the PNG/SVG/PDF figures."""
    reader_kwargs: dict[str, Any] = field(default_factory=dict)
    rsf_library: RsfLibrary | None = None
    """Instrument RSF library; its factors replace the recipe's where it has the line
    (overrides the recipe's own ``rsf_library``)."""


@dataclass
class RegionReport:
    file: str
    sample: str
    region: str
    status: str
    n_components: int | None = None
    selection: SelectionResult | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    auger: dict[str, Any] | None = None
    vbm: dict[str, Any] | None = None
    """``report: vbm`` regions: :meth:`VBEdge.to_dict` of the valence-band edge."""
    assignments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    def component_rows(self) -> list[dict[str, Any]]:
        if self.selection is None or self.selection.best is None:
            return []
        rows = []
        for c in self.selection.best.result.components:
            rows.append(
                {
                    "file": self.file,
                    "sample": self.sample,
                    "region": self.region,
                    "status": self.status,
                    "n_components": self.n_components,
                    "label": c.label,
                    "is_minor": c.is_minor,
                    "center_eV": c.center,
                    "center_err": c.center_err,
                    "fwhm_eV": c.fwhm,
                    "fwhm_err": c.fwhm_err,
                    "area": c.area,
                    "area_err": c.area_err,
                    "fraction_pct": c.fraction,
                    "component_fraction_pct": c.component_fraction,
                    "assignment_candidates": "; ".join(
                        a["species"] for a in self.assignments.get(c.label, [])[:3]
                    ),
                }
            )
        return rows


@dataclass
class FileReport:
    path: str
    sample: str
    n_spectra: int
    regions: list[RegionReport] = field(default_factory=list)
    charge_shift_eV: float | None = None
    quantification: QuantResult | None = None
    messages: list[str] = field(default_factory=list)
    report_pdf: str | None = None
    """PDF report of the file (``formats`` with ``report``)."""


@dataclass
class BatchReport:
    files: list[FileReport]
    summary_paths: dict[str, str] = field(default_factory=dict)

    @property
    def n_ok(self) -> int:
        return sum(1 for f in self.files for r in f.regions if r.status in ("ok", "reported"))


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s or "region"


def match_regions(
    spectra: list[Spectrum], recipe: Recipe, region_filter: list[str] | None = None
) -> list[tuple[Spectrum, RegionSpec]]:
    """Pair each recipe region with the spectrum that covers it (>= 60 % overlap).

    Metadata ``species``/``transition`` (from VAMAS) take precedence when present.
    """
    pairs: list[tuple[Spectrum, RegionSpec]] = []
    wanted = [
        r
        for r in recipe.regions
        if not region_filter or r.name.lower() in {f.lower() for f in region_filter}
    ]
    for region in wanted:
        best: Spectrum | None = None
        best_overlap = 0.0
        for s in spectra:
            if region.element and s.metadata.get("species") and s.metadata.get("transition"):
                label = f"{s.metadata['species']} {s.metadata['transition']}".lower()
                if (
                    label == f"{region.element} {region.line}".lower()
                    or label == region.name.lower()
                ):
                    best, best_overlap = s, 1.0
                    break
            if region.range is None:
                best, best_overlap = s, 1.0
                break
            lo, hi = region.range
            overlap = max(0.0, min(hi, s.energy[-1]) - max(lo, s.energy[0])) / (hi - lo)
            if overlap > best_overlap:
                best, best_overlap = s, overlap
        if best is not None and best_overlap >= 0.6:
            pairs.append((best, region))
    return pairs


def _photon_energy(spectrum: Spectrum, recipe: Recipe, options: RunOptions) -> float:
    return float(
        options.photon_energy or spectrum.photon_energy or recipe.photon_energy or AL_KALPHA_EV
    )


def _auger_report(spectrum: Spectrum, region: RegionSpec, hv: float) -> dict[str, Any]:
    spec = spectrum.crop(*region.range) if region.range else spectrum
    xu, ys = smooth_for_detection(spec.energy, spec.intensity, 1.5)
    i = int(np.argmax(ys))
    be = float(xu[i])
    return {
        "region": region.name,
        "max_binding_energy_eV": be,
        "max_kinetic_energy_eV": hv - be,
        "photon_energy_eV": hv,
        "method": "smoothed maximum (Savitzky-Golay, ~0.9 eV window)",
    }


def _vbm_report(
    path: Path, sample: str, spectrum: Spectrum, region: RegionSpec, options: RunOptions
) -> RegionReport:
    """The valence-band maximum of a ``report: vbm`` region, with a figure in the
    requested image formats (``<file>__<region>_vbm.png``)."""
    from .valence_band import VBEdgeError, find_vb_edge

    rr = RegionReport(str(path), sample, region.name, "reported")
    try:
        edge = find_vb_edge(spectrum, energy_range=region.range, edge_window=region.vbm_edge_window)
    except (VBEdgeError, ValueError) as exc:
        rr.status = "failed"
        rr.messages.append(f"no valence-band edge: {exc}")
        return rr
    rr.vbm = edge.to_dict()
    rr.messages.extend(edge.notes)
    if region.notes.strip():
        rr.messages.append(region.notes.strip())
    out = Path(options.output_dir)
    for fmt in ("png", "svg", "pdf"):
        if fmt in options.formats:
            from ..export.plots import plot_vb_edge

            out.mkdir(parents=True, exist_ok=True)
            target = out / f"{path.stem}__{slug(region.name)}_vbm.{fmt}"
            plot_vb_edge(
                spectrum.crop(*region.range) if region.range else spectrum,
                edge,
                target,
                title=f"{sample} - {region.name}",
                style=options.figure_style,
            )
            rr.outputs[fmt] = str(target)
    return rr


def _pick_reference_component(selection: SelectionResult, component: str | None) -> Any:
    best = selection.best
    if best is None:
        return None
    majors = best.result.majors()
    if component:
        for c in majors:
            if c.label.lower() == component.lower():
                return c
    return max(majors, key=lambda c: c.area) if majors else None


def fit_file(path: str | Path, recipe: Recipe, options: RunOptions) -> FileReport:
    path = Path(path)
    out = Path(options.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    spectra = read_spectra(path, **options.reader_kwargs)
    sample = spectra[0].metadata.get("sample") or path.stem
    report = FileReport(str(path), str(sample), len(spectra))
    pairs = match_regions(spectra, recipe, options.region_filter)
    if not pairs:
        report.messages.append("no recipe region matches the energy ranges in this file")
        return report

    # ---- charge correction -------------------------------------------------------
    shift: float | None = None
    if options.charge_correct and recipe.charge_reference is not None:
        ref = recipe.charge_reference
        ref_pair = next(((s, r) for s, r in pairs if r.name.lower() == ref.region.lower()), None)
        if ref_pair is None:
            report.messages.append(
                f"charge reference region {ref.region!r} not present; no correction applied"
            )
        else:
            sel = select_model(
                ref_pair[0],
                ref_pair[1],
                n_starts=options.n_starts,
                criterion=options.criterion,
                seed=options.seed,
            )
            comp = _pick_reference_component(sel, ref.component)
            if comp is None:
                report.messages.append("charge reference fit failed; no correction applied")
            else:
                shift = float(ref.value - comp.center)
                corrected = []
                for s in spectra:
                    s2, record = charge_correct(
                        s, comp.center, ref.value, f"{ref.region} {comp.label}"
                    )
                    corrected.append(s2)
                spectra = corrected
                pairs = match_regions(spectra, recipe, options.region_filter)
                report.charge_shift_eV = shift
                report.messages.append(
                    f"charge correction {shift:+.3f} eV using {ref.region} {comp.label}"
                )
                report.messages.append(C1S_REFERENCE_WARNING)

    # ---- regions --------------------------------------------------------------------
    quant_items: list[tuple[str, str | None, str | None, float, float | None]] = []
    rsf_sources: dict[str, str] = {}
    library = options.rsf_library
    if library is None and recipe.rsf_library:
        library = load_rsf_library(recipe.rsf_library)
    quant_samples: dict[str, np.ndarray] = {}
    photo_lines: dict[str, float] = {}
    auger_regions: list[tuple[Spectrum, RegionSpec]] = []
    for spectrum, region in pairs:
        if not region.fit:
            auger_regions.append((spectrum, region))
            continue
        rr = RegionReport(str(path), str(sample), region.name, "failed")
        try:
            sel = select_model(
                spectrum,
                region,
                n_starts=options.n_starts,
                criterion=options.criterion,
                seed=options.seed,
                fixed_n=options.fixed_n,
            )
        except Exception as exc:  # keep the batch going; record the failure
            rr.messages.append(f"error: {exc}")
            report.regions.append(rr)
            continue
        rr.selection = sel
        rr.status = sel.status
        rr.messages.extend(sel.notes)
        if sel.best is not None:
            best = sel.best
            rr.n_components = best.n_components
            for c in best.result.majors():
                rr.assignments[c.label] = suggest_assignments(region.element, region.line, c.center)
            main = max(best.result.majors(), key=lambda c: c.area)
            photo_lines[region.name] = main.center
            area = (
                best.result.total_area
                if region.rsf_applies_to == "total"
                else sum(c.area for c in best.result.majors())
            )
            rsf, rsf_source = resolve_rsf(region.element, region.line, region.rsf, library)
            rsf_sources[region.name] = rsf_source
            quant_items.append((region.name, region.element, region.line, area, rsf))
            extra: dict[str, Any] = {"assignments": rr.assignments, "charge_shift_eV": shift}
            if options.bootstrap > 0:
                boot = bootstrap(sel.spectrum, best.result, n=options.bootstrap, seed=sel.seed)
                extra["bootstrap"] = boot.to_dict()
                quant_samples[region.name] = (
                    boot.total_area_samples
                    if region.rsf_applies_to == "total"
                    else boot.major_area_samples
                )
            rr.outputs = write_region_outputs(path, spectrum, sel, options, extra)
        report.regions.append(rr)

    # ---- Auger parameter -------------------------------------------------------------
    for spectrum, region in auger_regions:
        if region.report == "vbm":
            report.regions.append(_vbm_report(path, str(sample), spectrum, region, options))
            continue
        rr = RegionReport(str(path), str(sample), region.name, "reported")
        hv = _photon_energy(spectrum, recipe, options)
        info = _auger_report(spectrum, region, hv)
        if region.auger_pair and region.auger_pair in photo_lines:
            be = photo_lines[region.auger_pair]
            info["paired_photoelectron_region"] = region.auger_pair
            info["paired_binding_energy_eV"] = be
            info["modified_auger_parameter_eV"] = auger_parameter(be, info["max_kinetic_energy_eV"])
        rr.auger = info
        rr.messages.append(region.notes.strip())
        report.regions.append(rr)

    if quant_items:
        hv = _photon_energy(spectra[0], recipe, options)
        kinetic = {name: hv - be for name, be in photo_lines.items()}
        report.quantification = atomic_percent(quant_items, recipe.quantification, kinetic)
        for e in report.quantification.entries:
            e.rsf_source = rsf_sources.get(e.label, "")
        if library is not None:
            report.quantification.note += f"; {library.describe()}"
        if quant_samples:
            atomic_percent_samples(report.quantification, quant_samples)
    if "report" in options.formats:
        report.report_pdf = str(_write_file_report(path, report, recipe, options))
    return report


def _write_file_report(path: Path, report: FileReport, recipe: Recipe, options: RunOptions) -> Path:
    from ..export.report import ReportRegion, write_report

    regions = []
    for rr in report.regions:
        sel = rr.selection
        if sel is None or sel.best is None:
            continue
        best = sel.best
        regions.append(
            ReportRegion(
                name=rr.region,
                result=best.result,
                status=rr.status,
                variant=best.variant,
                grade=best.grade.letter if best.grade else None,
                spectrum_name=sel.spectrum.name,
                notes=list(sel.notes),
                assignments={
                    label: f"{found[0]['species']} ({found[0]['energy']:.1f})"
                    for label, found in rr.assignments.items()
                    if found
                },
            )
        )
    out = Path(options.output_dir) / f"{path.stem}_report.pdf"
    return write_report(
        out,
        regions,
        report.quantification,
        sample=report.sample,
        source=str(path),
        recipe=recipe.name,
        style=options.figure_style,
    )


def write_region_outputs(
    path: Path, spectrum: Spectrum, sel: SelectionResult, options: RunOptions, extra: dict[str, Any]
) -> dict[str, str]:
    out = Path(options.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"{path.stem}__{slug(sel.region.name)}"
    outputs: dict[str, str] = {}
    best = sel.best
    if best is None:
        return outputs
    result = best.result
    fmts = set(options.formats)
    if "json" in fmts:
        source = {
            "path": str(path),
            "spectrum_name": spectrum.name,
            "sha256_region": sel.spectrum.sha256(),
        }
        p = save_project(base.with_suffix(".json"), project_dict(sel, source, spectrum, extra))
        outputs["json"] = str(p)
    comps = components_table(result)
    if "csv" in fmts:
        comps.to_csv(base.parent / f"{base.name}_components.csv", index=False)
        fit_table(result).to_csv(base.parent / f"{base.name}_fit.csv", index=False)
        candidates_table(sel).to_csv(base.parent / f"{base.name}_models.csv", index=False)
        outputs["csv"] = str(base.parent / f"{base.name}_components.csv")
    if "xlsx" in fmts:
        settings_rows = pd.DataFrame(
            [{"key": k, "value": str(v)} for k, v in _flatten(sel.region.to_dict()).items()]
            + [{"key": f"stats.{k}", "value": v} for k, v in result.stats.to_dict().items()]
        )
        p = write_xlsx(
            base.with_suffix(".xlsx"),
            {
                "components": comps,
                "fit": fit_table(result),
                "models": candidates_table(sel),
                "settings": settings_rows,
            },
        )
        outputs["xlsx"] = str(p)
    if "origin" in fmts:
        from ..export.origin import write_fit_for_origin

        written = write_fit_for_origin(base, result)
        outputs["origin"] = str(written["curves"])
        outputs["origin_components"] = str(written["components"])
    title = f"{spectrum.name} - {sel.region.name} (n={best.n_components}, {sel.status})"
    for fmt in ("png", "svg", "pdf"):
        if fmt in fmts:
            p = base.with_suffix(f".{fmt}")
            plot_fit(result, p, title=title, dpi=options.plot_dpi, style=options.figure_style)
            outputs[fmt] = str(p)
            if fmt == "png" and len(sel.candidates) > 1:
                plot_candidates(
                    sel, base.parent / f"{base.name}_models.png", style=options.figure_style
                )
    return outputs


_write_region_outputs = write_region_outputs  # backwards-compatible alias


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def expand_paths(paths: Sequence[str | Path]) -> list[Path]:
    from ..readers import supported_extensions

    exts = set(supported_extensions())
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(q for q in p.iterdir() if q.suffix.lower() in exts))
        elif p.is_file():
            files.append(p)
    return files


def run_batch(paths: Sequence[str | Path], recipe: Recipe, options: RunOptions) -> BatchReport:
    files = expand_paths(paths)
    reports = [fit_file(p, recipe, options) for p in files]
    batch = BatchReport(reports)
    batch.summary_paths = write_summary(batch, options)
    return batch


def write_summary(batch: BatchReport, options: RunOptions) -> dict[str, str]:
    out = Path(options.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    comp_rows: list[dict[str, Any]] = []
    region_rows: list[dict[str, Any]] = []
    quant_rows: list[dict[str, Any]] = []
    for f in batch.files:
        for r in f.regions:
            comp_rows.extend(r.component_rows())
            row: dict[str, Any] = {
                "file": f.path,
                "sample": f.sample,
                "region": r.region,
                "status": r.status,
                "n_components": r.n_components,
                "charge_shift_eV": f.charge_shift_eV,
            }
            if r.selection is not None and r.selection.best is not None:
                best = r.selection.best
                s = best.result.stats
                row.update(redchi=s.redchi, aicc=s.aicc, bic=s.bic, weighted=s.weighted)
                row["durbin_watson"] = s.durbin_watson
                row["max_correlation"] = s.max_correlation
                row["n_masked"] = s.n_masked
                row["grade"] = best.grade.letter if best.grade else None
                row["quality_score"] = best.grade.score if best.grade else None
                row["background"] = best.variant
                row["violations"] = "; ".join(v.message for v in r.selection.best.violations)
                row["warnings"] = "; ".join(v.message for v in r.selection.best.warnings)
            if r.auger:
                row.update({f"auger_{k}": v for k, v in r.auger.items() if k != "region"})
            if r.vbm:
                row.update(
                    vbm_eV=r.vbm["vbm_eV"],
                    vbm_err=r.vbm["vbm_err"],
                    vbm_window_spread_eV=r.vbm["window_spread_eV"],
                    vbm_band_maximum_eV=r.vbm["band_maximum_eV"],
                    vbm_edge_eV=" - ".join(f"{e:.2f}" for e in r.vbm["edge"]["range_eV"]),
                )
            row["messages"] = " | ".join(m for m in r.messages if m)
            region_rows.append(row)
        if f.quantification is not None:
            for e in f.quantification.entries:
                quant_rows.append(
                    {
                        "file": f.path,
                        "sample": f.sample,
                        "status": f.quantification.status,
                        "region": e.label,
                        "element": e.element,
                        "line": e.line,
                        "area": e.area,
                        "rsf": e.rsf,
                        "rsf_source": e.rsf_source,
                        "atomic_percent": e.atomic_percent,
                        "atomic_percent_std": e.atomic_percent_std,
                        "atomic_percent_p2_5": e.atomic_percent_p2_5,
                        "atomic_percent_p97_5": e.atomic_percent_p97_5,
                        "note": f.quantification.note,
                    }
                )
    tables = {
        "summary_regions": pd.DataFrame(region_rows),
        "summary_components": pd.DataFrame(comp_rows),
        "summary_quantification": pd.DataFrame(quant_rows),
    }
    paths: dict[str, str] = {}
    fmts = set(options.formats)
    # Composition series (depth profile / sample series) when several files have one
    series_items = [(Path(f.path).stem, f.quantification) for f in batch.files]
    if sum(1 for _s, q in series_items if q is not None and q.status == "OK") >= 2:
        series = composition_series(series_items)
        tables["summary_series"] = series
        if "origin" in fmts:
            p = write_origin_csv(out / "summary_series_origin.csv", series_origin_columns(series))
            paths["summary_series_origin"] = str(p)
        for fmt in ("png", "svg", "pdf"):
            if fmt in fmts:
                p = out / f"composition_series.{fmt}"
                plot_series(series, p, dpi=options.plot_dpi, style=options.figure_style)
                paths[f"composition_series_{fmt}"] = str(p)
    if "csv" in fmts or not fmts & {"xlsx"}:
        for name, df in tables.items():
            p = out / f"{name}.csv"
            df.to_csv(p, index=False)
            paths[name] = str(p)
    if "xlsx" in fmts:
        p = write_xlsx(out / "summary.xlsx", tables)
        paths["summary_xlsx"] = str(p)
    return paths
