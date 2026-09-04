"""
Tests for the Delft3D-FM interop layer (interop/delft3d.py).

Two rules govern this module:

1. STRUCTURE IS VERIFIED, EXECUTION IS NOT CLAIMED. The exported case must be
   a structurally valid UGRID mesh + .mdu + .ext + .bc set — checked here by
   round-trip inspection. Nothing in this file, or in any artefact the module
   writes, asserts that Delft3D-FM consumed the case. The provenance JSON
   written beside every export carries `executed_by_delft3d: False`.

2. IMPORTS ARE LABELLED. Anything read by `import_delft3d_map` carries the
   honesty statement and `executed_by_delft3d: True` — true because the file
   came out of Delft3D-FM (or a fixture shaped exactly like one), so the
   comparison layer can cite it as Delft3D output.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from jaldrishti.interop import (
    HONESTY_STATEMENT,
    export_case,
    import_delft3d_map,
    quad_nodes,
    validate_ugrid,
)
from jaldrishti.terrain.dem import TerrainGrid

import rasterio.transform


@pytest.fixture
def small_grid() -> TerrainGrid:
    """A synthetic 30 x 20 valley: ridge on the north, channel to the south."""
    ny, nx = 20, 30
    dx = 50.0
    x0, y1 = 500000.0, 4600000.0
    tr = rasterio.transform.from_origin(x0, y1, dx, dx)
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    z = 100.0 - 0.5 * jj * dx / 100.0 + 8.0 * np.exp(
        -((ii - 12) ** 2) / 50.0)   # slope down + a ridge
    return TerrainGrid(z=z, dx=dx, crs="EPSG:32644", transform=tr,
                       source="synthetic test grid")


# ---------------------------------------------------------------------------
# Export: UGRID structure
# ---------------------------------------------------------------------------


def test_export_produces_four_artifacts(small_grid, tmp_path):
    case = export_case(small_grid, tmp_path, case_name="test",
                       initial_surface=95.0, boundary_water_level=0.0,
                       duration_s=4000.0)
    assert case.net_file.exists()
    assert case.mdu_file.exists()
    assert case.ext_file.exists()
    assert case.bc_file.exists()
    prov_path = case.net_file.parent / "test_delft3d_case_provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["executed_by_delft3d"] is False
    assert "not" in prov["honesty"].lower()
    assert HONESTY_STATEMENT == prov["honesty"]


def test_ugrid_structure_valid(small_grid, tmp_path):
    case = export_case(small_grid, tmp_path, case_name="test",
                       initial_surface=95.0)
    checks = validate_ugrid(case.net_file)
    for key in ("conventions", "topology_var", "cf_role",
                "node_coordinates", "face_connectivity",
                "indices_in_range", "faces_ccw", "bed_finite"):
        assert checks[key], f"UGRID structural check failed: {key}"
    ny, nx = small_grid.shape
    assert checks["n_faces"] == ny * nx
    assert checks["n_nodes"] == (ny + 1) * (nx + 1)


def test_bed_elevation_matches_grid_row_order(small_grid, tmp_path):
    """
    The face bed array must match the raster in raster order: face row 0 is
    the NORTH row. This pins the north-down node-lattice convention — get it
    wrong and every Delft3D result lands in the wrong place silently.
    """
    import netCDF4

    case = export_case(small_grid, tmp_path, case_name="test",
                       initial_surface=95.0)
    with netCDF4.Dataset(case.net_file) as ds:
        bed = np.asarray(ds.variables["mesh2d_face_z"][:]).reshape(
            small_grid.shape)
        fy = np.asarray(ds.variables["mesh2d_face_y"][:]).reshape(
            small_grid.shape)
    assert np.allclose(bed, small_grid.z, atol=1e-9)
    # face row 0 must be the northernmost (max y) — raster row 0 convention.
    assert fy[0, 0] > fy[-1, 0]


def test_face_centres_inside_grid(small_grid, tmp_path):
    nodes, faces, centres = quad_nodes(small_grid)
    x0, y0, x1, y1 = small_grid.bounds
    assert (centres[:, 0] > x0).all() and (centres[:, 0] < x1).all()
    assert (centres[:, 1] > y0).all() and (centres[:, 1] < y1).all()


# ---------------------------------------------------------------------------
# Export: control files
# ---------------------------------------------------------------------------


def test_mdu_contains_required_settings(small_grid, tmp_path):
    case = export_case(small_grid, tmp_path, case_name="test",
                       initial_surface=95.0, manning=0.033,
                       duration_s=4000.0)
    text = case.mdu_file.read_text(encoding="ascii")
    assert "NetFile" in text and "test_net.nc" in text
    assert "UnifFrictCoef" in text and "0.033" in text
    assert "UniformWaterLevel" in text and "95.0" in text
    assert "TStop" in text


def test_bc_file_carries_boundary_series(small_grid, tmp_path):
    case = export_case(small_grid, tmp_path, case_name="test",
                       initial_surface=95.0, boundary_water_level=0.0)
    text = case.bc_file.read_text(encoding="ascii")
    assert "waterlevelbnd" in text
    assert "timeseries" in text


def test_export_rejects_nan_bed(small_grid, tmp_path):
    small_grid.z[5, 5] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        export_case(small_grid, tmp_path, case_name="bad")


# ---------------------------------------------------------------------------
# Import: Delft3D-FM map output (fixture shaped like a real map file)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_d3d_map(tmp_path, small_grid):
    """A NetCDF shaped the way Delft3D-FM writes map output."""
    import netCDF4

    path = tmp_path / "test_map.nc"
    ny, nx = small_grid.shape
    nodes, faces, centres = quad_nodes(small_grid)
    nt = 3
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("nmesh2d_node", nodes.shape[0])
        ds.createDimension("nmesh2d_face", faces.shape[0])
        ds.createDimension("time", nt)
        vx = ds.createVariable("mesh2d_node_x", "f8", ("nmesh2d_node",))
        vy = ds.createVariable("mesh2d_node_y", "f8", ("nmesh2d_node",))
        vx[:], vy[:] = nodes[:, 0], nodes[:, 1]
        topo = ds.createVariable("mesh2d", "i4")
        topo.cf_role = "mesh_topology"
        topo.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        fx = ds.createVariable("mesh2d_face_x", "f8", ("nmesh2d_face",))
        fy = ds.createVariable("mesh2d_face_y", "f8", ("nmesh2d_face",))
        fx[:], fy[:] = centres[:, 0], centres[:, 1]
        bl = ds.createVariable("mesh2d_bl", "f8", ("nmesh2d_face",))
        bl[:] = small_grid.z.ravel()
        wd = ds.createVariable("mesh2d_waterdepth", "f8",
                               ("time", "nmesh2d_face"))
        depth = np.zeros((nt, faces.shape[0]))
        # Decay with distance from the domain's west edge (local coords —
        # face x is ~500 km in UTM, so a raw exp(-x/500) underflows to zero).
        x_rel = centres[:, 0] - centres[:, 0].min()
        for k in range(nt):
            depth[k] = 1.5 * (k + 1) * np.exp(-x_rel / 500.0)
        wd[:] = depth
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-01-01 00:00:00"
        tv[:] = [0.0, 60.0, 120.0]
    return path


def test_import_reads_depth_and_labels_source(fake_d3d_map):
    out = import_delft3d_map(fake_d3d_map)
    assert "max_depth" in out and "depth" in out
    assert out["depth"].shape[0] == 3
    # max over time == 1.5 * 3 * exp(-x/500)
    assert out["max_depth"].max() == pytest.approx(4.5, rel=1e-6)
    assert out["executed_by_delft3d"] is True
    assert out["honesty"] == HONESTY_STATEMENT


def test_import_tolerates_missing_quantities(tmp_path):
    """A map file without water level or bed must not break the reader."""
    import netCDF4

    path = tmp_path / "sparse_map.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("nmesh2d_face", 4)
        fx = ds.createVariable("mesh2d_face_x", "f8", ("nmesh2d_face",))
        fx[:] = [0.0, 1.0, 2.0, 3.0]
        fy = ds.createVariable("mesh2d_face_y", "f8", ("nmesh2d_face",))
        fy[:] = [0.0, 0.0, 0.0, 0.0]
        wd = ds.createVariable("mesh2d_waterdepth", "f8", ("nmesh2d_face",))
        wd[:] = [1.0, 2.0, 0.5, 0.0]
    out = import_delft3d_map(path)
    assert "max_depth" in out
    assert "waterlevel" not in out
    assert "bed" not in out
