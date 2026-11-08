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
  than the static form, but on the four-component C 1s region (lines 0.8-0.9 eV
  apart) the free scattering factor can trade area with the overlapping
  components: in one of three seeds `k` drifted to 1.55 times the endpoint
  estimate and the largest area error reached 36 % (static: 11 %). A static
  background computed from the data "sees" the small peaks; the active one has to
  infer them. The static form therefore stays the default; use `active` for noisy
  or tail-laden endpoints, or `auto` and let the criterion decide.

  **Scatter window** (`scatter_window`, default 0.3). Since 0.5.0 the active `k`
  is bounded to `[k0 / (1 + w), k0 (1 + w)]` around the endpoint estimate `k0`
  (the factor that makes the Shirley/Tougaard background meet the high-BE
  endpoint; `info.scatter_start`). On the well-behaved synthetic regions `k`
  never leaves ±15 % of `k0`, so the window changes nothing there; in the C 1s
  case above it cuts the largest error from 36 % to 23 % (`w = 0.3`), 19 %
  (`w = 0.2`) and 15 % (`w = 0.1`). A fit whose `k` ends at the edge of the
  window carries a warning: the endpoints may be unreliable, and
  `scatter_window: null` (GUI: 0 = free) restores the free factor. The
  differential-evolution search respects the same bounds.

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
| `pseudo_voigt` | `fwhm`, `eta` | `eta L + (1 - eta) G` (sum form; CasaXPS `SGL(p)`, `p = 100 eta`) |
| `gl_product` | `fwhm`, `eta` | `G^(1 - eta) L^eta` (product form; CasaXPS `GL(p)`), normalised with the closed-form integral `pi / sqrt(b) exp(a/b) erfc(sqrt(a/b))`; `fwhm` is the width parameter of that definition and the reported FWHM is the measured one (up to 6 % smaller in between the limits) |
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
| `degenerate_parameters` | correlation between parameters of different components above `correlation_warning` (0.98) | warning |
| `large_relative_error` | area standard error above `relative_error_warning` (50 %) of the area | warning |

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

### Parameter correlations

From the covariance matrix every fit derives the correlation coefficients of the
free parameters. Pairs with |r| >= 0.9 are listed (`FitResult.correlations`, with a
flag saying whether both belong to the same component), and the largest |r|
between parameters of *different* components - or a component and the background -
is reported as `max_correlation` with the pair's names. Correlations inside one
component (its own area and width) are expected and not counted. A value above
`correlation_warning` (0.98) raises `degenerate_parameters`: the two components
are not determined independently by these data, however small their individual
standard errors look, and the split between them should not be reported without
a constraint (a fixed splitting, a shared width, a candidate window) or more data.

### Quality grade

Every candidate model receives a grade A-E (`xps_autofit.core.quality.grade_fit`)
so that a batch of fifty results can be triaged. It starts at 100 points and loses:

| Category | Rule | Max loss |
|---|---|---|
| goodness of fit | weighted fits: 30 x \|log10(reduced chi-square)\| | 30 |
| residual structure | Durbin-Watson < 1.0: 25; < 1.5: 10 | 25 |
| physical checks | each violation 25 | 50 |
| warnings | each warning 5 (residual, degeneracy and error warnings counted elsewhere) | 20 |
| parameter errors | no covariance 15; each area uncertain by > 50 %: 10 | 25 |
| degeneracy | `max_correlation` > 0.98: 10; > 0.995: 20 | 20 |
| convergence | optimiser failure | 20 |

A >= 90 (report as is), B >= 75 (read the warnings), C >= 60 (check the flagged
components), D >= 40 (inspect residual and model table), E (do not report without
manual work). Every deduction is listed with its number, so the letter can always be
traced back. The grade is a summary for triage, not a statistical test, and it does
not enter the model choice.

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

The project JSON stores the fitted data, settings (including the background mode,
the line shape, the loss and the spike mask), the start that won, all parameters
with bounds and expressions, the statistics, every candidate, and the versions of
Python, NumPy, SciPy, lmfit and this package. `xps-autofit verify` reloads it,
re-runs the fit from the stored start and compares parameters and envelope to 1e-6
relative.

## 10. Outliers: robust loss and spike mask

Least squares gives every point the same say, so a cosmic-ray hit, a detector
glitch or a tail the model cannot describe pulls the components towards it. Two
remedies are available per region; both are off by default and recorded in the
project file.

**Robust loss** (`loss: soft_l1 | huber | cauchy | arctan`, `--loss`, GUI
*Robustness*). The fit runs through `scipy.optimize.least_squares` with the chosen
loss ρ applied to the weighted residual `r/σ`: the cost is `Σ ρ((r/σ)²; s)` with the
scale `s = loss_scale` (default 3). Residuals below `s` behave as in least squares,
larger ones grow linearly (`soft_l1`, `huber`), logarithmically (`cauchy`) or are
bounded (`arctan`), so a point ten sigma off contributes little more than one three
sigma off. For unweighted fits the scale is `loss_scale` times the robust standard
deviation (1.4826 x MAD) of the starting residual. Standard errors are the
linearised estimate from the Jacobian at the solution; the result carries a
warning saying so, and a bootstrap is the honest check. On a synthetic oxidised S
2p region with four injected spikes the robust fit keeps both doublets within 3 %
of the truth while ordinary least squares adds a spurious third component to
absorb the spikes.

**Spike mask** (`spike_sigma`, `--mask-spikes SIGMA`, GUI *Mask spikes*). A point
is a spike when it lies more than `SIGMA` local standard deviations (counting
statistics when available) *above both of its neighbours* - or below both, for a
dropout; two adjacent points are a spike when both exceed the points on either side
of the pair. A smooth flank or a peak several points wide never satisfies this,
which is why the mask is refused (with a warning) when the step exceeds 0.25 eV:
at a coarse step a genuine narrow line could be two points wide. Masked points are
excluded from the fit, replaced by the running median for the background and the
peak detection, listed in the warnings with their energies, and left out of every
statistic (`n_masked`, `ndata`). More than 2 % masked points is not a few spikes
but a different problem, and the mask is skipped with a warning. Edge points cannot
be tested and are never masked.

## 11. Survey element identification

`xps-autofit identify` and the IDENTIFY button answer the first question about a
new sample - *what is in it?* - from a survey scan, before any region is fitted.

1. **Peaks.** The survey is put on a uniform grid, smoothed with a Savitzky-Golay
   window of about 1 eV, and maxima are located with a prominence floor of 5 x the
   noise (window-limited to 30 eV so a step background does not swallow small
   lines). Each maximum must also rise 5 x its own Poisson noise above the local
   baseline.
2. **Table.** `xps_autofit.database.survey_lines` lists, for 62 elements, the
   principal photoelectron lines (typical binding energy, Scofield-like relative
   intensity with C 1s = 1) and the common Auger lines by kinetic energy, which are
   placed with the spectrum's photon energy. Positions are typical values; chemical
   states and charging move them by about 1 eV, so matching uses a tolerance
   (default 1.5 eV, `--tolerance`) and an optional `--charge-shift`.
3. **Score.** For each element the lines inside the measured range are matched to
   the nearest peak within the tolerance. The element is a candidate only when its
   **strongest line in range** is found; its confidence is the matched share of the
   expected intensity, reduced when only secondary lines can be seen because the
   main line lies outside the range (`sqrt(strongest in range / strongest
   overall)`), and reduced when a secondary line is far stronger than the main line
   allows (that peak is something else).
4. **Shared peaks.** Candidates are walked from the most to the least confident. One
   whose main line sits on a peak already explained by a stronger candidate is
   *ambiguous* (half confidence, the alternative named: Bi 4f / S 2p, Au 4d / Pd
   3d, Ru 3d / C 1s); if every one of its peaks is already explained it is most
   likely a coincidence (quarter confidence) and usually falls below the threshold
   (default 0.3, `--min-confidence`).
5. **Report.** Candidates with their matched and missing lines, offsets and
   heights; peaks that no element explains, with the nearest table lines as hints;
   the parameters used. The app marks the matched lines on the spectrum.

On synthetic surveys of seven compositions (Cu/O/C/N, Si/O/C/F/Na, Ti/O/C/Au,
Pb/I/C/N/O, Bi/S/C/O, Mg/O/C, Fe/Ni/Cr/O/C) every element present is found and no
absent element is reported; the Bi/S overlap is reported as ambiguous. Real surveys
add satellites, plasmons and charging, so the result is a shortlist to confirm with
high-resolution regions, never an assignment.

## 12. Quantification

The relative composition of a sample uses one area per region - the doublet total
or the major line, as the recipe's `rsf_applies_to` says - and

```
n_i = (A_i / D_i) / sum_j (A_j / D_j),      D_i = RSF_i * KE_i^(a + b)
```

`RSF_i` is the recipe's relative sensitivity factor or, when the recipe gives
none, the Scofield cross-section of the built-in table (the source is reported).
A missing factor makes the sample `NOT_CALCULABLE` with the missing lines listed;
no value is guessed. `KE_i = hv - BE_i` is the kinetic energy of the region's
largest line and the exponents `a` (escape depth, `lambda ~ KE^a`, 0.6-0.75) and
`b` (analyser transmission, `T ~ KE^b`) come from the recipe's `quantification`
block; both default to 0, i.e. no correction, which is right for instrument RSF
libraries that already contain those dependences. Whatever the choice, the note
of the result states it. Bootstrap replicates of the region areas are divided by
the same `D_i` before the atomic percentages and their intervals are formed
(section 8), so the uncertainties follow the convention. The app's Composition
tab and the batch `summary_quantification.csv` run this same code.
