"""Extract text from a PDF using pdfplumber. Writes UTF-8 to stdout."""
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def extract(pdf_path: Path, page_range: str | None = None) -> None:
    start, end = None, None
    if page_range:
        if "-" in page_range:
            a, b = page_range.split("-", 1)
            start = int(a) - 1 if a else None
            end = int(b) if b else None
        else:
            start = int(page_range) - 1
            end = int(page_range)

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"=== {pdf_path.name} (total pages: {total}) ===\n")
        pages = pdf.pages[start:end] if (start is not None or end is not None) else pdf.pages
        for i, page in enumerate(pages, start=(start or 0) + 1):
            text = page.extract_text() or ""
            print(f"\n--- Page {i} ---")
            print(text)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    rng = sys.argv[2] if len(sys.argv) > 2 else None
    extract(src, rng)
