# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-08

Phase 3 (part): stronger fitting algorithm, richer desktop application, installers.

### Added - algorithm
- **Active backgrounds** (`background: {type: shirley | tougaard, mode: active}`,
  `--background-mode`, GUI *Mode*): the Shirley running integral or the Tougaard
  loss integral is taken of the *fitted peak envelope* inside the fit, with a free
  offset and scattering factor (`bg_offset`, `bg_scatter`). Endpoint noise and
  peak tails no longer bias the background; `mode: auto` tries static and active
  and chooses with the criterion. Candidate tables, project files and the summary
  carry the variant (`shirley(active)/voigt`).
- **Doniach-Sunjic line** (`shape: doniach_sunjic`): asymmetric metallic line
  (asymmetry `asym`, tail towards high binding energy) convolved numerically with
  a Gaussian; area defined within +/- 10 widths of the centre; `asym` bounds and
  `share_asym` in the constraints; reported with its standard error in every
  table. Not part of `shape: auto`.
- **Residual diagnostics** in every fit: Durbin-Watson statistic, runs-test z and
  lag-1 autocorrelation of the weighted residual (`stats.durbin_watson`, ...).
  A structured residual (DW below `residual_dw_warning`, default 1.0) is a
  warning; inside the parsimony margin a model with a white residual replaces one
  with a structured residual, and a structured close model does not make the
  result ambiguous.
- **Shoulder detection**: dips of the Savitzky-Golay second derivative with a
  prominence above 8 times the derivative noise (local Poisson noise included)
  add starting guesses for unresolved states on the flank of a stronger line.
- **Noise estimate corrected** for the part of the noise the smoother absorbs
  (`sqrt(1 - c0)`); without the correction it was 10-30 % low. Short series fall
  back to the median absolute first difference.
- **Bootstrap to composition**: replicates keep every component's area, line
  fraction and component fraction; in recipe runs the region replicates are
  propagated to `atomic_percent_std` and the 2.5 / 97.5 percentiles in
  `summary_quantification.csv`. Bootstrap replicates always use the local
  optimiser and the fitted background as start.

### Added - desktop application
- Diagnostics tab: monospace readout of statistics, residual diagnostics,
  background parameters, per-component values, warnings, notes and bootstrap.
- UNCERTAINTY action (F7): bootstrap of the displayed fit into the Diagnostics tab.
- Models tab shows the variant and the Durbin-Watson value per candidate; clicking
  a row shows that candidate (by row, so variants of equal `n` are distinct).
- Background *Mode* and the Doniach-Sunjic asymmetry bound in the settings panel;
  `Asym` column in the component table.
- Drag-and-drop of files and folders, Recent-files menu, Remove spectrum (Delete),
  Reset view (Home), Save plot image (Ctrl+Shift+S), Copy table (Ctrl+C in a table
  or Ctrl+Shift+C) as tab-separated text, cursor readout of energy and intensity
  with a hairline in both panels.
- Screenshots in `docs/images`, generated offscreen by `examples/make_screenshots.py`.

### Changed
- `RegionSpec.variants()` returns `Variant` objects (still unpack as
  `(background_type, shape)`); `fit_settings()` takes `background_mode`.
- `build_parameters()` takes the data and background when the background is
  active; `evaluate_total()` is kept for the static case.
- `PeakGuess` has a `kind` (`maximum` / `shoulder`).

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
