"""Full-page Tesseract OCR, cached as one text file per page."""

from pathlib import Path

import pymupdf

DPI = 200
LANGUAGE = "eng"


def ocr_pdf(pdf_path: Path, pages_dir: Path, dpi: int = DPI) -> list[str]:
    """Return OCR text for each page of pdf_path, page 1 first.

    Writes pages_dir/001.txt, 002.txt, ... and reuses those files on a later run.
    """
    pdf_path = Path(pdf_path)
    pages_dir = Path(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        cached = _read_cache(pages_dir, page_count)
        if cached is not None:
            print(f"{pdf_path.name}: using cached OCR ({page_count} pages)")
            return cached

        texts: list[str] = []
        for index, page in enumerate(doc, start=1):
            print(f"{pdf_path.name}: OCR page {index}/{page_count}", flush=True)
            textpage = page.get_textpage_ocr(language=LANGUAGE, dpi=dpi, full=True)
            text = page.get_text("text", textpage=textpage).strip()
            _page_path(pages_dir, index).write_text(text + "\n", encoding="utf-8")
            texts.append(text)
        return texts


def _read_cache(pages_dir: Path, page_count: int) -> list[str] | None:
    paths = [_page_path(pages_dir, index) for index in range(1, page_count + 1)]
    if not paths or not all(path.is_file() for path in paths):
        return None
    return [path.read_text(encoding="utf-8").strip() for path in paths]


def _page_path(pages_dir: Path, page_number: int) -> Path:
    return pages_dir / f"{page_number:03d}.txt"
