# Recipe reference

A recipe is a YAML document:

```yaml
name: my_recipe
description: free text
photon_energy: 1486.6          # eV, used when the file has none (kinetic-energy data)
charge_reference:              # optional
  region: C 1s                 # recipe region fitted first
  component: C-C/C-H           # label of the component used as reference (else the largest)
  value: 284.8                 # eV
references:
  - citations for the candidate positions
quantification:                # optional energy-dependent correction on top of the RSFs
  imfp_exponent: 0.0           # a: escape depth ~ KE^a (0.6-0.75 for Scofield factors)
  transmission_exponent: 0.0   # b: analyser transmission ~ KE^b (-1 in CRR mode)
                               # areas are divided by RSF * KE^(a + b); both 0 = none
regions:
  - name: S 2p                 # unique; "Element line" is matched against VAMAS metadata
    element: S
    line: 2p
    range: [160.0, 172.0]      # binding energy window, eV
    background: {type: shirley, mode: static, endpoint_points: 3}
                               # type: none | linear | shirley | tougaard | auto
                               # mode: static (from the endpoints, fixed) | active
                               #       (Shirley/Tougaard generated from the fitted
                               #       peaks inside the fit) | auto
                               # scatter_window: 0.3 (active: keep the scattering
                               #       factor within k0/1.3 .. 1.3 k0 of the endpoint
                               #       estimate k0; null = free)
    refine_background: true    # free linear term in the fit (default true)
    shape: voigt               # gaussian | lorentzian | voigt | pseudo_voigt (sum, SGL) |
                               # gl_product (CasaXPS GL(p)) |
                               # doniach_sunjic (asymmetric, metals) | auto
    optimizer: leastsq         # leastsq | global (differential evolution, then LM)
    constraints:
      fwhm_g: [0.5, 1.8]       # Gaussian FWHM bounds (voigt, doniach_sunjic)
      fwhm_l: [0.05, 0.5]      # Lorentzian FWHM bounds (voigt, doniach_sunjic)
      fwhm: [0.3, 3.5]         # FWHM bounds (gaussian, lorentzian, pseudo_voigt, gl_product)
      eta: [0.0, 1.0]          # pseudo_voigt / gl_product mixing bounds (p = 100 eta)
      asym: [0.0, 0.5]         # doniach_sunjic asymmetry bounds (metals 0.05-0.2)
      share_fwhm_l: true       # one Lorentzian width for the region
      share_fwhm_g: false
      share_fwhm: false
      share_eta: true
      share_asym: true         # one asymmetry for the region
      min_separation: 0.5      # eV between majors
      edge_margin: 0.2         # eV from the region edges
      significance_sigma: 3.0  # area and height significance
      residual_dw_warning: 1.0 # warn when the residual's Durbin-Watson falls below this
    doublet:                   # omit for s lines; "auto" looks up the database
      splitting: 1.18
      splitting_tolerance: 0.02
      area_ratio: 0.5
      ratio_tolerance: 0.0
      share_widths: true
    candidates:
      - {label: thiophene C-S-C, center: 164.0, window: 0.5}
      - {label: satellite, center: 941.0, window: 1.3, fwhm_g: [1.5, 4.5]}  # per-candidate width
    min_components: 1
    max_components: 3
    n_starts: 4
    criterion: aicc            # aicc | bic | aic
    min_improvement: 2.0       # parsimony margin
    require_assignment: false  # true: a component outside all windows disqualifies the model
    rsf: 1.677                 # relative sensitivity factor, or null (an rsf_library entry wins)
    rsf_applies_to: total      # total (doublet sum) | major
    weighting: auto            # auto | poisson | none
  - name: Cu LMM
    element: Cu
    line: LMM
    range: [562.0, 576.0]
    fit: false                 # report-only region
    report: auger_max          # kinetic energy of the smoothed maximum
    auger_pair: Cu 2p3/2       # photoelectron region for alpha' = BE + KE
```

`background: {type: auto}` fits every background in `shirley, tougaard, linear`,
`mode: auto` both the static and the active form of Shirley and Tougaard, and
`shape: auto` every shape in `voigt, pseudo_voigt`; each combination goes through
the same component-count search, and the final choice uses the same criterion and
physical checks. `optimizer: global` runs a seeded differential evolution inside
the parameter bounds for the first start of every model before the
Levenberg-Marquardt polish; it is several times slower and meant for heavily
overlapping regions.

Use `mode: active` when the region edges are noisy or carry peak tails (the
classical Shirley then starts too high or too low), and `shape: doniach_sunjic`
for metallic lines (Au 4f, Cu 2p of Cu(0), Pt 4f, ...) whose high-BE tail a
symmetric Voigt cannot follow. Both are described in `docs/algorithm.md`. The
active scattering factor stays within `scatter_window` (default ±30 %) of the
endpoint estimate; set `scatter_window: null` to free it when the endpoints are
known to be unreliable.

`quantification` applies only to the composition: with instrument RSFs (Avantage,
CasaXPS libraries) leave both exponents at 0, since those factors already contain
the transmission and escape-depth dependence; with Scofield cross-sections a
typical choice is `imfp_exponent: 0.6` plus the analyser's transmission exponent.
The exponents are written into every summary so the convention travels with the
numbers (`docs/algorithm.md`, section 12).

Regions are matched to the spectra in a file by `species`/`transition` metadata
when available (VAMAS blocks; Excel sheet or table titles such as `C1s Scan` or
`Region S 2p`), otherwise by energy-range overlap (at least 60 % of the region
range must be covered).

`xps-autofit recipes --show <name>` prints a built-in recipe in this format.

## Instrument sensitivity factors

A recipe may name the instrument's RSF library at the top level:

```yaml
rsf_library: libs/nexsa_althermo1.csv   # relative to this recipe file
```

The library is a CSV with `element,line,rsf` columns (or `label,rsf`, with
semicolons and decimal commas accepted) or a YAML file with `name`, `source` and
`factors: {"C 1s": 1.0, "O 1s": 2.881, ...}`. Where the library has a region's
element and line, its factor replaces the region's `rsf`; the summary's
`rsf_source` column says which one was used. `xps-autofit fit/batch
--rsf-library FILE` does the same for a run without editing the recipe.

## A recipe from a survey

`xps-autofit suggest survey.csv -o my_sample.yaml` identifies the elements in a
survey and writes a recipe with one region per element above the confidence
threshold (`--min-confidence 0.5`): the strongest matched photoelectron line, a
range of `--half-width 8` eV on each side of the *measured* peak (so a charged
sample gets shifted ranges), the spin-orbit doublet from the database when the
line is an unresolved `2p` / `3d` / `4f` (a listed component such as `Cu 2p3/2`
is fitted on its own, like the built-in recipes), the Scofield RSF where the table
has one, and adventitious carbon at 284.8 eV as the charge reference when a C 1s
region is present. The same proposal is available in the application after
IDENTIFY (*Analysis > Suggest recipe from survey…*). It is a starting point:
adjust ranges and component counts and add `candidates` before trusting the
compositions.
