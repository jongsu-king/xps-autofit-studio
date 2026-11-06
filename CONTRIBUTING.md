# Contributing

Thank you for considering a contribution. Issues and pull requests are welcome.

## Setting up

```bash
git clone https://github.com/jongsu-king/xps-autofit-studio
cd xps-autofit-studio
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Before opening a pull request:

```bash
ruff format src tests
ruff check src tests
mypy
pytest
```

CI runs the same commands on Linux, macOS and Windows with Python 3.11-3.13.

## Ground rules

- **The engine stays GUI-free.** Everything under `xps_autofit/core`,
  `automation`, `readers`, `database`, `export` must run without Qt. GUI code goes
  into `xps_autofit/gui` only.
- **Fits run on raw data.** Smoothing is allowed for detection and reporting, never
  as the input of a fit.
- **Every number must be reproducible.** New randomness must be seeded from the data
  (see `derive_seed`). A project file written by the new code must pass
  `xps-autofit verify`.
- **Say what you cannot compute.** Missing sensitivity factors, unreadable formats
  or failed physical checks are reported as such (`NOT_CALCULABLE`,
  `needs_review`), never replaced by a guess.
- **Reference data need a source.** Entries in `xps_autofit/database` carry a note
  on where the value comes from.
- **Tests use synthetic data with known truth** (`xps_autofit.synthetic`). Measured
  spectra may be used for integration tests only when the data owner agreed, and
  they are not committed to the repository.

## Adding a file reader

Write `read_<format>(path, **kwargs) -> list[Spectrum]` in `xps_autofit/readers/`
and register the extension with `register_reader`. Record the instrument metadata
you can recover (`species`, `transition`, dwell time, scans, source energy); the
batch runner uses `species`/`transition` to match recipe regions.

## Adding a recipe

Copy one of the YAML files in `xps_autofit/recipes/`, keep the region names
explicit (`"Cu 2p3/2"`, not `"Cu"`), cite the sources of the candidate positions in
`references`, and leave `rsf: null` when you do not have a factor for that line.

## Reporting a fit that went wrong

Attach the project JSON (`--formats json`), which contains the data, every setting
and the start values, and state which component or number you expected.
