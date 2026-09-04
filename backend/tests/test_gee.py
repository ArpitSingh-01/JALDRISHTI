"""Offline tests for the Sentinel-1 SAR flood-observation module.

Earth Engine is a network service, so none of this talks to it. Instead we pass a
FAKE ee module — a recording mock whose Image/ImageCollection/Filter/etc. return
chainable stubs that log every call — into the pure graph-building functions. That
lets us assert the *shape* of the computation (which collection, which dates, which
polarisation, that permanent-water + slope + speckle refinements are all applied,
and crucially that export goes to Drive and never to Cloud Storage) without a
credential or a byte over the wire.

The one thing we cannot check offline is whether the numbers are right — that needs
the live archive and is what `scripts/run_sar_observation.py` is for. These tests
guard the wiring and the export-discipline invariant; the science is validated by
eye against the deck overlay.
"""
from __future__ import annotations

from datetime import date

import pytest

from jaldrishti.gee import flood_observe as F


# --------------------------------------------------------------------------- #
# a chainable recording fake for the ee module
# --------------------------------------------------------------------------- #
class Rec:
    """A chainable stub: every attribute access returns a callable that returns
    another Rec, and every call is logged to the shared `calls` list. Enough to
    let ee expression graphs build without Earth Engine."""

    def __init__(self, log, name):
        self._log = log
        self._name = name

    def __getattr__(self, attr):
        # ee.Filter.eq, img.updateMask, etc. — return a logging callable.
        full = f"{self._name}.{attr}"

        def _call(*args, **kwargs):
            self._log.append((full, args, kwargs))
            return Rec(self._log, full)

        # allow attribute-only access (no call) to also chain
        _call._rec = Rec(self._log, full)
        return _call

    def __call__(self, *args, **kwargs):
        self._log.append((self._name, args, kwargs))
        return Rec(self._log, self._name)


class FakeEE:
    """Stands in for the `ee` module. Top-level names used by flood_observe are
    Rec factories; ee.batch.Export.image.toDrive returns a task with start()."""

    def __init__(self):
        self.calls: list = []
        self.tasks: list = []
        for top in ("Image", "ImageCollection", "Filter", "Geometry", "Kernel",
                    "Terrain", "Reducer"):
            setattr(self, top, Rec(self.calls, top))

        parent = self

        class _Export:
            class image:
                @staticmethod
                def toDrive(**kwargs):
                    parent.calls.append(("Export.image.toDrive", (), kwargs))
                    return _Task(parent, kwargs)

                @staticmethod
                def toCloudStorage(**kwargs):  # must never be called
                    parent.calls.append(("Export.image.toCloudStorage", (), kwargs))
                    raise AssertionError(
                        "toCloudStorage called — Community tier has no billing")

        class _batch:
            Export = _Export

        self.batch = _batch

    def names(self):
        return [c[0] for c in self.calls]


class _Task:
    def __init__(self, parent, kwargs):
        self._parent = parent
        self.kwargs = kwargs
        self.started = False

    def start(self):
        self.started = True
        self._parent.tasks.append(self)


# --------------------------------------------------------------------------- #
# AOI / spec construction (no ee at all)
# --------------------------------------------------------------------------- #
def test_aoi_from_domain_reprojects_utm_to_lonlat():
    from jaldrishti.config import RISHI_GANGA

    aoi = F.AOI.from_domain(RISHI_GANGA.domain)
    # Chamoli sits near 79.7 E, 30.4 N — the box must bracket that.
    assert 79.0 < aoi.west < aoi.east < 80.5
    assert 30.0 < aoi.south < aoi.north < 31.0
    assert aoi.east > aoi.west and aoi.north > aoi.south


def test_spec_for_study_area_pulls_event_date_and_windows():
    from jaldrishti.config import RISHI_GANGA

    spec = F.FloodObsSpec.for_study_area(RISHI_GANGA)
    assert spec.event_date == date(2021, 2, 7)
    # windows straddle the event
    assert spec.pre_start < spec.pre_end == spec.event_date == spec.post_start
    assert spec.post_end > spec.event_date
    # pre window is the configured number of days before the event
    assert (spec.event_date - spec.pre_start).days == spec.pre_window_days
    assert (spec.post_end - spec.event_date).days == spec.post_window_days


def test_spec_rejects_area_without_event_date():
    from jaldrishti.config import TEHRI  # a dam, no blockage.event_date

    with pytest.raises(ValueError):
        F.FloodObsSpec.for_study_area(TEHRI)


def _demo_spec():
    return F.FloodObsSpec(
        aoi=F.AOI(west=79.5, south=30.3, east=79.9, north=30.6),
        event_date=date(2021, 2, 7),
    )


# --------------------------------------------------------------------------- #
# graph construction
# --------------------------------------------------------------------------- #
def test_flood_image_uses_sentinel1_and_both_windows():
    ee = FakeEE()
    F.flood_image(ee, _demo_spec())
    names = ee.names()
    # two Sentinel-1 medians (pre + post)
    assert names.count("ImageCollection") == 2
    # the collection id used is Sentinel-1 GRD
    assert any(args and args[0] == F.S1_COLLECTION
               for n, args, kw in ee.calls if n == "ImageCollection")


def test_flood_image_applies_all_three_refinements():
    ee = FakeEE()
    F.flood_image(ee, _demo_spec())
    names = ee.names()
    # permanent-water mask (JRC), slope mask (HydroSHEDS DEM + Terrain.slope),
    # speckle removal (connectedPixelCount)
    assert any(args and args[0] == F.JRC_WATER
               for n, args, kw in ee.calls if n == "Image")
    assert any(args and args[0] == F.HYDROSHEDS_DEM
               for n, args, kw in ee.calls if n == "Image")
    assert any(n.endswith("connectedPixelCount") for n in names)
    assert any(n.endswith("Terrain.slope") for n in names)


def test_flood_image_thresholds_the_ratio():
    ee = FakeEE()
    F.flood_image(ee, _demo_spec())
    # a .gt(threshold) must appear with our configured threshold
    gts = [(n, args) for n, args, kw in ee.calls if n.endswith(".gt")]
    assert any(args and args[0] == F.DIFF_THRESHOLD_DB for n, args in gts)


def test_orbit_filter_only_added_when_requested():
    spec_no = _demo_spec()
    ee1 = FakeEE()
    F.flood_image(ee1, spec_no)
    pass_filters_no = [c for c in ee1.calls
                       if c[0] == "Filter.eq" and c[1]
                       and c[1][0] == "orbitProperties_pass"]
    assert not pass_filters_no

    import dataclasses
    spec_yes = dataclasses.replace(spec_no, orbit_pass="ASCENDING")
    ee2 = FakeEE()
    F.flood_image(ee2, spec_yes)
    pass_filters_yes = [c for c in ee2.calls
                        if c[0] == "Filter.eq" and c[1]
                        and c[1][0] == "orbitProperties_pass"]
    assert pass_filters_yes


# --------------------------------------------------------------------------- #
# export discipline — the load-bearing invariant
# --------------------------------------------------------------------------- #
def test_export_goes_to_drive_and_starts_task():
    ee = FakeEE()
    task = F.export_to_drive(ee, _demo_spec(), description="chamoli_test")
    assert "Export.image.toDrive" in ee.names()
    assert "Export.image.toCloudStorage" not in ee.names()
    assert task.started is True
    # the export names our folder + geotiff format
    _, _, kw = next(c for c in ee.calls if c[0] == "Export.image.toDrive")
    assert kw["fileFormat"] == "GeoTIFF"
    assert kw["folder"] == "jaldrishti"
    assert kw["description"] == "chamoli_test"


def test_export_can_be_built_without_starting():
    ee = FakeEE()
    task = F.export_to_drive(ee, _demo_spec(), start=False)
    assert task.started is False
    assert ee.tasks == []


def test_observed_area_km2_reduces_and_converts(monkeypatch):
    """observed_area_km2 multiplies by pixelArea, sums over the region, and
    converts m^2 -> km^2. We stub flood_image so the reduce chain terminates in a
    known m^2 value and check the /1e6 conversion."""
    ee = FakeEE()

    class _Num:
        def get(self, *_):
            return self
        def getInfo(self):
            return 2_500_000.0  # 2.5 km^2 in m^2

    class _NumImage:
        def multiply(self, *_):
            return self
        def reduceRegion(self, **_):
            return _Num()

    monkeypatch.setattr(F, "flood_image", lambda ee_, spec_: _NumImage())
    area = F.observed_area_km2(ee, _demo_spec())
    assert area == pytest.approx(2.5)


def test_observed_area_km2_handles_empty_region(monkeypatch):
    """A region with no detected flood returns 0.0, not a crash on None."""
    ee = FakeEE()

    class _NoneNum:
        def get(self, *_):
            return self
        def getInfo(self):
            return None

    class _NumImage:
        def multiply(self, *_):
            return self
        def reduceRegion(self, **_):
            return _NoneNum()

    monkeypatch.setattr(F, "flood_image", lambda ee_, spec_: _NumImage())
    assert F.observed_area_km2(ee, _demo_spec()) == 0.0
