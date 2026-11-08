## What this changes

<!-- One paragraph: the user-visible effect and why. -->

## Checks

- [ ] `ruff format src tests && ruff check src tests && mypy && pytest` pass locally
- [ ] New behaviour has a synthetic-data test with known truth
- [ ] A project file written by the new code passes `xps-autofit verify`
- [ ] Reference data (positions, sensitivity factors) cite their source
- [ ] `CHANGELOG.md` has an entry under *Unreleased*
