"""Classifier sections are the level-1 buckets from workpaper.pdf."""

import unittest
from pathlib import Path

import pymupdf

from schema import (
    SECTIONS,
    Section,
    WorkpaperSection,
    load_workpaper,
    table_of_contents_from_outline,
    workpaper_from_toc,
)

WORKPAPER = Path(__file__).resolve().parents[1] / "workpaper.pdf"


def level1_labels(path: Path) -> list[str]:
    document = pymupdf.open(path)
    labels: list[str] = []
    for level, title, _page in document.get_toc():
        if level == 1:
            labels.append(title)
    return labels


class SchemaTests(unittest.TestCase):
    def test_schema_sections_match_level1_toc(self) -> None:
        labels = level1_labels(WORKPAPER)
        self.assertEqual(list(SECTIONS), labels)
        self.assertEqual([section.value for section in Section], labels)
        packet = load_workpaper(WORKPAPER)
        self.assertEqual([section.name for section in packet.sections], labels)

    def test_outline_outside_the_buckets_is_rejected(self) -> None:
        toc = table_of_contents_from_outline([[1, "Wages", 1]])
        with self.assertRaises(ValueError):
            workpaper_from_toc(toc, page_count=1)

    def test_unknown_section_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WorkpaperSection(name="Not a workpaper section", bookmark_page=1)


if __name__ == "__main__":
    unittest.main()
