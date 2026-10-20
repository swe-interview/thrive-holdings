"""OCR tax-packet PDFs and split them into source-document segments."""

import json
from pathlib import Path
from typing import Any

from preprocess.ocr import ocr_pdf
from preprocess.segment import segment_pages


def preprocess_pdf(pdf_path: Path, out: Path, *, client: Any, model: str) -> Path:
    """OCR one PDF, split it into page ranges, and write out/<stem>/segments.json."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    stem_dir = Path(out) / pdf_path.stem
    print(f"{pdf_path.name}: segmenting", flush=True)
    pages = ocr_pdf(pdf_path, stem_dir / "pages")
    result = segment_pages(pages, client=client, model=model)
    payload = {"source": pdf_path.name, **result}
    out_path = stem_dir / "segments.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    ranges = ", ".join(f"{seg['start_page']}-{seg['end_page']}" for seg in result["segments"])
    print(f"{pdf_path.name}: {ranges} -> {out_path}", flush=True)
    return out_path
