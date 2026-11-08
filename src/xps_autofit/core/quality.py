"""A single quality grade for a fit, derived from the statistics and the checks.

The grade is a *summary for triage*, not a statistical test: it tells a user which
of fifty batch results deserve a look first.  Every deduction is listed in
``reasons`` so that the letter can always be traced back to a number.

Scoring (100 points, deductions capped per category):

====================  =============================================  =========
Category              Rule                                           Max loss
====================  =============================================  =========
goodness of fit       weighted fits: ``|log10(chi2red)|`` x 30        30
residual structure    Durbin-Watson < 1.0: 25; < 1.5: 10              25
physical checks       each violation 25                               50
warnings              each warning 5                                  20
parameter errors      no covariance 15; area error > 50 %: 10 each    25
degeneracy            max cross-component |r| > 0.98: 10, > 0.995: 20 20
convergence           optimiser failure 20                            20
====================  =============================================  =========

Letters: A >= 90, B >= 75, C >= 60, D >= 40, E below.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .constraints import Violation
from .fitting import FitResult

LETTERS: tuple[tuple[float, str], ...] = ((90, "A"), (75, "B"), (60, "C"), (40, "D"), (0, "E"))

DESCRIPTIONS = {
    "A": "report as is",
    "B": "good; read the warnings",
    "C": "usable; check the flagged components",
    "D": "doubtful; inspect residual and model table",
    "E": "do not report without manual work",
}


@dataclass
class FitGrade:
    letter: str
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        return DESCRIPTIONS[self.letter]

    def to_dict(self) -> dict[str, Any]:
        return {"letter": self.letter, "score": round(self.score, 1), "reasons": list(self.reasons)}


def _letter(score: float) -> str:
    for threshold, letter in LETTERS:
        if score >= threshold:
            return letter
    return "E"


def grade_fit(
    result: FitResult,
    violations: Iterable[Violation] = (),
    warnings: Iterable[Violation] = (),
) -> FitGrade:
    """Grade ``result`` given the physical checks already run on it."""
    s = result.stats
    reasons: list[str] = []
    score = 100.0

    if s.weighted and s.redchi > 0:
        dev = abs(math.log10(s.redchi))
        loss = min(30.0, 30.0 * dev)
        if loss >= 1.0:
            score -= loss
            reasons.append(f"reduced chi-square {s.redchi:.2f} (-{loss:.0f})")

    dw = s.durbin_watson
    if dw is not None and s.ndata >= 30:
        if dw < 1.0:
            score -= 25
            reasons.append(f"structured residual, Durbin-Watson {dw:.2f} (-25)")
        elif dw < 1.5:
            score -= 10
            reasons.append(f"residual partly autocorrelated, Durbin-Watson {dw:.2f} (-10)")

    viol = list(violations)
    if viol:
        loss = min(50.0, 25.0 * len(viol))
        score -= loss
        reasons.append(f"{len(viol)} physical violation(s) (-{loss:.0f})")

    warn = [w for w in warnings if w.code not in ("structured_residual", "degenerate_parameters")]
    warn = [w for w in warn if w.code != "large_relative_error"]
    if warn:
        loss = min(20.0, 5.0 * len(warn))
        score -= loss
        reasons.append(f"{len(warn)} warning(s) (-{loss:.0f})")

    err_loss = 0.0
    if not s.errorbars:
        err_loss += 15
        reasons.append("no covariance: standard errors unavailable (-15)")
    uncertain = [
        c.label
        for c in result.majors()
        if c.area > 0 and c.area_err is not None and c.area_err / c.area > 0.5
    ]
    if uncertain:
        add = min(25.0 - err_loss, 10.0 * len(uncertain))
        err_loss += add
        reasons.append(f"area uncertain by > 50 %: {', '.join(uncertain)} (-{add:.0f})")
    score -= min(25.0, err_loss)

    rmax = s.max_correlation
    if rmax is not None and rmax > 0.98:
        loss = 20.0 if rmax > 0.995 else 10.0
        score -= loss
        reasons.append(
            f"parameters {100 * rmax:.1f} % correlated ({s.max_correlation_pair}) (-{loss:.0f})"
        )

    if not s.success:
        score -= 20
        reasons.append("optimiser reported failure (-20)")

    score = max(0.0, min(100.0, score))
    return FitGrade(_letter(score), score, reasons)
