"""The :class:`Spectrum` container.

A spectrum is stored on an ascending binding-energy axis.  Readers deliver whatever
the file contains; the constructor sorts, merges duplicate energies and records every
such normalisation in :attr:`Spectrum.history` so the processing chain stays
auditable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

AL_KALPHA_EV = 1486.6
MG_KALPHA_EV = 1253.6

_AXES = ("binding", "kinetic")
_UNITS = ("counts", "cps", "arbitrary")


class SpectrumError(ValueError):
    """Raised when a spectrum cannot be constructed or processed."""


@dataclass(eq=False)
class Spectrum:
    """One measured region (or survey) on a single energy axis.

    Parameters
    ----------
    energy, intensity
        Equal-length 1-D arrays.  ``energy`` is in eV on the ``axis`` given.
    axis
        ``"binding"`` (default) or ``"kinetic"``.  Fitting requires binding energy;
        use :meth:`to_binding` to convert.
    intensity_unit
        ``"counts"`` (Poisson weights available), ``"cps"`` (Poisson weights need
        ``dwell_time_s`` and ``n_scans``) or ``"arbitrary"`` (unweighted fit).
    """

    energy: np.ndarray
    intensity: np.ndarray
    name: str = ""
    axis: str = "binding"
    intensity_unit: str = "counts"
    photon_energy: float | None = None
    dwell_time_s: float | None = None
    n_scans: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        e = np.array(self.energy, dtype=float).ravel()
        i = np.array(self.intensity, dtype=float).ravel()
        if e.size != i.size:
            raise SpectrumError(f"energy ({e.size}) and intensity ({i.size}) differ in length")
        finite = np.isfinite(e) & np.isfinite(i)
        if not finite.all():
            dropped = int((~finite).sum())
            e, i = e[finite], i[finite]
            self.history.append({"step": "drop_nonfinite", "points": dropped})
        if e.size < 5:
            raise SpectrumError("a spectrum needs at least 5 finite points")
        if self.axis not in _AXES:
            raise SpectrumError(f"axis must be one of {_AXES}, got {self.axis!r}")
        if self.intensity_unit not in _UNITS:
            raise SpectrumError(
                f"intensity_unit must be one of {_UNITS}, got {self.intensity_unit!r}"
            )

        order = np.argsort(e, kind="stable")
        if not np.array_equal(order, np.arange(e.size)):
            descending = bool(np.all(np.diff(e) < 0))
            e, i = e[order], i[order]
            self.history.append(
                {
                    "step": "sort_ascending",
                    "input_order": "descending" if descending else "unsorted",
                }
            )
        if np.any(np.diff(e) == 0):
            unique, inverse = np.unique(e, return_inverse=True)
            sums = np.bincount(inverse, weights=i)
            counts = np.bincount(inverse)
            self.history.append(
                {"step": "merge_duplicate_energies", "points_removed": int(e.size - unique.size)}
            )
            e, i = unique, sums / counts
        if e.size < 5:
            raise SpectrumError("fewer than 5 distinct energies after merging duplicates")
        self.energy = e
        self.intensity = i

    # ------------------------------------------------------------------ properties
    @property
    def n(self) -> int:
        return int(self.energy.size)

    @property
    def step(self) -> float:
        """Median spacing of the energy axis (eV)."""
        return float(np.median(np.diff(self.energy)))

    @property
    def is_uniform(self) -> bool:
        d = np.diff(self.energy)
        return bool(np.allclose(d, d[0], rtol=1e-3, atol=1e-9))

    @property
    def range(self) -> tuple[float, float]:
        return float(self.energy[0]), float(self.energy[-1])

    @property
    def sigma(self) -> np.ndarray | None:
        """Per-point standard deviation under counting statistics, or ``None``.

        ``None`` means the intensity scale carries no statistical meaning
        (``"arbitrary"``) or the information needed to recover counts is missing.
        """
        if self.intensity_unit == "counts":
            return np.sqrt(np.maximum(self.intensity, 1.0))
        if self.intensity_unit == "cps":
            if self.dwell_time_s and self.n_scans:
                t = float(self.dwell_time_s) * float(self.n_scans)
                counts = np.maximum(self.intensity * t, 1.0)
                return np.sqrt(counts) / t
            return None
        return None

    # ------------------------------------------------------------------ operations
    def copy(self) -> Spectrum:
        return Spectrum(
            self.energy.copy(),
            self.intensity.copy(),
            name=self.name,
            axis=self.axis,
            intensity_unit=self.intensity_unit,
            photon_energy=self.photon_energy,
            dwell_time_s=self.dwell_time_s,
            n_scans=self.n_scans,
            metadata=dict(self.metadata),
            history=[dict(h) for h in self.history],
        )

    def crop(self, lo: float, hi: float) -> Spectrum:
        """Return the part of the spectrum with ``lo <= energy <= hi``."""
        if lo > hi:
            lo, hi = hi, lo
        mask = (self.energy >= lo - 1e-9) & (self.energy <= hi + 1e-9)
        if mask.sum() < 5:
            raise SpectrumError(
                f"crop [{lo}, {hi}] leaves {int(mask.sum())} points; spectrum covers "
                f"[{self.energy[0]:.2f}, {self.energy[-1]:.2f}]"
            )
        out = self.copy()
        out.energy = self.energy[mask]
        out.intensity = self.intensity[mask]
        out.history.append({"step": "crop", "lo": float(lo), "hi": float(hi)})
        return out

    def shift(self, delta: float, reason: str = "") -> Spectrum:
        """Return a copy with ``delta`` eV added to the energy axis (charge correction)."""
        out = self.copy()
        out.energy = self.energy + float(delta)
        out.history.append({"step": "shift", "delta_eV": float(delta), "reason": reason})
        return out

    def to_binding(self, photon_energy: float | None = None) -> Spectrum:
        """Convert a kinetic-energy spectrum to binding energy (``BE = hv - KE``)."""
        if self.axis == "binding":
            return self
        hv = photon_energy if photon_energy is not None else self.photon_energy
        if hv is None:
            raise SpectrumError("photon energy is required to convert kinetic to binding energy")
        out = self.copy()
        out.energy = hv - self.energy
        out.axis = "binding"
        out.photon_energy = float(hv)
        out.history.append({"step": "kinetic_to_binding", "photon_energy_eV": float(hv)})
        return Spectrum(**{k: v for k, v in out.__dict__.items()})

    def sha256(self) -> str:
        """Hash of the numerical content (energy and intensity, as float64)."""
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.energy, dtype=np.float64).tobytes())
        h.update(np.ascontiguousarray(self.intensity, dtype=np.float64).tobytes())
        return h.hexdigest()

    # ------------------------------------------------------------------ serialisation
    def to_dict(self, include_data: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "axis": self.axis,
            "intensity_unit": self.intensity_unit,
            "photon_energy": self.photon_energy,
            "dwell_time_s": self.dwell_time_s,
            "n_scans": self.n_scans,
            "n_points": self.n,
            "range": list(self.range),
            "sha256": self.sha256(),
            "metadata": _jsonable(self.metadata),
            "history": self.history,
        }
        if include_data:
            d["energy"] = self.energy.tolist()
            d["intensity"] = self.intensity.tolist()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Spectrum:
        return cls(
            np.asarray(d["energy"], dtype=float),
            np.asarray(d["intensity"], dtype=float),
            name=d.get("name", ""),
            axis=d.get("axis", "binding"),
            intensity_unit=d.get("intensity_unit", "counts"),
            photon_energy=d.get("photon_energy"),
            dwell_time_s=d.get("dwell_time_s"),
            n_scans=d.get("n_scans"),
            metadata=dict(d.get("metadata", {})),
            history=list(d.get("history", [])),
        )


def _jsonable(obj: Any) -> Any:
    """Convert numpy scalars/arrays inside nested containers to JSON-friendly types."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj
