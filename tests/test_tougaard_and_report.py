"""Three-parameter Tougaard cross-sections and the PDF report."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xps_autofit.automation.batch_fitting import RunOptions, fit_file
from xps_autofit.automation.model_selection import select_model
from xps_autofit.cli import main
from xps_autofit.core.background import (
    TOUGAARD_CROSS_SECTIONS,
    BackgroundError,
    BackgroundSpec,
    compute_background,
    tougaard_kernel,
)
from xps_autofit.core.region import RegionSpec
from xps_autofit.export.report import (
    ReportRegion,
    _page_title,
    component_rows,
    summary_rows,
    write_report,
)
from xps_autofit.recipes import load_recipe
from xps_autofit.synthetic import example_dataset, p3ht_s2p, synthesize


def _pages(path: Path) -> int:
    raw = path.read_bytes()
    return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")


def test_cross_sections_and_presets():
    x = np.linspace(280.0, 300.0, 401)
    universal = tougaard_kernel(x, 1643.0)
    assert np.allclose(universal, tougaard_kernel(x, 1643.0, None))
    t = x[:, None] - x[None, :]
    expected = np.where(t > 0, t / (1643.0 + t**2) ** 2, 0.0) * np.gradient(x)[None, :]
    assert np.allclose(universal, expected), "the two-parameter form is unchanged"
    polymer = tougaard_kernel(x, 551.0, 436.0)
    assert np.all(polymer >= 0) and np.all(np.triu(polymer, 1) == 0)
    # the polymer loss rises faster than linearly over the first 20 eV, the universal one slower
    T = np.array([2.0, 20.0])
    f_u = T / (1643.0 + T**2) ** 2
    f_p = T / ((551.0 - T**2) ** 2 + 436.0 * T**2)
    assert f_u[1] / f_u[0] < 10.0 < f_p[1] / f_p[0]
    spec = BackgroundSpec.from_dict({"type": "tougaard", "tougaard_cross_section": "polymer"})
    assert (spec.tougaard_C, spec.tougaard_D) == TOUGAARD_CROSS_SECTIONS["polymer"]
    assert spec.tougaard_cross_section == "polymer"
    assert BackgroundSpec(type="tougaard").tougaard_cross_section == "universal"
    assert BackgroundSpec(type="tougaard", tougaard_C=300.0).tougaard_cross_section == "custom"
    assert BackgroundSpec.from_dict(spec.to_dict()).tougaard_D == 436.0
    for bad in ({"tougaard_cross_section": "metal"}, {"tougaard_C": 0.0}, {"tougaard_D": -1.0}):
        with pytest.raises(BackgroundError):
            BackgroundSpec.from_dict({"type": "tougaard", **bad})
    # a static background with the polymer form meets both averaged endpoints
    spectrum, _ = synthesize(p3ht_s2p(True), seed=1)
    bg = compute_background(spectrum.energy, spectrum.intensity, spec)
    assert bg.info["D"] == 436.0
    y = spectrum.intensity
    assert np.mean(bg.values[-3:]) == pytest.approx(np.mean(y[-3:]), rel=1e-9)
    assert bg.values[0] == pytest.approx(np.mean(y[:3]), rel=1e-9)
    # the generator's polymer background and the fitted one have the same form
    region = replace(p3ht_s2p(True), background="tougaard", tougaard_C=551.0, tougaard_D=436.0)
    synth, _ = synthesize(region, seed=1)
    assert synth.intensity[-1] > synth.intensity[0]


def test_polymer_cross_section_recovers_polymer_backgrounds():
    """On S 2p with a polymer-type loss background, the polymer cross-section gives the
    areas back markedly better than the universal one (fixed component count)."""
    base = load_recipe("p3ht").region("S 2p")
    errors = {"universal": [], "polymer": []}
    for seed in (1, 2):
        truth_region = replace(
            p3ht_s2p(True),
            background="tougaard",
            tougaard_C=551.0,
            tougaard_D=436.0,
            background_lo=400.0,
            background_hi=1400.0,
        )
        spec, truth = synthesize(truth_region, seed=seed)
        true_areas = sorted(
            (c["area"] * (1 + c["doublet"]["area_ratio"]) for c in truth["components"]),
            reverse=True,
        )
        for name in errors:
            bspec = BackgroundSpec.from_dict({"type": "tougaard", "tougaard_cross_section": name})
            region: RegionSpec = replace(base, background=bspec, shape="voigt")
            result = select_model(spec, region, fixed_n=2).best.result
            areas = sorted(
                (
                    sum(c.area for c in result.components if c.parent == m.parent)
                    for m in result.majors()
                ),
                reverse=True,
            )
            errors[name].append(max(abs(a - t) / t for a, t in zip(areas, true_areas)))
    assert max(errors["polymer"]) < 0.02
    assert min(errors["universal"]) > 2 * max(errors["polymer"])


def test_report_pdf(tmp_path):
    data = tmp_path / "data"
    example_dataset(data, seed=4)
    rep = fit_file(
        data / "p3ht_aged_multi.vms",
        load_recipe("p3ht"),
        RunOptions(tmp_path / "out", formats=("report",)),
    )
    pdf = Path(rep.report_pdf)
    assert pdf.name == "p3ht_aged_multi_report.pdf" and pdf.read_bytes().startswith(b"%PDF")
    fitted = [r for r in rep.regions if r.selection is not None and r.selection.best is not None]
    assert _pages(pdf) == 1 + len(fitted) == 3
    # the table builders behind the pages
    sel = fitted[0].selection
    region = ReportRegion(
        sel.region.name,
        sel.best.result,
        status="ok",
        variant=sel.best.variant,
        assignments={sel.best.result.majors()[0].label: "test state (1.0)"},
    )
    assert summary_rows([region])[0][:3] == [
        sel.region.name,
        "ok",
        str(len(sel.best.result.majors())),
    ]
    rows = component_rows(region)
    assert rows[0][-1] == "test state (1.0)" and len(rows) == len(sel.best.result.components)
    assert _page_title("P3HT C 1s", "C 1s") == "P3HT C 1s"
    assert _page_title("film A", "C 1s") == "film A - C 1s" and _page_title("", "C 1s") == "C 1s"
    # a report without a composition still writes
    single = write_report(tmp_path / "one.pdf", [region], None, sample="x", source="", recipe="")
    assert _pages(single) == 2
    # the command line: an ad-hoc Tougaard region with the polymer cross-section
    out = tmp_path / "cli"
    rc = main(
        [
            "fit",
            str(data / "p3ht_aged_S2p.csv"),
            "--element",
            "S",
            "--line",
            "2p",
            "--background",
            "tougaard",
            "--tougaard-cross-section",
            "polymer",
            "--output",
            str(out),
            "--formats",
            "report,json",
        ]
    )
    assert rc == 0 and _pages(out / "p3ht_aged_S2p_report.pdf") == 2
    (project,) = out.glob("p3ht_aged_S2p__*.json")
    saved = json.loads(project.read_text())
    assert '"tougaard_D": 436.0' in json.dumps(saved)
