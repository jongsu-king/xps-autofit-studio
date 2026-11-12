"""Analysis recipes: a named set of regions with constraints, candidates and RSFs.

Built-in recipes live next to this module as YAML; ``load_recipe`` accepts either a
built-in name or a path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..core.quantification import QuantCorrection
from ..core.region import RegionSpec


@dataclass
class ChargeReference:
    region: str
    value: float
    component: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Recipe:
    name: str
    description: str = ""
    photon_energy: float | None = None
    charge_reference: ChargeReference | None = None
    regions: list[RegionSpec] = field(default_factory=list)
    source: str = ""
    references: list[str] = field(default_factory=list)
    quantification: QuantCorrection = field(default_factory=QuantCorrection)
    """Energy-dependent correction applied on top of the RSFs (none by default)."""
    rsf_library: str | None = None
    """Path of an instrument RSF library (CSV / YAML) whose factors replace the
    regions' ``rsf`` where it has an entry; relative paths are resolved next to the
    recipe file."""

    def region(self, name: str) -> RegionSpec | None:
        for r in self.regions:
            if r.name.lower() == name.lower():
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "photon_energy": self.photon_energy,
            "charge_reference": self.charge_reference.to_dict() if self.charge_reference else None,
            "regions": [r.to_dict() for r in self.regions],
            "source": self.source,
            "references": list(self.references),
            "quantification": self.quantification.to_dict(),
            "rsf_library": self.rsf_library,
        }


def recipe_from_dict(d: dict[str, Any], source: str = "") -> Recipe:
    cr = d.get("charge_reference")
    charge = None
    if cr:
        charge = ChargeReference(
            region=str(cr["region"]),
            value=float(cr["value"]),
            component=cr.get("component"),
            note=str(cr.get("note", "")),
        )
    regions = [RegionSpec.from_dict(r) for r in d.get("regions", [])]
    names = [r.name for r in regions]
    if len(set(names)) != len(names):
        raise ValueError(f"recipe {d.get('name')!r} has duplicate region names")
    return Recipe(
        name=str(d.get("name", Path(source).stem if source else "recipe")),
        description=str(d.get("description", "")),
        photon_energy=(float(d["photon_energy"]) if d.get("photon_energy") is not None else None),
        charge_reference=charge,
        regions=regions,
        source=source,
        references=[str(r) for r in d.get("references", [])],
        quantification=QuantCorrection.from_dict(d.get("quantification")),
        rsf_library=_library_path(d.get("rsf_library"), source),
    )


def _library_path(value: Any, source: str) -> str | None:
    """An RSF library path from a recipe, resolved next to a recipe file."""
    if not value:
        return None
    p = Path(str(value)).expanduser()
    if not p.is_absolute() and source and not source.startswith("builtin:"):
        p = Path(source).parent / p
    return str(p)


def builtin_recipe_names() -> list[str]:
    files = resources.files(__package__)
    return sorted(p.name[:-5] for p in files.iterdir() if p.name.endswith(".yaml"))


def load_recipe(name_or_path: str | Path) -> Recipe:
    p = Path(name_or_path)
    if p.suffix.lower() in (".yaml", ".yml") and p.is_file():
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return recipe_from_dict(data, str(p))
    name = str(name_or_path)
    if name in builtin_recipe_names():
        text = resources.files(__package__).joinpath(f"{name}.yaml").read_text(encoding="utf-8")
        return recipe_from_dict(yaml.safe_load(text), f"builtin:{name}")
    raise FileNotFoundError(
        f"recipe {name_or_path!r} is neither a YAML file nor a built-in recipe "
        f"({', '.join(builtin_recipe_names())})"
    )


def save_recipe(recipe: Recipe, path: str | Path) -> Path:
    p = Path(path)
    p.write_text(
        yaml.safe_dump(recipe.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return p
