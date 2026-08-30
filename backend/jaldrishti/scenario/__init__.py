"""
Scenario construction: turning a real place and a hypothetical failure into the
inputs a solver run needs.

`breach.py` is the physics of the failure itself — a reservoir draining through a
growing gap in a dam. Its single output, Q(t) with the matching outlet velocity
U(t), is the only thing the routing solver ever learns about the dam. That
separation is deliberate: it means the same solver handles a dam breach, a
landslide-dam outburst and a gauged flood without modification, and it means the
breach model can be replaced (by SPH near-field output, or by a published design
hydrograph) without touching the solver.
"""

from .breach import (
    C_SIDE,
    C_WEIR,
    GROWTH_MODES,
    SUBMERGENCE_LIMIT,
    BreachGeometry,
    BreachHydrograph,
    ReservoirStorage,
    breach_state,
    breach_velocity,
    critical_velocity,
    formation_time_band,
    froehlich_breach_geometry,
    froehlich_peak_outflow,
    growth_fraction,
    max_bottom_width,
    mlm_peak_outflow,
    simulate_breach,
    submergence_factor,
    usbr_peak_outflow,
    weir_outflow,
)

__all__ = [
    "C_SIDE",
    "C_WEIR",
    "GROWTH_MODES",
    "SUBMERGENCE_LIMIT",
    "BreachGeometry",
    "BreachHydrograph",
    "ReservoirStorage",
    "breach_state",
    "breach_velocity",
    "critical_velocity",
    "formation_time_band",
    "froehlich_breach_geometry",
    "froehlich_peak_outflow",
    "growth_fraction",
    "mlm_peak_outflow",
    "simulate_breach",
    "submergence_factor",
    "usbr_peak_outflow",
    "weir_outflow",
]
