"""Read legacy documents into a normalized, CAS-shaped form.

Pure sqlite3 -- no Flask, no ORM -- so it can be exercised against a synthetic
database and against a client's real one without an app context.

Amounts are converted REAL -> Decimal via `str()`, never `Decimal(float)`, so a
value stored as 363992.72 does not arrive as 363992.71999999999. Balance is
asserted per document at read time: the source data is clean today (all 19,454
RIC documents balance), and an unbalanced document must stop the import rather
than post a lopsided journal entry.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

DESCRIPTION_MAX = 500          # JournalEntry.description
LINE_DESCRIPTION_MAX = 500     # JournalEntryLine.description
REFERENCE_MAX = 100            # JournalEntry.reference

_CENT = Decimal('0.01')

# `record_date` is TEXT and appears in two widths across the books.
_DATE_FORMATS = ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d')


class UnbalancedDocumentError(RuntimeError):
    """A legacy document's debits do not equal its credits."""


@dataclass(frozen=True)
class LegacyLine:
    account_id: int
    debit: Decimal
    credit: Decimal
    description: str = None


@dataclass(frozen=True)
class LegacyDoc:
    book: object
    legacy_id: int
    entry_date: object
    number: str
    description: str
    counterparty_name: str
    lines: tuple

    @property
    def total_debit(self):
        return sum((line.debit for line in self.lines), Decimal('0.00'))

    @property
    def total_credit(self):
        return sum((line.credit for line in self.lines), Decimal('0.00'))

    @property
    def source_key(self):
        return f'{self.book.header_table}:{self.legacy_id}'


def parse_legacy_date(raw):
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'unrecognized legacy date: {raw!r}')


def to_amount(raw):
    """REAL -> Decimal without a binary-float detour."""
    if raw is None:
        return Decimal('0.00')
    return Decimal(str(raw)).quantize(_CENT)


def _clean(text, limit):
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    return text[:limit]


def _counterparty_names(conn, book):
    if not book.counterparty_table:
        return {}
    rows = conn.execute(
        f'SELECT id, "{book.counterparty_name}" FROM "{book.counterparty_table}"'
    )
    return {row[0]: _clean(row[1], DESCRIPTION_MAX) for row in rows}


def read_documents(conn, book):
    """Return `(documents, skipped_header_ids)` for one book.

    Headers with no entry lines are skipped and reported -- 438 exist in RIC's
    data and 187 in Philgen's. An empty journal entry carries no information and
    would only pollute the books.
    """
    names = _counterparty_names(conn, book)

    columns = ['id', 'record_date', book.number_column, 'notes']
    if book.counterparty_column:
        columns.append(book.counterparty_column)
    selected = ', '.join(f'"{c}"' for c in columns)

    headers = conn.execute(
        f'SELECT {selected} FROM "{book.header_table}" ORDER BY record_date, id'
    ).fetchall()

    lines_by_header = {}
    line_rows = conn.execute(
        f'SELECT "{book.entry_fk}", account_id, debit, credit, notes '
        f'FROM "{book.entry_table}" ORDER BY entry_id'
    )
    for parent_id, account_id, debit, credit, note in line_rows:
        lines_by_header.setdefault(parent_id, []).append(
            LegacyLine(
                account_id=account_id,
                debit=to_amount(debit),
                credit=to_amount(credit),
                description=_clean(note, LINE_DESCRIPTION_MAX),
            )
        )

    documents = []
    skipped = []

    for row in headers:
        legacy_id, raw_date, raw_number, raw_notes = row[0], row[1], row[2], row[3]
        counterparty_id = row[4] if book.counterparty_column else None

        lines = lines_by_header.get(legacy_id, [])
        if not lines:
            skipped.append(legacy_id)
            continue

        number = str(raw_number).strip()
        counterparty_name = names.get(counterparty_id)

        # `description` is NOT NULL in CAS, and legacy `notes` is blank on almost
        # every `sales` and `petty_cash` row.
        description = (
            _clean(raw_notes, DESCRIPTION_MAX)
            or counterparty_name
            or f'{book.header_table} {number}'
        )[:DESCRIPTION_MAX]

        doc = LegacyDoc(
            book=book,
            legacy_id=legacy_id,
            entry_date=parse_legacy_date(raw_date),
            number=number,
            description=description,
            counterparty_name=counterparty_name,
            lines=tuple(lines),
        )

        debit, credit = doc.total_debit, doc.total_credit
        if debit != credit:
            raise UnbalancedDocumentError(
                f'{book.header_table} {number!r} (legacy id {legacy_id}): '
                f'debits {debit} != credits {credit}'
            )

        documents.append(doc)

    return documents, skipped
