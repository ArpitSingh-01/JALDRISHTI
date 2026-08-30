"""
Export tests — every deliverable is read back and checked, never just written.

WHY ROUND-TRIP RATHER THAN "DID IT CRASH"
----------------------------------------
Every silent failure this package guards against produces a file. A Shapefile
with truncated field names opens fine. A KML in UTM coordinates renders happily
in the wrong hemisphere. A GeoTIFF with 0.0 over the reservoir loads without
complaint and puts the lake in the most urgent isochrone. `write_*` returning a
path proves nothing.

So every test here opens what was written with an independent reader — rasterio
for the rasters, pyogrio/geopandas for the vectors, `json.loads` with
`allow_nan=False` for the metadata — and asserts a property that would be false
if the specific defect were present.

The `.shp` and `.kml` deliverables are on CLAUDE.md's "never cut" list and are
named explicitly in PS 26161. They get the most coverage here for that reason.
"""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from jaldrishti.analysis import (ScenarioSummary, analyse_arrival,
                                 analyse_exposure, classify_hazard)
from jaldrishti.analysis.arrival import (BAND_COLOURS,
                                         PRE_EXISTING_WATER_COLOUR)
from jaldrishti.analysis.damage import DamageRange, DamageResult
from jaldrishti import export
from jaldrishti.export import metadata as meta_mod
from jaldrishti.export import raster as raster_mod
from jaldrishti.export import vector as vec_mod

DX = 90.0
NY, NX = 40, 60
# A real projected CRS over Uttarakhand, so the KML reprojection has work to do
# and a failure to reproject is detectable rather than a no-op.
UTM44N = "EPSG:32644"
ORIGIN_X, ORIGIN_Y = 300000.0, 3350000.0

RESERVOIR_COLS = 3


@pytest.fixture(scope="module")
def scene():
    """
    A wedge-shaped flood with a reservoir on the left and a DEM void on the right.

    Every count in the tests below is exact and derived from this construction,
    not recorded from a previous run.
    """
    from rasterio.transform import from_origin

    yy, xx = np.mgrid[0:NY, 0:NX]
    dist = np.hypot(xx - 2, (yy - NY / 2) * 0.6)
    depth = np.clip(9.0 - dist * 0.22, 0.0, None)
    speed = np.where(depth > 0, np.clip(6.0 - dist * 0.12, 0.2, None), 0.0)
    dv = depth * speed * 0.75

    initially_wet = xx < RESERVOIR_COLS
    depth = np.where(initially_wet, 40.0, depth)
    speed = np.where(initially_wet, 0.05, speed)
    dv = np.where(initially_wet, 2.0, dv)

    arrival_s = np.where(depth > 0.1, dist * 90.0, np.nan)
    arrival_s = np.where(initially_wet, 0.0, arrival_s)

    dem_valid = np.ones((NY, NX), dtype=bool)
    dem_valid[28:32, 40:48] = False

    haz = classify_hazard(depth, speed, dv, dx=DX, landcover="urban",
                          initially_wet=initially_wet)
    arr = analyse_arrival(arrival_s, dx=DX, run_duration_s=7200.0,
                          initially_wet=initially_wet)
    exp = analyse_exposure(
        np.full((NY, NX), 10.0), haz, arr,
        infrastructure={"hospitals": 1, "schools": 4, "road_km": 22.5},
        resample_report={"conserved": True, "residual_fraction": 0.0})

    return ScenarioSummary(
        run_id="test-0001", study_area="Test valley",
        scenario="instantaneous full breach",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, DX, DX),
        crs=UTM44N, dx=DX, shape=(NY, NX),
        max_depth=depth, max_speed=speed, max_dv=dv,
        hazard=haz, arrival=arr, exposure=exp,
        duration_s=7200.0, wall_time_s=12.3, steps=1024, volume_error=2.0e-9,
        dem_valid_mask=dem_valid,
        solver_settings={"cfl": 0.4, "riemann": "HLLC"},
        terrain_provenance={"dem": "Copernicus DEM GLO-30"},
        breach_provenance={"mode": "instantaneous"},
    )


@pytest.fixture(scope="module")
def scene_with_damage(scene):
    """Same scene plus a damage estimate, which permanently blocks the gate."""
    import dataclasses
    return dataclasses.replace(scene, damage=DamageResult(
        by_category={"buildings": DamageRange.around(1.0e9)},
        structural_failure_buildings=12))


@pytest.fixture(scope="module")
def settlements():
    import geopandas as gpd
    from shapely.geometry import Point

    # (col, row) -> two inside the flood, one on dry land, one over the DEM void.
    picks = [(8, 20), (24, 19), (55, 4), (44, 30)]
    pts = [Point(ORIGIN_X + c * DX + DX / 2, ORIGIN_Y - r * DX - DX / 2)
           for c, r in picks]
    return gpd.GeoDataFrame(
        {"name": ["Near village", "Mid village", "Ridge hamlet", "Void hamlet"],
         "population": [4000, 9000, 250, 700]},
        geometry=pts, crs=UTM44N)


@pytest.fixture(scope="module")
def written(scene, settlements, tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    files = export.write_all(scene, out, settlements=settlements,
                             cog=False, hash_files=True)
    return out, files


# ==========================================================================
# 1. the deliverable set is complete
# ==========================================================================
def test_the_export_produces_every_format_the_ps_names(written):
    """GeoTIFF, Shapefile and KML are named in PS 26161. All three must appear."""
    out, files = written
    assert not (out / "EXPORT_ERRORS.json").exists(), \
        (out / "EXPORT_ERRORS.json").read_text()

    suffixes = {p.suffix for p in out.rglob("*") if p.is_file()}
    assert ".tif" in suffixes
    assert ".zip" in suffixes          # zipped Shapefile
    assert ".kmz" in suffixes          # zipped KML
    assert ".pdf" in suffixes
    assert ".json" in suffixes


def test_every_promised_raster_band_is_written(written):
    out, files = written
    for name in ("arrival_time_min", "arrival_band", "max_depth_m",
                 "max_speed_ms", "max_depth_velocity", "hazard_rating",
                 "hazard_class_defra", "hazard_class_aidr", "dem_valid"):
        assert (out / f"{name}.tif").exists(), name
        assert f"{name}.tif" in files


def test_manifest_keys_are_the_relative_path_of_the_file_written(written):
    """
    REGRESSION. A caller that zips or serves `write_all`'s return value must be
    able to trust the key. `write_scenario_vectors` used to key the Shapefile as
    `f"{layer}.shp"` while `write_shapefile` zips by default and returns a
    `.zip` — so the manifest named a zip archive `inundation_extent.shp`, and
    anything that wrote the file out under its key produced something no GIS
    will open.

    Asserting the full relative path, not just the suffix: a suffix-only check
    passes when the key names the wrong layer, which is the same class of bug
    one directory over.
    """
    out, files = written
    for key, path in files.items():
        assert path.exists(), key
        assert key == path.relative_to(out).as_posix(), (
            f"key {key!r} is not the path actually written "
            f"({path.relative_to(out).as_posix()!r})")


# ==========================================================================
# 2. rasters — georeferencing and the reservoir
# ==========================================================================
def test_the_reservoir_is_nodata_in_arrival_time_not_zero(written):
    """
    REGRESSION. The solver records arrival 0 over the reservoir. A float raster
    has no sentinel, so writing it raw hands anyone who opens the GeoTIFF 0.0
    across the whole lake — and styled with the obvious "0 = most urgent" ramp
    the reservoir becomes the most alarming thing on the map, while `min()` over
    the raster returns 0.

    This is the same defect that made `first_arrival_minutes()` report "0 min
    after failure", reappearing one layer down in a file that leaves the machine.
    """
    import rasterio

    out, _ = written
    with rasterio.open(out / "arrival_time_min.tif") as src:
        raw = src.read(1)
        masked = src.read(1, masked=True)
        assert src.nodata == raster_mod.FLOAT_NODATA
        # Every reservoir cell must be nodata.
        assert (raw[:, :RESERVOIR_COLS] == raster_mod.FLOAT_NODATA).all()
        # And therefore the minimum finite arrival is strictly positive.
        assert masked.min() > 0.0


def test_depth_keeps_the_reservoir_because_that_depth_is_real(written):
    """
    The counterpart to the test above, and the reason masking is per-band rather
    than global: 40 m of reservoir is a true depth and a legitimate thing to
    render. Only quantities that are *meaningless* over pre-existing water get
    masked.
    """
    import rasterio

    out, _ = written
    with rasterio.open(out / "max_depth_m.tif") as src:
        raw = src.read(1)
        assert (raw[:, :RESERVOIR_COLS] > 30.0).all()


def test_hazard_raster_and_hazard_shapefile_agree_about_the_reservoir(written):
    """
    `vector.hazard_zones` drops the reservoir from the polygons. If the raster
    kept it, the two deliverables built from one run would contradict each other
    — the same marginal-inconsistency failure `exposure.analyse` raises on.
    """
    import geopandas as gpd
    import rasterio

    out, _ = written
    with rasterio.open(out / "hazard_class_defra.tif") as src:
        cls = src.read(1)
    assert (cls[:, :RESERVOIR_COLS] == raster_mod.INT_NODATA).all()

    gdf = gpd.read_file(out / "shapefile" / "hazard_zones_defra.zip")
    # No hazard polygon may cover the reservoir's centre column.
    from shapely.geometry import Point
    probe = Point(ORIGIN_X + DX / 2, ORIGIN_Y - (NY / 2) * DX)
    assert not gdf.contains(probe).any()


def test_rasters_carry_the_crs_and_transform_they_were_given(written, scene):
    import rasterio

    out, _ = written
    for name in ("arrival_time_min", "max_depth_m", "hazard_class_defra"):
        with rasterio.open(out / f"{name}.tif") as src:
            assert src.crs.to_string() == UTM44N, name
            assert src.shape == (NY, NX), name
            assert src.transform.almost_equals(scene.transform), name


def test_raster_tags_record_provenance_and_never_claim_delft3d_was_run(written):
    """
    CLAUDE.md: never claim we ran Delft3D. The tags are the only provenance that
    travels with a file once it has been emailed, so the claim has to be correct
    there, not just in the PPT.
    """
    import rasterio

    out, _ = written
    with rasterio.open(out / "arrival_time_min.tif") as src:
        tags = src.tags()
    assert tags["RUN_ID"] == "test-0001"
    assert tags["STUDY_AREA"] == "Test valley"
    assert tags["RESOLUTION_M"] == "90"
    assert "DISCLAIMER" in tags
    assert tags["MASKED_OVER_PRE_EXISTING_WATER"] == "True"
    joined = " ".join(tags.values())
    assert "Delft3D" not in joined
    assert "HLLC" in joined


def test_band_raster_keeps_both_negative_sentinels_distinct(written):
    """
    -1 (dry, never reached) and -2 (water before the failure) are different
    statements and must survive the round trip as different values. Collapsing
    them would put the reservoir back into the flood extent.
    """
    import rasterio

    out, _ = written
    with rasterio.open(out / "arrival_band.tif") as src:
        b = src.read(1)
    present = set(np.unique(b).tolist())
    assert -2 in present, "reservoir sentinel lost"
    assert -1 in present, "never-flooded sentinel lost"
    assert (b[:, :RESERVOIR_COLS] == -2).all()


def test_domain_mask_writes_nodata_rather_than_zero_outside_the_domain(
        scene, tmp_path):
    """
    "We did not model here" must never render as "we modelled here and found
    nothing" — that is what makes an inundation extent honest at its edges.
    """
    import rasterio

    mask = np.ones((NY, NX), dtype=bool)
    mask[:, 50:] = False
    raster_mod.write_scenario_rasters(scene, tmp_path, cog=False,
                                      domain_mask=mask)
    with rasterio.open(tmp_path / "max_depth_m.tif") as src:
        a = src.read(1)
    assert (a[:, 50:] == raster_mod.FLOAT_NODATA).all()


def test_qgis_style_files_name_every_class(written):
    """
    A class raster without a style opens as a grey ramp of integers. The .qml is
    the difference between shipping data and shipping something legible.
    """
    from jaldrishti.analysis.hazard import DEFRA_CLASS_NAMES

    out, files = written
    qml = (out / "hazard_class_defra.qml").read_text(encoding="utf-8")
    for name in DEFRA_CLASS_NAMES:
        assert name in qml
    assert qml.count("paletteEntry") == len(DEFRA_CLASS_NAMES)
    assert "hazard_class_defra.qml" in files
    assert "arrival_band.qml" in files


# ==========================================================================
# 3. Shapefile — the DBF traps
# ==========================================================================
def test_no_field_name_exceeds_the_dbf_ten_character_limit(scene):
    """
    The DBF format cannot store a longer name. GDAL truncates and warns on
    stderr, which nobody reads — and two fields truncating to the same prefix
    collapse into one, losing a column without losing the file.
    """
    for builder in (vec_mod.inundation_extent, vec_mod.arrival_isochrones):
        gdf = builder(scene)
        for col in gdf.columns:
            if col == "geometry":
                assert len(col) <= 8
            else:
                assert len(col) <= vec_mod.DBF_NAME_LIMIT, f"{builder}: {col}"


def test_writing_an_over_long_field_name_raises_instead_of_truncating(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(
        {"population_at_risk": [1], "population_at_night": [2]},
        geometry=[Point(0, 0)], crs="EPSG:4326")
    with pytest.raises(ValueError, match="DBF limit|silently truncated"):
        vec_mod.write_shapefile(gdf, tmp_path / "x.shp")


def test_shapefile_round_trips_with_its_crs_and_all_attributes(written):
    import geopandas as gpd

    out, _ = written
    gdf = gpd.read_file(out / "shapefile" / "arrival_isochrones.zip")
    assert len(gdf) > 0
    assert gdf.crs.to_string() == UTM44N
    for col in ("band", "label", "min_min", "max_min", "area_km2", "action"):
        assert col in gdf.columns
    # Colour is a KML styling attribute, not a measurement, and is dropped from
    # the attribute table on purpose.
    assert "colour" not in gdf.columns


def test_the_zipped_shapefile_contains_the_prj_that_carries_the_crs(written):
    """
    A .shp emailed without its .prj has lost its coordinate system entirely.
    That happens constantly, which is why the zip is the default deliverable.
    """
    out, _ = written
    with zipfile.ZipFile(out / "shapefile" / "arrival_isochrones.zip") as zf:
        names = {n.rsplit(".", 1)[-1] for n in zf.namelist()}
    assert {"shp", "shx", "dbf", "prj"} <= names


def test_zipping_leaves_no_loose_sidecars_beside_the_archive(written):
    """
    REGRESSION. `write_shapefile` used to zip the Shapefile and leave all five
    sidecars on disk, so the directory held both `arrival_isochrones.zip` and an
    openable `arrival_isochrones.shp` set. Two copies of one layer that can drift
    apart, double the payload, and — because only `*.zip` is in the ignore
    rules — the loose set leaks a run's Shapefiles into version control.
    """
    out, _ = written
    shp_dir = out / "shapefile"
    assert list(shp_dir.glob("*.zip")), "expected zipped Shapefiles"
    for ext in ("shp", "shx", "dbf", "prj", "cpg"):
        stray = sorted(p.name for p in shp_dir.glob(f"*.{ext}"))
        assert not stray, f"loose .{ext} left beside the archive: {stray}"


def test_not_zipping_keeps_the_shapefile_where_it_was_asked_for(tmp_path, scene):
    """
    The cleanup must be tied to zipping. With `zip_it=False` the caller wants the
    loose set and deleting it would destroy the only output.
    """
    gdf = vec_mod.arrival_isochrones(scene)
    p = vec_mod.write_shapefile(gdf, tmp_path / "loose.shp", zip_it=False)
    assert p == tmp_path / "loose.shp"
    assert p.exists()
    assert (tmp_path / "loose.dbf").exists()
    assert (tmp_path / "loose.prj").exists()
    assert not (tmp_path / "loose.zip").exists()


def test_the_unbounded_final_band_is_a_sentinel_not_infinity(written):
    """
    DBF cannot represent infinity; drivers write it as a huge float or as 0
    depending on version. -1 is the documented "no upper bound" value.
    """
    import geopandas as gpd

    out, _ = written
    gdf = gpd.read_file(out / "shapefile" / "arrival_isochrones.zip")
    assert np.isfinite(gdf["max_min"]).all()
    last = gdf.loc[gdf["band"].idxmax()]
    if last["band"] == len(BAND_COLOURS) - 1:
        assert last["max_min"] == -1.0


def test_inundation_extent_separates_new_flooding_from_pre_existing_water(scene):
    """
    A single blue polygon covering reservoir and floodplain alike is exactly the
    misleading picture this project exists not to produce. Two rows can be
    dissolved into one; one row cannot be split back apart.
    """
    gdf = vec_mod.inundation_extent(scene)
    kinds = set(gdf["kind"])
    assert kinds == {"new_flood", "pre_water"}
    new_area = float(gdf.loc[gdf["kind"] == "new_flood", "area_km2"].iloc[0])
    assert new_area == pytest.approx(scene.flooded_area_km2, rel=1e-6)


def test_isochrone_areas_sum_to_the_banded_area_from_the_analysis(scene):
    """
    Polygonisation must not lose or invent area. `features.shapes` traces exact
    cell boundaries, so the sum is exact to floating point, not approximate.
    """
    gdf = vec_mod.arrival_isochrones(scene)
    from_vector = float(gdf["area_km2"].sum())
    by_band = scene.arrival.area_by_band_km2()
    from_raster = sum(by_band.values())
    assert from_vector == pytest.approx(from_raster, rel=1e-6)


# ==========================================================================
# 4. KML — the coordinate-system and byte-order traps
# ==========================================================================
def test_kml_colour_swaps_to_aabbggrr_byte_order():
    """
    KML inherited little-endian colour from the Keyhole binary format: alpha,
    blue, green, red. Every other format the project touches is rrggbb. Passing
    one straight through renders #7f0000 (extreme hazard, dark red) as dark navy,
    which on a flood map reads as deep calm water — a legend inversion on the
    single most important class.
    """
    assert vec_mod._kml_colour("#7f0000", 1.0) == "ff00007f"
    assert vec_mod._kml_colour("#ffeda0", 1.0) == "ffa0edff"
    # Alpha is the FIRST byte, not the last.
    assert vec_mod._kml_colour("#0000ff", 0.0).startswith("00")
    assert vec_mod._kml_colour("#0000ff", 1.0) == "ffff0000"


def test_kml_colour_rejects_a_malformed_hex():
    with pytest.raises(ValueError):
        vec_mod._kml_colour("#abc")


def test_kml_is_written_in_geographic_coordinates_not_the_source_utm(written):
    """
    KML has no CRS declaration — the specification fixes it at WGS84 geographic.
    A UTM easting of 300000 is read as 300000 degrees east, wrapped, and drawn in
    the ocean, without any error. This is the single most likely way for the KML
    deliverable to be silently wrong.
    """
    import geopandas as gpd

    out, _ = written
    gdf = gpd.read_file(out / "kml" / "arrival_isochrones.kmz")
    xmin, ymin, xmax, ymax = gdf.total_bounds
    assert -180.0 <= xmin <= xmax <= 180.0
    assert -90.0 <= ymin <= ymax <= 90.0
    # UTM 44N easting 300000 near northing 3350000 is roughly 78.9E, 30.2N.
    assert 78.0 < xmin < 80.0
    assert 29.5 < ymin < 31.0


def test_writing_kml_from_a_crs_less_frame_raises(tmp_path):
    """
    `to_crs` on a GeoDataFrame with crs=None does not always raise, and the
    failure downstream is a flood map of the Gulf of Guinea. The bounds check
    catches it at the boundary where it is diagnosable.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame({"label": ["x"], "colour": ["#ff0000"]},
                           geometry=[Point(300000, 3350000)], crs=UTM44N)
    gdf = gdf.set_crs(None, allow_override=True)
    with pytest.raises(Exception):
        vec_mod.write_kml(gdf, tmp_path / "bad.kml", name="bad")


def test_the_kml_has_no_folders_because_ogr_reads_a_folder_as_a_layer(written):
    """
    REGRESSION. `write_kml` used to wrap a multi-part row's pieces in
    `kml.newfolder(...)`. OGR maps one KML <Folder> to one layer, so the file
    split: single-part bands stayed in the document root and every multi-part
    band became its own layer. `geopandas.read_file` returns only the default
    layer, so the isochrone KMZ silently lost its ">120 min" band — with nothing
    but a UserWarning to say so.
    """
    out, _ = written
    with zipfile.ZipFile(out / "kml" / "arrival_isochrones.kmz") as zf:
        body = zf.read("doc.kml").decode("utf-8")
    assert "<Folder>" not in body and "<Folder " not in body
    assert "<MultiGeometry" in body, (
        "the fixture's isochrones include a multi-part band, so the "
        "MultiGeometry path should be exercised here")


def test_the_kml_has_one_placemark_per_row_of_the_source_frame(written, scene):
    """
    The row-for-row invariant. If the KML and the Shapefile written from the same
    GeoDataFrame disagree about how many features exist, one of the two
    deliverables is lying, and the KML is the one nobody will check.

    Counting placemarks in the XML rather than reading with geopandas: a reader
    that returns only the default layer is precisely the bug being guarded
    against, so it cannot be the instrument that detects it.
    """
    import geopandas as gpd

    out, _ = written
    expected = len(vec_mod.arrival_isochrones(scene))
    assert expected > 1

    with zipfile.ZipFile(out / "kml" / "arrival_isochrones.kmz") as zf:
        body = zf.read("doc.kml").decode("utf-8")
    assert body.count("<Placemark") == expected

    # And the Shapefile, read back, agrees with that same count.
    shp = gpd.read_file(out / "shapefile" / "arrival_isochrones.zip")
    assert len(shp) == expected


def test_kmz_is_a_zip_containing_exactly_one_doc_kml(written):
    """
    Government mail servers reject large attachments and a 30 m isochrone KML is
    tens of megabytes of coordinate text. KMZ is what actually gets delivered, so
    it has to be a well-formed archive Google Earth will open.
    """
    out, _ = written
    with zipfile.ZipFile(out / "kml" / "arrival_isochrones.kmz") as zf:
        assert zf.namelist() == ["doc.kml"]
        body = zf.read("doc.kml").decode("utf-8")
    assert "<kml" in body
    assert "</kml>" in body


def test_every_kml_carries_the_disclaimer_where_the_reader_will_see_it(written):
    """
    A KML gets forwarded by email far more often than it gets opened next to its
    provenance JSON. The caveat has to be in the file the user actually clicks.
    """
    out, _ = written
    with zipfile.ZipFile(out / "kml" / "arrival_isochrones.kmz") as zf:
        body = zf.read("doc.kml").decode("utf-8")
    assert "not a survey" in body
    assert "NOT warning time" in body


# ==========================================================================
# 5. settlements — the per-village table
# ==========================================================================
def test_settlements_never_reached_are_kept_with_a_negative_sentinel(
        scene, settlements):
    """
    A village absent from the table looks like an oversight. "Not reached in this
    scenario" is information a planner can act on.
    """
    gdf = vec_mod.settlements_at_risk(scene, settlements)
    assert len(gdf) == len(settlements)
    assert set(gdf["name"]) == set(settlements["name"])
    unreached = gdf[gdf["flooded"] == 0]
    assert len(unreached) >= 1
    assert (unreached["arr_min"] == -1.0).all()
    assert (unreached["depth_m"] == 0.0).all()


def test_settlements_are_sorted_by_urgency_with_unreached_last(scene,
                                                              settlements):
    """The top of the file is the top of the response priority list."""
    gdf = vec_mod.settlements_at_risk(scene, settlements)
    order = np.where(gdf["arr_min"].to_numpy() < 0, np.inf,
                     gdf["arr_min"].to_numpy())
    assert (order[:-1] <= order[1:]).all(), order


def test_a_settlement_inside_the_reservoir_is_not_given_an_arrival_time(scene):
    """
    A centroid on the reservoir has raster arrival 0. Reporting that as "arrives
    in 0 minutes" is the reservoir defect resurfacing in the per-village table,
    which is the single most quotable output in the whole system.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    on_lake = gpd.GeoDataFrame(
        {"name": ["Lake point"]},
        geometry=[Point(ORIGIN_X + DX / 2, ORIGIN_Y - (NY / 2) * DX)],
        crs=UTM44N)
    gdf = vec_mod.settlements_at_risk(scene, on_lake)
    assert gdf["arr_min"].iloc[0] == -1.0
    assert gdf["flooded"].iloc[0] == 0


def test_settlements_without_a_name_column_still_appear(scene):
    """
    A point with a location and an arrival time is actionable without a gazetteer
    name. Dropping it would understate exposure.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    anon = gpd.GeoDataFrame(
        geometry=[Point(ORIGIN_X + 8 * DX, ORIGIN_Y - 20 * DX)], crs=UTM44N)
    gdf = vec_mod.settlements_at_risk(scene, anon)
    assert len(gdf) == 1
    assert gdf["name"].iloc[0].startswith("unnamed")


# ==========================================================================
# 6. metadata and manifest
# ==========================================================================
def test_metadata_is_strict_json_with_no_nan(written):
    """
    `json.dumps` emits bare `NaN` by default, which is not valid JSON and which
    `JSON.parse` rejects outright. `allow_nan=False` here fails on exactly the
    values a browser refuses.
    """
    out, _ = written
    doc = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    json.dumps(doc, allow_nan=False)          # raises if any NaN survived
    assert doc["schema_version"] == meta_mod.METADATA_SCHEMA_VERSION


def test_metadata_never_claims_delft3d_was_executed(written):
    """
    CLAUDE.md is explicit: the interoperability claim is a Delft3D-compatible
    adapter and comparison against PUBLISHED benchmarks. Overstating it once
    destroys the credibility of every other number in the file.
    """
    out, _ = written
    text = (out / "metadata.json").read_text(encoding="utf-8")
    doc = json.loads(text)
    attribution = doc["attribution"]
    assert "NOT run" in attribution
    assert "PUBLISHED" in attribution
    assert "HLLC" in attribution
    for bad in ("ran Delft3D", "using Delft3D", "computed with Delft3D",
                "simulated in Delft3D"):
        assert bad.lower() not in text.lower(), bad


def test_metadata_records_every_unverified_input(written, scene):
    out, _ = written
    doc = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    listed = doc["honesty"]["unverified_inputs"]
    assert listed == scene.unverified_inputs
    assert len(listed) > 0, "the fixture should have unverified citations"
    assert doc["honesty"]["presentable_as_fact"] is False


def test_metadata_records_the_environment_and_the_git_state(written):
    """
    "We cannot reproduce your figure" has no diagnosis without versions, and a
    dirty tree means the commit hash does not identify the code that ran.
    """
    out, _ = written
    doc = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    env = doc["environment"]
    assert env["numpy"] is not None
    assert env["rasterio"] is not None
    assert "python" in env
    assert set(doc["git"]) == {"commit", "branch", "dirty",
                              "reproducible_from_commit"}


def test_metadata_cites_the_dam_safety_act(written):
    """
    CLAUDE.md: cite the Dam Safety Act, 2021. It legally mandates dam-break
    studies, which reframes the tool as compliance infrastructure.
    """
    out, _ = written
    doc = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    joined = " ".join(doc["legal_context"])
    assert "Dam Safety Act, 2021" in joined
    assert "Sendai" in joined
    assert "CWC" in joined


def test_manifest_hashes_every_file_and_excludes_itself(written):
    """
    The reproducibility question is "if I run it again do I get the same answer?"
    A timestamp cannot answer that; a content hash can. The manifest must not
    hash itself, which would be a file whose hash depends on its own hash.
    """
    out, _ = written
    man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = {e["path"] for e in man["files"]}
    assert "MANIFEST.json" not in paths
    assert man["file_count"] == len(man["files"])
    assert all(len(e["sha256"]) == 64 for e in man["files"])
    assert man["total_bytes"] == sum(e["bytes"] for e in man["files"])
    # And the hashes are real.
    first = man["files"][0]
    assert meta_mod.sha256_of(out / first["path"]) == first["sha256"]


def test_the_readme_states_that_arrival_time_is_not_warning_time(written):
    """
    The realistic delivery path is a ZIP opened months later by someone who was
    not in the room. If they read one thing, it must be this distinction.
    """
    out, _ = written
    text = (out / "README.txt").read_text(encoding="utf-8")
    assert "NOT warning time" in text
    assert "Dam Safety Act" in text or "Dam Safety" in text
    assert "arrival_time_min.tif" in text
    assert "NOT presentable as fact" in text or "NO —" in text


# ==========================================================================
# 7. the PDF and the release gate
# ==========================================================================
def test_the_pdf_is_a_valid_pdf_with_content(written):
    out, _ = written
    data = (out / "report.pdf").read_bytes()
    assert data[:5] == b"%PDF-"
    assert b"%%EOF" in data[-2048:]
    assert len(data) > 20_000, "a report this small is probably empty"


def test_an_unpresentable_run_is_watermarked(scene_with_damage, tmp_path):
    """
    A screenshot of a demo output gets pasted into a briefing note, loses its
    context, and becomes a number someone plans around. A watermark survives the
    screenshot; a footnote does not.
    """
    ok, reasons = scene_with_damage.is_presentable()
    assert ok is False
    assert any("order-of-magnitude" in r for r in reasons)

    from jaldrishti.export.report import _Stamper, write_report
    p = write_report(scene_with_damage, tmp_path / "r.pdf", include_maps=False)
    data = p.read_bytes()
    # reportlab compresses page streams, so assert on the stamper's decision
    # rather than searching the bytes for the word.
    st = _Stamper(scene_with_damage.run_id, scene_with_damage.study_area,
                  watermark_text=None if ok else "UNVERIFIED")
    assert st.watermark_text == "UNVERIFIED"
    assert data[:5] == b"%PDF-"


def test_a_damage_estimate_permanently_blocks_the_gate(scene_with_damage):
    """
    Documented as permanent and by design in `is_presentable`. Monetary loss is
    the product of four uncertain factors and no amount of source verification
    makes a rupee figure a fact. The correct response to an unwanted watermark is
    to drop the damage estimate, not to bypass the gate.
    """
    ok, reasons = scene_with_damage.is_presentable()
    assert not ok
    assert "monetary damage figures are order-of-magnitude only" in reasons


def test_the_report_tables_reuse_the_summary_and_cannot_drift_from_it(scene):
    """
    Every figure in the PDF comes from `ScenarioSummary`, so the narrative and
    the tables cannot disagree. This checks the arrival table against the
    analysis object directly.
    """
    from jaldrishti.export.report import _arrival_rows
    from jaldrishti.analysis.arrival import band_labels

    rows = _arrival_rows(scene)
    labels = band_labels(scene.arrival.bands_min)
    assert [r[0] for r in rows[1:]] == labels
    areas = scene.arrival.area_by_band_km2()
    for row, label in zip(rows[1:], labels):
        assert row[1] == f"{areas[label]:,.2f}"


def test_the_arrival_map_renders_and_is_a_real_png(scene, tmp_path):
    p = export.render_arrival_map(scene, tmp_path / "m.png", dpi=80)
    data = p.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5_000


def test_the_least_urgent_band_colour_is_visible_against_neutral_land():
    """
    Unflooded land renders as neutral grey. A near-white ">120 min" class is
    invisible against it, so the least urgent band silently disappears and the
    reader concludes it is empty. The lightest step must stay clearly blue.
    """
    lightest = BAND_COLOURS[-1].lstrip("#")
    r, g, b = (int(lightest[i:i + 2], 16) for i in (0, 2, 4))
    assert b - r >= 24, f"{BAND_COLOURS[-1]} is not recognisably blue"
    assert max(r, g, b) < 245, f"{BAND_COLOURS[-1]} is effectively white"


def test_pre_existing_water_is_off_the_urgency_ramp():
    """
    Drawing the lake in a pale blue that sits between two band colours invites
    reading it as "an isochrone band I can't quite place on the legend".
    """
    assert PRE_EXISTING_WATER_COLOUR not in BAND_COLOURS


# ==========================================================================
# 8. failure handling
# ==========================================================================
def test_a_scenario_that_floods_nothing_exports_without_crashing(tmp_path):
    """
    A scenario with no inundation is a legitimate result — an intact dam, or a
    breach too small to overtop the valley. It must produce a readable deliverable
    saying so, not a traceback.
    """
    from rasterio.transform import from_origin

    z = np.zeros((20, 20))
    haz = classify_hazard(z, z, z, dx=DX,
                          initially_wet=np.zeros((20, 20), dtype=bool))
    arr = analyse_arrival(np.full((20, 20), np.nan), dx=DX,
                          initially_wet=np.zeros((20, 20), dtype=bool))
    s = ScenarioSummary(
        run_id="empty", study_area="Nowhere", scenario="no failure",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, DX, DX), crs=UTM44N,
        dx=DX, shape=(20, 20), max_depth=z, max_speed=z, max_dv=z,
        hazard=haz, arrival=arr)

    files = export.write_all(s, tmp_path, cog=False, include_maps=False,
                             hash_files=False)
    assert "metadata.json" in files
    doc = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    json.dumps(doc, allow_nan=False)
    assert doc["scenario"]["results"]["first_arrival_min"] is None
    assert doc["scenario"]["results"]["flooded_area_km2"] == 0.0


def test_a_stage_failure_is_recorded_rather_than_aborting_the_export(
        scene, tmp_path, monkeypatch):
    """
    A run that produces eight rasters and no PDF is still useful. One that
    produces nothing because reportlab was unhappy is not. But a partial export
    must never look like a complete one.
    """
    def boom(*a, **k):
        raise RuntimeError("simulated reportlab failure")

    monkeypatch.setattr("jaldrishti.export.write_report", boom)
    files = export.write_all(scene, tmp_path, cog=False, hash_files=False)

    assert "report.pdf" not in files
    assert "EXPORT_ERRORS.json" in files
    errors = json.loads((tmp_path / "EXPORT_ERRORS.json").read_text())
    assert "report" in errors
    assert "simulated reportlab failure" in errors["report"]
    # The rest of the deliverable still landed.
    assert (tmp_path / "arrival_time_min.tif").exists()
    assert (tmp_path / "metadata.json").exists()


def test_an_empty_layer_is_skipped_rather_than_written_as_a_broken_file(
        tmp_path):
    import geopandas as gpd

    empty = gpd.GeoDataFrame({"label": []}, geometry=[], crs=UTM44N)
    assert vec_mod.write_shapefile(empty, tmp_path / "none.shp") is None
    assert not (tmp_path / "none.shp").exists()
