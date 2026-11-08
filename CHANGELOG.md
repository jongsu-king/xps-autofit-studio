# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-08

Robust fitting, a quality grade for every fit, survey element identification and
update notifications.

### Added - algorithm
- **Robust loss** (`loss: soft_l1 | huber | cauchy | arctan`, `--loss`, GUI
  *Robustness > Loss*): the fit runs through `scipy.optimize.least_squares` and
  residuals beyond `loss_scale` standard deviations (default 3) pull less, so
  cosmic-ray hits, detector spikes and misfit tails no longer drag the components.
  On a synthetic S 2p with four spikes the robust fit keeps both components within
  3 % of the truth where ordinary least squares adds a spurious third one. Standard
  errors are the linearised estimate; the result carries a warning saying so.
- **Spike mask** (`spike_sigma`, `--mask-spikes SIGMA`, GUI *Mask spikes*): points
  more than `SIGMA` local standard deviations above or below *both* neighbours (one
  or two points wide) are excluded from the fit, the background and the detection
  and listed in the warnings; the statistics count only the remaining points
  (`stats.n_masked`, `mask` in the project file). The mask is skipped with a warning
  when the step is above 0.25 eV or more than 2 % of the points would go.
- **Parameter correlations**: every fit reports the strongly correlated parameter
  pairs (`FitResult.correlations`, |r| >= 0.9) and the largest correlation between
  parameters of *different* components (`stats.max_correlation`). Above
  `correlation_warning` (default 0.98) the physical checks add a
  `degenerate_parameters` warning: the data do not determine those components
  independently. Components whose area is uncertain by more than
  `relative_error_warning` (default 50 %) get a `large_relative_error` warning.
- **Quality grade** A-E (`xps_autofit.core.quality.grade_fit`) for every candidate
  model: 100 points minus deductions for reduced chi-square, residual structure,
  violations, warnings, missing or large standard errors, degeneracy and optimiser
  failure, with every deduction listed. Shown in the CLI report, the Models tab
  (*Grade* column), the Diagnostics readout (QUALITY line), the candidate tables
  (`grade`, `quality_score`, `max_correlation`), `summary_regions.csv` and the
  project JSON. The grade is for triage of batch results, not a statistical test.
- **Survey element identification** (`xps-autofit identify`, GUI *IDENTIFY* F8):
  peaks of a survey are located above the noise and every element of the new
  `database.survey_lines` table (62 elements, 164 lines; principal photoelectron lines with
  Scofield-like relative intensities and the common Auger lines by kinetic energy)
  is scored by the share of its expected intensity found within a tolerance
  (default 1.5 eV). An element counts only when its strongest line in range is
  present; a peak claimed by several elements marks the weaker candidate as
  *ambiguous* (Bi 4f / S 2p, Au 4d / Pd 3d); coincidences of a secondary line with
  a stronger element's line are dropped. `--charge-shift` moves the expected
  positions for charging samples; `--elements` restricts the search; `--json`
  prints everything. On synthetic surveys of seven compositions every element is
  found and no false element is reported. The app marks the matched lines on the
  spectrum and lists the candidates in a table.
- `xps_autofit.synthetic.synthesize_survey()` and an example survey
  (`cu2o_survey.csv`) in `xps-autofit synth`.

### Added - desktop application and command line
- **Update notice**: at most once a day (and only when enabled) the app asks the
  GitHub Releases API for the latest version; a newer release shows as a clickable
  status-bar link to the installer for the running operating system (DMG, Setup.exe
  or .deb) or to the release page. *Help > Check for updates…* runs it on demand
  with Download / Skip this version / Later; *Help > Check for updates at startup*
  turns the automatic check off; `XPS_AUTOFIT_NO_UPDATE_CHECK=1` disables it for
  managed installations. `xps-autofit update-check [--json]` does the same on the
  command line and never runs unasked. Nothing but the version string is sent.
- *Robustness* group in the settings panel (loss, loss scale, spike mask); *Grade*
  column in the Models tab; QUALITY and PARAMETERS lines in the Diagnostics tab.
- `--loss`, `--loss-scale`, `--mask-spikes` for `fit` and `batch`; recipes accept
  `loss`, `loss_scale`, `spike_sigma` per region.

### Changed
- `FitStatistics` gained `n_masked`, `max_correlation`, `max_correlation_pair`,
  `loss`; `FitResult` gained `mask` and `correlations`; `Candidate` gained `grade`.
- `PeakConstraints` gained `correlation_warning` and `relative_error_warning`.
- Issue templates, a pull-request template and `SECURITY.md`; GitHub Discussions
  enabled for questions.

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
