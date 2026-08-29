"""
Numerical solvers for JALDRISHTI.

`swe2d` is the workhorse: a 2D depth-averaged shallow water solver that routes
the flood wave across the terrain and produces depth, velocity and arrival time.
`flux` and `reconstruct` are its two numerical building blocks, kept separate so
each can be unit-tested and explained on its own.
"""

from .swe2d import GRAVITY, NG, RunStats, SWE2D

__all__ = ["SWE2D", "RunStats", "GRAVITY", "NG"]
