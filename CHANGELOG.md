# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Text reader: a numeric block without its own header no longer inherits the header of the previous block (which could mislabel its axis as kinetic or its unit as cps).

### Packaging
- Installers for every release, built and checked by the `Installers` workflow:
  Windows x64 setup program (Inno Setup; optional PATH entry for the command-line
  tool) and zip, macOS Apple-Silicon DMG, Debian/Ubuntu `.deb` and portable
  tar.gz, with `SHA256SUMS.txt`. One PyInstaller folder holds both the desktop
  application and `xps-autofit`; the launchers keep Matplotlib's font cache in a
  per-user cache folder. Builds are not code-signed.

## [0.2.0] - 2026-11-06

Phase 2: desktop application; stronger automatic fitting.

### Added
- `optimizer: global` (recipe, `--optimizer global`, GUI): seeded differential
  evolution inside the parameter bounds before the Levenberg-Marquardt polish.
- `background: {type: auto}` and `shape: auto`: every background (Shirley,
  Tougaard, linear) and shape (Voigt, pseudo-Voigt) combination is fitted and chosen
  with the same criterion and physical checks as the component count; candidate
  tables and project files record the variant.
- `xps-autofit gui` (extra `gui`: PySide6, PyQtGraph): instrument-style window with
  sample tree, live spectrum (raw, background, components, envelope, residual with
  ±1σ band), fit-settings panel that mirrors the recipe schema, component and
  candidate-model tables, log and status lamp.
- Interactive refit: draggable centre lines, editable centre / width cells, add a
  component at the largest residual, remove the selected one. Manual results are
  exported with the automatic candidates kept for comparison.
- Export and batch dialogs that call the same functions as the command line.
- Background jobs on a QThread with explicit clean-up order (no worker deletion from
  the worker thread).
- `write_region_outputs` is now public; it creates the output folder itself.
- Offscreen GUI tests (`tests/test_gui.py`), skipped when PySide6 is absent.

## [0.1.0] - 2026-11-06

Phase 1: fitting core and command-line tool.

### Added
- `Spectrum` container with axis normalisation (ascending binding energy, merged
  duplicates, kinetic-to-binding conversion) and a processing history.
- Readers for delimited text (CSV/TSV/TXT/DAT/XY/ASC; header detection, decimal
  commas, multi-block exports, kinetic-energy columns) and ISO 14976 VAMAS files,
  plus a VAMAS writer for fixtures and interchange.
- Linear, iterative Shirley and two-parameter universal Tougaard backgrounds.
- Area-normalised Gaussian, Lorentzian, Voigt (exact) and pseudo-Voigt shapes.
- lmfit-based fitting with spin-orbit doublet constraints (splitting, area ratio,
  shared widths), width bounds, shared Lorentzian width, candidate windows for
  chemical states and an optional linear background refinement (on by default in
  automatic fits; it absorbs endpoint bias from peak tails and noise).
- Automatic model selection: multi-start fits for each component count, AICc/BIC
  compared only among models that pass physical checks (significant area, height
  above local noise, centre inside region, minimum separation); a parsimony margin;
  statuses `ok`, `ambiguous`, `needs_review`, `failed`.
- Peak detection with doublet pairing and residual-guided component addition.
- Quantification from RSFs with `NOT_CALCULABLE` when a factor is missing; modified
  Auger parameter for Cu LMM; literature candidate assignments.
- Reference tables: binding-energy ranges, spin-orbit splittings and ratios,
  Scofield cross-sections for common lines.
- Recipes (`p3ht`, `cu2o`, `cbo`, `sam_2pacz`) and a YAML loader; charge
  referencing with an explicit warning about the C 1s convention.
- Batch processing with per-file and cross-sample summaries; identical results for
  batch and single runs by construction (seeds derived from data and region).
- Exports: CSV, XLSX, JSON project files (data, settings, starts, parameters,
  versions), PNG/SVG/PDF figures, model-comparison plots; `verify` command that
  re-runs a project and compares.
- Bootstrap uncertainties (Poisson or residual resampling).
- Synthetic data generator with known truth and a test suite covering shape
  normalisation, background recovery, parameter recovery, doublet preservation,
  axis handling, readers, batch/single equality and project reproduction.

### Not yet
- Comparison against measured data and other fitting programs (planned for 1.0).
- Vendor binary formats; NPL format.
