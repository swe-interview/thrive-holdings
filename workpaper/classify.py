"""Classify one document segment into a section from schema.py."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from openai import OpenAI
from pydantic import BaseModel

from schema import SECTIONS, Section, Workpaper, WorkpaperSection, load_workpaper
from workpaper.segment import Segment

TEXT_CHAR_LIMIT = 12_000
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_WORKPAPER = Path(__file__).resolve().parents[1] / "workpaper.pdf"

_RULES = """
Rules:
- W-2 and W-2G wage statements go to Wages.
- A standalone bank or credit-union Form 1099-INT goes to Schedule B - Interest.
- A standalone Form 1099-DIV goes to Schedule B - Dividends.
- A consolidated brokerage package (1099 Composite, combined 1099, or year-end summary from a broker such as Charles Schwab, Robinhood, or National Financial Services / Fidelity) goes to Brokerage & Combined Tax Statements even when it also contains Form 1099-DIV, 1099-INT, or 1099-B. Do not split those into Schedule B or Schedule D.
- Form 1098 mortgage interest goes to Schedule A - Interest.
- Form 1095-A, 1095-B, and 1095-C go to Other Credits.
- If the segment does not clearly match a section, choose Unclassified Documents.
""".strip()

_cached_workpaper: Workpaper | None = None


@dataclass(frozen=True)
class Classification:
    """One section assignment. `section` is the schema.py workpaper section."""

    section: WorkpaperSection
    confidence: Literal["high", "medium", "low"]
    reason: str


def section_names() -> list[str]:
    """Closed section names from schema.Section, in table-of-contents order."""
    return list(SECTIONS)


def system_prompt() -> str:
    sections = "\n".join(f"- {name}" for name in section_names())
    return (
        "You file a client document segment into one section of a tax workpaper.\n"
        "Choose exactly one section from this closed list:\n"
        f"{sections}\n\n"
        f"{_RULES}\n\n"
        "Return the section name exactly as listed, a confidence of high, medium, "
        "or low, and one sentence explaining the choice."
    )


def user_message(segment: Segment) -> str:
    lines: list[str] = []
    if segment.source:
        lines.append(f"Source: {segment.source}")
    if segment.start_page is not None or segment.end_page is not None:
        lines.append(f"Pages: {segment.start_page}-{segment.end_page}")
    lines.append("Segment text:")
    lines.append(segment.text[:TEXT_CHAR_LIMIT])
    return "\n".join(lines)


class SegmentLabel(BaseModel):
    """Model output. `section` is one schema.Section value and nothing else."""

    section: Section
    confidence: Literal["high", "medium", "low"]
    reason: str


def classify_segment(
    segment: Segment,
    *,
    client: OpenAI | None = None,
    model: str | None = None,
    workpaper: Workpaper | None = None,
) -> Classification:
    """Send one segment to the model and return its workpaper section."""
    packet = workpaper if workpaper is not None else default_workpaper()
    response = _client(client).responses.parse(
        model=model or _model(),
        instructions=system_prompt(),
        input=user_message(segment),
        text_format=SegmentLabel,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("Model response did not include a workpaper section.")
    return _classification(packet, parsed)


def classify_segments(
    segments: Sequence[Segment],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
    workpaper: Workpaper | None = None,
) -> list[Classification]:
    """Classify each segment with its own model call."""
    packet = workpaper if workpaper is not None else default_workpaper()
    openai_client = _client(client)
    results = []
    for index, segment in enumerate(segments, start=1):
        print(
            f"  classify {index}/{len(segments)} {segment.source} pp. {segment.start_page}-{segment.end_page}",
            flush=True,
        )
        results.append(
            classify_segment(segment, client=openai_client, model=model, workpaper=packet)
        )
    return results


def default_workpaper() -> Workpaper:
    global _cached_workpaper
    if _cached_workpaper is None:
        _cached_workpaper = load_workpaper(DEFAULT_WORKPAPER)
    return _cached_workpaper


def _classification(workpaper: Workpaper, parsed: SegmentLabel) -> Classification:
    name = parsed.section.value
    by_name = {section.name: section for section in workpaper.sections}
    try:
        section = by_name[name]
    except KeyError as exc:
        raise RuntimeError(f"Model returned a section that is not in the workpaper: {name}") from exc
    return Classification(
        section=section,
        confidence=parsed.confidence,
        reason=parsed.reason,
    )


def _client(client: OpenAI | None) -> OpenAI:
    if client is not None:
        return client
    _load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env or the environment."
        )
    return OpenAI()


def _model() -> str:
    _load_dotenv()
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the repo .env without overriding the environment."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
