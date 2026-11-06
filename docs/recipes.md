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
regions:
  - name: S 2p                 # unique; "Element line" is matched against VAMAS metadata
    element: S
    line: 2p
    range: [160.0, 172.0]      # binding energy window, eV
    background: {type: shirley, endpoint_points: 3}   # none | linear | shirley | tougaard | auto
    refine_background: true    # free linear term in the fit (default true)
    shape: voigt               # gaussian | lorentzian | voigt | pseudo_voigt | auto
    optimizer: leastsq         # leastsq | global (differential evolution, then LM)
    constraints:
      fwhm_g: [0.5, 1.8]       # Gaussian FWHM bounds (voigt)
      fwhm_l: [0.05, 0.5]      # Lorentzian FWHM bounds (voigt)
      fwhm: [0.3, 3.5]         # FWHM bounds (gaussian, lorentzian, pseudo_voigt)
      eta: [0.0, 1.0]          # pseudo_voigt mixing bounds
      share_fwhm_l: true       # one Lorentzian width for the region
      share_fwhm_g: false
      share_fwhm: false
      share_eta: true
      min_separation: 0.5      # eV between majors
      edge_margin: 0.2         # eV from the region edges
      significance_sigma: 3.0  # area and height significance
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
    rsf: 1.677                 # relative sensitivity factor, or null
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

`background: {type: auto}` fits every background in `shirley, tougaard, linear`
and `shape: auto` every shape in `voigt, pseudo_voigt`; each combination goes
through the same component-count search, and the final choice uses the same
criterion and physical checks. `optimizer: global` runs a seeded differential
evolution inside the parameter bounds for the first start of every model before
the Levenberg-Marquardt polish; it is several times slower and meant for heavily
overlapping regions.

Regions are matched to the spectra in a file by VAMAS `species`/`transition`
metadata when available, otherwise by energy-range overlap (at least 60 % of the
region range must be covered).

`xps-autofit recipes --show <name>` prints a built-in recipe in this format.
