# How the automatic fit works

This page describes what `select_model` does, in the order it does it, so a result
can be audited from the project file.

## 1. Region and background

The spectrum is cropped to the recipe range. The background of
`BackgroundSpec.type` is computed on the raw data from the averaged endpoint
intensities (`endpoint_points`, default 3):

- **linear** - straight line between the endpoints.
- **shirley** - iterative; `B(E) = I_lo + (I_hi - I_lo) * Q(E) / Q_total`, where
  `Q(E)` integrates the background-subtracted signal from the low-BE end. The loop
  stops when the largest change falls below `tolerance * |I_hi - I_lo|`.
- **tougaard** - universal cross-section `F(T) = B T / (C + T^2)^2`, `C = 1643 eV^2`,
  convolved with the signal above the low-BE endpoint; `B` is scaled so the
  background meets the high-BE endpoint unless given.

Endpoint-based backgrounds inherit two errors: Poisson noise in the endpoint
average and the Lorentzian tails of the peaks themselves. With
`refine_background: true` (the default for automatic fits) the fit carries a free
offset and slope on top of the fixed background. On synthetic data this is the
difference between reduced chi-square near 1 and values of 2-6 with distorted
components; the refined term is written to the fit table and the project file as
`bg_adjust`.

## 2. Noise and detection

The baseline noise is the median absolute deviation (scaled by 1.4826) of the
difference between the net signal and its Savitzky-Golay smooth (window about
0.6 FWHM). Candidate peaks are local maxima of the smoothed signal with a prominence
above 3 sigma; for doublet regions a maximum sitting one splitting above another
with a plausible height ratio is folded into its major line.

## 3. Starts for `n` components

For each `n` from `min_components` to `max_components`:

1. the `n` most prominent detected majors, topped up from the largest positive
   residual of a quick model when fewer were detected;
2. the `n` candidate positions carrying the most smoothed signal (when the recipe
   lists at least `n` candidates);
3. the previous best (`n - 1`) model plus one component at the largest positive
   residual;
4. jittered copies of start 1 until `n_starts` starts exist (centres +/- 0.3 FWHM,
   widths x 0.8-1.25, areas x 0.7-1.3) drawn from a generator seeded by
   `sha256(data) | region name | n`.

Each start is fitted with Levenberg-Marquardt (`lmfit.minimize`, method `leastsq`)
and the lowest chi-square survives. With `optimizer: global` the first start of
every model is preceded by a differential-evolution search (SciPy, seeded from the
same data-derived seed, areas and the linear background term given data-driven
finite bounds) whose best point is then polished by Levenberg-Marquardt; the other
starts stay local, so the global result can only lower the best chi-square.

When `background.type` or `shape` is `auto`, steps 1-4 run for every combination
of `shirley / tougaard / linear` and `voigt / pseudo_voigt`. All candidates share
one criterion scale (same data, same weights), so the background and shape are
chosen like the number of components: best variant per component count, then the
parsimony rule below. Variants within the margin of the winner are listed in the
notes. Labels: a component inside a candidate window
takes that candidate's label and centre bounds; others are generic and are
relabelled after the fit if they ended inside an unused window.

## 4. Physical checks

| Code | Condition | Severity |
|------|-----------|----------|
| `non_positive_area` | area <= 0 | violation |
| `insignificant_area` | area / stderr < `significance_sigma` (3) | violation |
| `below_noise` | height < `significance_sigma` x local noise (baseline noise or Poisson sigma at the centre, whichever is larger) | violation |
| `center_at_edge` | centre within `edge_margin` (0.2 eV) of the region edge | violation |
| `too_close` | two majors closer than `min_separation` | violation |
| `unassigned` | centre outside every candidate window | warning, or violation with `require_assignment` |
| `width_at_lower_bound` / `width_at_upper_bound` | width within 1 % of its bound | warning |

Standard errors are taken from the covariance matrix (rescaled by reduced
chi-square only for unweighted fits). A parameter resting on a bound gets a
vanishing error from lmfit's bound transform; such errors are reported as
unavailable and listed in the warnings.

## 5. Choice

Among the models that pass the checks, the simplest is the starting point and a
model with more components replaces it only when it lowers the criterion (AICc by
default, BIC optional) by at least `min_improvement` (2.0). If another valid model
lies within that margin the status is `ambiguous`; if no model passes, the
statistically best one is returned as `needs_review`. Every candidate, with its
statistics and its reasons for rejection, is kept in the project file and the
`_models.csv` table.

Criteria for weighted fits: `AIC = chi2 + 2k`, `AICc = AIC + 2k(k+1)/(n-k-1)`,
`BIC = chi2 + k ln n`. For unweighted fits `chi2` is replaced by `n ln(RSS/n)`.

## 6. Doublets

A doublet is a single component. The minor line has `center = major + splitting`,
`area = major x ratio` and the major's widths (expressions in lmfit), with optional
tolerances on splitting and ratio. Reported fractions are given both per line
(`fraction_pct`) and per chemical component (`component_fraction_pct`, major plus
minor).

## 7. Reproducibility

The project JSON stores the fitted data, settings, the start that won, all
parameters with bounds and expressions, the statistics, every candidate, and the
versions of Python, NumPy, SciPy, lmfit and this package. `xps-autofit verify`
reloads it, re-runs the fit from the stored start and compares parameters and
envelope to 1e-6 relative.
