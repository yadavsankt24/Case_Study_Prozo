"""
Generic table reader for text-based statutory PDFs (EPFO / ESIC ECRs).

Why not `pdfplumber.extract_tables()`?
    ECR PDFs have no ruling lines between cells, so table detection returns
    nothing. Instead we rebuild the table from word positions:

    1. Group the words on a page into visual lines (similar `top` coordinate).
    2. Find the column-header line and record where each column starts (x).
    3. Assign every word below it to the column whose start is at or left of it.
    4. A line whose identifier column holds a valid ID starts a new row.
       Short text-only lines just below a row are a wrapped name and are
       appended to that row.

The column layout found on one page is reused on following pages that do not
repeat the header, so long ECRs (hundreds of pages) parse page by page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

import pdfplumber

from app.shared.errors import InputError
from app.case_study_2.models import ParseLog

LINE_TOLERANCE = 3.0        # words whose tops differ by <= 3pt are on the same line
COLUMN_TOLERANCE = 4.0      # a value may start slightly left of its header
MAX_WRAP_GAP = 16.0         # a wrapped-name line sits within 16pt below its row

ProgressCallback = Callable[[int, int], None]  # (page_number, total_pages)


@dataclass(frozen=True)
class ColumnSpec:
    """A column, identified by the words of its header (e.g. ('IP', 'Number'))."""

    key: str
    header_words: tuple[str, ...]
    optional: bool = False


@dataclass
class TableLayout:
    columns: list[tuple[str, float]]  # (key, x where the column starts), left to right

    def column_for(self, x0: float) -> Optional[str]:
        chosen = None
        for key, start in self.columns:
            if x0 + COLUMN_TOLERANCE >= start:
                chosen = key
        return chosen


@dataclass
class TableSpec:
    """Describes one kind of ECR table."""

    columns: list[ColumnSpec]
    id_column: str                 # column that must contain the identifier
    id_pattern: re.Pattern         # e.g. 12 digits for UAN
    wrap_columns: tuple[str, ...]  # columns where wrapped text can continue (names)
    header_keywords: set[str]      # words that must appear on the header line


@dataclass
class Line:
    top: float
    words: list[dict]

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)


@dataclass
class TableRow:
    cells: dict[str, str]
    page: int
    top: float
    wrapped_lines: int = 0
    extra: dict = field(default_factory=dict)


def open_pdf(path: str, label: str) -> pdfplumber.PDF:
    """Open a PDF or raise a clear, user-facing error."""
    try:
        return pdfplumber.open(path)
    except Exception as exc:  # pdfminer raises many different exception types
        raise InputError(
            f"The {label} could not be opened as a PDF. It may be corrupt or password-protected. "
            f"Please download it again from the portal.",
        ) from exc


def group_lines(words: list[dict]) -> list[Line]:
    """Cluster words into visual lines, top to bottom, each sorted left to right."""
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1].top - word["top"]) <= LINE_TOLERANCE:
            lines[-1].words.append(word)
        else:
            lines.append(Line(top=word["top"], words=[word]))
    for line in lines:
        line.words.sort(key=lambda w: w["x0"])
    return lines


def page_lines(page) -> list[Line]:
    return group_lines(page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False))


def find_layout(line: Line, spec: TableSpec) -> Optional[TableLayout]:
    """Return the column layout if `line` is the table header line, else None."""
    texts = [_clean(w["text"]) for w in line.words]
    if not spec.header_keywords.issubset({t.lower() for t in texts}):
        return None

    columns: list[tuple[str, float]] = []
    cursor = 0
    for column in spec.columns:
        index = _find_phrase(texts, [_clean(h) for h in column.header_words], cursor)
        if index is None:
            if column.optional:
                continue
            return None
        columns.append((column.key, line.words[index]["x0"]))
        cursor = index + len(column.header_words)
    return TableLayout(columns)


def read_table(pdf: pdfplumber.PDF, spec: TableSpec, log: ParseLog,
               on_page: Optional[ProgressCallback] = None) -> Iterator[TableRow]:
    """Yield table rows from every page of the PDF."""
    layout: Optional[TableLayout] = None
    total_pages = len(pdf.pages)
    log.pages = total_pages

    for page_number, page in enumerate(pdf.pages, start=1):
        lines = page_lines(page)
        header_index = None
        for index, line in enumerate(lines):
            found = find_layout(line, spec)
            if found:
                layout, header_index = found, index
                break

        if layout is None:
            # No header seen yet (e.g. page 1 summary block): nothing to read on this page.
            if on_page:
                on_page(page_number, total_pages)
            continue

        body = lines[header_index + 1:] if header_index is not None else lines
        yield from _rows_from_lines(body, layout, spec, page_number, log)

        if on_page:
            on_page(page_number, total_pages)

    if layout is None:
        raise InputError("Could not find the member table header in the PDF. The layout is not recognised.")


def _rows_from_lines(lines: list[Line], layout: TableLayout, spec: TableSpec,
                     page_number: int, log: ParseLog) -> Iterator[TableRow]:
    current: Optional[TableRow] = None
    last_line_top = 0.0

    for line in lines:
        cells = _assign_cells(line, layout)
        identifier = cells.get(spec.id_column, "").strip()

        if spec.id_pattern.fullmatch(identifier):
            if current:
                yield current
            current = TableRow(cells=cells, page=page_number, top=line.top)
            last_line_top = line.top
            log.rows_parsed += 1
            continue

        if current and _is_wrapped_text(cells, line, last_line_top, spec):
            for key in spec.wrap_columns:
                if cells.get(key):
                    current.cells[key] = f"{current.cells.get(key, '')} {cells[key]}".strip()
            current.wrapped_lines += 1
            log.wrapped_name_lines += 1
            last_line_top = line.top
            continue

        # Repeated header words, footers, page numbers ... recorded, never silently dropped.
        if line.text.strip():
            log.skipped_lines.append(f"p{page_number}: {line.text[:120]}")

    if current:
        yield current


def _assign_cells(line: Line, layout: TableLayout) -> dict[str, str]:
    cells: dict[str, list[str]] = {}
    for word in line.words:
        key = layout.column_for(word["x0"])
        if key:
            cells.setdefault(key, []).append(word["text"])
    return {key: " ".join(parts) for key, parts in cells.items()}


def _is_wrapped_text(cells: dict[str, str], line: Line, last_top: float, spec: TableSpec) -> bool:
    """A continuation line: close below the previous row, letters only, only in name columns."""
    if line.top - last_top > MAX_WRAP_GAP:
        return False
    if any(key not in spec.wrap_columns for key in cells):
        return False
    return all(re.fullmatch(r"[A-Za-z .'\-]+", value) for value in cells.values())


def _find_phrase(texts: list[str], phrase: list[str], start: int) -> Optional[int]:
    lowered = [t.lower() for t in texts]
    target = [p.lower() for p in phrase]
    for index in range(start, len(texts) - len(target) + 1):
        if lowered[index:index + len(target)] == target:
            return index
    return None


def _clean(text: str) -> str:
    return text.strip().rstrip(".:")


def value_below_label(lines: list[Line], label_words: tuple[str, ...]) -> Optional[str]:
    """
    For summary blocks laid out as a row of labels with values on the next line
    (ESIC header), return the value printed under the given label.
    """
    target = [w.lower() for w in label_words]
    for index, line in enumerate(lines[:-1]):
        texts = [_clean(w["text"]).lower() for w in line.words]
        position = _find_phrase(texts, target, 0)
        if position is None:
            continue
        label_x = line.words[position]["x0"]
        for word in lines[index + 1].words:
            if abs(word["x0"] - label_x) <= 12:
                return word["text"]
    return None
