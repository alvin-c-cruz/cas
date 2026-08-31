"""Memo numbers are unique PER TYPE, not across the whole table.

Both memo tables share one shape: `memo_type` ('credit' | 'debit') plus a
`memo_number`, and their generators filter by `memo_type` so each type climbs its
own series. Before this change the column carried a table-wide `unique=True` and
`assigned_number_or_raise` checked for collisions WITHOUT that filter -- so the
guard rejected exactly the number the generator was designed to produce.

The effect was not a first-run hiccup. The second type's series is empty forever,
so its generator returns the `00001` placeholder on every attempt and the guard
finds the first type's `00001` every time: once a Credit Memo existed, Debit Notes
could never be created, and symmetrically. The create form has no number field and
`/sales-memos/settings` holds only account assignments, so the error's advice --
"ask an administrator to record the first one" -- pointed at nothing.

Two independent layers are pinned here, because either alone would let the bug
back in:
  * the SCHEMA must permit credit 00001 alongside debit 00001, and still refuse
    two credits both numbered 00001;
  * the GUARD must apply the same filter the generator uses.
A schema-only fix would still be blocked by the unfiltered guard; a guard-only fix
would reach the database and die on an IntegrityError.

NB: these assert against conftest's create_all() schema. That builds today's models,
NOT the migration history -- the batch migration is verified separately against a
copy of a real DB (memory `migration-verify-on-real-db-copy`).
"""
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy

from app import db
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.sales_memos.models import SalesMemo, generate_memo_number
from app.purchase_memos.models import PurchaseMemo
from app.utils.doc_numbering import assigned_number_or_raise

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos,
              pytest.mark.purchase_memos]


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def si(db_session, main_branch):
    c = Customer(code='MNC1', name='Numbering Customer', is_active=True)
    db.session.add(c)
    db.session.commit()
    inv = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-NUM-1',
                       invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
                       customer_id=c.id, customer_name=c.name, notes='',
                       status='posted', total_amount=Decimal('1120'),
                       balance=Decimal('1120'))
    db.session.add(inv)
    db.session.commit()
    return inv


@pytest.fixture
def vendor(db_session):
    v = Vendor(code='MNV1', name='Numbering Vendor', is_active=True)
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture
def ap(db_session, vendor, main_branch):
    bill = AccountsPayable(branch_id=main_branch.id, ap_number='AP-NUM-1',
                           ap_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
                           payee_type='vendor', payee_id=vendor.id,
                           vendor_id=vendor.id, vendor_name=vendor.name,
                           status='posted')
    db.session.add(bill)
    db.session.commit()
    return bill


def _sales_memo(si, branch, memo_type, number):
    m = SalesMemo(memo_type=memo_type, memo_number=number,
                  memo_date=date(2026, 8, 2), branch_id=branch.id,
                  sales_invoice_id=si.id,
                  original_invoice_number=si.invoice_number,
                  customer_id=si.customer_id, customer_name=si.customer_name,
                  reason='numbering test')
    db.session.add(m)
    return m


def _purchase_memo(ap, branch, memo_type, number):
    m = PurchaseMemo(memo_type=memo_type, memo_number=number,
                     memo_date=date(2026, 8, 2), branch_id=branch.id,
                     accounts_payable_id=ap.id, original_ap_number=ap.ap_number,
                     vendor_id=ap.vendor_id, vendor_name='Numbering Vendor',
                     reason='numbering test')
    db.session.add(m)
    return m


# --- the schema half --------------------------------------------------------

class TestSchemaAllowsTheSameNumberInEachSeries:

    def test_a_credit_and_a_debit_sales_memo_may_share_a_number(
            self, db_session, si, main_branch):
        # THE bug, at the storage layer. Both series start at 00001 by design;
        # a table-wide unique constraint makes that permanently impossible.
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()
        _sales_memo(si, main_branch, 'debit', '00001')
        db.session.commit()

        got = {(m.memo_type, m.memo_number) for m in SalesMemo.query.all()}
        assert got == {('credit', '00001'), ('debit', '00001')}

    def test_two_credit_sales_memos_may_not_share_a_number(
            self, db_session, si, main_branch):
        # The control. Loosening the constraint must not make numbers free-for-all
        # WITHIN a series -- dropping uniqueness altogether would pass the test
        # above and silently allow duplicate credit memos.
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()
        _sales_memo(si, main_branch, 'credit', '00001')
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_a_credit_and_a_debit_purchase_memo_may_share_a_number(
            self, db_session, ap, main_branch):
        # The sibling table, same defect, same shape.
        _purchase_memo(ap, main_branch, 'credit', '00001')
        db.session.commit()
        _purchase_memo(ap, main_branch, 'debit', '00001')
        db.session.commit()

        got = {(m.memo_type, m.memo_number) for m in PurchaseMemo.query.all()}
        assert got == {('credit', '00001'), ('debit', '00001')}

    def test_two_debit_purchase_memos_may_not_share_a_number(
            self, db_session, ap, main_branch):
        _purchase_memo(ap, main_branch, 'debit', '00001')
        db.session.commit()
        _purchase_memo(ap, main_branch, 'debit', '00001')
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


# --- the guard half ---------------------------------------------------------

class TestTheGuardAppliesTheGeneratorsFilter:

    def test_the_other_types_number_is_not_a_collision(
            self, db_session, si, main_branch):
        # A credit 00001 exists; the debit series is empty, so the generator
        # returns 00001. With the generator's own filter applied, that is free.
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()

        got = assigned_number_or_raise(
            SalesMemo, SalesMemo.memo_number, '00001', 'Sales memo',
            filters=[SalesMemo.memo_type == 'debit'])
        assert got == '00001'

    def test_the_same_types_number_is_still_a_collision(
            self, db_session, si, main_branch):
        # The control: the guard must still fire within a series, or it has just
        # been turned off rather than corrected.
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()

        with pytest.raises(ValueError) as exc:
            assigned_number_or_raise(
                SalesMemo, SalesMemo.memo_number, '00001', 'Sales memo',
                filters=[SalesMemo.memo_type == 'credit'])
        assert '00001' in str(exc.value)

    def test_an_unfiltered_call_still_collides(self, db_session, si, main_branch):
        # Quotation and any other single-series caller pass no filters and must
        # keep the old table-wide behaviour exactly.
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()

        with pytest.raises(ValueError):
            assigned_number_or_raise(
                SalesMemo, SalesMemo.memo_number, '00001', 'Sales memo')

    def test_a_free_number_is_returned_unchanged(self, db_session, si, main_branch):
        _sales_memo(si, main_branch, 'credit', '00001')
        db.session.commit()
        assert assigned_number_or_raise(
            SalesMemo, SalesMemo.memo_number, '00002', 'Sales memo') == '00002'


# --- the two halves together: the filed repro -------------------------------

def test_a_debit_note_is_numberable_after_a_credit_memo(
        db_session, si, main_branch):
    """BUG-SALES-MEMO-SERIES-VS-UNIQUE-CONSTRAINT, end to end at the numbering
    layer: generate -> guard -> persist, the exact sequence sales_memos.create
    runs, which previously could not complete for the second memo type."""
    first = generate_memo_number('credit', main_branch.id)
    _sales_memo(si, main_branch, 'credit',
                assigned_number_or_raise(
                    SalesMemo, SalesMemo.memo_number, first, 'Sales memo',
                    filters=[SalesMemo.memo_type == 'credit']))
    db.session.commit()

    second = generate_memo_number('debit', main_branch.id)
    assert second == '00001', 'the debit series is empty, so it starts at 1'
    _sales_memo(si, main_branch, 'debit',
                assigned_number_or_raise(
                    SalesMemo, SalesMemo.memo_number, second, 'Sales memo',
                    filters=[SalesMemo.memo_type == 'debit']))
    db.session.commit()

    assert SalesMemo.query.filter_by(memo_type='debit').count() == 1
    # and the NEXT debit continues its own series rather than jumping past credit
    assert generate_memo_number('debit', main_branch.id) == '00002'
