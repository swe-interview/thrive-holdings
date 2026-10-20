"""Preprocess source PDFs, classify each segment, and write the workpaper.

    python -m workpaper 1.pdf 2.pdf 3.pdf 4.pdf
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from openai import OpenAI

from preprocess import preprocess_pdf
from workpaper.assemble import assemble, bookmark_title, segments_from_preprocess
from workpaper.classify import _load_dotenv, classify_segments


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="OCR source PDFs, split them into documents, and write a bookmarked workpaper."
    )
    parser.add_argument("pdfs", nargs="+", type=Path, help="Source PDFs in scan order")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model for segmentation and classification (default: OPENAI_MODEL or gpt-4.1)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out"),
        help="Directory for OCR text and segments.json",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("assembled_workpaper.pdf"),
        help="Output PDF",
    )
    args = parser.parse_args(argv)

    _load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    for pdf_path in args.pdfs:
        if not pdf_path.is_file():
            raise SystemExit(f"PDF not found: {pdf_path}")

    model = args.model or os.environ.get("OPENAI_MODEL", "gpt-4.1")
    client = OpenAI()
    for pdf_path in args.pdfs:
        preprocess_pdf(pdf_path, args.out, client=client, model=model)

    segments = []
    for pdf_path in args.pdfs:
        segments.extend(segments_from_preprocess(pdf_path, args.out))

    classifications = classify_segments(segments, client=client, model=model)
    filed = []
    for segment, classification in zip(segments, classifications, strict=True):
        print(
            f"{bookmark_title(segment)} -> {classification.section.name} ({classification.confidence})",
            flush=True,
        )
        filed.append((segment, classification.section))

    assemble(args.pdfs, filed, args.dest)
    print(f"wrote {args.dest}", flush=True)


if __name__ == "__main__":
    main()
