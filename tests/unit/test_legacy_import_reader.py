"""Reading legacy documents into a normalized, CAS-shaped form.

Exercised against a synthetic database built to the real legacy schema, so the
edge cases below are the ones actually present in RIC's data:

  * `record_date` appears in two widths -- '...00:00:00.000000' and '...00:00:00'
  * `notes` is blank on 5,192 of 5,193 `sales` rows, yet CAS's
    `JournalEntry.description` is NOT NULL
  * amounts are stored as SQLite REAL and must not round-trip through binary float
  * 438 headers carry zero entry lines and must be skipped, not imported as empty
"""
import sqlite3
from decimal import Decimal

import pytest

from scripts.legacy_import.reader import (
    UnbalancedDocumentError,
    parse_legacy_date,
    read_documents,
)
from scripts.legacy_import.schema import Book

pytestmark = [pytest.mark.unit, pytest.mark.legacy_import]


SALES = Book('sales', 'sales_entry', 'sales_id', 'sales_number', 'SJ', 'CORP',
             'customer_id', 'customers', 'customer_name')
GENERAL = Book('general', 'general_entry', 'general_id', 'general_number', 'JV', 'CORP')


@pytest.fixture()
def conn():
    c = sqlite3.connect(':memory:')
    c.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, customer_name TEXT, customer_tin TEXT);
        CREATE TABLE sales (id INTEGER PRIMARY KEY, record_date TEXT, sales_number TEXT,
                            notes TEXT, customer_id INTEGER);
        CREATE TABLE sales_entry (entry_id INTEGER PRIMARY KEY, sales_id INTEGER,
                            account_id INTEGER, debit REAL, credit REAL, notes TEXT);
        CREATE TABLE general (id INTEGER PRIMARY KEY, record_date TEXT, general_number TEXT,
                            notes TEXT);
        CREATE TABLE general_entry (entry_id INTEGER PRIMARY KEY, general_id INTEGER,
                            account_id INTEGER, debit REAL, credit REAL, notes TEXT);
        INSERT INTO customers VALUES (14, 'MONDE MY SAN CORPORATION', '209-152-680-000');
    """)
    return c


def _sale(conn, sid, date, number, notes, customer_id=14, lines=()):
    conn.execute('INSERT INTO sales VALUES (?,?,?,?,?)',
                 (sid, date, number, notes, customer_id))
    for i, (acct, dr, cr) in enumerate(lines, start=1):
        conn.execute('INSERT INTO sales_entry VALUES (?,?,?,?,?,?)',
                     (sid * 100 + i, sid, acct, dr, cr, None))


def test_parses_both_record_date_widths():
    assert parse_legacy_date('2023-01-03 00:00:00.000000').isoformat() == '2023-01-03'
    assert parse_legacy_date('2023-01-03 00:00:00').isoformat() == '2023-01-03'
    assert parse_legacy_date('2023-01-03').isoformat() == '2023-01-03'


def test_reads_a_balanced_document_with_decimal_amounts(conn):
    _sale(conn, 1, '2023-01-03 00:00:00.000000', '0028061', 'Sale to Monde',
          lines=[(10, 363992.72, 0.0), (20, 0.0, 363992.72)])
    docs, skipped = read_documents(conn, SALES)

    assert skipped == []
    (doc,) = docs
    assert doc.legacy_id == 1
    assert doc.number == '0028061'
    assert doc.entry_date.isoformat() == '2023-01-03'
    assert doc.total_debit == Decimal('363992.72')
    assert doc.total_credit == Decimal('363992.72')
    assert [line.debit for line in doc.lines] == [Decimal('363992.72'), Decimal('0.00')]
    assert all(isinstance(line.debit, Decimal) for line in doc.lines)


def test_zero_line_header_is_skipped_not_imported(conn):
    """438 such headers exist in RIC's data. An empty JE would be meaningless."""
    _sale(conn, 7, '2023-01-03 00:00:00', '0028999', 'orphan header', lines=[])
    docs, skipped = read_documents(conn, SALES)
    assert docs == []
    assert skipped == [7]


def test_unbalanced_document_fails_closed(conn):
    _sale(conn, 2, '2023-01-03 00:00:00', '0028062', 'bad',
          lines=[(10, 100.0, 0.0), (20, 0.0, 99.0)])
    with pytest.raises(UnbalancedDocumentError, match='0028062'):
        read_documents(conn, SALES)


def test_description_falls_back_to_counterparty_when_notes_blank(conn):
    """`sales.notes` is blank on 5,192 of 5,193 rows, but description is NOT NULL."""
    _sale(conn, 3, '2023-01-03 00:00:00', '0028063', '   ',
          lines=[(10, 5.0, 0.0), (20, 0.0, 5.0)])
    (doc,), _ = read_documents(conn, SALES)
    assert doc.description == 'MONDE MY SAN CORPORATION'
    assert doc.counterparty_name == 'MONDE MY SAN CORPORATION'


def test_description_falls_back_to_book_and_number_with_no_counterparty(conn):
    conn.execute("INSERT INTO general VALUES (5, '2025-09-30 00:00:00', '202509-050', NULL)")
    conn.execute('INSERT INTO general_entry VALUES (1, 5, 10, 1.0, 0.0, NULL)')
    conn.execute('INSERT INTO general_entry VALUES (2, 5, 20, 0.0, 1.0, NULL)')
    (doc,), _ = read_documents(conn, GENERAL)
    assert doc.description == 'general 202509-050'
    assert doc.counterparty_name is None


def test_notes_win_over_counterparty(conn):
    _sale(conn, 4, '2023-01-03 00:00:00', '0028064', 'Collection re DM0254',
          lines=[(10, 5.0, 0.0), (20, 0.0, 5.0)])
    (doc,), _ = read_documents(conn, SALES)
    assert doc.description == 'Collection re DM0254'


def test_description_is_truncated_to_the_column_width(conn):
    _sale(conn, 6, '2023-01-03 00:00:00', '0028066', 'x' * 600,
          lines=[(10, 5.0, 0.0), (20, 0.0, 5.0)])
    (doc,), _ = read_documents(conn, SALES)
    assert len(doc.description) == 500


def test_documents_are_ordered_by_date_then_legacy_id(conn):
    _sale(conn, 9, '2023-02-01 00:00:00', 'b', 'n', lines=[(10, 1.0, 0.0), (20, 0.0, 1.0)])
    _sale(conn, 8, '2023-01-01 00:00:00', 'a', 'n', lines=[(10, 1.0, 0.0), (20, 0.0, 1.0)])
    docs, _ = read_documents(conn, SALES)
    assert [d.legacy_id for d in docs] == [8, 9]
