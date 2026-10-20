"""Segment names and merges of related pieces."""

import unittest
from types import SimpleNamespace
from typing import Literal

from schema import WorkpaperSection
from workpaper.name import (
    SYSTEM_PROMPT,
    DocumentLabel,
    FiledSegment,
    SegmentNames,
    format_title,
    label_segments,
    merge_related,
)
from workpaper.segment import Segment


def section(name: str) -> WorkpaperSection:
    return WorkpaperSection(name=name, bookmark_page=1)


WAGES = section("Wages")
DIVIDENDS = section("Schedule B - Dividends")
INTEREST = section("Schedule B - Interest")
BROKERAGE = section("Brokerage & Combined Tax Statements")
MORTGAGE = section("Schedule A - Interest")
LOOKUP = {item.name: item for item in (WAGES, DIVIDENDS, INTEREST, BROKERAGE, MORTGAGE)}


def filed(
    start: int,
    end: int,
    document_type: str,
    issuer: str,
    section_name: WorkpaperSection,
    *,
    role: Literal["document", "continuation"] = "document",
    account: str | None = None,
    source: str = "a.pdf",
) -> FiledSegment:
    return FiledSegment(
        Segment("body", source, start, end),
        section_name,
        DocumentLabel(document_type, issuer, account, role),
    )


class FakeResponses:
    def __init__(self, batches: list[list[dict]]) -> None:
        self.batches = batches
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.batches.pop(0)
        return SimpleNamespace(
            output_parsed=kwargs["text_format"].model_validate({"segments": payload})
        )


class FakeClient:
    def __init__(self, batches: list[list[dict]]) -> None:
        self.responses = FakeResponses(batches)


def named(
    document_type: str,
    issuer: str,
    role: str = "document",
    account: str | None = None,
    *,
    segment: int = 1,
) -> dict:
    return {
        "segment": segment,
        "document_type": document_type,
        "issuer": issuer,
        "account": account,
        "role": role,
    }


class NameTests(unittest.TestCase):
    def test_title_uses_form_and_issuer(self) -> None:
        self.assertEqual(
            format_title("W-2", "Wenatchee Valley College", None, 1),
            "W-2  Wenatchee Valley College (1 page)",
        )
        self.assertEqual(
            format_title("Dividends", "Robinhood", "662282839", 4),
            "Dividends  Robinhood - 662282839 (4 pages)",
        )

    def test_different_employers_stay_separate(self) -> None:
        merged = merge_related(
            [
                filed(1, 1, "W-2", "Wenatchee Valley College", WAGES),
                filed(2, 2, "W-2", "North Central Regional Library", WAGES),
            ],
            LOOKUP,
        )

        self.assertEqual(
            [segment.title for segment, _section in merged],
            [
                "W-2  Wenatchee Valley College (1 page)",
                "W-2  North Central Regional Library (1 page)",
            ],
        )
        self.assertEqual([section.name for _segment, section in merged], ["Wages", "Wages"])

    def test_brokerage_packet_merges_into_one_composite(self) -> None:
        merged = merge_related(
            [
                filed(1, 4, "Dividends", "Charles Schwab", DIVIDENDS, account="4619-5457"),
                filed(5, 6, "Instructions", "Charles Schwab", DIVIDENDS, role="continuation"),
                filed(7, 8, "Interest", "Schwab", INTEREST, account="4619-5457"),
                filed(9, 11, "1099-B", "Charles Schwab", BROKERAGE, account="4619-5457"),
            ],
            LOOKUP,
        )

        self.assertEqual(len(merged), 1)
        segment, section = merged[0]
        self.assertEqual(segment.start_page, 1)
        self.assertEqual(segment.end_page, 11)
        self.assertEqual(segment.title, "1099 Composite  Charles Schwab - 4619-5457 (11 pages)")
        self.assertEqual(section.name, "Brokerage & Combined Tax Statements")

    def test_cover_sheet_joins_the_form_after_it(self) -> None:
        merged = merge_related(
            [
                filed(1, 1, "Cover", "Robinhood", DIVIDENDS, role="continuation"),
                filed(2, 4, "Dividends", "Robinhood", DIVIDENDS),
            ],
            LOOKUP,
        )

        self.assertEqual(len(merged), 1)
        segment, section = merged[0]
        self.assertEqual(segment.start_page, 1)
        self.assertEqual(segment.end_page, 4)
        self.assertEqual(segment.title, "Dividends  Robinhood (4 pages)")
        self.assertEqual(section.name, "Schedule B - Dividends")

    def test_blank_page_does_not_split_a_packet(self) -> None:
        merged = merge_related(
            [
                filed(1, 4, "1099 Composite", "Schwab", BROKERAGE, account="4619-5457"),
                filed(5, 6, "Document", "Unknown", BROKERAGE),
                filed(7, 11, "1099 Composite", "Charles Schwab", BROKERAGE, account="4619-5457"),
            ],
            LOOKUP,
        )

        self.assertEqual(len(merged), 1)
        segment, section = merged[0]
        self.assertEqual((segment.start_page, segment.end_page), (1, 11))
        self.assertEqual(segment.title, "1099 Composite  Schwab - 4619-5457 (11 pages)")
        self.assertEqual(section.name, "Brokerage & Combined Tax Statements")

    def test_cover_for_another_issuer_stays_separate(self) -> None:
        merged = merge_related(
            [
                filed(1, 2, "Dividends", "Commonwealth", DIVIDENDS),
                filed(3, 3, "Cover", "Robinhood", DIVIDENDS, role="continuation"),
                filed(4, 6, "1099-B", "Commonwealth", BROKERAGE),
            ],
            LOOKUP,
        )

        self.assertEqual(
            [segment.title for segment, _section in merged],
            [
                "Dividends  Commonwealth (2 pages)",
                "Cover  Robinhood (1 page)",
                "1099-B  Commonwealth (3 pages)",
            ],
        )

    def test_different_accounts_of_one_broker_merge(self) -> None:
        merged = merge_related(
            [
                filed(1, 2, "Dividends", "Robinhood", DIVIDENDS, account="111"),
                filed(3, 4, "Dividends", "Robinhood", DIVIDENDS, account="222"),
            ],
            LOOKUP,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0].title, "Dividends  Robinhood (4 pages)")

    def test_gap_and_other_institution_stay_split(self) -> None:
        merged = merge_related(
            [
                filed(1, 1, "Dividends", "American Funds", DIVIDENDS),
                filed(2, 4, "Dividends", "Robinhood", DIVIDENDS),
                filed(6, 6, "Dividends", "Robinhood", DIVIDENDS),
                filed(7, 7, "1098", "JPMorgan Chase", MORTGAGE),
                filed(8, 8, "Interest", "JPMorgan Chase", INTEREST),
            ],
            LOOKUP,
        )

        self.assertEqual(
            [(segment.start_page, segment.end_page, segment.title) for segment, _section in merged],
            [
                (1, 1, "Dividends  American Funds (1 page)"),
                (2, 4, "Dividends  Robinhood (3 pages)"),
                (6, 6, "Dividends  Robinhood (1 page)"),
                (7, 7, "1098  JPMorgan Chase (1 page)"),
                (8, 8, "Interest  JPMorgan Chase (1 page)"),
            ],
        )

    def test_other_source_is_not_merged(self) -> None:
        merged = merge_related(
            [
                filed(1, 1, "W-2", "Awdience, LLC", WAGES, source="2.pdf"),
                filed(1, 1, "W-2", "Awdience, LLC", WAGES, source="3.pdf"),
            ],
            LOOKUP,
        )

        self.assertEqual(len(merged), 2)

    def test_label_segments_names_each_source_in_order(self) -> None:
        client = FakeClient(
            [
                [
                    named("W-2", "Wenatchee Valley College", segment=1),
                    named("W-2", "North Central Regional Library", segment=2),
                ],
                [named("Dividends", "Robinhood", account="662282839", segment=1)],
            ]
        )
        segments = [
            Segment("Form W-2 Wenatchee", "1.pdf", 1, 1),
            Segment("Form W-2 Library", "1.pdf", 2, 2),
            Segment("1099-DIV Robinhood", "3.pdf", 1, 3),
        ]

        labels = label_segments(segments, client=client, model="gpt-4.1")

        self.assertEqual(
            labels,
            [
                DocumentLabel("W-2", "Wenatchee Valley College"),
                DocumentLabel("W-2", "North Central Regional Library"),
                DocumentLabel("Dividends", "Robinhood", "662282839"),
            ],
        )
        self.assertEqual(len(client.responses.calls), 2)
        first = client.responses.calls[0]
        self.assertEqual(first["instructions"], SYSTEM_PROMPT)
        self.assertEqual(first["text_format"], SegmentNames)
        self.assertIn("Form W-2 Wenatchee", first["input"])
        self.assertIn("Segment 2", first["input"])
        self.assertNotIn("Robinhood", first["input"])

    def test_bad_batch_falls_back_per_segment(self) -> None:
        client = FakeClient(
            [
                [],
                [],
                [named("W-2", "Wenatchee Valley College", segment=1)],
                [],
            ]
        )
        segments = [
            Segment("Form W-2", "1.pdf", 1, 1),
            Segment("blank", "1.pdf", 2, 2),
        ]

        labels = label_segments(segments, client=client, model="gpt-4.1")

        self.assertEqual(
            labels,
            [
                DocumentLabel("W-2", "Wenatchee Valley College"),
                DocumentLabel("Document", "Unknown", role="continuation"),
            ],
        )
        self.assertEqual(len(client.responses.calls), 4)
        self.assertIn("previous segment", client.responses.calls[3]["input"])

    def test_extra_name_is_ignored_when_every_segment_is_numbered(self) -> None:
        client = FakeClient(
            [
                [
                    named("W-2", "Wenatchee Valley College", segment=1),
                    named("W-2", "North Central Regional Library", segment=2),
                    named("W-2", "Ignored", segment=2),
                ]
            ]
        )
        segments = [
            Segment("Form W-2 college", "1.pdf", 1, 1),
            Segment("Form W-2 library", "1.pdf", 2, 2),
        ]

        labels = label_segments(segments, client=client, model="gpt-4.1")

        self.assertEqual(labels[1].issuer, "North Central Regional Library")
        self.assertEqual(len(client.responses.calls), 1)


if __name__ == "__main__":
    unittest.main()
