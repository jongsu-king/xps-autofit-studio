"""Compare fitted components with the generating truth of the synthetic examples.

Usage: python examples/compare_with_truth.py <data_dir> <results_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from xps_autofit.core.peak_shapes import voigt_fwhm


def main(data_dir: str, results_dir: str) -> int:
    truth = json.loads((Path(data_dir) / "truth.json").read_text())
    comps = pd.read_csv(Path(results_dir) / "summary_components.csv")
    comps = comps[~comps["is_minor"]]
    rows = []
    for _, r in comps.iterrows():
        name = Path(r["file"]).name
        t = truth.get(name)
        if t is None:
            continue
        blocks = t.get("blocks", [t])
        for b in blocks:
            for c in b["components"]:
                if c["label"] == r["label"]:
                    rows.append(
                        {
                            "file": name,
                            "label": c["label"],
                            "center_true": c["center"],
                            "center_fit": r["center_eV"],
                            "d_center": r["center_eV"] - c["center"],
                            "area_true": c["area"],
                            "area_fit": r["area"],
                            "area_rel_%": 100 * (r["area"] - c["area"]) / c["area"],
                            "fwhm_true": voigt_fwhm(c["fwhm_g"], c["fwhm_l"]),
                            "fwhm_fit": r["fwhm_eV"],
                        }
                    )
    if not rows:
        print("no matching components found")
        return 1
    with pd.option_context("display.width", 160, "display.float_format", "{:.3f}".format):
        print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
