"""Writing replayed legacy documents into CAS as posted journal vouchers.

Entries land POSTED and CAS has no journal-entry edit route, so the properties
that matter are: the write is idempotent (a re-run cannot double the books), it
is a single transaction (a failure leaves nothing behind), and `--purge` removes
exactly what the importer wrote and nothing else.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from scripts.legacy_import.persist import (
    IMPORT_ENTRY_TYPE,
    existing_source_refs,
    purge_imported,
    resolve_branch_ids,
    write_documents,
)
from scripts.legacy_import.reader import LegacyDoc, LegacyLine
from scripts.legacy_import.schema import Book

pytestmark = [pytest.mark.integration, pytest.mark.legacy_import]

SALES = Book('sales', 'sales_entry', 'sales_id', 'sales_number', 'SJ', 'CORP',
             'customer_id', 'customers', 'customer_name')
SALES_X = Book('sales_x', 'sales_entry_x', 'sales_x_id', 'sales_number', 'SJX', 'EXTRA',
               'customer_id', 'customers', 'customer_name')

BRANCH_CODES = {'CORP': '00000', 'EXTRA': '00000-X'}


@pytest.fixture()
def books(db_session):
    corp = Branch(name='Corp', code='00000')
    extra = Branch(name='Extra', code='00000-X')
    ar = Account(code='10201', name='AR-Trade', account_type='Asset', normal_balance='debit')
    rev = Account(code='40101', name='Sales', account_type='Revenue', normal_balance='credit')
    db.session.add_all([corp, extra, ar, rev])
    db.session.commit()
    return {'corp': corp, 'extra': extra, 'ar': ar, 'rev': rev}


def _doc(book, legacy_id, number, amount='100.00', when=date(2023, 1, 3)):
    amt = Decimal(amount)
    return LegacyDoc(
        book=book, legacy_id=legacy_id, entry_date=when, number=number,
        description=f'doc {number}', counterparty_name='ACME',
        lines=(LegacyLine(1, amt, Decimal('0.00'), 'dr leg'),
               LegacyLine(2, Decimal('0.00'), amt, 'cr leg')),
    )


def _write(docs, books, admin_user, allocated=None):
    account_map = {1: books['ar'].id, 2: books['rev'].id}
    allocated = allocated or {
        (d.book.prefix, d.legacy_id): f'{d.book.prefix}-{d.number}' for d in docs
    }
    return write_documents(
        session=db.session, slug='ric', documents=docs, allocated=allocated,
        account_map=account_map,
        branch_ids=resolve_branch_ids(db.session, BRANCH_CODES),
        admin_user_id=admin_user.id,
    )


def test_writes_a_posted_balanced_entry_with_provenance(books, admin_user):
    stats = _write([_doc(SALES, 1, '0028061', '363992.72')], books, admin_user)
    assert stats.written == 1 and stats.skipped_existing == 0

    entry = JournalEntry.query.one()
    assert entry.entry_number == 'SJ-0028061'
    assert entry.reference == '0028061'
    assert entry.status == 'posted'
    assert entry.entry_type == IMPORT_ENTRY_TYPE
    assert entry.source_ref == 'ric:sales:1'
    assert entry.is_balanced is True
    assert entry.total_debit == Decimal('363992.72')
    assert entry.total_credit == Decimal('363992.72')
    assert entry.entry_date == date(2023, 1, 3)
    assert entry.posted_at is not None
    assert entry.posted_by_id == admin_user.id
    assert entry.created_by_id == admin_user.id
    assert entry.branch_id == books['corp'].id

    lines = JournalEntryLine.query.order_by(JournalEntryLine.line_number).all()
    assert [l.line_number for l in lines] == [1, 2]
    assert [l.account_id for l in lines] == [books['ar'].id, books['rev'].id]
    assert lines[0].debit_amount == Decimal('363992.72')
    assert lines[1].credit_amount == Decimal('363992.72')
    assert lines[0].description == 'dr leg'


def test_the_x_book_lands_in_the_extra_branch(books, admin_user):
    _write([_doc(SALES_X, 1, '0000001')], books, admin_user)
    entry = JournalEntry.query.one()
    assert entry.branch_id == books['extra'].id
    assert entry.entry_number == 'SJX-0000001'


def test_rerun_is_idempotent(books, admin_user):
    docs = [_doc(SALES, 1, '0028061'), _doc(SALES, 2, '0028062')]
    assert _write(docs, books, admin_user).written == 2

    again = _write(docs, books, admin_user)
    assert again.written == 0
    assert again.skipped_existing == 2
    assert JournalEntry.query.count() == 2
    assert JournalEntryLine.query.count() == 4


def test_partial_rerun_writes_only_the_new_document(books, admin_user):
    _write([_doc(SALES, 1, '0028061')], books, admin_user)
    stats = _write([_doc(SALES, 1, '0028061'), _doc(SALES, 2, '0028062')], books, admin_user)
    assert (stats.written, stats.skipped_existing) == (1, 1)
    assert JournalEntry.query.count() == 2


def test_existing_source_refs_is_scoped_to_the_client(books, admin_user):
    _write([_doc(SALES, 1, '0028061')], books, admin_user)
    assert existing_source_refs(db.session, 'ric') == {'ric:sales:1'}
    assert existing_source_refs(db.session, 'philgen') == set()


def test_purge_removes_exactly_what_the_importer_wrote(books, admin_user):
    """A hand-entered CAS voucher must survive the purge untouched."""
    _write([_doc(SALES, 1, '0028061')], books, admin_user)

    native = JournalEntry(
        entry_number='JV-2026-07-0001', entry_date=date(2026, 7, 1),
        description='real CAS voucher', entry_type='adjustment',
        branch_id=books['corp'].id, created_by_id=admin_user.id,
        is_balanced=True, total_debit=0, total_credit=0, status='posted',
    )
    db.session.add(native)
    db.session.commit()

    removed = purge_imported(db.session, 'ric')
    db.session.commit()

    assert removed == 1
    remaining = JournalEntry.query.all()
    assert [e.entry_number for e in remaining] == ['JV-2026-07-0001']
    assert JournalEntryLine.query.count() == 0


def test_an_unmapped_account_aborts_before_writing_anything(books, admin_user):
    doc = _doc(SALES, 1, '0028061')
    with pytest.raises(KeyError):
        write_documents(
            session=db.session, slug='ric', documents=[doc],
            allocated={('SJ', 1): 'SJ-0028061'},
            account_map={1: books['ar'].id},          # line 2's account is missing
            branch_ids=resolve_branch_ids(db.session, BRANCH_CODES),
            admin_user_id=admin_user.id,
        )
    db.session.rollback()
    assert JournalEntry.query.count() == 0
    assert JournalEntryLine.query.count() == 0
