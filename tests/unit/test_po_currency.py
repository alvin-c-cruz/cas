"""A Purchase Order carries a currency CODE, defaulting to PHP.

Owner directive 2026-08-31, from the annotated legacy pad (PO 00984): "PO can be
of any currency. default is PHP". Scoped deliberately to a LABEL -- the amount is
still booked in pesos, nothing downstream converts, and no FX rate exists. This is
the first currency field anywhere in CAS; every other `currency` match in the tree
is the word `concurrency`.

The column is NOT NULL with a server-side default so the ~thousands of existing
orders across five client instances read 'PHP' rather than None, which would print
an empty label where the legacy pad prints a currency.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder

pytestmark = [pytest.mark.unit, pytest.mark.purchase_orders]


def _po(main_branch, vendor, number, **kw):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 31),
                       vendor_id=vendor.id, branch_id=main_branch.id,
                       status='draft', total_amount=Decimal('100.00'), **kw)
    db.session.add(po)
    db.session.commit()
    return po


def test_a_new_po_defaults_to_php(db_session, main_branch, vl_vendor):
    po = _po(main_branch, vl_vendor, 'PO-CUR-1')
    assert po.currency == 'PHP'


def test_currency_cannot_be_nulled(db_session, main_branch, vl_vendor):
    """The label must never print empty, so the column is NOT NULL.

    Asserted by writing NULL round the ORM and requiring the DATABASE to refuse it.
    Drop `nullable=False` from the model and this UPDATE silently succeeds.
    """
    from sqlalchemy.exc import IntegrityError
    po = _po(main_branch, vl_vendor, 'PO-CUR-2')
    with pytest.raises(IntegrityError):
        db.session.execute(db.text(
            'UPDATE purchase_orders SET currency = NULL WHERE id = :i'), {'i': po.id})
        db.session.flush()
    db.session.rollback()


def test_the_column_carries_a_SERVER_default(db_session):
    """Mutation target: a python-side `default=` alone backfills nothing.

    The migration's ADD COLUMN is what gives the ~thousands of Purchase Orders already
    on the five client instances a value; without a server default they would land NULL
    and the NOT NULL add would fail outright on any non-empty table.
    """
    col = PurchaseOrder.__table__.c.currency
    assert col.server_default is not None, 'no server_default -- existing rows backfill to NULL'
    assert 'PHP' in str(col.server_default.arg)


def test_an_explicit_currency_persists(db_session, main_branch, vl_vendor):
    po = _po(main_branch, vl_vendor, 'PO-CUR-3', currency='USD')
    db.session.expire(po)
    assert po.currency == 'USD'


def test_the_form_offers_a_currency_choice_defaulting_to_php():
    from app.purchase_orders.forms import PurchaseOrderForm
    field = PurchaseOrderForm.currency
    assert field is not None, 'PurchaseOrderForm has no currency field'
    kw = field.kwargs
    assert kw.get('default') == 'PHP', f"default is {kw.get('default')!r}, not 'PHP'"
    codes = [c[0] for c in kw.get('choices', [])]
    assert 'PHP' in codes, f'PHP missing from choices: {codes}'
    assert len(codes) > 1, 'a one-option currency list is not "any currency"'
    assert all(len(c) == 3 for c in codes), f'not all ISO-4217 3-letter codes: {codes}'
