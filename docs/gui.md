# Desktop application

```bash
pip install "xps-autofit[gui]"
xps-autofit gui
```

The window follows the layout of instrument software: samples on the left, the
live spectrum in the centre, fit settings and result tables on the right, a log at
the bottom and a status lamp in the status bar (IDLE / FITTING / CONVERGED /
AMBIGUOUS / NEEDS REVIEW / FAILED / MANUAL FIT).

## Workflow

1. **Open files…** or **Open folder…** (CSV, TXT, VAMAS, …). Each spectrum in a file
   becomes a row under its file in SAMPLES.
2. Pick a **Recipe**; the region matching the selected spectrum is chosen
   automatically and its settings fill the panel. Without a recipe the panel is an
   ad-hoc region: set element/line (the doublet is filled from the database), range,
   background, shape, component count and width bounds.
3. **AUTO FIT** (F5) runs the full model selection in a background thread. The plot
   shows raw data, background (fixed + linear refinement), each component with a
   draggable centre line, the envelope and the residual with the ±1σ band. The
   Components tab lists centres, FWHM, areas with standard errors and the fraction
   per chemical component; the Models tab lists every candidate with its criterion,
   reduced chi-square and the physical checks it failed (click a row to view it).
4. To adjust: drag a centre line (refits on release when *Refit when a peak is
   dragged* is on), double-click a centre or width cell to type a value, or use
   **+ Component** (placed at the largest residual) and **- Component** (selected
   row). Manual results are labelled MANUAL FIT and keep the automatic candidates
   for comparison.
5. **EXPORT** (Ctrl+E) writes the same files as the command line for the current
   spectrum (CSV, XLSX, JSON project, PNG/SVG/PDF, optional bootstrap).
6. **BATCH** (Ctrl+B) applies a recipe to files or folders and shows the summary
   table; the per-file outputs land in the chosen folder.

## Notes

- Fits run on a worker thread; the window stays responsive and the lamp blinks
  while FITTING. One job runs at a time.
- The GUI never computes anything itself: every number comes from the same
  functions the CLI uses (`select_model`, `fit_peaks`, `write_region_outputs`,
  `run_batch`), so results are identical.
- Settings such as the last folder are stored with `QSettings` ("xps-autofit",
  "studio").
- Headless testing: set `QT_QPA_PLATFORM=offscreen` and construct
  `MainWindow(synchronous_jobs=True)`; see `tests/test_gui.py`.
