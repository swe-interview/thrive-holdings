"""OCR PDFs and split each one into source-document page ranges.

    python -m preprocess 1.pdf 2.pdf 3.pdf 4.pdf
"""

import argparse
import os
from pathlib import Path

from openai import OpenAI

from preprocess import preprocess_pdf


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
        try:
            preprocess_pdf(pdf_path, args.out, client=client, model=args.model)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc


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
