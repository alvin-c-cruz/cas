"""Unit tests for the AP real save path: _build_validated_ap_lines().

These tests exercise the function the app actually calls on create/edit, not a
dead helper.  They use app.test_request_context() to supply request.form data
and a real leaf account in the DB to pass the postable-account guard.
"""
import json
import pytest
from decimal import Decimal

from app.accounts.models import Account
from app.accounts_payable.views import _build_validated_ap_lines

pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]


def _leaf_account(db_session, code='5001'):
    """Create and return an active leaf (postable) expense account."""
    acct = Account(
        code=code,
        name=f'Expense Account {code}',
        account_type='Expense',
        classification='Operating Expense',
        normal_balance='Debit',
        is_active=True,
    )
    db_session.add(acct)
    db_session.commit()
    return acct


def test_ap_line_qty_price_derives_amount(app, db_session):
    """qty × unit_price drives amount via calculate_amounts() on the real save path.

    Passes amount='1.00' in the form (valid for the >0 guard) but expects the
    result to be 4 × 56.00 = 224.00, proving calculate_amounts() overrode it.
    Also verifies uom_text, product_id, and unit_of_measure_id survive the path.
    """
    acct = _leaf_account(db_session)
    line = {
        'description': 'Parts',
        'quantity': '4',
        'unit_price': '56.00',
        'uom_id': None,
        'uom_text': 'set',
        'product_id': None,
        'vat_category': None,
        'wt_id': None,
        'account_id': str(acct.id),
        'amount': '1.00',   # passes >0 guard; overridden by qty×price below
    }
    with app.test_request_context(
        '/', method='POST',
        data={'line_items': json.dumps([line])}
    ):
        lines = _build_validated_ap_lines()

    assert len(lines) == 1
    item = lines[0]
    assert item.quantity == Decimal('4')
    assert item.unit_price == Decimal('56.00')
    assert item.amount == Decimal('224.00')   # 4 × 56 derived by calculate_amounts()
    assert item.uom_text == 'set'
    assert item.product_id is None
    assert item.unit_of_measure_id is None


def test_ap_line_null_qty_keeps_explicit_amount(app, db_session):
    """When qty and unit_price are null, amount stays as the explicitly typed value."""
    acct = _leaf_account(db_session, code='5002')
    line = {
        'description': 'Service fee',
        'quantity': None,
        'unit_price': None,
        'uom_id': None,
        'uom_text': '',
        'product_id': None,
        'vat_category': None,
        'wt_id': None,
        'account_id': str(acct.id),
        'amount': '500.00',
    }
    with app.test_request_context(
        '/', method='POST',
        data={'line_items': json.dumps([line])}
    ):
        lines = _build_validated_ap_lines()

    assert len(lines) == 1
    item = lines[0]
    assert item.quantity is None
    assert item.unit_price is None
    assert item.amount == Decimal('500.00')


def test_ap_line_malformed_product_id_and_uom_id_are_guarded(app, db_session):
    """Malformed product_id / uom_id strings don't crash — _int_safe() returns None."""
    acct = _leaf_account(db_session, code='5003')
    line = {
        'description': 'Widget',
        'quantity': None,
        'unit_price': None,
        'uom_id': 'GARBAGE',
        'uom_text': '',
        'product_id': 'NOT_AN_INT',
        'vat_category': None,
        'wt_id': None,
        'account_id': str(acct.id),
        'amount': '100.00',
    }
    with app.test_request_context(
        '/', method='POST',
        data={'line_items': json.dumps([line])}
    ):
        lines = _build_validated_ap_lines()

    assert len(lines) == 1
    item = lines[0]
    assert item.product_id is None
    assert item.unit_of_measure_id is None
    assert item.amount == Decimal('100.00')
