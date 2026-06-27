"""Unit test — Task 13: wire qty/uom/unit-price + product into CR Section B.

Tests the REAL save path: _parse_and_attach_revenue_lines, which is called by
_parse_line_items, which is called by both create() and edit() views.
"""
import json
import pytest
from decimal import Decimal
from app.accounts.models import Account
from app.cash_receipts.models import CashReceiptVoucher

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


@pytest.mark.usefixtures("app")
def test_cr_revenue_line_qty_price_derives_amount(db_session, main_branch):
    """qty × unit_price → amount is set by calculate_amounts() on the REAL save path."""
    from app.cash_receipts.views import _parse_and_attach_revenue_lines
    acct = _leaf_account(db_session)
    crv = CashReceiptVoucher(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Service',
        'quantity':    '3',
        'unit_price':  '100.00',
        'uom_id':      None,
        'uom_text':    'hr',
        'product_id':  None,
        'vat_category': None,
        'account_id':  str(acct.id),
        'wt_id':       None,
        'amount':      0,
    }])
    _parse_and_attach_revenue_lines(crv, payload)
    assert len(crv.revenue_lines) == 1
    line = crv.revenue_lines[0]
    assert line.quantity == Decimal('3')
    assert line.unit_price == Decimal('100.00')
    assert line.amount == Decimal('300.00')
    assert line.uom_text == 'hr'
    assert line.product_id is None


@pytest.mark.usefixtures("app")
def test_cr_revenue_line_none_account_raises(db_session, main_branch):
    """A revenue line with account_id=None must be rejected (GL integrity guard).

    A crafted POST with no account but a real amount must raise CRVLineError —
    the residual-absorber in the JE builder would otherwise silently misattribute
    the amount onto the first valid revenue line's credit.
    """
    from app.cash_receipts.views import _parse_and_attach_revenue_lines, CRVLineError
    crv = CashReceiptVoucher(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Service',
        'quantity':    '3',
        'unit_price':  '100.00',
        'uom_id':      None,
        'uom_text':    'hr',
        'product_id':  None,
        'vat_category': None,
        'account_id':  None,
        'wt_id':       None,
        'amount':      0,
    }])
    with pytest.raises(CRVLineError, match='must have an account assigned'):
        _parse_and_attach_revenue_lines(crv, payload)
