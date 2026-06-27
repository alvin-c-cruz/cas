"""Unit test — Task 14: wire qty/uom/unit-price + product into CD Section B.

Tests the REAL save path: _parse_and_attach_expense_lines, which is extracted
from _parse_line_items and called by both create() and edit() views.
"""
import json
import pytest
from decimal import Decimal
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher

pytestmark = [pytest.mark.unit]


def _leaf_account(db_session, code='50101'):
    """Create and return an active leaf (postable) expense account."""
    acct = Account(
        code=code,
        name=f'Office Supplies {code}',
        account_type='Expense',
        classification='Operating Expense',
        normal_balance='Debit',
        is_active=True,
    )
    db_session.add(acct)
    db_session.commit()
    return acct


@pytest.mark.usefixtures("app")
def test_cd_expense_line_qty_price_derives_amount(db_session, main_branch):
    """qty × unit_price → amount is set by calculate_amounts() on the REAL save path."""
    from app.cash_disbursements.views import _parse_and_attach_expense_lines
    acct = _leaf_account(db_session)
    cdv = CashDisbursementVoucher(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Supplies',
        'quantity':    '5',
        'unit_price':  '20.00',
        'uom_id':      None,
        'uom_text':    'box',
        'product_id':  None,
        'vat_category': None,
        'account_id':  str(acct.id),
        'wt_id':       None,
        'amount':      0,
    }])
    _parse_and_attach_expense_lines(cdv, payload)
    assert len(cdv.expense_lines) == 1
    line = cdv.expense_lines[0]
    assert line.quantity == Decimal('5')
    assert line.unit_price == Decimal('20.00')
    assert line.amount == Decimal('100.00')
    assert line.uom_text == 'box'
    assert line.product_id is None


@pytest.mark.usefixtures("app")
def test_cd_expense_line_none_account_raises(db_session, main_branch):
    """An expense line with account_id=None must be rejected (GL integrity guard).

    The JE builder silently skips expense lines with no account and its residual
    absorber can misattribute the amount onto the first valid line.  The parser
    guard must prevent None accounts from ever reaching the JE builder.
    """
    from app.cash_disbursements.views import _parse_and_attach_expense_lines, CDVLineError
    cdv = CashDisbursementVoucher(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Supplies',
        'quantity':    '5',
        'unit_price':  '20.00',
        'uom_id':      None,
        'uom_text':    'box',
        'product_id':  None,
        'vat_category': None,
        'account_id':  None,
        'wt_id':       None,
        'amount':      100,
    }])
    with pytest.raises(CDVLineError, match='valid, postable account'):
        _parse_and_attach_expense_lines(cdv, payload)
