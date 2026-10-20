"""One structured LLM call per adjacent page pair, then group the pages."""

import json
from typing import Any

HEAD_CHARS = 4000
TAIL_CHARS = 2000
MAX_CHARS = 6000

SYSTEM_PROMPT = """You decide whether the next page of a scanned tax packet starts a new source document.

A new segment is a different form, payer, institution, or account packet.

Keep the pages in the same segment when any of these is true:
- the next page is a continuation, such as "page X of Y" of the same document
- the next page is instructions that follow a form
- the next page is another copy of the same form (for example W-2 Copy B, Copy 2, and Copy D for the same employee and employer)
- the next page is a blank or near-empty back of the previous form

A repeated header or a layout restart is not, by itself, a new segment.

new_segment is true only when page n+1 starts a different source document."""

BOUNDARY_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "boundary_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "new_segment": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["new_segment", "reason"],
        },
    },
}


def segment_pages(pages: list[str], *, client: Any, model: str) -> dict:
    """Decide each page boundary and return inclusive 1-indexed segments.

    pages[0] is page 1. Page 1 always opens the first segment. Each later
    boundary is one chat completion over the OCR of page n and page n+1.
    """
    boundaries = []
    for index in range(len(pages) - 1):
        page_n = index + 1
        page_n1 = index + 2
        decision = decide_boundary(
            client,
            model,
            clip_page(pages[index]),
            clip_page(pages[index + 1]),
            page_n,
            page_n1,
        )
        boundaries.append(
            {
                "after_page": page_n,
                "new_segment": decision["new_segment"],
                "reason": decision["reason"],
            }
        )
        print(
            f"  after page {page_n}: new_segment={decision['new_segment']} ({decision['reason']})",
            flush=True,
        )

    return {
        "boundaries": boundaries,
        "segments": group_segments(len(pages), boundaries),
    }


def decide_boundary(
    client: Any,
    model: str,
    page_n_text: str,
    page_n1_text: str,
    page_n: int,
    page_n1: int,
) -> dict:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Page {page_n} OCR:\n\n{_show(page_n_text)}\n\n"
                    f"---\n\n"
                    f"Page {page_n1} OCR:\n\n{_show(page_n1_text)}\n\n"
                    f"Does page {page_n1} start a new source document?"
                ),
            },
        ],
        response_format=BOUNDARY_FORMAT,
    )
    payload = json.loads(response.choices[0].message.content)
    if not isinstance(payload.get("new_segment"), bool) or not isinstance(payload.get("reason"), str):
        raise ValueError(f"Boundary response for pages {page_n}->{page_n1} was not the expected object")
    return payload


def clip_page(text: str) -> str:
    """Keep the start and end of a long page so titles and footers both survive."""
    if len(text) <= MAX_CHARS:
        return text
    return text[:HEAD_CHARS] + "\n\n[...middle omitted...]\n\n" + text[-TAIL_CHARS:]


def group_segments(page_count: int, boundaries: list[dict]) -> list[dict]:
    """Turn left-to-right new_segment flags into inclusive page ranges."""
    if page_count < 1:
        return []
    segments = []
    start = 1
    for index, decision in enumerate(boundaries):
        end_page = index + 1
        if decision["new_segment"]:
            segments.append({"start_page": start, "end_page": end_page})
            start = end_page + 1
    segments.append({"start_page": start, "end_page": page_count})
    return segments


def _show(text: str) -> str:
    stripped = text.strip()
    return stripped if stripped else "(no text recognized)"
