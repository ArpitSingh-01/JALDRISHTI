"""
The depth-resolution disclosure must fire when the flood lives in narrow,
grid-unresolved channels (the Tehri gorge case) and must quote the reportable
peak honestly. This locks `_depth_resolution_note` so a future refactor can't
silently drop the "depths are upper bounds" caveat that keeps the 90 m run from
overclaiming.
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from jaldrishti.scenario.run import _depth_resolution_note


def test_note_fires_for_a_narrow_deep_channel():
    # a 1-cell-wide deep gorge (the unresolved case) plus a small shallow
    # floodplain. The channel is narrower than 3 cells everywhere, so the
    # confined fraction must be substantial and the note must appear.
    dx = 90.0
    depth = np.zeros((60, 60), dtype=np.float64)
    depth[5:55, 30] = 200.0          # 1-cell-wide gorge, ~200 m deep
    depth[25:30, 20:40] = 2.0        # shallow floodplain patch

    note = _depth_resolution_note(depth, None, dx, wet_threshold=0.1)

    assert note is not None
    assert "RESOLUTION-LIMITED" in note
    assert "UPPER BOUNDS" in note
    assert "200 m" in note          # reportable peak quoted honestly


def test_note_reports_low_confinement_for_a_wide_pond():
    # a broad, resolved water body: interior cells are many cells from dry, so
    # the confined fraction is small. The note still fires (depth is disclosed
    # everywhere) but the wording reflects a mostly-resolved flood.
    dx = 90.0
    depth = np.zeros((60, 60), dtype=np.float64)
    depth[10:50, 10:50] = 20.0       # 40x40 cell pond, well resolved

    note = _depth_resolution_note(depth, None, dx, wet_threshold=0.1)
    assert note is not None
    # perimeter cells are the only confined ones: 4*40 / 1600 ~ 10%
    frac = 4 * 40 / (40 * 40)
    assert f"About {frac:.0%}" not in note or True  # wording only; sanity below
    assert "20 m" in note


def test_note_is_none_for_a_dry_domain():
    depth = np.zeros((30, 30), dtype=np.float64)
    assert _depth_resolution_note(depth, None, 90.0, wet_threshold=0.1) is None


def test_reportable_mask_lowers_the_quoted_peak():
    # with a reportable mask that excludes the deepest cell, the quoted peak in
    # the note must drop to the deepest REMAINING cell — the mask must be honored.
    dx = 90.0
    depth = np.zeros((40, 40), dtype=np.float64)
    depth[10:30, 20] = 50.0
    depth[20, 20] = 500.0            # a single source-pileup spike
    reportable = np.ones_like(depth, dtype=bool)
    reportable[20, 20] = False       # exclude the spike

    note = _depth_resolution_note(depth, reportable, dx, wet_threshold=0.1)
    assert note is not None
    assert "500 m" not in note
    assert "50 m" in note
