"""
Validation: analytical solutions, solver cross-comparisons, and the error
metrics we report against them.

Kept inside the package rather than in `tests/` on purpose — the same curves and
the same numbers appear in the validation charts in the PDF report and in the
presentation, so they are a deliverable, not just test scaffolding.

`compare` implements the problem statement's "compare the scenario produced by
these modelling approaches": SWE vs SPH on the identical dam-break problem,
SPH vs parametric breach hydrographs, and overlays against imported or
published Delft3D output.
"""

from .analytical import (
    ritter,
    ritter_front_position,
    stoker,
    stoker_middle_state,
)
from .compare import (
    compare_hydrographs,
    compare_solvers,
    ritter_breach_discharge,
)

__all__ = [
    "ritter",
    "ritter_front_position",
    "stoker",
    "stoker_middle_state",
    "compare_solvers",
    "compare_hydrographs",
    "ritter_breach_discharge",
]
