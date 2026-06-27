"""Unit tests for SI line-item parser: qty/uom/unit-price derivation + account guard.

Tests the REAL save path: _parse_and_attach_line_items, which is called by
both create() and edit() views.
"""
import json
import pytest
from datetime import date
from decimal import Decimal
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.views import _parse_and_attach_line_items

pytestmark = [pytest.mark.unit]


def _leaf_account(db_session, code='4001'):
    """Create and return an active leaf (postable) revenue account."""
    acct = Account(
        code=code,
        name=f'Sales Revenue {code}',
        account_type='Income',
        classification='Operating Revenue',
        normal_balance='Credit',
        is_active=True,
    )
    db_session.add(acct)
    db_session.commit()
    return acct


def _make_invoice(main_branch):
    return SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='T-001',
        invoice_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        customer_id=1,
        customer_name='Test',
    )


def test_parser_reads_qty_uom_price(db_session, main_branch):
    """qty × unit_price → amount is derived by calculate_amounts() on the REAL save path."""
    acct = _leaf_account(db_session)
    inv = _make_invoice(main_branch)
    payload = json.dumps([{
        'description': 'Widget',
        'quantity': '10',
        'unit_price': '112.00',
        'uom_id': None,
        'uom_text': 'pcs',
        'product_id': None,
        'vat_category': None,
        'account_id': str(acct.id),
        'wt_id': None,
        'amount': '0',
    }])
    _parse_and_attach_line_items(inv, payload)
    line = inv.line_items[0]
    assert line.quantity == Decimal('10')
    assert line.unit_price == Decimal('112.00')
    assert line.uom_text == 'pcs'
    assert line.amount == Decimal('1120.00')        # derived


def test_si_line_none_account_raises(db_session, main_branch):
    """A line item with account_id=None must be rejected (GL integrity guard).

    A crafted POST with no account but a real amount must raise ValueError —
    the residual-absorber in the SI JE builder would otherwise silently misattribute
    the amount onto the first valid line's revenue credit.
    """
    inv = _make_invoice(main_branch)
    payload = json.dumps([{
        'description': 'Widget',
        'quantity': '10',
        'unit_price': '112.00',
        'uom_id': None,
        'uom_text': 'pcs',
        'product_id': None,
        'vat_category': None,
        'account_id': None,
        'wt_id': None,
        'amount': '0',
    }])
    with pytest.raises(ValueError, match='must have an account assigned'):
        _parse_and_attach_line_items(inv, payload)
