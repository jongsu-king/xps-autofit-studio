"""Synthetic spectra with known truth, for tests, benchmarks and demonstrations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.integrate import cumulative_trapezoid

from .core.constraints import DoubletSpec
from .core.peak_shapes import evaluate
from .core.spectrum import AL_KALPHA_EV, Spectrum
from .readers.excel_reader import write_excel
from .readers.vamas_reader import write_vamas


@dataclass
class SynthComponent:
    label: str
    center: float
    area: float
    fwhm_g: float = 1.0
    fwhm_l: float = 0.2
    doublet: DoubletSpec | None = None
    shape: str = "voigt"
    """``"voigt"`` or ``"doniach_sunjic"`` (asymmetric metallic line, uses ``asym``)."""
    asym: float = 0.0

    def widths(self) -> dict[str, float]:
        w = {"fwhm_g": self.fwhm_g, "fwhm_l": self.fwhm_l}
        if self.shape == "doniach_sunjic":
            w["asym"] = self.asym
        return w

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "doublet"}
        d["doublet"] = self.doublet.to_dict() if self.doublet else None
        return d


@dataclass
class SynthRegion:
    name: str
    lo: float
    hi: float
    step: float
    components: list[SynthComponent]
    background_lo: float = 300.0
    background_hi: float = 600.0
    background: str = "shirley"
    """``shirley``, ``linear``, ``tougaard`` (loss integral of the peaks with
    ``tougaard_C`` / ``tougaard_D``) or anything else for a flat background."""
    element: str | None = None
    line: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    tougaard_C: float = 1643.0
    tougaard_D: float | None = None


def shirley_like_background(x: np.ndarray, signal: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """A background that the Shirley algorithm reproduces exactly on noiseless data."""
    q = cumulative_trapezoid(signal, x, initial=0.0)
    return lo + (hi - lo) * q / q[-1]


def synthesize(
    region: SynthRegion,
    seed: int | None = 0,
    noise: str = "poisson",
    name: str = "",
) -> tuple[Spectrum, dict[str, Any]]:
    """Return a spectrum and the truth used to generate it."""
    x = np.arange(region.lo, region.hi + region.step / 2, region.step)
    signal = np.zeros_like(x)
    for c in region.components:
        signal += evaluate(c.shape, x, c.area, c.center, **c.widths())
        if c.doublet is not None:
            signal += evaluate(
                c.shape,
                x,
                c.area * c.doublet.area_ratio,
                c.center + c.doublet.splitting,
                **c.widths(),
            )
    if region.background == "shirley":
        bg = shirley_like_background(x, signal, region.background_lo, region.background_hi)
    elif region.background == "tougaard":
        from .core.background import tougaard_kernel

        k = tougaard_kernel(x, region.tougaard_C, region.tougaard_D) @ signal
        bg = region.background_lo + (region.background_hi - region.background_lo) * k / k[-1]
    elif region.background == "linear":
        bg = region.background_lo + (region.background_hi - region.background_lo) * (x - x[0]) / (
            x[-1] - x[0]
        )
    else:
        bg = np.full_like(x, region.background_lo)
    clean = signal + bg
    if noise == "poisson":
        rng = np.random.default_rng(seed)
        y = rng.poisson(np.maximum(clean, 0.0)).astype(float)
    elif noise == "none":
        y = clean.copy()
    else:
        raise ValueError("noise must be 'poisson' or 'none'")
    spec = Spectrum(
        x,
        y,
        name=name or region.name,
        intensity_unit="counts",
        photon_energy=AL_KALPHA_EV,
        metadata={"synthetic": True, "region": region.name, **region.extra},
    )
    truth = {
        "region": region.name,
        "element": region.element,
        "line": region.line,
        "components": [c.to_dict() for c in region.components],
        "background": {
            "type": region.background,
            "lo": region.background_lo,
            "hi": region.background_hi,
        },
        "noise": noise,
        "seed": seed,
        "n_points": int(x.size),
        "step": region.step,
    }
    return spec, truth


S2P = DoubletSpec(splitting=1.18, area_ratio=0.5)
BI4F = DoubletSpec(splitting=5.31, area_ratio=0.75)


def p3ht_s2p(oxidized: bool = False) -> SynthRegion:
    comps = [SynthComponent("thiophene C-S-C", 164.0, 20000.0, 0.85, 0.15, S2P)]
    if oxidized:
        comps.append(SynthComponent("sulfonate/sulfate", 168.4, 3000.0, 1.4, 0.15, S2P))
    return SynthRegion("S 2p", 158.0, 172.0, 0.05, comps, 300.0, 600.0, element="S", line="2p")


def p3ht_c1s() -> SynthRegion:
    comps = [
        SynthComponent("C-C/C-H", 284.8, 50000.0, 1.0, 0.1),
        SynthComponent("C-S/C-N", 285.6, 15000.0, 1.0, 0.1),
        SynthComponent("C-O", 286.5, 5000.0, 1.1, 0.1),
        SynthComponent("O-C=O", 288.8, 2000.0, 1.2, 0.1),
    ]
    return SynthRegion("C 1s", 280.0, 292.0, 0.05, comps, 500.0, 900.0, element="C", line="1s")


def cu2p3_mixed() -> SynthRegion:
    comps = [
        SynthComponent("Cu(0)/Cu(I)", 932.5, 80000.0, 1.1, 0.4),
        SynthComponent("Cu(II) CuO", 933.8, 15000.0, 1.6, 0.4),
        SynthComponent("satellite A", 941.0, 8000.0, 3.0, 0.4),
        SynthComponent("satellite B", 943.8, 6000.0, 2.5, 0.4),
    ]
    return SynthRegion(
        "Cu 2p3/2", 926.0, 950.0, 0.1, comps, 2000.0, 3500.0, element="Cu", line="2p3/2"
    )


def au4f_metal(asym: float = 0.10) -> SynthRegion:
    """Metallic Au 4f: one spin-orbit doublet with a Doniach-Sunjic tail (``asym=0``
    gives the symmetric Voigt doublet of the same widths)."""
    doublet = DoubletSpec(splitting=3.67, area_ratio=0.75)
    shape = "doniach_sunjic" if asym > 0 else "voigt"
    comps = [SynthComponent("Au(0)", 84.0, 60000.0, 0.55, 0.30, doublet, shape, asym)]
    return SynthRegion("Au 4f", 80.0, 92.0, 0.05, comps, 400.0, 700.0, element="Au", line="4f")


def synthesize_survey(
    composition: dict[str, float],
    seed: int | None = 0,
    lo: float = 0.0,
    hi: float = 1200.0,
    step: float = 0.5,
    fwhm_g: float = 1.6,
    fwhm_l: float = 0.4,
    scale: float = 20000.0,
    baseline: float = 400.0,
    step_fraction: float = 0.15,
    photon_energy: float = AL_KALPHA_EV,
    name: str = "survey",
) -> tuple[Spectrum, dict[str, Any]]:
    """A survey spectrum of the elements in ``composition`` (symbol -> relative amount).

    Every line of the element in :data:`~xps_autofit.database.survey_lines.SURVEY_LINES`
    is placed at its typical position (Auger lines converted with ``photon_energy``)
    with an area proportional to amount x relative intensity x ``scale``.  Each peak
    adds a Shirley-like step of ``step_fraction`` of its height to the background on
    the high-binding-energy side; Poisson noise is applied.
    """
    from .database.survey_lines import SURVEY_LINES

    x = np.arange(lo, hi + step / 2, step)
    signal = np.zeros_like(x)
    placed: list[dict[str, Any]] = []
    heights = 0.0
    areas = 0.0
    for element, amount in composition.items():
        for line in SURVEY_LINES:
            if line.element != element:
                continue
            e = photon_energy - line.energy if line.kind == "auger" else line.energy
            if not lo + 3 * fwhm_g < e < hi - 3 * fwhm_g:
                continue
            area = scale * amount * line.intensity
            comp = evaluate("voigt", x, area, e, fwhm_g=fwhm_g, fwhm_l=fwhm_l)
            signal += comp
            heights += float(comp.max())
            areas += area
            placed.append({"element": element, "line": line.line, "energy": e, "area": area})
    if areas > 0:
        kappa = step_fraction * heights / areas
        bg = baseline + kappa * cumulative_trapezoid(signal, x, initial=0.0)
    else:
        bg = np.full_like(x, baseline)
    bg = bg + 0.05 * baseline * (x - x[0]) / max(x[-1] - x[0], 1e-9)
    clean = signal + bg
    rng = np.random.default_rng(seed)
    y = rng.poisson(np.maximum(clean, 0.0)).astype(float)
    spec = Spectrum(
        x,
        y,
        name=name,
        intensity_unit="counts",
        photon_energy=photon_energy,
        metadata={"synthetic": True, "survey": True, "composition": dict(composition)},
    )
    truth = {
        "composition": dict(composition),
        "lines": placed,
        "fwhm_g": fwhm_g,
        "fwhm_l": fwhm_l,
        "baseline": baseline,
        "step_fraction": step_fraction,
        "seed": seed,
        "photon_energy": photon_energy,
    }
    return spec, truth


def example_dataset(out_dir: str | Path, seed: int = 1) -> list[Path]:
    """Write a small example data set in several file formats and a ``truth.json``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    truths: dict[str, Any] = {}

    def save_csv(
        spec: Spectrum,
        truth: dict[str, Any],
        filename: str,
        descending: bool = False,
        sep: str = ",",
        header: str = "Binding Energy (eV),Counts",
    ) -> None:
        e, i = spec.energy, spec.intensity
        if descending:
            e, i = e[::-1], i[::-1]
        lines = [header.replace(",", sep)] + [f"{a:.3f}{sep}{int(b)}" for a, b in zip(e, i)]
        p = out / filename
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(p)
        truths[filename] = truth

    s_fresh, t = synthesize(p3ht_s2p(False), seed=seed, name="P3HT fresh S 2p")
    save_csv(s_fresh, t, "p3ht_fresh_S2p.csv")
    s_aged, t = synthesize(p3ht_s2p(True), seed=seed + 1, name="P3HT aged S 2p")
    save_csv(s_aged, t, "p3ht_aged_S2p.csv")
    c1s, t = synthesize(p3ht_c1s(), seed=seed + 2, name="P3HT C 1s")
    save_csv(c1s, t, "p3ht_C1s.csv")
    cu, t = synthesize(cu2p3_mixed(), seed=seed + 3, name="Cu2O/CuO Cu 2p3/2")
    save_csv(
        cu, t, "cu2o_Cu2p3.txt", descending=True, sep="\t", header="Binding Energy (eV),Counts"
    )
    survey, t = synthesize_survey(
        {"Cu": 1.0, "O": 1.4, "C": 2.5, "N": 0.15}, seed=seed + 4, name="Cu2O/CuO survey"
    )
    save_csv(survey, t, "cu2o_survey.csv", descending=True)
    # kinetic-energy export of the fresh S 2p
    ke = AL_KALPHA_EV - s_fresh.energy
    p = out / "p3ht_fresh_S2p_kinetic.csv"
    p.write_text(
        "Kinetic Energy (eV),Counts\n"
        + "\n".join(f"{a:.3f},{int(b)}" for a, b in zip(ke, s_fresh.intensity))
        + "\n",
        encoding="utf-8",
    )
    paths.append(p)
    truths[p.name] = truths["p3ht_fresh_S2p.csv"]
    # multi-region VAMAS file (kinetic energy axis)
    blocks = []
    for spec, species, transition in ((s_aged, "S", "2p"), (c1s, "C", "1s")):
        b = spec.copy()
        b.metadata.update({"species": species, "transition": transition, "sample": "P3HT aged"})
        blocks.append(b)
    p = write_vamas(
        out / "p3ht_aged_multi.vms",
        blocks,
        institution="example",
        instrument="synthetic",
        axis="kinetic",
    )
    paths.append(p)
    truths[p.name] = {"blocks": [truths["p3ht_aged_S2p.csv"], truths["p3ht_C1s.csv"]]}
    # the same two regions as an Excel workbook, one worksheet per region
    sheets = []
    for spec, title in ((s_aged, "S 2p"), (c1s, "C 1s")):
        b = spec.copy()
        b.name = title
        sheets.append(b)
    p = write_excel(out / "p3ht_aged_multi.xlsx", sheets, layout="sheets", metadata=True)
    paths.append(p)
    truths[p.name] = truths["p3ht_aged_multi.vms"]
    (out / "truth.json").write_text(json.dumps(truths, indent=1), encoding="utf-8")
    paths.append(out / "truth.json")
    return paths
