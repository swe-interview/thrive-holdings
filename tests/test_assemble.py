"""Assembled outline follows the schema sections and classified segment pages."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf

from schema import WorkpaperSection, load_workpaper
from workpaper.assemble import assemble, segments_from_preprocess
from workpaper.segment import Segment

WORKPAPER = Path(__file__).resolve().parents[1] / "workpaper.pdf"


def write_pdf(path: Path, pages: int) -> None:
    document = pymupdf.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"{path.name} page {index + 1}")
        document.save(path)
    finally:
        document.close()


def section_named(name: str) -> WorkpaperSection:
    packet = load_workpaper(WORKPAPER)
    for section in packet.sections:
        if section.name == name:
            return section
    raise AssertionError(f"missing section {name}")


def level1_page(toc: list[list], title: str) -> int:
    for level, label, page in toc:
        if level == 1 and label == title:
            return page
    raise AssertionError(f"missing section bookmark {title}")


def child_page(toc: list[list], section: str, title: str) -> int:
    current = None
    for level, label, page in toc:
        if level == 1:
            current = label
        elif level == 2 and current == section and label == title:
            return page
    raise AssertionError(f"missing bookmark {section} / {title}")


class AssembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.a = root / "a.pdf"
        self.b = root / "b.pdf"
        write_pdf(self.a, 2)
        write_pdf(self.b, 1)
        self.dest = root / "assembled.pdf"

    def test_outline_uses_schema_order_and_concatenated_pages(self) -> None:
        template = load_workpaper(WORKPAPER)
        filed = [
            (
                Segment(text="later wages", source="b.pdf", start_page=1, end_page=1),
                section_named("Wages"),
            ),
            (
                Segment(text="brokerage", source="a.pdf", start_page=2, end_page=2),
                section_named("Brokerage & Combined Tax Statements"),
            ),
            (
                Segment(text="earlier wages", source="a.pdf", start_page=1, end_page=1),
                section_named("Wages"),
            ),
        ]

        assemble([self.a, self.b], filed, self.dest)

        document = pymupdf.open(self.dest)
        try:
            self.assertEqual(document.page_count, 3)
            toc = document.get_toc()
        finally:
            document.close()

        level1 = [title for level, title, _page in toc if level == 1]
        self.assertEqual(level1, [section.name for section in template.sections])
        self.assertEqual(level1_page(toc, "Cover Sheet"), 1)
        self.assertEqual(level1_page(toc, "Wages"), 1)
        self.assertEqual(level1_page(toc, "Brokerage & Combined Tax Statements"), 2)
        self.assertEqual(child_page(toc, "Wages", "a.pdf pp. 1-1"), 1)
        self.assertEqual(child_page(toc, "Wages", "b.pdf pp. 1-1"), 3)
        self.assertEqual(
            child_page(toc, "Brokerage & Combined Tax Statements", "a.pdf pp. 2-2"),
            2,
        )
        wages_children = _children(toc, "Wages")
        self.assertEqual(wages_children, ["a.pdf pp. 1-1", "b.pdf pp. 1-1"])

        loaded = load_workpaper(self.dest)
        self.assertEqual(
            [section.name for section in loaded.sections],
            [section.name for section in template.sections],
        )

    def test_segments_from_preprocess_joins_ocr_pages(self) -> None:
        root = Path(self.tmp.name) / "out" / "a"
        pages = root / "pages"
        pages.mkdir(parents=True)
        (pages / "001.txt").write_text("page one\n", encoding="utf-8")
        (pages / "002.txt").write_text("page two\n", encoding="utf-8")
        (root / "segments.json").write_text(
            json.dumps(
                {
                    "source": "a.pdf",
                    "segments": [{"start_page": 1, "end_page": 2}],
                }
            ),
            encoding="utf-8",
        )

        segments = segments_from_preprocess(self.a, Path(self.tmp.name) / "out")

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].source, "a.pdf")
        self.assertEqual(segments[0].start_page, 1)
        self.assertEqual(segments[0].end_page, 2)
        self.assertEqual(segments[0].text, "page one\n\npage two\n")


def _children(toc: list[list], section: str) -> list[str]:
    current = None
    titles: list[str] = []
    for level, label, _page in toc:
        if level == 1:
            current = label
        elif level == 2 and current == section:
            titles.append(label)
    return titles


if __name__ == "__main__":
    unittest.main()
