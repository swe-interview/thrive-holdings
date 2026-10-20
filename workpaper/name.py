"""Name each segment and merge pieces of the same source document.

Bookmarks read like "W-2  Wenatchee Valley College (1 page)" or
"Dividends  Robinhood (4 pages)". Contiguous pieces of one packet — a W-2
split from its copies, or a brokerage statement split into dividends,
interest, and broker transactions — become one bookmark.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel

from schema import Section, WorkpaperSection
from workpaper.classify import _client, _model
from workpaper.segment import Segment

_BROKERAGE = Section.BROKERAGE_COMBINED_TAX_STATEMENTS.value
_CONTINUATION_TYPES = {
    "blank",
    "continuation",
    "cover",
    "coverletter",
    "instruction",
    "instructions",
    "unidentified",
    "unknown",
}

SYSTEM_PROMPT = """You name segments of a scanned tax packet for workpaper bookmarks.

For each segment return:
- segment: the segment number from the prompt.
- document_type: a short form name. Use "W-2" for wage statements, "Dividends" for Form 1099-DIV, "Interest" for Form 1099-INT, "1099-B" for broker proceeds, "1099-MISC" for miscellaneous information, "1098" for mortgage interest, "1095-A", "1095-B", or "1095-C" for health coverage, and "1099 Composite" when the segment is itself a consolidated brokerage statement. Use "Cover" for a cover sheet.
- issuer: the employer, payer, broker, or fund that issued the form, not the taxpayer and not a column heading. Use one short name a preparer would recognize, such as "Wenatchee Valley College" or "Robinhood". Spell that name the same way on every segment from the same institution.
- account: the account number if one is printed, otherwise null.
- role: "continuation" when the segment is only instructions, a blank or illegible page, or a cover sheet with no form of its own. Otherwise "document".

Return one entry for every segment number, and no extras."""


class SegmentName(BaseModel):
    """Model output for one segment."""

    segment: int
    document_type: str
    issuer: str
    account: str | None
    role: Literal["document", "continuation"]


class SegmentNames(BaseModel):
    """One name per input segment, in order."""

    segments: list[SegmentName]


@dataclass(frozen=True)
class DocumentLabel:
    """Form, issuer, and account used to title and merge a segment."""

    document_type: str
    issuer: str
    account: str | None = None
    role: Literal["document", "continuation"] = "document"


@dataclass(frozen=True)
class FiledSegment:
    """A classified segment plus the name used to merge it."""

    segment: Segment
    section: WorkpaperSection
    label: DocumentLabel


def label_segments(
    segments: Sequence[Segment],
    *,
    client=None,
    model: str | None = None,
) -> list[DocumentLabel]:
    """Name every segment. One model call per source PDF, then a per-segment fallback."""
    openai_client = _client(client)
    chosen = model or _model()
    labels: list[DocumentLabel | None] = [None] * len(segments)
    for indexes in _source_groups(segments):
        batch = [segments[index] for index in indexes]
        try:
            named = _label_batch(batch, openai_client, chosen)
        except ValueError as first_error:
            try:
                named = _label_batch(batch, openai_client, chosen)
            except ValueError as exc:
                print(f"  naming fallback ({first_error}; {exc})", flush=True)
                named = _label_in_order(batch, openai_client, chosen)
        for index, label in zip(indexes, named, strict=True):
            labels[index] = label
            segment = segments[index]
            print(
                f"  {segment.source} pp. {segment.start_page}-{segment.end_page}: "
                f"{label.role} {label.document_type}  {label.issuer}",
                flush=True,
            )
    return [label for label in labels if label is not None]


def merge_related(
    filed: Sequence[FiledSegment],
    sections: Mapping[str, WorkpaperSection],
) -> list[tuple[Segment, WorkpaperSection]]:
    """Collapse contiguous pieces of the same form packet into one titled segment.

    A piece joins the previous one when the pages touch and it is a continuation
    (instructions, blank, cover) or the same issuer and the same kind of form.
    Dividends, interest, and 1099-B pages from one broker become one composite.
    A different employer or institution stays its own bookmark.
    """
    merged: list[tuple[Segment, WorkpaperSection]] = []
    for indexes in _source_groups([item.segment for item in filed]):
        ordered = sorted(
            (filed[index] for index in indexes),
            key=lambda item: item.segment.start_page or 0,
        )
        merged.extend(_merge_source(_absorb_leading_continuations(_group_contiguous(ordered)), sections))
    return merged


def format_title(
    document_type: str,
    issuer: str,
    account: str | None,
    page_count: int,
) -> str:
    """Level-2 bookmark title. Two spaces separate the form from the issuer."""
    kind = " ".join(document_type.split()) or "Document"
    who = " ".join(issuer.split()) or "Unknown"
    if account and account.strip():
        who = f"{who} - {account.strip()}"
    unit = "page" if page_count == 1 else "pages"
    return f"{kind}  {who} ({page_count} {unit})"


def _label_in_order(segments: Sequence[Segment], client, model: str) -> list[DocumentLabel]:
    """Name segments one at a time, carrying the previous issuer forward."""
    named: list[DocumentLabel] = []
    for segment in segments:
        previous = named[-1] if named else None
        try:
            named.append(_label_batch([segment], client, model, previous=previous)[0])
        except ValueError:
            named.append(DocumentLabel("Document", "Unknown", role="continuation"))
    return named


def _label_batch(
    segments: Sequence[Segment],
    client,
    model: str,
    *,
    previous: DocumentLabel | None = None,
) -> list[DocumentLabel]:
    response = client.responses.parse(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=_user_message(segments, previous),
        text_format=SegmentNames,
    )
    parsed = response.output_parsed
    if parsed is None or not parsed.segments:
        raise ValueError("Model response did not include segment names.")
    by_number: dict[int, SegmentName] = {}
    for item in parsed.segments:
        by_number.setdefault(item.segment, item)
    expected = range(1, len(segments) + 1)
    missing = [number for number in expected if number not in by_number]
    if missing:
        raise ValueError(f"Expected names for segments {list(expected)}, missing {missing}.")
    return [_document_label(by_number[number]) for number in expected]


def _user_message(segments: Sequence[Segment], previous: DocumentLabel | None = None) -> str:
    blocks = [f"Segments: {len(segments)}"]
    if previous and _issuer_key(previous.issuer) not in {"", "unknown"}:
        blocks.append(
            f"The previous segment in this PDF was {previous.document_type} from {previous.issuer}. "
            "If this segment continues that same packet, reuse that issuer."
        )
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Segment {index}",
                    f"Source: {segment.source or ''}",
                    f"Pages: {segment.start_page}-{segment.end_page}",
                    "Text:",
                    _excerpt(segment.text),
                ]
            )
        )
    return "\n\n".join(blocks)


def _excerpt(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 2000:
        return stripped
    return stripped[:1400] + "\n\n[...]\n\n" + stripped[-500:]


def _document_label(parsed: SegmentName) -> DocumentLabel:
    account = (parsed.account or "").strip() or None
    return DocumentLabel(
        document_type=parsed.document_type.strip() or "Document",
        issuer=parsed.issuer.strip(),
        account=account,
        role=parsed.role,
    )


def _source_groups(segments: Sequence[Segment]) -> list[list[int]]:
    groups: list[list[int]] = []
    index_of: dict[str, int] = {}
    for index, segment in enumerate(segments):
        source = segment.source or ""
        if source not in index_of:
            index_of[source] = len(groups)
            groups.append([])
        groups[index_of[source]].append(index)
    return groups


def _group_contiguous(ordered: Sequence[FiledSegment]) -> list[list[FiledSegment]]:
    groups: list[list[FiledSegment]] = []
    current: list[FiledSegment] = []
    for item in ordered:
        if not current or _related(current, item):
            current.append(item)
            continue
        groups.append(current)
        current = [item]
    if current:
        groups.append(current)
    return groups


def _absorb_leading_continuations(groups: list[list[FiledSegment]]) -> list[list[FiledSegment]]:
    merged: list[list[FiledSegment]] = []
    pending: list[FiledSegment] = []
    for group in groups:
        if _only_continuations(group):
            if pending and not _contiguous(pending[-1].segment, group[0].segment):
                merged.append(pending)
                pending = []
            pending.extend(group)
            continue
        if pending and _contiguous(pending[-1].segment, group[0].segment) and _continuations_match(pending, group):
            group = pending + group
        elif pending:
            merged.append(pending)
        pending = []
        merged.append(group)
    if pending:
        merged.append(pending)
    return merged


def _merge_source(
    groups: Sequence[Sequence[FiledSegment]],
    sections: Mapping[str, WorkpaperSection],
) -> list[tuple[Segment, WorkpaperSection]]:
    return [_merged_segment(list(group), sections) for group in groups]


def _merged_segment(
    group: Sequence[FiledSegment],
    sections: Mapping[str, WorkpaperSection],
) -> tuple[Segment, WorkpaperSection]:
    first = group[0].segment
    last = group[-1].segment
    start = first.start_page
    end = last.end_page if last.end_page is not None else last.start_page
    title = format_title(
        _choose_type(group),
        _choose_issuer(group),
        _choose_account(group),
        _page_count(start, end),
    )
    text = "\n".join(item.segment.text for item in group)
    segment = Segment(
        text=text,
        source=first.source,
        start_page=start,
        end_page=end,
        title=title,
    )
    return segment, _choose_section(group, sections)


def _related(group: Sequence[FiledSegment], item: FiledSegment) -> bool:
    if not _contiguous(group[-1].segment, item.segment):
        return False
    anchor = _anchor(group)
    if _is_continuation(item.label):
        if anchor is None:
            return False
        if not _has_issuer(item.label.issuer):
            return True
        return _same_issuer(anchor.label.issuer, item.label.issuer)
    if anchor is None:
        return False
    return _same_party(anchor.label, item.label)


def _same_party(left: DocumentLabel, right: DocumentLabel) -> bool:
    return _same_issuer(left.issuer, right.issuer) and _family(left.document_type) == _family(
        right.document_type
    )


def _contiguous(left: Segment, right: Segment) -> bool:
    if (left.source or "") != (right.source or ""):
        return False
    left_end = _end_page(left)
    if left_end is None or right.start_page is None:
        return False
    return right.start_page == left_end + 1


def _end_page(segment: Segment) -> int | None:
    if segment.start_page is None:
        return None
    return segment.end_page if segment.end_page is not None else segment.start_page


def _page_count(start: int | None, end: int | None) -> int:
    if start is None:
        return 1
    last = end if end is not None else start
    return max(1, last - start + 1)


def _anchor(group: Sequence[FiledSegment]) -> FiledSegment | None:
    for item in group:
        if not _is_continuation(item.label) and _issuer_key(item.label.issuer):
            return item
    return None


def _continuations_match(pending: Sequence[FiledSegment], group: Sequence[FiledSegment]) -> bool:
    """A labeled cover joins the next form only when it names that form's issuer."""
    anchor = _anchor(group)
    labeled = [item for item in pending if _has_issuer(item.label.issuer)]
    if anchor is None or not labeled:
        return True
    return all(_same_issuer(item.label.issuer, anchor.label.issuer) for item in labeled)


def _only_continuations(group: Sequence[FiledSegment]) -> bool:
    return all(_is_continuation(item.label) for item in group)


def _is_continuation(label: DocumentLabel) -> bool:
    if label.role == "continuation":
        return True
    compact = re.sub(r"[^a-z0-9]+", "", label.document_type.casefold())
    if compact in _CONTINUATION_TYPES:
        return True
    issuer = _issuer_key(label.issuer)
    return compact in {"document", "form", ""} and issuer in {"", "unknown"}


def _same_issuer(left: str, right: str) -> bool:
    left_key = _issuer_key(left)
    right_key = _issuer_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    short, long = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
    return len(short) >= 6 and short in long


def _issuer_key(issuer: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", issuer.casefold())


def _has_issuer(issuer: str) -> bool:
    return _issuer_key(issuer) not in {"", "unknown", "unidentified"}


def _account_key(account: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", account.casefold())


def _family(document_type: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", document_type.casefold())
    if "w2" in compact:
        return "wage"
    if "1098" in compact:
        return "mortgage"
    if "1095" in compact:
        return "health"
    if any(word in compact for word in ("1099", "dividend", "composite", "brokerage", "yearend", "consolidated")):
        return "brokerage"
    if compact in {"interest", "int"}:
        return "brokerage"
    return compact or "other"


def _real_items(group: Sequence[FiledSegment]) -> Sequence[FiledSegment]:
    documents = [item for item in group if not _is_continuation(item.label)]
    return documents or group


def _choose_type(group: Sequence[FiledSegment]) -> str:
    types = [item.label.document_type.strip() for item in _real_items(group) if item.label.document_type.strip()]
    if not types:
        return "Document"
    distinct = list(dict.fromkeys(types))
    if len(distinct) == 1:
        compact = re.sub(r"[^a-z0-9]+", "", distinct[0].casefold())
        if compact in {"continuation", "document", "unknown", "unidentified", "blank"}:
            return "Cover" if _has_issuer(_choose_issuer(group)) else "Unidentified"
        return distinct[0]
    if all(_family(document_type) == "brokerage" for document_type in distinct):
        return "1099 Composite"
    return distinct[0]


def _choose_issuer(group: Sequence[FiledSegment]) -> str:
    for item in _real_items(group):
        issuer = " ".join(item.label.issuer.split())
        if issuer:
            return issuer
    return "Unknown"


def _choose_account(group: Sequence[FiledSegment]) -> str | None:
    found: list[str] = []
    seen: set[str] = set()
    for item in _real_items(group):
        if not item.label.account:
            continue
        account = item.label.account.strip()
        key = _account_key(account)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(account)
    if len(found) == 1:
        return found[0]
    return None


def _choose_section(
    group: Sequence[FiledSegment],
    sections: Mapping[str, WorkpaperSection],
) -> WorkpaperSection:
    voting = list(_real_items(group))
    names = [item.section.name for item in voting]
    if len(set(names)) == 1 and not _is_composite(voting):
        return voting[0].section
    if _is_composite(voting) and _BROKERAGE in sections:
        return sections[_BROKERAGE]
    winner = _majority(names)
    return sections.get(winner, voting[0].section)


def _is_composite(group: Sequence[FiledSegment]) -> bool:
    types = [item.label.document_type for item in group if not _is_continuation(item.label)]
    distinct = {item.strip() for item in types if item.strip()}
    return len(distinct) > 1 and all(_family(document_type) == "brokerage" for document_type in distinct)


def _majority(names: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    first: str | None = None
    best = ""
    best_count = -1
    for name in names:
        if first is None:
            first = name
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > best_count:
            best = name
            best_count = counts[name]
    return best or (first or "")
