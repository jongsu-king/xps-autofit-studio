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
    # ad-hoc region (used when no recipe is given)
    p.add_argument(
        "--range", nargs=2, type=float, metavar=("LO", "HI"), help="binding-energy window (eV)"
    )
    p.add_argument(
        "--background", choices=["none", "linear", "shirley", "tougaard", "auto"], default="shirley"
    )
    p.add_argument(
        "--no-refine-background",
        action="store_true",
        help="do not add a free linear background term",
    )
    p.add_argument(
        "--shape",
        choices=["gaussian", "lorentzian", "voigt", "pseudo_voigt", "auto"],
        default="voigt",
    )
    p.add_argument(
        "--optimizer",
        choices=["leastsq", "global"],
        default="leastsq",
        help="global: differential evolution before Levenberg-Marquardt (slower, robust)",
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
    p.add_argument("--energy-col", default=None, help="text files: energy column name or index")
    p.add_argument(
        "--intensity-col", default=None, help="text files: intensity column name or index"
    )
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
        background=BackgroundSpec(type=args.background),
        refine_background=not args.no_refine_background,
        shape=args.shape,
        optimizer=args.optimizer,
        constraints=PeakConstraints(**c_kwargs),  # type: ignore[arg-type]
        doublet=doublet,
        min_components=args.min_components,
        max_components=args.max_components,
        rsf=args.rsf,
    )
    return Recipe(name="adhoc", description="command-line region", regions=[region])


def _options(args: argparse.Namespace) -> RunOptions:
    reader_kwargs: dict[str, object] = {}
    for key in ("energy_col", "intensity_col"):
        v = getattr(args, key)
        if v is not None:
            reader_kwargs[key] = int(v) if str(v).isdigit() else v
    if args.intensity_unit:
        reader_kwargs["intensity_unit"] = args.intensity_unit
    if args.photon_energy:
        reader_kwargs["photon_energy"] = args.photon_energy
    return RunOptions(
        output_dir=Path(args.output),
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
                res = r.selection.best.result
                st = res.stats
                print(
                    f"      reduced chi-sq {st.redchi:.3g}  AICc {st.aicc:.1f}  "
                    f"weighted={st.weighted}"
                )
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
                rsf = f"{e.rsf:7.3f}" if e.rsf is not None else "      -"
                print(f"      {e.label:<12} area {e.area:12.1f}  RSF {rsf}  {pct}")
    if batch.summary_paths:
        print("\nsummary:")
        for name, path in batch.summary_paths.items():
            print(f"  {name}: {path}")


def cmd_info(args: argparse.Namespace) -> int:
    for f in args.files:
        try:
            spectra = read_spectra(f, photon_energy=args.photon_energy)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "info":
        return cmd_info(args)
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
