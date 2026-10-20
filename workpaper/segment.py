"""Input contract for a document segment produced by an earlier pipeline step."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """One contiguous document already split out of a source PDF.

    This type does not run OCR or decide page boundaries. Callers fill it.
    """

    text: str
    source: str | None = None
    start_page: int | None = None
    end_page: int | None = None
