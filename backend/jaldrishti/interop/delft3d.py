"""
Delft3D-FM interoperability: case export, output import, honest claims.

WHAT THIS MODULE IS — AND WHAT IT IS NOT
----------------------------------------
The problem statement asks the framework to use "SPH and Delft3D" and to
compare the scenarios produced by the modelling approaches. JALDRISHTI's
position on Delft3D is deliberate and must be stated verbatim wherever this
module appears:

    We have NOT run Delft3D. This module makes the framework
    solver-agnostic: it can (a) export a complete Delft3D-FM simulation
    case — UGRID NetCDF mesh, .mdu control file, .ext external-forcing
    file and .bc boundary conditions — so that a Delft3D-FM user can run
    OUR scenario without re-building it, and (b) import published or
    locally-produced Delft3D-FM result files so our scenarios can be
    compared against Delft3D results. No artefact — code comment, slide,
    PDF or spoken answer — may imply we executed Delft3D.

Every export carries `delft3d_case_provenance` metadata stating exactly this,
and `import_delft3d_map` marks imported arrays with their source so the
comparison module (`validation/compare.py`) can label them honestly.

UGRID CONVENTIONS
-----------------
The mesh follows the UGRID conventions v1.0 (https://ugrid-conventions.github.io):
a `mesh2d` variable with cf_role = "mesh_topology", node_coordinates,
face_node_connectivity (quadrilateral faces, start_index = 0), and face
coordinates. Delft3D-FM's network files use the same conventions.

.mdu FORMAT
-----------
Delft3D-FM's main input is a Windows-INI-style file consumed by DIMR. We emit
the geometry, physics, time and output sections needed for a dam-break run of
the exported mesh. Field names follow the Delft3D-FM input descriptions; the
file is written to be structurally valid and human-checkable, and the module
records that it has not been consumed by a Delft3D-FM binary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HONESTY_STATEMENT = (
    "JALDRISHTI exports Delft3D-FM-compatible simulation cases and imports "
    "Delft3D-FM results. JALDRISHTI has not executed the Delft3D-FM binary. "
    "Any comparison labelled 'Delft3D' uses either imported Delft3D output or "
    "published Delft3D results, with the source named."
)


# ---------------------------------------------------------------------------
# Case export
# ---------------------------------------------------------------------------


@dataclass
class Delft3DCase:
    """Paths of one exported case plus its provenance metadata."""
    net_file: Path
    mdu_file: Path
    ext_file: Path
    bc_file: Path
    provenance: dict = field(default_factory=dict)


def quad_nodes(grid) -> tuple[np.ndarray, np.ndarray]:
    """
    Corner nodes and quad connectivity for a TerrainGrid.

    Delft3D-FM is unstructured, but a structured grid is the simplest valid
    UGRID input: one node per cell corner, one quadrilateral face per cell.

    Raster convention: z row 0 is the NORTH row. The node lattice is built
    north-down to match, so face row jj corresponds to z row jj, and each
    face is wound counter-clockwise (SW -> SE -> NE -> NW) as UGRID tools
    and the shoelace check expect.

    Returns (nodes (N,2) x/y, faces (M,4) node indices, face centres).
    """
    ny, nx = grid.shape
    x0, y0, x1, y1 = grid.bounds
    # Node (j, i) sits at the corner: north row first (j = 0 at y = y1).
    node_x = np.linspace(x0, x1, nx + 1)
    node_y = np.linspace(y1, y0, ny + 1)
    nxg, nyg = np.meshgrid(node_x, node_y)
    nodes = np.column_stack([nxg.ravel(), nyg.ravel()])

    def node_index(j, i):
        return j * (nx + 1) + i

    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    # Counter-clockwise: SW, SE, NE, NW.
    faces = np.column_stack([
        node_index(jj + 1, ii).ravel(),
        node_index(jj + 1, ii + 1).ravel(),
        node_index(jj, ii + 1).ravel(),
        node_index(jj, ii).ravel(),
    ])

    face_x = x0 + (ii.ravel() + 0.5) * grid.dx
    face_y = y1 - (jj.ravel() + 0.5) * grid.dx
    return nodes, faces, np.column_stack([face_x, face_y])


def export_case(grid, out_dir: str | Path, *, case_name: str = "jaldrishti",
                initial_surface: float | None = None,
                manning: float = 0.033,
                duration_s: float = 4000.0,
                boundary_water_level: float | None = None,
                crs: str | None = None) -> Delft3DCase:
    """
    Export a complete Delft3D-FM case for `grid`'s terrain and scenario.

    Parameters
    ----------
    grid : TerrainGrid
        Bed elevation and georeferencing. Must have no NaNs.
    initial_surface : uniform initial water-surface elevation (m). For the
        Malpasset-style scenario this is the reservoir level (e.g. 100.0);
        the initial-condition file marks wet cells (bed < surface).
    boundary_water_level : constant water-level boundary value for the
        downstream (sea) boundary; None writes a zero-gradient-free closed
        boundary note instead.

    Returns a Delft3DCase with the four artefact paths.
    """
    import netCDF4

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if np.isnan(grid.z).any():
        raise ValueError("grid.z contains NaNs — condition the DEM first")

    nodes, faces, face_xy = quad_nodes(grid)
    ny, nx = grid.shape

    # --- UGRID NetCDF network file -----------------------------------------
    net_path = out_dir / f"{case_name}_net.nc"
    with netCDF4.Dataset(net_path, "w", format="NETCDF4") as ds:
        ds.Conventions = "CF-1.8 UGRID-1.0"
        ds.title = f"JALDRISHTI exported case: {case_name}"
        ds.institution = "JALDRISHTI — SIH 2026 PS 26161"
        ds.source = ("Exported from JALDRISHTI's TerrainGrid "
                     f"({grid.source}); NOT produced by or run through "
                     "Delft3D-FM")
        ds.history = (f"{datetime.now(timezone.utc).isoformat()} "
                      "export by jaldrishti.interop.delft3d")

        ds.createDimension("nmesh2d_node", nodes.shape[0])
        ds.createDimension("nmesh2d_face", faces.shape[0])
        ds.createDimension("nmax_mesh2d_face_nodes", 4)

        vx = ds.createVariable("mesh2d_node_x", "f8", ("nmesh2d_node",))
        vx.standard_name = "projection_x_coordinate"
        vx.units = "m"
        vy = ds.createVariable("mesh2d_node_y", "f8", ("nmesh2d_node",))
        vy.standard_name = "projection_y_coordinate"
        vy.units = "m"
        vx[:] = nodes[:, 0]
        vy[:] = nodes[:, 1]

        fn = ds.createVariable(
            "mesh2d_face_nodes", "i8",
            ("nmesh2d_face", "nmax_mesh2d_face_nodes"))
        fn.cf_role = "face_node_connectivity"
        fn.long_name = "maps every face to its corner nodes (CCW)"
        fn.start_index = 0
        fn[:] = faces

        fx = ds.createVariable("mesh2d_face_x", "f8", ("nmesh2d_face",))
        fy = ds.createVariable("mesh2d_face_y", "f8", ("nmesh2d_face",))
        fx.standard_name = "projection_x_coordinate"
        fy.standard_name = "projection_y_coordinate"
        fx.units = fy.units = "m"
        fx[:] = face_xy[:, 0]
        fy[:] = face_xy[:, 1]

        bz = ds.createVariable("mesh2d_face_z", "f8", ("nmesh2d_face",))
        bz.standard_name = "altitude"
        bz.long_name = "bed level at face"
        bz.units = "m"
        bz[:] = grid.z.ravel().astype(np.float64)

        mesh = ds.createVariable("mesh2d", "i4")
        mesh.cf_role = "mesh_topology"
        mesh.long_name = "JALDRISHTI quadrilateral mesh"
        mesh.topology_dimension = 2
        mesh.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        mesh.face_node_connectivity = "mesh2d_face_nodes"
        mesh.face_coordinates = "mesh2d_face_x mesh2d_face_y"
        mesh.edge_coordinates = ""  # edges are implied by faces

    # --- .mdu control file ----------------------------------------------------
    mdu_path = out_dir / f"{case_name}.mdu"
    surf = initial_surface if initial_surface is not None else 0.0
    mdu = _MDU_TEMPLATE.format(
        case=case_name,
        net=net_path.name,
        water_level=surf,
        manning=manning,
        duration_s=duration_s,
        refdate="20260101000000",
    )
    mdu_path.write_text(mdu, encoding="ascii")

    # --- .ext external forcing file --------------------------------------------
    ext_path = out_dir / f"{case_name}.ext"
    if boundary_water_level is not None:
        ext = _EXT_TEMPLATE.format(
            case=case_name,
            bc=f"{case_name}_bnd.bc",
            quantity="waterlevelbnd",
        )
    else:
        ext = ("# No open boundary specified: closed (wall) boundaries only.\n"
               "# A real Delft3D-FM run of a dam-break scenario normally adds\n"
               "# a waterlevelbnd or dischargebnd at the downstream end.\n")
    ext_path.write_text(ext, encoding="ascii")

    # --- .bc boundary forcing -----------------------------------------------------
    bc_path = out_dir / f"{case_name}_bnd.bc"
    if boundary_water_level is not None:
        bc_path.write_text(
            _BC_TEMPLATE.format(
                name=f"{case_name}_sea",
                quantity="waterlevelbnd",
                unit="m",
                t0="2026-01-01 00:00:00",
                steps=int(duration_s) + 1,
                value=boundary_water_level,
            ),
            encoding="ascii",
        )
    else:
        bc_path.write_text("# no open boundary\n", encoding="ascii")

    provenance = {
        "generator": "JALDRISHTI interop.delft3d.export_case",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "honesty": HONESTY_STATEMENT,
        "executed_by_delft3d": False,
        "grid_source": grid.source,
        "grid_crs": crs or grid.crs,
        "cells": int(ny * nx),
        "faces": int(faces.shape[0]),
        "initial_surface_m": surf,
        "manning": manning,
        "duration_s": duration_s,
    }
    (out_dir / f"{case_name}_delft3d_case_provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")

    return Delft3DCase(net_path, mdu_path, ext_path, bc_path,
                       provenance=provenance)


# ---------------------------------------------------------------------------
# Output import
# ---------------------------------------------------------------------------

# Delft3D-FM map files name their variables with the mesh2d_ prefix; different
# FM versions have used minor variants. Match on substrings, not exact names.
_DEPTH_KEYS = ("mesh2d_waterdepth", "waterdepth", "water_depth")
_WATERLEVEL_KEYS = ("mesh2d_s1", "s1", "waterlevel")
_BED_KEYS = ("mesh2d_bl", "bedlevel", "bl")


def import_delft3d_map(path: str | Path) -> dict:
    """
    Read a Delft3D-FM map output NetCDF into plain arrays for comparison.

    Returns a dict with:
        face_x, face_y   : (nface,) face-centre coordinates
        bed              : (nface,) bed elevation, if present
        times            : (ntime,) times in seconds since ref date
        depth            : (ntime, nface) water depth
        max_depth        : (nface,) max over time
        source           : the file path
        honesty          : the standing statement about what this is

    Variable lookup is by substring so minor FM version differences do not
    break the reader; missing quantities are simply absent from the result.
    """
    import netCDF4

    path = Path(path)
    out: dict = {"source": str(path),
                 "honesty": HONESTY_STATEMENT,
                 "executed_by_delft3d": True}
    with netCDF4.Dataset(path) as ds:
        # Face coordinates
        for key in ("mesh2d_face_x", "Face_x", "face_x"):
            if key in ds.variables:
                out["face_x"] = np.asarray(ds.variables[key][:])
                break
        for key in ("mesh2d_face_y", "Face_y", "face_y"):
            if key in ds.variables:
                out["face_y"] = np.asarray(ds.variables[key][:])
                break

        def find(keys):
            for want in keys:
                for name, var in ds.variables.items():
                    if want in name.lower() and getattr(var, "ndim", 0) >= 1:
                        return var
            return None

        if "mesh2d" in ds.variables:
            topo = ds.variables["mesh2d"]
            node_coords = getattr(topo, "node_coordinates", "")
            if node_coords:
                nx_name = node_coords.split()[0]
                ny_name = node_coords.split()[1]
                out["node_x"] = np.asarray(ds.variables[nx_name][:])
                out["node_y"] = np.asarray(ds.variables[ny_name][:])

        depth = find(_DEPTH_KEYS)
        if depth is not None:
            a = np.asarray(depth[:], dtype=np.float64)
            if a.ndim == 1:
                a = a[None, :]
            out["depth"] = a
            out["max_depth"] = a.max(axis=0)
        wl = find(_WATERLEVEL_KEYS)
        if wl is not None:
            a = np.asarray(wl[:], dtype=np.float64)
            if a.ndim == 1:
                a = a[None, :]
            out["waterlevel"] = a
        bed = find(_BED_KEYS)
        if bed is not None:
            out["bed"] = np.asarray(bed[:], dtype=np.float64)

        # Times: FM stores time with units "seconds since ..."; use netCDF4.
        for tname in ("time", "mesh2d_time", "t"):
            if tname in ds.variables:
                tvar = ds.variables[tname]
                try:
                    import cftime
                    out["times"] = cftime.num2date(
                        tvar[:], tvar.units,
                        only_use_cftime_datetimes=False)
                except Exception:
                    out["times"] = np.asarray(tvar[:])
                break
    return out


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_MDU_TEMPLATE = """# JALDRISHTI exported Delft3D-FM case: {case}
# Generated by jaldrishti.interop.delft3d - see the provenance JSON beside
# this file. JALDRISHTI has NOT executed Delft3D; this case is provided so a
# Delft3D-FM user can run the identical scenario.
[Geometry]
    NetFile                      = {net}
    BedLevelType                 = 3          # bed level from net file
    UniformWaterLevel            = {water_level}   # initial surface, m
    WaterLevIniFile              =
[Physics]
    UnifFrictType                = 1          # 1 = Manning
    UnifFrictCoef                = {manning}
    UFRMPt                       =
[Numerics]
    CflStr                       = 0.4
    AdvecType                    = 33
    ViscousflowDefault           = 1.0
[Time]
    RefDate                      = {refdate}
    TStart                       = 0          # s
    TStop                        = {duration_s:.0f}          # s
    TUnit                        = S
[Timestep]
    DtUser                       = 1.0        # s
    DtMax                        = 30.0
[Output]
    # Interval in DtUser units; face and node maps on.
    Mbalhisinterval              = 60.0
    MapInterval                  = 60.0
    WrimapFlow                   = 1
    WrimapWaves                  = 0
"""

_EXT_TEMPLATE = """# JALDRISHTI exported external-forcing file for {case}
[Boundary]
    quantity                     = {quantity}
    forcingfile                  = {bc}
    bndname                      = sea_boundary
"""

_BC_TEMPLATE = """[forcing]
    Name                         = {name}
    Function                     = timeseries
    TimeInterpolation            = linear
    Quantity                     = time
    Unit                         = datetime
    Quantity1                    = {quantity}
    Unit1                        = {unit}
    VERIFICATION                 = {t0} ({steps} s at 1 s step, constant {value} m)
    {t0}
    values                       = {value}
"""


def validate_ugrid(net_path: str | Path) -> dict:
    """
    Structural checks on an exported network file.

    Verifies: CF/UGRID conventions declared, topology variable present with
    the three required attributes, connectivity indices in range, faces
    counter-clockwise, bed elevations finite. Returns the check results —
    used by tests and by the metadata writer. This validates STRUCTURE only;
    passing it does not mean Delft3D-FM consumed the file.
    """
    import netCDF4

    checks: dict = {}
    with netCDF4.Dataset(net_path) as ds:
        checks["conventions"] = "UGRID" in getattr(ds, "Conventions", "")
        mesh = ds.variables.get("mesh2d")
        checks["topology_var"] = mesh is not None
        if mesh is not None:
            checks["cf_role"] = getattr(mesh, "cf_role", "") == "mesh_topology"
            checks["node_coordinates"] = bool(
                getattr(mesh, "node_coordinates", ""))
            checks["face_connectivity"] = bool(
                getattr(mesh, "face_node_connectivity", ""))
        fn = np.asarray(ds.variables["mesh2d_face_nodes"][:])
        nnodes = ds.dimensions["nmesh2d_node"].size
        checks["indices_in_range"] = bool(
            fn.min() >= 0 and fn.max() < nnodes)
        nx = np.asarray(ds.variables["mesh2d_node_x"][:])
        ny = np.asarray(ds.variables["mesh2d_node_y"][:])
        quad = nx[fn]  # (nface, 4)
        quady = ny[fn]
        # CCW check via the shoelace sign, on the projection plane.
        x = quad
        y = quady
        area = 0.0
        for k in range(4):
            j = (k + 1) % 4
            area += x[:, k] * y[:, j] - x[:, j] * y[:, k]
        checks["faces_ccw"] = bool((area > 0).all())
        bz = np.asarray(ds.variables["mesh2d_face_z"][:])
        checks["bed_finite"] = bool(np.isfinite(bz).all())
        checks["n_faces"] = int(fn.shape[0])
        checks["n_nodes"] = int(nnodes)
    return checks
