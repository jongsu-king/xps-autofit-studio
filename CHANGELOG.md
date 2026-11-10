# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-11-10

Version DOI: https://doi.org/10.5281/zenodo.24096285 (concept DOI for all versions: 10.5281/zenodo.24071088).

### Added - Origin
- **Files OriginLab Origin opens as a labelled workbook** (`export/origin.py`):
  CSV with Origin's three label rows (Long Name, Units, Comments) above the data,
  the binding energy as the first (X) column. Fits give `_origin.csv` (raw,
  background, envelope, each component on the background, residual; component
  centres, widths, areas and fractions in the Comments row) and
  `_origin_components.csv` (the parameter table). `--formats origin` in `fit` and
  `batch`, *origin* in the EXPORT dialog, and **File > Export for Origin…**
  (Ctrl+Alt+E) in the app, which also writes the X/Y pairs of the comparison view
  or a bare spectrum and opens the file in Origin when the program is found
  (Windows, `Program Files\OriginLab`, or `XPS_AUTOFIT_ORIGIN`), else in the
  default program.

### Added - installers and updates
- **Automatic installation of updates** for installed copies (*Help > Install
  updates automatically*, on by default): a newer release is downloaded in the
  background, verified against the release's `SHA256SUMS.txt` and installed on exit
  or after *Restart now* (Windows setup run silently, zip folder / macOS app / Linux
  folder swapped after exit, `.deb` via `pkexec apt-get`). The update dialog offers
  *Download and install* for such copies; `xps-autofit update-check --install` does it
  from the command line. pip and source installs are never modified
  (`selfupdate.py`, shared with the other jongsu-king desktop programs).
- **macOS disk image for Intel Macs** (`…-macOS-x86_64.dmg`, built on `macos-15-intel`).
- The release notes get a generated download table (platform, size, SHA-256, how to
  install) after the installers are attached.
- The Windows installer removes the previous `_internal` folder before an upgrade.

### Added - engine and command line
- **Origin-style figures**: the PNG/SVG/PDF figures of `fit`, `batch` and the
  application's EXPORT use a publication look in the manner of OriginLab graphs
  (white canvas, black frame on all four sides, inward major and minor ticks,
  Arial-type labels, no grid, open black data symbols, red envelope, boxed
  legend), matching the application's Origin-style plot. `--figure-style classic`
  (`RunOptions.figure_style`, `plot_fit(style=)`) keeps the earlier look.
- **Recipe suggestion from a survey** (`xps-autofit suggest survey.csv -o
  recipe.yaml`, `automation.suggest.suggest_recipe`): one region per identified
  element above a confidence threshold, built from its strongest matched
  photoelectron line with a range around the measured peak, the database doublet
  for an unresolved p/d/f level (listed components such as `Cu 2p3/2` are fitted
  alone), the Scofield RSF, and C 1s at 284.8 eV as charge reference. The YAML
  loads like any recipe.

### Added - desktop application
- **Light theme** next to the dark instrument theme (*View > Theme*, remembered
  between sessions). Both themes share one stylesheet template and the figures'
  validated palette: dark-surface series colours in the dark theme, light-surface
  ones in the light theme.
- **Origin-style plot** (*View > Plot style*, the default): a publication look in
  the manner of OriginLab graphs: white canvas, black frame on all four sides,
  inward ticks, Arial tick and axis labels, no grid, open black data symbols, red
  envelope, grey dashed background, filled components, a boxed legend. The
  *Instrument* style follows the theme as before (dark or light canvas, grid).
  Switching style or theme redraws the current fit, keeps the draggable centre
  lines, element marks and a renamed title; the setting is remembered. The legend
  is now compact at the top of its column instead of stretched over the plot
  height.
- **Session files** (*File > Save session… / Open session…*, `.xpsession`): the
  open files, titles, charge shifts, recipe and every fit (as project content) are
  written out and restored in a fresh window; fits are rebuilt from their stored
  start, so parameters are reproduced exactly. Candidate tables and bootstraps are
  not stored; missing files are reported and the rest restored.
- **Suggest recipe from survey…** (Analysis menu) after IDENTIFY: writes the
  proposed recipe and selects it in the Recipe box.
- **Parameter locks**: *Fix C* and *Fix W* check boxes in the Components table hold
  a component's centre or its widths during refits (`ComponentSpec.vary_width` is
  new; `vary_center` existed). Locks travel with project and session files.
- **Plot options…** (*View*, Ctrl+Shift+P): title, axis labels, tick / label font
  sizes, symbol size, envelope width, fill opacity, legend / fills / centre labels
  on or off, fixed x / y ranges; persisted, with *Restore defaults*.
- **Save settings as recipe…** (*File*): the panel's region plus the other regions
  of the recipe in use as a YAML recipe, optionally with the fitted components as
  candidate states and a fixed component count; selected in the Recipe box.

### Fixed
- The update check of the macOS (and some Linux) installer builds could not verify
  GitHub's certificate - the bundled OpenSSL has no CA store there - and reported
  "GitHub not reachable". Requests now fall back to certifi or the system CA bundle.
- Session files carry a `kind` marker: an exported project JSON (same integer
  format) is now rejected with a clear message instead of restoring nothing.
- Opening a session no longer replaces fits that are already open (and their undo
  history) unless asked (`replace_fits`); malformed entries are skipped and
  reported; structural errors are caught instead of escaping the menu action.
- A recipe file that disappears or breaks no longer raises from the Recipe box; the
  box falls back to manual settings with a log line.
- Origin-style figures set their fonts on the artists, so a figure returned without
  saving keeps them; the first installed family is resolved once (no font warnings).
- A manual result without an automatic fit behind it is now reported as unsaved
  by *Save session*; `--elements` ignores empty names; a theme change no longer
  redraws an Origin-style plot; the tree is rebuilt once after a session restore.
- **Linux / Python 3.11 abort** (CI exit 134, "Fatal Python error: none_dealloc"):
  the Linux build of PySide6 6.12.0 lowers the reference count of `None` on every
  event it dispatches to Python, and Python 3.11 aborts once it reaches zero, after
  a few hundred redraws in the app as well. PySide6 6.9.3-6.11.3 and the macOS /
  Windows builds of 6.12.0 are clean and Python 3.12+ makes `None` immortal; the
  `gui` extra now requires `PySide6<6.12` on Linux with Python < 3.12, and the app
  logs a warning when it finds that combination anyway.
- Every redraw of a fit leaked its draggable centre lines and their labels (the
  drag callback was a lambda holding the line, a cycle through the Qt connection
  that the garbage collector cannot see); they are now released.
- Colours reach pyqtgraph as `QColor` / `QBrush` instead of tuples, which sent
  every redraw through `numpy.dtype(tuple)` (a reference leak in numpy 2.2-2.4).
- GUI tests now really delete their windows (`deleteLater()` needs an event loop;
  deferred deletions are now sent explicitly), so a closed window no longer stays
  alive with all its widgets for the rest of the session.
- GUI tests no longer create a `MainWindow` only to drop it: the cyclic garbage
  collector deleted its Qt objects at an arbitrary later moment, which aborted the
  Linux / Python 3.11 CI job in the middle of the run (exit 134 after 172 tests).
- The PyPI publish workflow read the package version by importing it, which
  needs the dependencies its build job does not install; it now reads the
  version from the source file and also checks the built wheel's name.

### Added - project
- Zenodo DOI badge and `doi` / `identifiers` in `CITATION.cff` (concept DOI
  10.5281/zenodo.24071088; 0.5.0: 10.5281/zenodo.24071089).

## [0.5.0] - 2026-11-09

Composition in the app, charge alignment, comparison views, a bounded active
background, the CasaXPS product line shape, an energy-dependent quantification
correction and Excel workbooks as input.

### Added - file formats
- **Excel workbooks** (`.xlsx`, `.xlsm`) are read everywhere files are accepted:
  the command line, batch folders, the desktop application's Open / drop / folder
  actions. Every worksheet is scanned for numeric tables (a header row above a run
  of at least five numeric rows); the energy column is found by header (`Binding
  Energy (eV)`, `BE`, `KE`, `eV` ...) or, without one, as the monotonic uniformly
  spaced column. One sheet per region, one intensity column per sample on a shared
  axis, energy/intensity pairs side by side (ragged lengths allowed), several
  tables in one sheet and vendor exports with `Background` / `Envelope` /
  `Residual` / peak columns next to the measured `Counts / s` column all read as
  intended. Rows such as `Photon energy | 1486.6`, `Dwell time (s) | 0.1` and
  `Number of scans | 10` are used; kinetic-energy columns are converted; decimal
  commas and cached formula results are accepted. Sheet titles or table titles
  like `C1s Scan` set `species` / `transition`, so recipes match them as they match
  VAMAS blocks. `--sheet`, `--energy-col`, `--intensity-col` (index, Excel letter
  or header) override the choice. `write_excel` writes the three layouts for
  fixtures and interchange; `xps-autofit synth` adds `p3ht_aged_multi.xlsx`.
- Workbooks without their extension are recognised by content (zip signature).

### Added - algorithm
- **Scatter window for active backgrounds** (`background.scatter_window`, default
  0.3; GUI *Scatter window*, 0 = free). The scattering factor `k` of an active
  Shirley/Tougaard background is bounded to `[k0 / 1.3, 1.3 k0]` around the
  endpoint estimate `k0`, which is now stored as `info.scatter_start`. On the
  well-behaved synthetic regions `k` never leaves ±15 % of `k0`, so nothing
  changes there; on the four-component C 1s where `k` drifted to 1.55 `k0` the
  largest area error drops from 36 % to 23 % (15 % with a ±10 % window). A fit
  whose `k` ends on the window edge carries a warning; `null` restores the free
  factor. The differential-evolution search respects the same bounds.
- **`gl_product` line shape**: the Gaussian-Lorentzian *product* `G^(1-eta) L^eta`
  (CasaXPS `GL(p)`, `p = 100 eta`), area-normalised with the closed-form integral
  `pi/sqrt(b) exp(a/b) erfc(sqrt(a/b))` (evaluated with `erfcx`, so small `eta`
  does not overflow). `fwhm` is the width parameter of that definition; the
  reported FWHM is the measured one (up to 6 % smaller between the limits).
  Available in recipes, `--shape gl_product` and the GUI; not part of `auto`.
- **Energy-dependent quantification correction** (`quantification:
  {imfp_exponent, transmission_exponent}` in a recipe, `QuantCorrection`): areas
  are divided by `KE^(a + b)` in addition to the RSF, for cross-section factors
  that lack the instrument's escape-depth and transmission dependence. Off by
  default; the exponents are stated in every output and the result is
  `NOT_CALCULABLE` when a kinetic energy is missing. Bootstrap replicates use the
  same divisor.

### Added - desktop application
- **Composition tab**: atomic percentages of the current file from every fitted
  region in it, with the recipe's RSF or, failing that, the Scofield table
  (source shown), kinetic energies, the recipe's correction and bootstrap
  intervals when every region has a bootstrap. Same arithmetic as the batch
  summary; copies as TSV.
- **FIT ALL** (Shift+F5): queues an automatic fit for every loaded spectrum
  (recipe region matched by energy range; the panel settings for the selected
  one). The job runner now has a queue.
- **ALIGN** (Ctrl+Shift+A): charge correction in the app. Shifts every spectrum of
  the current file so the chosen component (table selection, the recipe's
  reference component, or the largest line) sits at the reference energy, records
  the shift in each spectrum's history and the project file, and refits the regions
  that had a fit. The C 1s adventitious-carbon caveat is logged.
- **Undo / Redo** (Ctrl+Z / Ctrl+Shift+Z, Edit menu) for component edits: drags,
  typed values, added and removed components, renames. A new automatic fit starts
  a new history. The Rename actions moved to the Edit menu.
- **Comparison view**: select two or more spectra in SAMPLES (Ctrl/Shift-click) to
  overlay their raw data; *View* offers raw / normalised to maximum / normalised
  to area and a stacked (offset) waterfall for sample series and depth profiles.
  Selecting one spectrum returns to its fit.
- *Scatter window* control in the BACKGROUND group (enabled for active/auto).

### Changed
- The text and Excel readers share one set of header heuristics
  (`readers/columns.py`); `Counts / s` with spaces is now recognised as cps.
- Tests: 201 (30 new: engine 7, line shapes 8, desktop 7, Excel input 8). The test process now
  ends without the interpreter's finalisation when Qt was used: PySide6 objects
  collected at shutdown had aborted green CI runs on Linux / Python 3.11 (exit
  134, `bool_dealloc`); the summary, coverage and exit status are unaffected.

## [0.4.1] - 2026-11-08

Editable names in the desktop application; archiving and publishing metadata.

### Added
- **Rename spectra and components in the app.** Double-click a spectrum in SAMPLES
  (or F2, *File > Rename spectrum…*) to give it a title: it appears in the tree,
  the plot title, the exported figure and the project file (`source.spectrum_name`,
  `original_spectrum.name`, plus a `rename` step in the spectrum history); output
  file names keep the source file's stem. Double-click a component's name in the
  Components tab (or Shift+F2, *Analysis > Rename component…*) to rename it: the
  minor doublet line, the stored spec, the legend and centre-line label, the
  Components table, the Diagnostics readout, a bootstrap and every export follow.
  A rename is not a refit: the numbers and the fit status are unchanged; empty and
  duplicate names are refused and logged.
- `rename_component(result, old, new)` and `minor_label()` in `core.fitting`,
  `BootstrapResult.renamed()`, `Session.rename_spectrum()` and
  `Session.rename_component()` for scripts and tests.
- `.zenodo.json`, so that releases archived on Zenodo carry the title, author,
  licence and keywords; `CITATION.cff` updated.
- `publish.yml` workflow: builds and checks the distributions of every published
  release and uploads them to PyPI through trusted publishing (no tokens), once the
  publisher is registered on PyPI (repository variable `PYPI_TRUSTED_PUBLISHER`).
- Project URLs for the package index (documentation, changelog, source).

### Changed
- Tests: 171 (7 new, for renaming).

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
