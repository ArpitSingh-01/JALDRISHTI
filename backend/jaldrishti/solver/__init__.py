"""
Numerical solvers for JALDRISHTI.

`swe2d` is the workhorse: a 2D depth-averaged shallow water solver that routes
the flood wave across the terrain and produces depth, velocity and arrival time.
`flux` and `reconstruct` are its two numerical building blocks, kept separate so
each can be unit-tested and explained on its own. `sph2d` is the near-field
weakly-compressible SPH model: it resolves the breach jet at particle scale and
hands the routing solver a discharge hydrograph.
"""

from .sph2d import DamBreakSPH, SPHRunStats
from .swe2d import (
    GRAVITY,
    NG,
    FieldAccumulator,
    Inflow,
    RunStats,
    SWE2D,
)

__all__ = [
    "SWE2D",
    "Inflow",
    "FieldAccumulator",
    "RunStats",
    "DamBreakSPH",
    "SPHRunStats",
    "GRAVITY",
    "NG",
]
