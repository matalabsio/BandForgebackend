#!/usr/bin/env python3
"""Extract plain text from MT2 listening transcript PDFs.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.extract_mt2_listening_pdfs
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = REPO_ROOT / "test" / "MT2" / "LT" / "pdf"
OUT_DIR = REPO_ROOT / "test" / "MT2" / "LT" / "transcripts"


def main() -> int:
    if not PDF_DIR.is_dir():
        print(f"Missing {PDF_DIR}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("MT2_LT_S*_Transcript.pdf"))
    if not pdfs:
        print(f"No PDFs in {PDF_DIR}")
        return 1
    for pdf in pdfs:
        reader = PdfReader(str(pdf))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        out = OUT_DIR / f"{pdf.stem}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out.relative_to(REPO_ROOT)} ({len(reader.pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
