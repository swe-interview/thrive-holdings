"""Classification uses schema.py sections and one model call per segment."""

import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from schema import Section, WorkpaperSection, load_workpaper
from workpaper.classify import (
    TEXT_CHAR_LIMIT,
    SegmentLabel,
    classify_segment,
    classify_segments,
    system_prompt,
)
from workpaper.segment import Segment

WORKPAPER = load_workpaper(Path(__file__).resolve().parents[1] / "workpaper.pdf")


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["input"]
        section = (
            "Wages"
            if "Form W-2" in text
            else "Brokerage & Combined Tax Statements"
        )
        return SimpleNamespace(
            output_parsed=kwargs["text_format"].model_validate(
                {
                    "section": section,
                    "confidence": "high",
                    "reason": "Matched the form named in the segment.",
                }
            )
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


class ClassifyTests(unittest.TestCase):
    def test_w2_segment_returns_wages(self) -> None:
        client = FakeClient()
        segment = Segment(
            text="Form W-2 Wage and Tax Statement 2024\nAwdience, LLC",
            source="2.pdf",
            start_page=1,
            end_page=2,
        )

        result = classify_segment(segment, client=client, workpaper=WORKPAPER)

        self.assertIsInstance(result.section, WorkpaperSection)
        self.assertEqual(result.section.name, "Wages")
        self.assertEqual(result.confidence, "high")
        call = client.responses.calls[0]
        self.assertIn("Form W-2 Wage and Tax Statement 2024", call["input"])
        self.assertIn("Source: 2.pdf", call["input"])
        self.assertIn("Brokerage & Combined Tax Statements", call["instructions"])
        self.assertIn("Do not split those into Schedule B or Schedule D.", call["instructions"])
        self.assertEqual(call["instructions"], system_prompt())
        allowed = [member.value for member in call["text_format"].model_fields["section"].annotation]
        self.assertEqual(allowed, [section.value for section in Section])
        self.assertEqual(allowed, [section.name for section in WORKPAPER.sections])

    def test_each_segment_is_its_own_call(self) -> None:
        client = FakeClient()
        segments = [
            Segment(text="Form W-2 Wage and Tax Statement"),
            Segment(text="Charles Schwab FORM 1099 COMPOSITE"),
        ]

        results = classify_segments(segments, client=client, workpaper=WORKPAPER)

        self.assertEqual(
            [result.section.name for result in results],
            ["Wages", "Brokerage & Combined Tax Statements"],
        )
        self.assertEqual(len(client.responses.calls), 2)

    def test_user_message_keeps_front_matter_only(self) -> None:
        client = FakeClient()
        segment = Segment(text="Form W-2 " + ("x" * TEXT_CHAR_LIMIT) + "TAIL_MARKER")

        classify_segment(segment, client=client, workpaper=WORKPAPER)

        body = client.responses.calls[0]["input"].split("Segment text:\n", 1)[1]
        self.assertLessEqual(len(body), TEXT_CHAR_LIMIT)
        self.assertNotIn("TAIL_MARKER", body)

    def test_unknown_section_cannot_be_parsed(self) -> None:
        with self.assertRaises(ValidationError):
            SegmentLabel.model_validate(
                {
                    "section": "Not a workpaper section",
                    "confidence": "high",
                    "reason": "no",
                }
            )


if __name__ == "__main__":
    unittest.main()
