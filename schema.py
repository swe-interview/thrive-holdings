"""Schemas for a CCH ProSystem fx Scan workpaper and its bookmark outline.

Level-1 sections are the closed buckets in `Section`, in the table-of-contents
order of workpaper.pdf. Classification may use those names and no others.
Level-2 bookmarks are the source documents filed in a section. Empty sections
are still present; Scan points those bookmarks at page 1, which is not a page
range for that section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# "W-2  Awdience, LLC (2 pages)" — form, then two or more spaces, then the rest.
_TITLE = re.compile(
    r"^(?P<document_type>.+?)\s{2,}(?P<body>.+?)(?:\s+\((?P<pages>\d+)\s+pages?\))?$"
)
# "Robinhood Markets Inc as agent - 662282839"
_ACCOUNT = re.compile(r"^(?P<issuer>.+?)\s+-\s+(?P<account>.+)$")
# "SCAN; 24I:P156:V1; 24; Payne, Aaron; P156; ; Default; 1099B Checked"
_KEYWORDS = re.compile(
    r"^SCAN;\s*(?P<scan_id>[^;]*);\s*(?P<year>\d{2,4});\s*(?P<client>[^;]*);\s*(?P<client_id>[^;]*);"
)


class Section(StrEnum):
    """Level-1 buckets from the workpaper.pdf table of contents, in outline order."""

    COVER_SHEET = "Cover Sheet"
    NOTES_FROM_CLIENT = "Notes from Client"
    ORGANIZER_1040 = "Organizer - 1040"
    WAGES = "Wages"
    SCHEDULE_B_INTEREST = "Schedule B - Interest"
    SCHEDULE_B_DIVIDENDS = "Schedule B - Dividends"
    BROKERAGE_COMBINED_TAX_STATEMENTS = "Brokerage & Combined Tax Statements"
    STATE_AND_LOCAL_TAX_REFUNDS = "State and Local Tax Refunds"
    SCHEDULE_C_BUSINESS = "Schedule C - Business"
    SCHEDULE_D_CAPITAL_GAINS = "Schedule D - Capital Gains"
    FORM_4797_SALES_OF_ASSETS = "Form 4797 - Sales of Assets"
    PENSIONS_ANNUITIES_IRAS = "Pensions, Annuities, IRA's"
    SCHEDULE_E_RENTALS = "Schedule E - Rentals"
    SCHEDULE_E_K1S = "Schedule E - K-1s"
    SCHEDULE_F_FARM_INCOME = "Schedule F - Farm Income"
    UNEMPLOYMENT_COMPENSATION = "Unemployment Compensation"
    SOCIAL_SECURITY_BENEFITS = "Social Security Benefits"
    OTHER_INCOME = "Other Income"
    OTHER_DEDUCTIONS_FROM_TOTAL_INCOME = "Other Deductions from Total Income"
    SCHEDULE_A_ITEMIZED_DEDUCTIONS_COMBINED = "Schedule A - Itemized Deductions Combined"
    SCHEDULE_A_MEDICAL_EXPENSES = "Schedule A - Medical Expenses"
    SCHEDULE_A_TAXES = "Schedule A - Taxes"
    SCHEDULE_A_INTEREST = "Schedule A - Interest"
    SCHEDULE_A_CONTRIBUTIONS = "Schedule A - Contributions"
    SCHEDULE_A_MISCELLANEOUS_DEDUCTIONS = "Schedule A - Miscellaneous Deductions"
    OTHER_CREDITS = "Other Credits"
    OTHER_TAXES = "Other Taxes"
    TAX_PAYMENTS = "Tax Payments"
    EFILE_INFORMATION = "E-File Information"
    EXTENSIONS = "Extensions"
    STATE_AND_LOCAL_INFORMATION = "State & Local Information"
    FOREIGN_INFORMATION = "Foreign Information"
    GIFTS_MADE = "Gifts Made"
    MISCELLANEOUS_IRS_FORMS = "Miscellaneous IRS Forms"
    PAYROLL_FORMS = "Payroll Forms"
    MISCELLANEOUS_DOCUMENTS = "Miscellaneous Documents"
    CUSTOM_DOCUMENTS = "Custom Documents"
    UNUSED_DOCUMENTS = "Unused Documents"
    UNCLASSIFIED_DOCUMENTS = "Unclassified Documents"


SECTIONS: tuple[str, ...] = tuple(section.value for section in Section)
_SECTION_NAMES = frozenset(SECTIONS)


@dataclass
class TocEntry:
    """One bookmark in the workpaper outline."""

    level: int
    title: str
    page: int
    children: list[TocEntry] = field(default_factory=list)

    def leaves(self) -> list[TocEntry]:
        """Document bookmarks under this entry. A childless entry is itself a leaf."""
        if not self.children:
            return [self]
        found: list[TocEntry] = []
        for child in self.children:
            found.extend(child.leaves())
        return found


@dataclass
class TableOfContents:
    """Bookmark tree as stored in the PDF. `entries` are the top-level sections."""

    entries: list[TocEntry]

    def sections(self) -> list[TocEntry]:
        return list(self.entries)

    def documents(self) -> list[TocEntry]:
        found: list[TocEntry] = []
        for section in self.entries:
            for child in section.children:
                found.extend(child.leaves())
        return found


@dataclass
class SourceDocument:
    """A client document filed under one workpaper section."""

    title: str
    document_type: str | None
    issuer: str | None
    account: str | None
    is_instructions: bool
    page_start: int
    page_end: int
    labeled_page_count: int | None = None

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1


@dataclass
class WorkpaperSection:
    """A level-1 bookmark. Empty sections are classification slots with no pages."""

    name: str
    bookmark_page: int
    documents: list[SourceDocument] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.name not in _SECTION_NAMES:
            raise ValueError(f"Unknown workpaper section: {self.name}")

    @property
    def is_empty(self) -> bool:
        return not self.documents

    @property
    def page_start(self) -> int | None:
        if not self.documents:
            return None
        return self.documents[0].page_start

    @property
    def page_end(self) -> int | None:
        if not self.documents:
            return None
        return self.documents[-1].page_end


@dataclass
class Workpaper:
    """Curated client packet: scan metadata plus the section outline and its documents."""

    page_count: int
    tax_year: int | None
    client_name: str | None
    client_id: str | None
    scan_id: str | None
    sections: list[WorkpaperSection]
    toc: TableOfContents

    def filed_sections(self) -> list[WorkpaperSection]:
        return [section for section in self.sections if not section.is_empty]


def parse_document_title(title: str) -> tuple[str | None, str | None, str | None, int | None, bool]:
    """Split a level-2 bookmark title into type, issuer, account, and labeled page count.

    Returns (document_type, issuer, account, labeled_page_count, is_instructions).
    Titles that are not "{type}  {issuer}" stay unparsed.
    """
    match = _TITLE.match(title.strip())
    if not match:
        return None, None, None, None, False

    document_type = match.group("document_type").strip()
    body = match.group("body").strip()
    labeled = int(match.group("pages")) if match.group("pages") else None

    account_match = _ACCOUNT.match(body)
    if account_match:
        issuer = account_match.group("issuer").strip()
        account = account_match.group("account").strip()
    else:
        issuer = body
        account = None

    is_instructions = issuer.casefold() == "instructions"
    return document_type, issuer, account, labeled, is_instructions


def _tax_year(year_token: str) -> int:
    year = int(year_token)
    if year < 100:
        return 2000 + year
    return year


def _scan_fields(keywords: str | None) -> tuple[int | None, str | None, str | None, str | None]:
    if not keywords:
        return None, None, None, None
    match = _KEYWORDS.match(keywords.strip())
    if not match:
        return None, None, None, None
    client = match.group("client").strip() or None
    client_id = match.group("client_id").strip() or None
    scan_id = match.group("scan_id").strip() or None
    return _tax_year(match.group("year")), client, client_id, scan_id


def table_of_contents_from_outline(outline: list[list]) -> TableOfContents:
    """Build a tree from PyMuPDF's flat `[level, title, page]` outline."""
    roots: list[TocEntry] = []
    stack: list[TocEntry] = []
    for item in outline:
        level, title, page = int(item[0]), str(item[1]), int(item[2])
        node = TocEntry(level=level, title=title, page=page)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return TableOfContents(entries=roots)


def _assign_page_spans(documents: list[SourceDocument], page_count: int) -> None:
    """Each document runs from its bookmark page through the page before the next one."""
    for index, document in enumerate(documents):
        if index + 1 < len(documents):
            next_page = documents[index + 1].page_start
            document.page_end = document.page_start if next_page <= document.page_start else next_page - 1
        else:
            document.page_end = page_count


def workpaper_from_toc(
    toc: TableOfContents,
    *,
    page_count: int,
    keywords: str | None = None,
) -> Workpaper:
    tax_year, client_name, client_id, scan_id = _scan_fields(keywords)
    titles = [entry.title for entry in toc.entries]
    if titles != list(SECTIONS):
        raise ValueError(
            "Workpaper level-1 bookmarks must match schema.SECTIONS in order. "
            f"Got {titles}."
        )
    pending: list[SourceDocument] = []
    sections: list[WorkpaperSection] = []

    for entry in toc.entries:
        documents: list[SourceDocument] = []
        for leaf in entry.leaves() if entry.children else []:
            document_type, issuer, account, labeled, is_instructions = parse_document_title(leaf.title)
            document = SourceDocument(
                title=leaf.title,
                document_type=document_type,
                issuer=issuer,
                account=account,
                is_instructions=is_instructions,
                page_start=leaf.page,
                page_end=leaf.page,
                labeled_page_count=labeled,
            )
            documents.append(document)
            pending.append(document)
        sections.append(
            WorkpaperSection(name=entry.title, bookmark_page=entry.page, documents=documents)
        )

    _assign_page_spans(pending, page_count)
    return Workpaper(
        page_count=page_count,
        tax_year=tax_year,
        client_name=client_name,
        client_id=client_id,
        scan_id=scan_id,
        sections=sections,
        toc=toc,
    )


def load_workpaper(path: str | Path) -> Workpaper:
    import pymupdf

    pdf = pymupdf.open(path)
    try:
        toc = table_of_contents_from_outline(pdf.get_toc())
        return workpaper_from_toc(
            toc,
            page_count=pdf.page_count,
            keywords=(pdf.metadata or {}).get("keywords"),
        )
    finally:
        pdf.close()


def format_workpaper(workpaper: Workpaper) -> str:
    lines = [
        f"tax_year={workpaper.tax_year} client={workpaper.client_name} "
        f"client_id={workpaper.client_id} pages={workpaper.page_count}",
        "",
    ]
    for section in workpaper.sections:
        if section.is_empty:
            lines.append(f"{section.name}")
            continue
        span = f"pp. {section.page_start}-{section.page_end}"
        lines.append(f"{section.name}  ({span})")
        for document in section.documents:
            account = f"  account={document.account}" if document.account else ""
            kind = "instructions" if document.is_instructions else (document.document_type or "document")
            issuer = f"  {document.issuer}" if document.issuer and not document.is_instructions else ""
            lines.append(
                f"  {kind}{issuer}{account}  "
                f"pp. {document.page_start}-{document.page_end} ({document.page_count})"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "workpaper.pdf")
    loaded = load_workpaper(target)
    print(format_workpaper(loaded))
    mismatches = [
        document
        for section in loaded.sections
        for document in section.documents
        if document.labeled_page_count is not None
        and document.labeled_page_count != document.page_count
    ]
    if mismatches:
        print("\npage-count mismatches:")
        for document in mismatches:
            print(f"  {document.title}: labeled {document.labeled_page_count}, span {document.page_count}")
        sys.exit(1)
