"""Reference data: elements, binding energies, spin-orbit splittings, sensitivity factors.

Values are compiled from widely used public references and are meant to *suggest*
candidates and *constrain* fits.  Verify against the NIST XPS Database and the
primary literature before publishing an assignment.
"""

from .binding_energies import REFERENCE_LINES, SPIN_ORBIT, spin_orbit, suggest_assignments
from .elements import ELEMENTS
from .sensitivity_factors import SCOFIELD_AL_KALPHA, get_rsf

__all__ = [
    "ELEMENTS",
    "REFERENCE_LINES",
    "SCOFIELD_AL_KALPHA",
    "SPIN_ORBIT",
    "get_rsf",
    "spin_orbit",
    "suggest_assignments",
]
