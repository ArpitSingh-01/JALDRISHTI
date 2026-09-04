"""Solver-agnostic model interoperability.

`delft3d` exports Delft3D-FM–compatible simulation cases (UGRID NetCDF mesh,
.mdu control file, .ext / .bc forcing) and imports Delft3D-FM result files so
JALDRISHTI scenarios can be compared against Delft3D results. The honesty
statement in the module is binding: JALDRISHTI has not executed Delft3D, and
no artefact may claim otherwise.
"""

from .delft3d import (
    HONESTY_STATEMENT,
    Delft3DCase,
    export_case,
    import_delft3d_map,
    quad_nodes,
    validate_ugrid,
)

__all__ = [
    "HONESTY_STATEMENT",
    "Delft3DCase",
    "export_case",
    "import_delft3d_map",
    "quad_nodes",
    "validate_ugrid",
]
