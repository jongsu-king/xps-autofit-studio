"""Command-line interface.

Examples::

    xps-autofit info sample.vms
    xps-autofit fit sample.vms --recipe p3ht --output results
    xps-autofit fit s2p.csv --range 160 172 --doublet 1.18 0.5 --max-components 3
    xps-autofit batch ./spectra --recipe cu2o --output results --formats csv,xlsx,json,png
    xps-autofit synth --out examples/data
    xps-autofit verify results/sample__S_2p.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .automation.batch_fitting import BatchReport, RunOptions, run_batch
from .core.background import BackgroundSpec
from .core.constraints import DoubletSpec, PeakConstraints
from .core.preprocessing import check_axis, estimate_noise
from .core.region import RegionSpec
from .readers import read_spectra
from .recipes import Recipe, builtin_recipe_names, load_recipe


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--recipe", "-r", help="built-in recipe name or path to a YAML recipe")
    p.add_argument("--output", "-o", default="xps_autofit_results", help="output directory")
    p.add_argument(
        "--formats", default="csv,json,png", help="comma list of csv,xlsx,json,png,svg,pdf"
    )
    p.add_argument("--region", action="append", help="only these recipe regions (repeatable)")
    p.add_argument(
        "--no-charge-correction", action="store_true", help="skip the recipe's charge reference"
    )
    p.add_argument(
        "--seed", type=int, default=None, help="extra seed mixed into the deterministic starts"
    )
    p.add_argument("--n-starts", type=int, default=None, help="initial guesses per component count")
    p.add_argument("--criterion", choices=["aicc", "bic", "aic"], default=None)
    p.add_argument(
        "--fixed-n", type=int, default=None, help="fit exactly N components (skip selection)"
    )
    p.add_argument(
        "--bootstrap", type=int, default=0, help="bootstrap replicates for uncertainties (0 = off)"
    )
    p.add_argument(
        "--photon-energy", type=float, default=None, help="eV; default from file or 1486.6"
    )
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument(
        "--figure-style",
        choices=["origin", "classic"],
        default="origin",
        help="look of the PNG/SVG/PDF figures: origin (publication, default) or classic",
    )
    # ad-hoc region (used when no recipe is given)
    p.add_argument(
        "--range", nargs=2, type=float, metavar=("LO", "HI"), help="binding-energy window (eV)"
    )
    p.add_argument(
        "--background", choices=["none", "linear", "shirley", "tougaard", "auto"], default="shirley"
    )
    p.add_argument(
        "--background-mode",
        choices=["static", "active", "auto"],
        default="static",
        help="active: Shirley/Tougaard generated from the fitted peaks inside the fit",
    )
    p.add_argument(
        "--no-refine-background",
        action="store_true",
        help="do not add a free linear background term",
    )
    p.add_argument(
        "--shape",
        choices=[
            "gaussian",
            "lorentzian",
            "voigt",
            "pseudo_voigt",
            "gl_product",
            "doniach_sunjic",
            "auto",
        ],
        default="voigt",
        help="doniach_sunjic: asymmetric line for metals (Gaussian-broadened)",
    )
    p.add_argument(
        "--optimizer",
        choices=["leastsq", "global"],
        default="leastsq",
        help="global: differential evolution before Levenberg-Marquardt (slower, robust)",
    )
    p.add_argument(
        "--loss",
        choices=["linear", "soft_l1", "huber", "cauchy", "arctan"],
        default="linear",
        help="robust loss: residuals beyond --loss-scale pull less (spikes, misfit tails)",
    )
    p.add_argument(
        "--loss-scale",
        type=float,
        default=3.0,
        help="robust loss: residual size in sigma where down-weighting starts",
    )
    p.add_argument(
        "--mask-spikes",
        type=float,
        default=None,
        metavar="SIGMA",
        help="exclude isolated points more than SIGMA local std. dev. off the running median",
    )
    p.add_argument("--min-components", type=int, default=1)
    p.add_argument("--max-components", type=int, default=3)
    p.add_argument(
        "--doublet",
        nargs=2,
        type=float,
        metavar=("SPLIT", "RATIO"),
        help="spin-orbit splitting (eV) and minor/major area ratio",
    )
    p.add_argument("--fwhm-g", nargs=2, type=float, metavar=("MIN", "MAX"), default=None)
    p.add_argument("--fwhm-l", nargs=2, type=float, metavar=("MIN", "MAX"), default=None)
    p.add_argument("--min-separation", type=float, default=None)
    p.add_argument("--element", default=None)
    p.add_argument("--line", default=None)
    p.add_argument("--rsf", type=float, default=None)
    p.add_argument(
        "--energy-col", default=None, help="text/Excel files: energy column name or index"
    )
    p.add_argument(
        "--intensity-col", default=None, help="text/Excel files: intensity column name or index"
    )
    p.add_argument("--sheet", default=None, help="Excel files: worksheet title or 0-based index")
    p.add_argument("--intensity-unit", choices=["counts", "cps", "arbitrary"], default=None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xps-autofit", description="Automated, reproducible XPS peak fitting"
    )
    p.add_argument("--version", action="version", version=f"xps-autofit {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("info", help="list the spectra in files")
    pi.add_argument("files", nargs="+")
    pi.add_argument("--photon-energy", type=float, default=None)
    pi.add_argument("--sheet", default=None, help="Excel files: worksheet title or 0-based index")

    pf = sub.add_parser("fit", help="fit one or more files with a recipe or an ad-hoc region")
    pf.add_argument("files", nargs="+")
    _add_run_args(pf)

    pb = sub.add_parser("batch", help="fit every supported file in directories")
    pb.add_argument("paths", nargs="+", help="files or directories")
    _add_run_args(pb)

    pr = sub.add_parser("recipes", help="list built-in recipes")
    pr.add_argument("--show", default=None, help="print one recipe as YAML")

    ps = sub.add_parser("synth", help="write synthetic example data with known truth")
    ps.add_argument("--out", default="examples/data")
    ps.add_argument("--seed", type=int, default=1)

    pv = sub.add_parser("verify", help="re-run a saved project and compare")
    pv.add_argument("project", nargs="+")

    pid = sub.add_parser("identify", help="list the elements whose lines explain a survey")
    pid.add_argument("files", nargs="+")
    pid.add_argument(
        "--tolerance", type=float, default=1.5, help="eV between a peak and the typical position"
    )
    pid.add_argument("--min-confidence", type=float, default=0.3)
    pid.add_argument(
        "--charge-shift",
        type=float,
        default=0.0,
        help="eV by which the measured scale is displaced (measured C 1s - 284.8)",
    )
    pid.add_argument("--photon-energy", type=float, default=None)
    pid.add_argument("--elements", default=None, help="comma list restricting the search")
    pid.add_argument("--json", action="store_true", help="print the full result as JSON")

    ps = sub.add_parser(
        "suggest", help="propose a recipe (regions, doublets, RSFs) from a survey spectrum"
    )
    ps.add_argument("file", help="survey spectrum")
    ps.add_argument("--output", "-o", default=None, help="write the recipe YAML here")
    ps.add_argument("--name", default=None, help="recipe name (default: the file stem)")
    ps.add_argument(
        "--min-confidence", type=float, default=0.5, help="elements below this are left out"
    )
    ps.add_argument(
        "--half-width", type=float, default=8.0, help="eV on each side of the main line"
    )
    ps.add_argument("--max-components", type=int, default=3)
    ps.add_argument(
        "--tolerance", type=float, default=1.5, help="eV between a peak and the typical position"
    )
    ps.add_argument("--charge-shift", type=float, default=0.0)
    ps.add_argument("--photon-energy", type=float, default=None)
    ps.add_argument("--elements", default=None, help="comma list restricting the search")

    pu = sub.add_parser("update-check", help="compare this version with the latest release")
    pu.add_argument("--json", action="store_true")
    pu.add_argument("--timeout", type=float, default=6.0)

    sub.add_parser("gui", help="start the desktop application")
    return p


def _adhoc_recipe(args: argparse.Namespace) -> Recipe:
    c_kwargs: dict[str, object] = {}
    if args.fwhm_g:
        c_kwargs["fwhm_g"] = tuple(args.fwhm_g)
    if args.fwhm_l:
        c_kwargs["fwhm_l"] = tuple(args.fwhm_l)
    if args.min_separation is not None:
        c_kwargs["min_separation"] = args.min_separation
    doublet = (
        DoubletSpec(splitting=args.doublet[0], area_ratio=args.doublet[1], splitting_tolerance=0.02)
        if args.doublet
        else None
    )
    name = " ".join(t for t in (args.element, args.line) if t) or "region"
    region = RegionSpec(
        name=name,
        element=args.element,
        line=args.line,
        range=tuple(args.range) if args.range else None,
        background=BackgroundSpec(type=args.background, mode=args.background_mode),
        refine_background=not args.no_refine_background,
        shape=args.shape,
        optimizer=args.optimizer,
        loss=args.loss,
        loss_scale=args.loss_scale,
        spike_sigma=args.mask_spikes,
        constraints=PeakConstraints(**c_kwargs),  # type: ignore[arg-type]
        doublet=doublet,
        min_components=args.min_components,
        max_components=args.max_components,
        rsf=args.rsf,
    )
    return Recipe(name="adhoc", description="command-line region", regions=[region])


def _options(args: argparse.Namespace) -> RunOptions:
    reader_kwargs: dict[str, object] = {}
    for key in ("energy_col", "intensity_col", "sheet"):
        v = getattr(args, key, None)
        if v is not None:
            reader_kwargs[key] = int(v) if str(v).isdigit() else v
    if args.intensity_unit:
        reader_kwargs["intensity_unit"] = args.intensity_unit
    if args.photon_energy:
        reader_kwargs["photon_energy"] = args.photon_energy
    return RunOptions(
        output_dir=Path(args.output),
        figure_style=getattr(args, "figure_style", "origin"),
        formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
        charge_correct=not args.no_charge_correction,
        seed=args.seed,
        n_starts=args.n_starts,
        criterion=args.criterion,
        photon_energy=args.photon_energy,
        region_filter=args.region,
        fixed_n=args.fixed_n,
        bootstrap=args.bootstrap,
        plot_dpi=args.dpi,
        reader_kwargs=reader_kwargs,
    )


def _print_report(batch: BatchReport) -> None:
    for f in batch.files:
        print(f"\n{f.path}  ({f.n_spectra} spectrum/spectra)")
        for m in f.messages:
            print(f"  ! {m}")
        for r in f.regions:
            head = f"  [{r.status:>12}] {r.region}"
            if r.n_components is not None:
                head += f"  n={r.n_components}"
            print(head)
            if r.selection is not None and r.selection.best is not None:
                best = r.selection.best
                res = best.result
                st = res.stats
                dw = f"  DW {st.durbin_watson:.2f}" if st.durbin_watson is not None else ""
                g = best.grade
                grade = f"  grade {g.letter} ({g.score:.0f})" if g else ""
                print(
                    f"      reduced chi-sq {st.redchi:.3g}  AICc {st.aicc:.1f}{dw}{grade}  "
                    f"weighted={st.weighted}  model {best.variant}"
                )
                if best.grade and best.grade.reasons:
                    print("      grade: " + "; ".join(best.grade.reasons))
                for c in res.components:
                    err = f" ± {c.center_err:.3f}" if c.center_err is not None else ""
                    frac = (
                        f"{c.component_fraction:5.1f} %" if c.component_fraction is not None else ""
                    )
                    print(
                        f"      {c.label:<28} {c.center:8.3f}{err:<10} eV  "
                        f"FWHM {c.fwhm:5.2f}  area {c.area:11.1f}  {frac}"
                    )
                for v in r.selection.best.violations + r.selection.best.warnings:
                    print(f"      - {v.severity}: {v.message}")
            if r.auger:
                a = r.auger
                text = f"      {r.region} max KE {a['max_kinetic_energy_eV']:.2f} eV"
                if "modified_auger_parameter_eV" in a:
                    text += f"  alpha' = {a['modified_auger_parameter_eV']:.2f} eV"
                print(text)
            for m in r.messages:
                if m and not m.startswith("n="):
                    print(f"      note: {m[:160]}")
        if f.quantification is not None:
            q = f.quantification
            print(f"  quantification: {q.status}" + (f" ({q.note})" if q.status != "OK" else ""))
            for e in q.entries:
                pct = f"{e.atomic_percent:6.2f} at.%" if e.atomic_percent is not None else "   n/a"
                if e.atomic_percent_std is not None:
                    pct += f" ± {e.atomic_percent_std:.2f}"
                rsf = f"{e.rsf:7.3f}" if e.rsf is not None else "      -"
                print(f"      {e.label:<12} area {e.area:12.1f}  RSF {rsf}  {pct}")
    if batch.summary_paths:
        print("\nsummary:")
        for name, path in batch.summary_paths.items():
            print(f"  {name}: {path}")


def cmd_info(args: argparse.Namespace) -> int:
    kwargs: dict[str, object] = {"photon_energy": args.photon_energy}
    sheet = getattr(args, "sheet", None)
    if sheet is not None:
        kwargs["sheet"] = int(sheet) if str(sheet).isdigit() else sheet
    for f in args.files:
        try:
            spectra = read_spectra(f, **kwargs)
        except Exception as exc:
            print(f"{f}: cannot read ({exc})")
            continue
        print(f"{f}: {len(spectra)} spectrum/spectra")
        for s in spectra:
            ax = check_axis(s)
            noise = estimate_noise(s.energy, s.intensity)
            print(
                f"  {s.name!r}: {ax.n_points} pts, {ax.lo:.2f}-{ax.hi:.2f} eV, "
                f"step {ax.step_median:.3f}, unit {s.intensity_unit}, "
                f"input order {ax.input_order}, SNR ~{noise.snr:.0f}"
            )
            for issue in ax.issues:
                print(f"      ! {issue}")
            for h in s.history:
                if h.get("step") not in ("sort_ascending",):
                    print(f"      history: {h}")
    return 0


def cmd_fit(args: argparse.Namespace, paths: list[str]) -> int:
    recipe = load_recipe(args.recipe) if args.recipe else _adhoc_recipe(args)
    options = _options(args)
    batch = run_batch(paths, recipe, options)
    _print_report(batch)
    failed = sum(1 for f in batch.files for r in f.regions if r.status == "failed")
    return 1 if failed and not batch.n_ok else 0


def cmd_suggest(args: argparse.Namespace) -> int:
    import yaml

    from .automation.identify import identify_elements
    from .automation.suggest import suggest_recipe
    from .recipes import save_recipe

    spectra = read_spectra(args.file, photon_energy=args.photon_energy)
    survey = max(spectra, key=lambda s: s.range[1] - s.range[0])
    elements = [e.strip() for e in args.elements.split(",") if e.strip()] if args.elements else None
    ident = identify_elements(
        survey,
        tolerance=args.tolerance,
        min_confidence=min(args.min_confidence, 0.3),
        charge_shift=args.charge_shift,
        photon_energy=args.photon_energy,
        elements=elements,
    )
    try:
        recipe = suggest_recipe(
            ident,
            name=args.name or Path(args.file).stem,
            min_confidence=args.min_confidence,
            half_width=args.half_width,
            max_components=args.max_components,
        )
    except ValueError as exc:
        print(f"{args.file}: {exc}")
        return 1
    for r in recipe.regions:
        lo, hi = r.range if r.range else (float("nan"), float("nan"))
        doublet = f"doublet {r.doublet.splitting:.2f} eV" if r.doublet else "single"
        rsf = f"RSF {r.rsf}" if r.rsf is not None else "RSF unknown"
        print(f"  {r.name:<10} {lo:7.1f}-{hi:6.1f} eV  {doublet:<18} {rsf}")
    if recipe.charge_reference:
        cr = recipe.charge_reference
        print(f"  charge reference: {cr.region} at {cr.value} eV")
    if args.output:
        p = save_recipe(recipe, args.output)
        print(f"recipe written to {p}")
    else:
        print(yaml.safe_dump(recipe.to_dict(), sort_keys=False, allow_unicode=True))
    return 0


def cmd_recipes(args: argparse.Namespace) -> int:
    if args.show:
        import yaml

        print(yaml.safe_dump(load_recipe(args.show).to_dict(), sort_keys=False, allow_unicode=True))
        return 0
    for name in builtin_recipe_names():
        r = load_recipe(name)
        print(f"{name:<12} {r.description}")
        for reg in r.regions:
            rng = f"{reg.range[0]:.0f}-{reg.range[1]:.0f} eV" if reg.range else "any"
            kind = (
                "report"
                if not reg.fit
                else f"{reg.shape}, {reg.background.type}, n<={reg.max_components}"
            )
            print(f"    {reg.name:<10} {rng:<14} {kind}")
    return 0


def cmd_synth(args: argparse.Namespace) -> int:
    from .synthetic import example_dataset

    paths = example_dataset(args.out, seed=args.seed)
    for p in paths:
        print(p)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from .export.project import verify_project

    rc = 0
    for p in args.project:
        rep = verify_project(p)
        verdict = "OK" if rep.ok else "MISMATCH"
        print(
            f"{p}: {verdict} (max param rel diff {rep.max_param_rel_diff:.2e}, "
            f"envelope diff {rep.max_envelope_abs_diff:.2e})"
        )
        for m in rep.messages:
            print(f"    {m}")
        rc |= 0 if rep.ok else 1
    return rc


def cmd_identify(args: argparse.Namespace) -> int:
    import json

    from .automation.identify import identify_elements, nearest_lines

    elements = [e.strip() for e in args.elements.split(",") if e.strip()] if args.elements else None
    rc = 0
    for f in args.files:
        try:
            spectra = read_spectra(f, photon_energy=args.photon_energy)
        except Exception as exc:
            print(f"{f}: cannot read ({exc})")
            rc = 1
            continue
        for s in spectra:
            ident = identify_elements(
                s,
                tolerance=args.tolerance,
                min_confidence=args.min_confidence,
                charge_shift=args.charge_shift,
                photon_energy=args.photon_energy,
                elements=elements,
            )
            if args.json:
                print(json.dumps(ident.to_dict(), indent=1))
                continue
            print(
                f"{f} {s.name!r}: {len(ident.peaks)} peaks above {5:g} sigma "
                f"(noise {ident.noise_sigma:.1f}), tolerance {ident.tolerance_eV:g} eV"
            )
            if not ident.candidates:
                print("  no element identified")
            for c in ident.candidates:
                main = c.main_line
                where = f"{main.peak.energy:7.1f} eV" if main and main.peak else "       -"
                amb = f"  ambiguous with {', '.join(c.ambiguous_with)}" if c.ambiguous_with else ""
                print(
                    f"  {c.element:<3} confidence {c.confidence:4.2f}  "
                    f"{(main.label if main else ''):<9} {where}  "
                    f"lines {len(c.matched)}/{len(c.matched) + len(c.missing)}{amb}"
                )
                for m in c.matched:
                    assert m.peak is not None
                    print(
                        f"        {m.label:<10} expected {m.expected_eV:7.1f}  found "
                        f"{m.peak.energy:7.1f}  ({m.offset_eV:+.1f})  height {m.peak.height:9.0f}"
                    )
                for m in c.missing:
                    print(f"        {m.label:<10} expected {m.expected_eV:7.1f}  not found")
                if c.note:
                    print(f"        note: {c.note}")
            if ident.unassigned:
                print("  unassigned peaks:")
                for p in ident.unassigned:
                    hints = ", ".join(nearest_lines(p.energy, ident.photon_energy))
                    print(f"    {p.energy:7.1f} eV  height {p.height:9.0f}  nearest: {hints}")
            for n in ident.notes:
                print(f"  note: {n}")
    return rc


def cmd_update_check(args: argparse.Namespace) -> int:
    import json

    from .update_check import UpdateCheckError, check_for_update, describe

    try:
        info = check_for_update(timeout=args.timeout)
    except UpdateCheckError as exc:
        print(f"update check failed: {exc}")
        return 2
    if args.json:
        print(json.dumps(info.to_dict(), indent=1))
    else:
        print(describe(info))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "info":
        return cmd_info(args)
    if args.command == "suggest":
        return cmd_suggest(args)
    if args.command == "identify":
        return cmd_identify(args)
    if args.command == "update-check":
        return cmd_update_check(args)
    if args.command == "fit":
        return cmd_fit(args, args.files)
    if args.command == "batch":
        return cmd_fit(args, args.paths)
    if args.command == "recipes":
        return cmd_recipes(args)
    if args.command == "synth":
        return cmd_synth(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "gui":
        try:
            from .gui import run as run_gui
        except ImportError as exc:
            print(f"cannot start the desktop application: {exc}")
            return 2
        try:
            return int(run_gui([]))
        except SystemExit as exc:  # missing optional dependency
            print(exc)
            return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
