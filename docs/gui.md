# Desktop application

```bash
pip install "xps-autofit[gui]"
xps-autofit gui
```

The window follows the layout of instrument software: samples on the left, the
live spectrum in the centre, fit settings and result tables on the right, a log at
the bottom and a status lamp in the status bar (IDLE / FITTING / CONVERGED /
AMBIGUOUS / NEEDS REVIEW / FAILED / MANUAL FIT).

![Main window after an automatic fit of a Cu 2p3/2 region](images/gui_main_cu2p.png)

## Workflow

1. **Open files…**, **Open folder…**, the **Recent files** menu, or drop files and
   folders onto the window (CSV, TXT, VAMAS, …). Each spectrum in a file becomes a
   row under its file in SAMPLES. **Remove spectrum** (Delete) takes the selected
   row out again.
2. Pick a **Recipe**; the region matching the selected spectrum is chosen
   automatically and its settings fill the panel. Without a recipe the panel is an
   ad-hoc region: set element/line (the doublet is filled from the database), range,
   background type and **mode** (static / active / auto), shape (including the
   asymmetric `doniach_sunjic` line with its asymmetry bound), component count and
   width bounds.
3. **AUTO FIT** (F5) runs the full model selection in a background thread. The plot
   shows raw data, background (static + linear refinement, or the active
   background), each component with a draggable centre line, the envelope and the
   residual with the ±1σ band. A hairline cursor follows the mouse in both panels
   and the status bar reads out energy and intensity. The Components tab lists
   centres, FWHM, areas with standard errors, the fraction per chemical component
   and the asymmetry; the Models tab lists every candidate with its variant
   (background / shape), criterion, reduced chi-square, Durbin-Watson statistic and
   the physical checks it failed (click a row to view that model); the
   Diagnostics tab is a monospace readout of the statistics, residual diagnostics,
   background parameters, warnings and notes.

   ![Models and diagnostics tabs](images/gui_diagnostics.png)

4. To adjust: drag a centre line (refits on release when *Refit when a peak is
   dragged* is on), double-click a centre or width cell to type a value, or use
   **+ Component** (placed at the largest residual) and **- Component** (selected
   row). Manual results are labelled MANUAL FIT and keep the automatic candidates
   for comparison.
5. **UNCERTAINTY** (F7) bootstraps the displayed fit (Poisson replicates for
   counts, resampled residuals otherwise) and adds standard deviations and 95 %
   intervals of areas, fractions and centres to the Diagnostics tab. The bootstrap
   is cleared when the model changes.
6. **EXPORT** (Ctrl+E) writes the same files as the command line for the current
   spectrum (CSV, XLSX, JSON project, PNG/SVG/PDF, optional bootstrap);
   **Save plot image…** (Ctrl+Shift+S) saves the live view as PNG; **Copy table**
   (Ctrl+Shift+C, or Ctrl+C inside a table) puts the current table on the clipboard
   as tab-separated text for a spreadsheet.
7. **BATCH** (Ctrl+B) applies a recipe to files or folders and shows the summary
   table; the per-file outputs land in the chosen folder.

![Interactive refit of an S 2p region with two doublets](images/gui_s2p_manual.png)

## Notes

- Fits run on a worker thread; the window stays responsive and the lamp blinks
  while FITTING. One job runs at a time.
- The GUI never computes anything itself: every number comes from the same
  functions the CLI uses (`select_model`, `fit_peaks`, `bootstrap`,
  `write_region_outputs`, `run_batch`), so results are identical.
- Settings such as the last folder and the recent-files list are stored with
  `QSettings` ("xps-autofit", "studio").
- Headless testing: set `QT_QPA_PLATFORM=offscreen` and construct
  `MainWindow(synchronous_jobs=True)`; see `tests/test_gui.py` and
  `tests/test_gui_features.py`. The screenshots on this page are produced the
  same way by `examples/make_screenshots.py`.
