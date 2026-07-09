"""Fail-closed resolution of the accountant-assigned memo accounts."""
import pytest

from app.sales_memos.service import (resolve_memo_account, SALES_RETURNS_KEY,
                                     CUSTOMER_CREDITS_KEY)

pytestmark = [pytest.mark.unit]


def test_resolve_memo_account_raises_when_unassigned(app, db_session):
    with pytest.raises(ValueError):
        resolve_memo_account(SALES_RETURNS_KEY, 'Sales Returns & Allowances')


def test_resolve_memo_account_raises_when_code_not_in_coa(app, db_session):
    from app.settings import AppSettings
    AppSettings.set_setting(CUSTOMER_CREDITS_KEY, '99999')  # assigned but not in COA
    with pytest.raises(ValueError):
        resolve_memo_account(CUSTOMER_CREDITS_KEY, 'Customer Credits/Advances')


def test_resolve_memo_account_returns_account_when_assigned(app, db_session):
    from app.accounts.models import Account
    from app.settings import AppSettings
    db_session.add(Account(code='40103', name='Sales Returns and Allowances',
                           account_type='Income', classification='General',
                           normal_balance='Debit'))
    db_session.commit()
    AppSettings.set_setting(SALES_RETURNS_KEY, '40103')
    acct = resolve_memo_account(SALES_RETURNS_KEY, 'Sales Returns & Allowances')
    assert acct.code == '40103'
