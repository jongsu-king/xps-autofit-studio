"""ISO 14976 (VAMAS) reader and a minimal writer.

The block layout follows Dench, Hazell & Seah, *Surf. Interface Anal.* 13, 63 (1988).
Supported: experiment modes NORM / SDP / MAP-style headers, REGULAR and IRREGULAR
scans, any technique.  Not supported: non-empty parameter inclusion/exclusion lists
(blocks after the first then omit parameters).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..core.spectrum import Spectrum

FORMAT_PREFIX = "VAMAS Surface Chemical Analysis Standard Data Transfer Format"
FORMAT_ID = FORMAT_PREFIX + " 1988 May 4"

MAP_MODES = {"MAP", "MAPDP"}
FOV_MODES = {"MAP", "MAPDP", "MAPSV", "MAPSVDP", "SEM"}
LINESCAN_MODES = {"MAPSV", "MAPSVDP", "SEM"}
SPUTTER_MODES = {"MAPDP", "MAPSVDP", "SDP", "SDPSV"}
REGIONS_MODES = {"MAP", "MAPDP", "NORM", "SDP"}
ION_TECHNIQUES = {
    "FABMS",
    "FABMS energy spec",
    "ISS",
    "SIMS",
    "SIMS energy spec",
    "SNMS",
    "SNMS energy spec",
}
SPECTRAL_TECHNIQUES = {"AES diff", "AES dir", "EDX", "ELS", "UPS", "XPS", "XRF"}


class VamasError(ValueError):
    """Raised for files that do not follow the VAMAS layout."""


class _Cursor:
    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.i = 0

    def next(self) -> str:
        if self.i >= len(self.lines):
            raise VamasError("unexpected end of file")
        s = self.lines[self.i].strip()
        self.i += 1
        return s

    def next_int(self) -> int:
        s = self.next()
        try:
            return int(float(s))
        except ValueError as exc:
            raise VamasError(f"line {self.i}: expected an integer, got {s!r}") from exc

    def next_float(self) -> float:
        s = self.next()
        try:
            return float(s)
        except ValueError as exc:
            raise VamasError(f"line {self.i}: expected a number, got {s!r}") from exc

    def next_lines(self, n: int) -> list[str]:
        return [self.next() for _ in range(n)]


@dataclass
class VamasHeader:
    institution: str
    instrument: str
    operator: str
    experiment: str
    comment: list[str]
    experiment_mode: str
    scan_mode: str
    n_spectral_regions: int | None
    experimental_variables: list[tuple[str, str]]
    n_future_block_entries: int
    n_blocks: int
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VamasBlock:
    identifier: str
    sample: str
    date: str
    comment: list[str]
    technique: str
    source_label: str
    source_energy: float
    analyser_mode: str
    pass_energy: float
    work_function: float
    species: str
    transition: str
    abscissa_label: str
    abscissa_units: str
    abscissa_start: float
    abscissa_increment: float
    variables: list[tuple[str, str]]
    signal_mode: str
    collection_time: float
    n_scans: int
    additional: list[tuple[str, str, float]]
    data: np.ndarray
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def n_points(self) -> int:
        return int(self.data.shape[1])

    def abscissa(self) -> np.ndarray:
        if self.extra.get("scan_mode") == "IRREGULAR":
            return self.data[0]
        return self.abscissa_start + self.abscissa_increment * np.arange(self.n_points)

    def ordinate(self, index: int = 0) -> np.ndarray:
        if self.extra.get("scan_mode") == "IRREGULAR":
            index += 1
        return self.data[index]


def parse_vamas(text: str) -> tuple[VamasHeader, list[VamasBlock]]:
    c = _Cursor(text)
    fmt = c.next()
    if not fmt.startswith(FORMAT_PREFIX):
        raise VamasError("not a VAMAS file (format identifier missing)")
    institution, instrument, operator, experiment = c.next(), c.next(), c.next(), c.next()
    comment = c.next_lines(c.next_int())
    mode = c.next()
    scan_mode = c.next()
    n_regions = c.next_int() if mode in REGIONS_MODES else None
    extra: dict[str, Any] = {}
    if mode in MAP_MODES:
        extra["n_analysis_positions"] = c.next_int()
        extra["n_x"] = c.next_int()
        extra["n_y"] = c.next_int()
    n_exp_vars = c.next_int()
    exp_vars = [(c.next(), c.next()) for _ in range(n_exp_vars)]
    n_incl = c.next_int()
    if n_incl != 0:
        raise VamasError(
            "parameter inclusion/exclusion lists are not supported "
            f"({n_incl} entries); export the file without them"
        )
    n_manual = c.next_int()
    extra["manual_items"] = [c.next_int() for _ in range(n_manual)]
    n_future_exp = c.next_int()
    n_future_block = c.next_int()
    extra["future_experiment_entries"] = c.next_lines(n_future_exp)
    n_blocks = c.next_int()
    header = VamasHeader(
        institution,
        instrument,
        operator,
        experiment,
        comment,
        mode,
        scan_mode,
        n_regions,
        exp_vars,
        n_future_block,
        n_blocks,
        extra,
    )
    blocks = [_parse_block(c, header) for _ in range(n_blocks)]
    return header, blocks


def _parse_block(c: _Cursor, h: VamasHeader) -> VamasBlock:
    mode, scan_mode = h.experiment_mode, h.scan_mode
    extra: dict[str, Any] = {"scan_mode": scan_mode, "experiment_mode": mode}
    identifier = c.next()
    sample = c.next()
    y, mo, d, hh, mi, ss = (c.next_int() for _ in range(6))
    extra["gmt_offset_hours"] = c.next_int()
    date = f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mi:02d}:{ss:02d}"
    comment = c.next_lines(c.next_int())
    technique = c.next()
    if mode in MAP_MODES:
        extra["x_coordinate"] = c.next_int()
        extra["y_coordinate"] = c.next_int()
    extra["experimental_variable_values"] = [c.next_float() for _ in h.experimental_variables]
    source_label = c.next()
    if mode in SPUTTER_MODES or technique in ION_TECHNIQUES:
        extra["sputter_ion"] = (c.next_int(), c.next_int(), c.next_int())
    source_energy = c.next_float()
    extra["source_strength"] = c.next_float()
    extra["source_beam_width"] = (c.next_float(), c.next_float())
    if mode in FOV_MODES:
        extra["field_of_view"] = (c.next_float(), c.next_float())
    if mode in LINESCAN_MODES:
        extra["linescan"] = [c.next_int() for _ in range(6)]
    extra["source_polar"] = c.next_float()
    extra["source_azimuth"] = c.next_float()
    analyser_mode = c.next()
    pass_energy = c.next_float()
    if technique == "AES diff":
        extra["differential_width"] = c.next_float()
    extra["magnification"] = c.next_float()
    work_function = c.next_float()
    extra["target_bias"] = c.next_float()
    extra["analysis_width"] = (c.next_float(), c.next_float())
    extra["takeoff_polar"] = c.next_float()
    extra["takeoff_azimuth"] = c.next_float()
    species = c.next()
    transition = c.next()
    extra["particle_charge"] = c.next_int()
    if scan_mode == "REGULAR":
        abscissa_label, abscissa_units = c.next(), c.next()
        abscissa_start, abscissa_increment = c.next_float(), c.next_float()
    else:
        abscissa_label, abscissa_units, abscissa_start, abscissa_increment = "", "", 0.0, 0.0
    n_vars = c.next_int()
    variables = [(c.next(), c.next()) for _ in range(n_vars)]
    signal_mode = c.next()
    collection_time = c.next_float()
    n_scans = c.next_int()
    extra["signal_time_correction"] = c.next_float()
    if technique in SPECTRAL_TECHNIQUES and mode in SPUTTER_MODES:
        extra["sputter_source"] = [c.next_float() for _ in range(6)] + [c.next()]
    extra["sample_tilt"] = (c.next_float(), c.next_float())
    extra["sample_rotation"] = c.next_float()
    n_add = c.next_int()
    additional = [(c.next(), c.next(), c.next_float()) for _ in range(n_add)]
    extra["future_block_entries"] = c.next_lines(h.n_future_block_entries)
    n_ord = c.next_int()
    extra["ordinate_minmax"] = [(c.next_float(), c.next_float()) for _ in range(n_vars)]
    if n_vars == 0 or n_ord % n_vars != 0:
        raise VamasError(f"block {identifier!r}: {n_ord} ordinate values for {n_vars} variables")
    values = np.array([c.next_float() for _ in range(n_ord)], dtype=float)
    data = values.reshape(n_ord // n_vars, n_vars).T
    if scan_mode == "IRREGULAR":
        abscissa_label, abscissa_units = variables[0]
    return VamasBlock(
        identifier,
        sample,
        date,
        comment,
        technique,
        source_label,
        source_energy,
        analyser_mode,
        pass_energy,
        work_function,
        species,
        transition,
        abscissa_label,
        abscissa_units,
        abscissa_start,
        abscissa_increment,
        variables,
        signal_mode,
        collection_time,
        n_scans,
        additional,
        data,
        extra,
    )


def _intensity_unit(label: str, units: str, values: np.ndarray, signal_mode: str) -> str:
    text = f"{label} {units}".lower()
    if any(k in text for k in ("c/s", "cps", "counts/s", "counts per second")):
        return "cps"
    if "count" in text:
        return "counts"
    if signal_mode.lower().startswith("pulse") and np.all(np.abs(values - np.round(values)) < 1e-9):
        return "counts"
    return "arbitrary"


def _block_name(identifier: str, species: str, transition: str) -> str:
    """Block identifier plus species and transition, unless the identifier names them.

    Instruments often write the region into the identifier already ("P3HT C 1s"); the
    name then stays "P3HT C 1s" instead of "P3HT C 1s C 1s".
    """
    ident = (identifier or "").strip()
    label = " ".join(t for t in (species, transition) if t).strip()
    if not label:
        return ident
    if re.search(rf"(?<![\w]){re.escape(label)}(?![\w])", ident, re.IGNORECASE):
        return ident
    return f"{ident} {label}".strip()


def block_to_spectrum(block: VamasBlock, header: VamasHeader, variable: int = 0) -> Spectrum:
    x = block.abscissa()
    y = block.ordinate(variable)
    label = block.abscissa_label.lower()
    if "kinetic" in label:
        axis = "kinetic"
    elif "binding" in label:
        axis = "binding"
    else:
        axis = "binding"
    var_label, var_units = block.variables[
        variable + (1 if block.extra.get("scan_mode") == "IRREGULAR" else 0)
    ]
    unit = _intensity_unit(var_label, var_units, y, block.signal_mode)
    name = _block_name(block.identifier, block.species, block.transition)
    meta: dict[str, Any] = {
        "format": "VAMAS",
        "institution": header.institution,
        "instrument": header.instrument,
        "operator": header.operator,
        "experiment": header.experiment,
        "block": block.identifier,
        "sample": block.sample,
        "date": block.date,
        "technique": block.technique,
        "species": block.species,
        "transition": block.transition,
        "source": block.source_label,
        "source_energy_eV": block.source_energy,
        "analyser_mode": block.analyser_mode,
        "pass_energy_eV": block.pass_energy,
        "work_function_eV": block.work_function,
        "abscissa_label": block.abscissa_label,
        "abscissa_units": block.abscissa_units,
        "variable": var_label,
        "variable_units": var_units,
        "signal_mode": block.signal_mode,
        "comment": block.comment,
        "additional_parameters": block.additional,
    }
    if "binding" not in label and "kinetic" not in label:
        meta["warning"] = (
            f"abscissa label {block.abscissa_label!r} unrecognised; assumed binding energy"
        )
    spec = Spectrum(
        x,
        y,
        name=name,
        axis=axis,
        intensity_unit=unit,
        photon_energy=float(block.source_energy) if block.source_energy > 0 else None,
        dwell_time_s=block.collection_time if block.collection_time > 0 else None,
        n_scans=block.n_scans if block.n_scans > 0 else None,
        metadata=meta,
    )
    if spec.axis == "kinetic":
        spec = spec.to_binding()
    return spec


def read_vamas(path: str | Path, **_: Any) -> list[Spectrum]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    header, blocks = parse_vamas(text)
    out = []
    for b in blocks:
        s = block_to_spectrum(b, header)
        s.metadata["path"] = str(path)
        out.append(s)
    return out


# ------------------------------------------------------------------------------ writer
def write_vamas(
    path: str | Path,
    spectra: list[Spectrum],
    *,
    institution: str = "",
    instrument: str = "",
    operator: str = "",
    experiment: str = "",
    axis: str = "binding",
) -> Path:
    """Write uniformly sampled spectra as a NORM / REGULAR VAMAS file.

    ``axis="kinetic"`` stores the abscissa as kinetic energy (requires the photon
    energy on every spectrum); otherwise binding energy is written.
    """
    out: list[str] = [
        FORMAT_ID,
        institution,
        instrument,
        operator,
        experiment,
        "0",  # comment lines
        "NORM",
        "REGULAR",
        str(len(spectra)),  # spectral regions
        "0",  # experimental variables
        "0",  # inclusion/exclusion entries
        "0",  # manually entered items
        "0",
        "0",  # future upgrade experiment / block entries
        str(len(spectra)),
    ]
    for s in spectra:
        if not s.is_uniform:
            raise VamasError(f"{s.name!r}: VAMAS REGULAR scans need a uniform energy grid")
        hv = s.photon_energy or 0.0
        if axis == "kinetic":
            if not hv:
                raise VamasError(f"{s.name!r}: photon energy required to write kinetic energy")
            x = hv - s.energy[::-1]
            y = s.intensity[::-1]
            label = "kinetic energy"
        else:
            x, y, label = s.energy, s.intensity, "binding energy"
        var_label = {"counts": "counts", "cps": "c/s"}.get(s.intensity_unit, "Intensity")
        out += [
            s.name or "block",
            s.metadata.get("sample", s.name or "sample"),
            "2026",
            "1",
            "1",
            "0",
            "0",
            "0",  # date/time
            "0",  # GMT offset
            "0",  # comment lines
            s.metadata.get("technique", "XPS"),
            s.metadata.get("source", "Al K-alpha" if abs(hv - 1486.6) < 1 else "X-ray"),
            f"{hv:.4f}",
            "0",
            "0",
            "0",  # source energy, strength, beam width x, y
            "0",
            "0",  # source polar, azimuth
            s.metadata.get("analyser_mode", "FAT"),
            f"{s.metadata.get('pass_energy_eV', 0.0)}",
            "1",  # magnification
            f"{s.metadata.get('work_function_eV', 0.0)}",
            "0",  # target bias
            "0",
            "0",  # analysis width
            "0",
            "0",  # take-off polar, azimuth
            s.metadata.get("species", ""),
            s.metadata.get("transition", ""),
            "-1",  # particle charge
            label,
            "eV",
            f"{x[0]:.6f}",
            f"{x[1] - x[0]:.6f}",
            "1",
            var_label,
            "d",  # one corresponding variable
            "pulse counting" if s.intensity_unit == "counts" else "analogue",
            f"{s.dwell_time_s or 0.0}",
            f"{s.n_scans or 1}",
            "0",
            "0",
            "0",
            "0",  # sample tilt polar, azimuth, rotation
            "0",  # additional numerical parameters
            str(len(y)),
            f"{float(np.min(y)):.6f}",
            f"{float(np.max(y)):.6f}",
        ]
        out += [f"{v:.6f}" for v in y]
    out.append("end of experiment")
    p = Path(path)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return p
