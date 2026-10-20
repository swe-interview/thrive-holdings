"""Concatenate source PDFs in scan order and write the workpaper bookmark outline.

Level-1 bookmarks are the sections from schema.py, in table-of-contents order.
Level-2 bookmarks are classified segments. Empty sections stay in the outline
and point at page 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import pymupdf

from schema import SECTIONS, WorkpaperSection
from workpaper.segment import Segment


def assemble(
    sources: Sequence[str | Path],
    filed: Sequence[tuple[Segment, WorkpaperSection]],
    dest: str | Path,
) -> None:
    """Write a bookmarked PDF. `filed` pairs each segment with its section."""
    paths = [Path(source) for source in sources]
    names = [path.name for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("Source PDF file names must be unique.")

    section_order = list(SECTIONS)
    grouped: dict[str, list[Segment]] = {name: [] for name in section_order}
    for segment, section in filed:
        if section.name not in grouped:
            raise ValueError(f"Unknown workpaper section: {section.name}")
        grouped[section.name].append(segment)

    output = pymupdf.open()
    try:
        offsets, counts = _append_sources(output, paths)
        order = {name: index for index, name in enumerate(names)}
        toc: list[list] = []
        for name in section_order:
            documents = sorted(grouped[name], key=lambda segment: _sort_key(segment, order))
            if not documents:
                toc.append([1, name, 1])
                continue
            toc.append([1, name, _destination(documents[0], offsets, counts)])
            for segment in documents:
                toc.append([2, bookmark_title(segment), _destination(segment, offsets, counts)])
        output.set_toc(toc)
        output.save(dest)
    finally:
        output.close()


def bookmark_title(segment: Segment) -> str:
    """Level-2 label. Preprocess and classify do not emit a document title."""
    source = Path(segment.source or "").name
    start = segment.start_page
    end = segment.end_page if segment.end_page is not None else start
    return f"{source} pp. {start}-{end}"


def segments_from_preprocess(pdf_path: str | Path, segments_dir: str | Path) -> list[Segment]:
    """Load one PDF's page ranges and join its cached OCR pages."""
    pdf_path = Path(pdf_path)
    stem = Path(segments_dir) / pdf_path.stem
    payload_path = stem / "segments.json"
    if not payload_path.is_file():
        raise FileNotFoundError(
            f"Missing {payload_path}. Run python -m preprocess on {pdf_path.name} first."
        )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    segments: list[Segment] = []
    for item in payload["segments"]:
        start = int(item["start_page"])
        end = int(item["end_page"])
        pages = [_read_page(stem / "pages", page) for page in range(start, end + 1)]
        segments.append(
            Segment(
                text="\n".join(pages),
                source=pdf_path.name,
                start_page=start,
                end_page=end,
            )
        )
    return segments


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Classify preprocessed segments and write a bookmarked workpaper PDF."
    )
    parser.add_argument("pdfs", nargs="+", type=Path, help="Source PDFs in scan order")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out"),
        help="Directory written by python -m preprocess",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("assembled_workpaper.pdf"),
        help="Output PDF",
    )
    args = parser.parse_args(argv)

    from workpaper.classify import classify_segments

    segments: list[Segment] = []
    for pdf_path in args.pdfs:
        if not pdf_path.is_file():
            raise SystemExit(f"PDF not found: {pdf_path}")
        try:
            segments.extend(segments_from_preprocess(pdf_path, args.out))
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc

    classifications = classify_segments(segments)
    filed = [
        (segment, classification.section)
        for segment, classification in zip(segments, classifications, strict=True)
    ]
    assemble(args.pdfs, filed, args.dest)
    print(f"wrote {args.dest}", flush=True)


def _append_sources(output: pymupdf.Document, paths: Sequence[Path]) -> tuple[dict[str, int], dict[str, int]]:
    offsets: dict[str, int] = {}
    counts: dict[str, int] = {}
    running = 0
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")
        with pymupdf.open(path) as source:
            offsets[path.name] = running
            counts[path.name] = source.page_count
            output.insert_pdf(source)
            running += source.page_count
    return offsets, counts


def _sort_key(segment: Segment, order: dict[str, int]) -> tuple[int, int]:
    name = _source_name(segment)
    if name not in order:
        raise ValueError(f"Segment source is not one of the assembled PDFs: {segment.source}")
    if segment.start_page is None:
        raise ValueError(f"Segment from {name} is missing start_page.")
    return (order[name], segment.start_page)


def _destination(segment: Segment, offsets: dict[str, int], counts: dict[str, int]) -> int:
    name = _source_name(segment)
    if name not in offsets:
        raise ValueError(f"Segment source is not one of the assembled PDFs: {segment.source}")
    if segment.start_page is None:
        raise ValueError(f"Segment from {name} is missing start_page.")
    page_count = counts[name]
    end = segment.end_page if segment.end_page is not None else segment.start_page
    if segment.start_page < 1 or end < segment.start_page or end > page_count:
        raise ValueError(
            f"Segment {name} pp. {segment.start_page}-{end} is outside the PDF ({page_count} pages)."
        )
    return offsets[name] + segment.start_page


def _source_name(segment: Segment) -> str:
    if not segment.source:
        raise ValueError("Segment is missing source.")
    return Path(segment.source).name


def _read_page(pages_dir: Path, page_number: int) -> str:
    path = pages_dir / f"{page_number:03d}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Missing OCR page: {path}")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
