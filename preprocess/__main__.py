"""OCR PDFs and split each one into source-document page ranges.

    python -m preprocess 1.pdf 2.pdf 3.pdf 4.pdf
"""

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI

from preprocess.ocr import ocr_pdf
from preprocess.segment import segment_pages


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OCR tax PDFs and segment them at document boundaries.")
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files to preprocess")
    parser.add_argument("--model", default="gpt-4.1", help="OpenAI model for the boundary call")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Directory for OCR text and segments.json")
    args = parser.parse_args(argv)

    _load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    client = OpenAI()
    for pdf_path in args.pdfs:
        if not pdf_path.is_file():
            raise SystemExit(f"PDF not found: {pdf_path}")
        stem_dir = args.out / pdf_path.stem
        print(f"{pdf_path.name}: segmenting", flush=True)
        pages = ocr_pdf(pdf_path, stem_dir / "pages")
        result = segment_pages(pages, client=client, model=args.model)
        payload = {"source": pdf_path.name, **result}
        out_path = stem_dir / "segments.json"
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        ranges = ", ".join(f"{seg['start_page']}-{seg['end_page']}" for seg in result["segments"])
        print(f"{pdf_path.name}: {ranges} -> {out_path}", flush=True)


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines into the environment without overriding existing vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()
