"""python -m workpaper preprocesses every PDF, then writes the assembled outline."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pymupdf

from schema import load_workpaper
from workpaper.classify import Classification
from workpaper.segment import Segment

WORKPAPER = load_workpaper(Path(__file__).resolve().parents[1] / "workpaper.pdf")


def write_pdf(path: Path) -> None:
    document = pymupdf.open()
    try:
        document.new_page()
        document.save(path)
    finally:
        document.close()


class PipelineTests(unittest.TestCase):
    def test_preprocesses_each_pdf_then_assembles(self) -> None:
        wages = next(section for section in WORKPAPER.sections if section.name == "Wages")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "a.pdf"
            write_pdf(pdf)
            out = root / "cache"
            dest = root / "workpaper.pdf"
            segment = Segment(text="Form W-2", source="a.pdf", start_page=1, end_page=1)

            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test", "OPENAI_MODEL": "from-env"}),
                patch("workpaper.__main__.OpenAI") as openai,
                patch("workpaper.__main__.preprocess_pdf") as preprocess,
                patch("workpaper.__main__.segments_from_preprocess", return_value=[segment]),
                patch(
                    "workpaper.__main__.classify_segments",
                    return_value=[Classification(wages, "high", "W-2")],
                ) as classify,
                patch("workpaper.__main__.assemble") as assemble,
            ):
                from workpaper.__main__ import main

                main([str(pdf), "--out", str(out), "--dest", str(dest)])

            client = openai.return_value
            preprocess.assert_called_once_with(pdf, out, client=client, model="from-env")
            classify.assert_called_once_with([segment], client=client, model="from-env")
            assemble.assert_called_once_with([pdf], [(segment, wages)], dest)


if __name__ == "__main__":
    unittest.main()
