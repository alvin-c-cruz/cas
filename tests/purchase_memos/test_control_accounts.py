"""Fail-closed resolution of the accountant-assigned Vendor Debit Memo accounts.

Purchase Returns & Allowances (contra-expense) and Vendor Credits (liability) are
NOT ``app.posting.control_accounts`` entries -- they mirror the sales-side
``app/sales_memos/service.py`` mechanism exactly (verified: neither
``sales_returns_allowances_account_code`` nor ``customer_credits_advances_account_code``
appears in ``CONTROL_ACCOUNTS``/``DEFAULT_CONTROL_ACCOUNT_CODES``, any seed COA, or any
migration -- both are resolved directly from ``AppSettings`` via
``sales_memos.service.resolve_memo_account``, with NO default code, and accountant-
assigned via the Sales Memo settings page). ``app/purchase_memos/service.py`` mirrors
that module 1:1 for the buy side.
"""
import pytest

from app.purchase_memos.service import (resolve_memo_account, PURCHASE_RETURNS_KEY,
                                        VENDOR_CREDITS_KEY)

pytestmark = [pytest.mark.unit]


def test_resolve_memo_account_raises_when_purchase_returns_unassigned(app, db_session):
    with pytest.raises(ValueError):
        resolve_memo_account(PURCHASE_RETURNS_KEY, 'Purchase Returns & Allowances')


def test_resolve_memo_account_raises_when_vendor_credits_unassigned(app, db_session):
    with pytest.raises(ValueError):
        resolve_memo_account(VENDOR_CREDITS_KEY, 'Vendor Credits')


def test_resolve_memo_account_raises_when_code_not_in_coa(app, db_session):
    from app.settings import AppSettings
    AppSettings.set_setting(VENDOR_CREDITS_KEY, '99999')  # assigned but not in COA
    with pytest.raises(ValueError):
        resolve_memo_account(VENDOR_CREDITS_KEY, 'Vendor Credits')


def test_resolve_memo_account_returns_account_when_purchase_returns_assigned(app, db_session):
    from app.accounts.models import Account
    from app.settings import AppSettings
    db_session.add(Account(code='50103', name='Purchase Returns and Allowances',
                           account_type='Expense', classification='General',
                           normal_balance='Credit'))
    db_session.commit()
    AppSettings.set_setting(PURCHASE_RETURNS_KEY, '50103')
    acct = resolve_memo_account(PURCHASE_RETURNS_KEY, 'Purchase Returns & Allowances')
    assert acct.code == '50103'


def test_resolve_memo_account_returns_account_when_vendor_credits_assigned(app, db_session):
    from app.accounts.models import Account
    from app.settings import AppSettings
    db_session.add(Account(code='20302', name='Vendor Credits',
                           account_type='Liability', classification='Current Liability',
                           normal_balance='Credit'))
    db_session.commit()
    AppSettings.set_setting(VENDOR_CREDITS_KEY, '20302')
    acct = resolve_memo_account(VENDOR_CREDITS_KEY, 'Vendor Credits')
    assert acct.code == '20302'
