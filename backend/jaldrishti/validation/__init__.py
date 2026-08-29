"""
Validation: analytical solutions and the error metrics we report against them.

Kept inside the package rather than in `tests/` on purpose — the same curves and
the same numbers appear in the validation charts in the PDF report and in the
presentation, so they are a deliverable, not just test scaffolding.
"""

from .analytical import (
    ritter,
    ritter_front_position,
    stoker,
    stoker_middle_state,
)

__all__ = ["ritter", "ritter_front_position", "stoker", "stoker_middle_state"]
