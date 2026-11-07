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
average and the Lorentzian tails of the peaks themselves. Two remedies exist:

- `refine_background: true` (the default for automatic fits) carries a free offset
  and slope on top of the fixed background. On synthetic data this is the
  difference between reduced chi-square near 1 and values of 2-6 with distorted
  components; the refined term is written to the fit table and the project file as
  `bg_adjust`.
- `background: {type: shirley, mode: active}` (also `tougaard`) makes the
  background part of the model: `B(E) = offset + k * S[envelope](E)`, where `S` is
  the Shirley running integral (or the Tougaard loss integral) of the *fitted peak
  envelope*, and `offset` and the scattering factor `k` are free parameters
  (`bg_offset`, `bg_scatter`). The endpoints only provide the starting values, so
  neither their noise nor the peak tails bias the result, and background and peaks
  are self-consistent by construction. With `refine_background` a free slope is
  added. `mode: auto` fits both forms and chooses with the criterion. The fitted
  background is stored in the project as `background.values` with
  `info.mode = active`, `info.offset` and `info.scatter`.

  The active form is not better in every case. On synthetic data (three seeds
  each) it reproduces the S 2p and Cu 2p3/2 truths as well as or slightly better
  than the static form, but on the four-component C 1s region its free scattering
  factor trades area with the weak O-C=O line on the high-BE flank (largest area
  error 22 % against 6 % static). A static background computed from the data
  "sees" that small peak; the active one has to infer it. The static form
  therefore stays the default; use `active` for noisy or tail-laden endpoints, or
  `auto` and let the criterion decide.

## 2. Noise and detection

The baseline noise is the median absolute deviation (scaled by 1.4826) of the
difference between the net signal and its Savitzky-Golay smooth (window about
0.6 FWHM), divided by `sqrt(1 - c0)` with `c0` the central filter weight: a smoother
absorbs part of the noise, and without the correction the estimate is 10-30 % low
(the shorter the window, the more). Too few points for a window fall back to the
scaled median absolute first difference.

Candidate peaks come from two detectors:

- **maxima** of the smoothed signal with a prominence above 3 sigma; for doublet
  regions a maximum sitting one splitting above another with a plausible height
  ratio is folded into its major line;
- **shoulders**: dips of the Savitzky-Golay second derivative (window about one
  FWHM). On the flank of a single bell-shaped line the second derivative is
  monotonic beyond the inflection point, so a local dip there requires a second
  component. White noise of standard deviation `s` propagates through the
  derivative filter to `s * sqrt(sum c_k^2)`; a dip counts when its prominence
  exceeds 8 times that value for the *local* noise (baseline noise or the Poisson
  sigma of the raw counts at that energy, whichever is larger). Shoulders rank
  after maxima and start with 30 % of the smoothed signal as height; the fit
  decides the rest. The detector is deliberately conservative - its job is a
  better starting point, not the final verdict.

## 3. Starts for `n` components

For each `n` from `min_components` to `max_components`:

1. the `n` most prominent detected guesses, topped up from the largest positive
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
same data-derived seed; areas and the background terms are given data-driven
finite bounds) whose best point is then polished by Levenberg-Marquardt; the other
starts stay local, so the global result can only lower the best chi-square.

When `background.type`, `background.mode` or `shape` is `auto`, steps 1-4 run for
every combination of `shirley / tougaard / linear` (static and, for Shirley and
Tougaard, active) and `voigt / pseudo_voigt`. All candidates share one criterion
scale (same data, same weights), so background and shape are chosen like the
number of components: best variant per component count, then the parsimony rule
below. Variants within the margin of the winner are listed in the notes. Labels: a
component inside a candidate window takes that candidate's label and centre
bounds; others are generic and are relabelled after the fit if they ended inside an
unused window.

## 4. Line shapes

All shapes are area-normalised so the fitted amplitude is the area:

| Shape | Parameters | Use |
|-------|------------|-----|
| `gaussian`, `lorentzian` | `fwhm` | limiting cases |
| `voigt` | `fwhm_g`, `fwhm_l` | default; exact convolution (`scipy.special.voigt_profile`) |
| `pseudo_voigt` | `fwhm`, `eta` | `eta L + (1 - eta) G`, CasaXPS-like GL mixing |
| `doniach_sunjic` | `fwhm_g`, `fwhm_l`, `asym` | metals: Doniach-Sunjic line (asymmetry `alpha`, tail towards high binding energy) convolved numerically with a Gaussian |

The Doniach-Sunjic tail is not integrable, so its *area* is defined as the
integral within +/- 10 total widths of the centre (`peak_shapes.DS_AREA_WINDOW`);
for `asym = 0` the profile is the Voigt profile with that area convention (the
difference to the plain Voigt is the 1 % of the Lorentzian tail beyond the
window). `center` is the position parameter of the line; the apparent maximum
lies slightly above it. `asym` is bounded by `constraints.asym` (default
`[0, 0.5]`) and shared across the components of a region by default
(`share_asym: true`), like the Lorentzian width. A line resting at `asym = 0` is
the symmetric case and raises no warning. The asymmetric shape is not part of
`shape: auto`; set it explicitly for metallic regions.

## 5. Physical checks

| Code | Condition | Severity |
|------|-----------|----------|
| `non_positive_area` | area <= 0 | violation |
| `insignificant_area` | area / stderr < `significance_sigma` (3) | violation |
| `below_noise` | height < `significance_sigma` x local noise (baseline noise or Poisson sigma at the centre, whichever is larger) | violation |
| `center_at_edge` | centre within `edge_margin` (0.2 eV) of the region edge | violation |
| `too_close` | two majors closer than `min_separation` | violation |
| `unassigned` | centre outside every candidate window | warning, or violation with `require_assignment` |
| `width_at_lower_bound` / `width_at_upper_bound` | width within 1 % of its bound | warning |
| `structured_residual` | Durbin-Watson statistic of the residual below `residual_dw_warning` (1.0) with at least 30 points | warning |

Standard errors are taken from the covariance matrix (rescaled by reduced
chi-square only for unweighted fits). A parameter resting on a bound gets a
vanishing error from lmfit's bound transform; such errors are reported as
unavailable and listed in the warnings.

### Residual diagnostics

Every fit reports, on the weighted residual, the Durbin-Watson statistic
`sum (r_i - r_{i-1})^2 / sum r_i^2` (2 for white noise, towards 0 for a residual
with structure), the Wald-Wolfowitz runs-test z-score of the residual signs
(strongly negative = long runs of one sign) and the lag-1 autocorrelation. They
appear in the statistics (`durbin_watson`, `runs_z`, `lag1_autocorr`), the
candidate table, the desktop Diagnostics tab and the summary tables. A missing
component or a wrong background shows up here even when chi-square looks
acceptable.

## 6. Choice

Among the models that pass the checks, the simplest is the starting point and a
model with more components replaces it only when it lowers the criterion (AICc by
default, BIC optional) by at least `min_improvement` (2.0). Inside that margin the
residual decides: a model whose residual is white replaces one flagged
`structured_residual` when it also has the lower criterion, and a close model
whose residual is structured while the chosen one is white does not make the
result ambiguous. Otherwise, if another valid model lies within the margin the
status is `ambiguous`; if no model passes, the statistically best one is returned
as `needs_review`. Every candidate, with its statistics and its reasons for
rejection, is kept in the project file and the `_models.csv` table.

Criteria for weighted fits: `AIC = chi2 + 2k`, `AICc = AIC + 2k(k+1)/(n-k-1)`,
`BIC = chi2 + k ln n`. For unweighted fits `chi2` is replaced by `n ln(RSS/n)`.

## 7. Doublets

A doublet is a single component. The minor line has `center = major + splitting`,
`area = major x ratio` and the major's widths (expressions in lmfit), with optional
tolerances on splitting and ratio. Reported fractions are given both per line
(`fraction_pct`) and per chemical component (`component_fraction_pct`, major plus
minor).

## 8. Uncertainties

Covariance errors assume the model is right and the noise is as weighted.
`--bootstrap N` (recipe runs), the EXPORT dialog or the UNCERTAINTY button refit
`N` replicates of the data drawn from the fitted model (Poisson counts when the
data are counts, otherwise resampled residuals), starting from the fitted values
with the local optimiser. The project file receives, per component, the standard
deviation and the 2.5 / 50 / 97.5 percentiles of area, centre, FWHM, line fraction
and component fraction. In a recipe run the replicate areas of every region are
paired index by index and propagated to the atomic percentages
(`atomic_percent_std`, `atomic_percent_p2_5`, `atomic_percent_p97_5` in
`summary_quantification.csv`), so the composition carries an uncertainty that
includes the peak-fitting trade-offs, not only counting statistics.

## 9. Reproducibility

The project JSON stores the fitted data, settings (including the background mode
and the line shape), the start that won, all parameters with bounds and
expressions, the statistics, every candidate, and the versions of Python, NumPy,
SciPy, lmfit and this package. `xps-autofit verify` reloads it, re-runs the fit
from the stored start and compares parameters and envelope to 1e-6 relative.
