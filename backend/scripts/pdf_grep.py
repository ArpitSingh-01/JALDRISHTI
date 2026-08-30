"""
Dump text from a downloaded PDF so numbers can be read off a primary source.

Companion to nrld_lookup.py, generalised: point it at any reference PDF in
data/reference/ and either dump pages or grep for keywords. Exists so that
"verified=True" in config.py means someone actually read the characters, and so
that the same characters can be produced again on demand.

Usage:
    python scripts/pdf_grep.py thdc_tehri_progress_dec2024.pdf FRL catchment
    python scripts/pdf_grep.py thdc_tehri_progress_dec2024.pdf --page 1 --page 2
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from jaldrishti.config import DATA_DIR

REF = DATA_DIR / "reference"

# Journal PDFs carry en-dashes, degree signs, superscripts and the odd
# unmappable glyph. Windows hands us a cp1252 stdout, and `conda run` relays it
# through another cp1252 encode, so an unencodable character crashes conda itself
# rather than this script. Force UTF-8 with replacement: a "?" in place of a
# superscript costs nothing, a crash costs the whole extraction.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help=f"filename inside {REF}, or a full path")
    ap.add_argument("terms", nargs="*", help="case-insensitive substrings to find")
    ap.add_argument("--page", type=int, action="append", default=[])
    ap.add_argument("--context", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="list available PDFs")
    args = ap.parse_args()

    if args.list:
        for p in sorted(REF.glob("*.pdf")):
            print(f"{p.stat().st_size / 1e6:8.1f} MB  {p.name}")
        return 0

    path = Path(args.pdf)
    if not path.exists():
        path = REF / args.pdf
    if not path.exists():
        print(f"missing {path}")
        return 1

    reader = PdfReader(str(path))
    print(f"{path.name}: {len(reader.pages)} pages\n")

    if args.page:
        for p in args.page:
            print(f"{'=' * 78}\nPAGE {p}\n{'=' * 78}")
            print(reader.pages[p - 1].extract_text())
        return 0

    if not args.terms:
        print("nothing to search for; pass terms or --page")
        return 1

    pats = [(t, re.compile(re.escape(t), re.I)) for t in args.terms]
    hits = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            lines = (page.extract_text() or "").splitlines()
        except Exception as exc:
            print(f"[page {i}: extract failed: {exc}]")
            continue
        for j, line in enumerate(lines):
            for term, pat in pats:
                if pat.search(line):
                    hits += 1
                    print(f"--- page {i}, line {j}  ({term!r})")
                    for k in range(max(0, j - args.context),
                                   min(len(lines), j + args.context + 1)):
                        print(f"{'>>' if k == j else '  '} {lines[k]}")
                    print()
    print(f"{hits} matching lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
