"""
Regenerate the validation-ladder figures — the never-cut deliverable.

WHY THIS SCRIPT EXISTS
----------------------
The four ladder charts (well-balancedness, Ritter dry bed, Stoker wet bed,
Manning friction) are produced by the `test_*_chart` functions inside the test
suite, so that a figure is never allowed to disagree with the assertions that
prove the solver correct: the same run that writes the PNG also asserts the L2 /
L-infinity error, the mass drift and the wave speeds are within tolerance. A
chart that would be wrong is a test that fails, and no PNG is emitted.

That coupling is exactly what we want, but it makes the figures awkward to
regenerate on demand ("which pytest node IDs were those again?"). This wrapper is
the one honest command:

    python scripts/make_validation_figures.py

It runs *only* the chart tests, with capture disabled so the measured error
numbers each test prints land on the console, then lists the PNGs it produced.
Its exit code is pytest's: a non-zero exit means a validation assertion failed
and the figures it wrote — if any — must not be trusted or presented.

    python scripts/make_validation_figures.py            # all chart figures
    python scripts/make_validation_figures.py -k ritter  # just one rung
    python scripts/make_validation_figures.py --quiet     # suppress the per-test prints
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

FIG_DIR = REPO_ROOT / "outputs" / "validation"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "-k", dest="pattern", default="chart",
        help="pytest -k expression selecting which chart tests to run "
             "(default: 'chart', i.e. every validation figure)")
    p.add_argument(
        "--quiet", action="store_true",
        help="hide the per-test measured-error prints (keeps only the summary)")
    a = p.parse_args()

    # Deferred: importing pytest and matplotlib is slow, and argparse should be
    # able to fail fast on a bad flag without paying for it.
    import pytest

    tests_dir = BACKEND_DIR / "tests"
    before = _snapshot(FIG_DIR)

    args = [str(tests_dir), "-k", a.pattern, "-p", "no:cacheprovider"]
    # -s surfaces the '[ritter] front @ 0.10 m ...' lines the chart tests print;
    # those measured numbers are the point, so they are on by default.
    args += ["-q"] if a.quiet else ["-rA", "-s"]

    print("=" * 74)
    print(f"Regenerating validation figures  ->  {FIG_DIR}")
    print(f"  pytest {' '.join(args)}")
    print("=" * 74)

    code = int(pytest.main(args))

    after = _snapshot(FIG_DIR)
    print("\n" + "=" * 74)
    print("FIGURES")
    print("=" * 74)
    if not after:
        print("  (none found — did any chart test match the pattern?)")
    for name, (size, mtime) in sorted(after.items()):
        tag = ""
        if name not in before:
            tag = "  [new]"
        elif mtime > before[name][1]:
            tag = "  [regenerated]"
        else:
            tag = "  [unchanged]"
        print(f"  {name:32s} {size / 1024:7.1f} KiB{tag}")

    print("\n" + ("PASS — figures were produced by a validation run that passed."
                  if code == 0 else
                  f"FAIL — pytest exit {code}. A validation assertion failed; "
                  "do not present any figure written by this run."))
    return code


def _snapshot(d: Path) -> dict[str, tuple[int, float]]:
    """Map of *.png name -> (size_bytes, mtime) currently in the figures dir."""
    if not d.exists():
        return {}
    return {f.name: (f.stat().st_size, f.stat().st_mtime)
            for f in d.glob("*.png")}


if __name__ == "__main__":
    raise SystemExit(main())
