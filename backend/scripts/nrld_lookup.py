"""
Pull dam rows out of the CWC National Register of Large Dams PDF.

WHY THIS EXISTS
---------------
CLAUDE.md forbids putting a reservoir volume on a slide unless it was read off a
primary source. The NRLD is that primary source for Indian dams, and it is a
40 MB scanned-layout PDF with one dam per row across ~30 columns. Reading the
Tehri row by hand and typing it into config.py is exactly the step where a digit
gets transposed, so this script extracts the page text and prints every line
matching a dam name, and the numbers stay auditable: rerun it and you get the
same page number and the same characters.

The extraction is deliberately dumb — raw page text, no table parsing. NRLD's
column alignment does not survive text extraction reliably, so a human still has
to read the row. The value here is (a) finding the right page in 4 seconds and
(b) proving later which page a number came from.

Usage:
    python scripts/nrld_lookup.py TEHRI KOTESHWAR
    python scripts/nrld_lookup.py --page 371          # dump one page verbatim
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from jaldrishti.config import DATA_DIR

PDF = DATA_DIR / "reference" / "nrld_2019.pdf"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="dam names to search for (case-insensitive)")
    ap.add_argument("--page", type=int, action="append", default=[],
                    help="dump this 1-based page verbatim (repeatable)")
    ap.add_argument("--context", type=int, default=0,
                    help="also print N lines either side of a match")
    args = ap.parse_args()

    if not PDF.exists():
        print(f"missing {PDF}\n"
              f"  curl -sL -o {PDF} "
              f"https://cwc.gov.in/sites/default/files/nrld06042019.pdf")
        return 1

    reader = PdfReader(str(PDF))
    print(f"{PDF.name}: {len(reader.pages)} pages\n")

    if args.page:
        for p in args.page:
            print(f"{'=' * 78}\nPAGE {p}\n{'=' * 78}")
            print(reader.pages[p - 1].extract_text())
        return 0

    pats = [(n, re.compile(re.escape(n), re.I)) for n in args.names]
    hits = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:                    # a few NRLD pages are odd
            print(f"[page {i}: extract failed: {exc}]")
            continue
        lines = text.splitlines()
        for j, line in enumerate(lines):
            for name, pat in pats:
                if pat.search(line):
                    hits += 1
                    print(f"--- page {i}, line {j}  (match {name!r})")
                    lo = max(0, j - args.context)
                    hi = min(len(lines), j + args.context + 1)
                    for k in range(lo, hi):
                        mark = ">>" if k == j else "  "
                        print(f"{mark} {lines[k]}")
                    print()
    print(f"{hits} matching lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
