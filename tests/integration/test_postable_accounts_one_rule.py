"""One rule for which accounts can be posted to, used by every account picker (ACCT-PICK, owner 14 Nov 2026: "ACCT-PICK
shared helper"; ACCT-RULE, 17 Nov 2026: "B (my pick)"; triage BUG-ACCOUNT-PICKER-CHILDLESS-TOPLEVEL-POSTABLE).

The rule: an account is a HEADER if another active account has it as its parent; every other active account is
postable, a top-level one with no sub-accounts included (RIC's 119000 / 229000 / 611000, Philgen's 115000 / 116000).
Twelve pickers now agree -- before, three (opening balances, control accounts, fixed assets) also treated every
top-level account as a header. All read app/accounts/postable.py.
"""
import pytest

from app import db
from app.accounts.models import Account
from app.accounts.postable import header_ids, postable_accounts

pytestmark = [pytest.mark.integration]


@pytest.fixture
def chart(db_session):
    """110000 Current Assets > 111000 Cash in Bank (leaf); 119000 Other Current Assets (top-level, no children);
    an inactive top-level 999000 with an inactive child."""
    def acct(code, name, atype='Asset', parent=None, active=True):
        a = Account(code=code, name=name, account_type=atype, normal_balance='debit', is_active=active,
                    parent_id=parent.id if parent else None)
        db.session.add(a); db.session.commit()
        return a
    current = acct('110000', 'Current Assets')
    cash = acct('111000', 'Cash in Bank', parent=current)
    lonely = acct('119000', 'Other Current Assets')
    old = acct('999000', 'Old Top', active=False)
    acct('999100', 'Old Leaf', parent=old, active=False)
    return {'current': current, 'cash': cash, 'lonely': lonely}


def _ids(rows, key='id'):
    return {r[key] if isinstance(r, dict) else r for r in rows}


class TestTheRule:

    def test_headers_and_postables(self, app, chart):
        heads = header_ids()
        assert chart['current'].id in heads
        assert chart['lonely'].id not in heads, 'a top-level account with no sub-accounts is postable (rule B)'
        assert chart['cash'].id not in heads
        assert [a.code for a in postable_accounts()] == ['111000', '119000']

    def test_by_type(self, app, chart):
        assert [a.code for a in postable_accounts(account_type='Asset')] == ['111000', '119000']
        assert postable_accounts(account_type='Expense') == []


@pytest.mark.parametrize('module', ['accounts_payable', 'cash_disbursements', 'cash_receipts', 'sales_invoices'])
def test_the_voucher_pickers_agree_on_the_rule(app, chart, module):
    import importlib
    rows = importlib.import_module(f'app.{module}.views')._get_all_accounts_for_select()
    flags = {r['code']: r['is_group'] for r in rows}
    assert flags['119000'] is False and flags['110000'] is True and flags['111000'] is False
    depth = {r['code']: r['depth'] for r in rows}
    assert depth['111000'] == 1 and depth['110000'] == 0


def test_the_jv_picker(app, chart):
    from app.journal_entries.views import _accounts_for_select
    flags = {r['code']: r['is_group'] for r in _accounts_for_select()}
    assert flags == {'110000': True, '111000': False, '119000': False}


@pytest.mark.parametrize('module,func', [('vat_categories', '_vat_account_choices'),
                                         ('sales_vat_categories', '_output_vat_account_choices'),
                                         ('withholding_tax', '_wht_account_choices')])
def test_the_tax_account_pickers_offer_only_postable_accounts(app, chart, module, func):
    import importlib
    choices = getattr(importlib.import_module(f'app.{module}.views'), func)()
    assert choices[0][0] == 0, 'the "none" choice stays first'
    assert [label.split(' : ')[0] for _id, label in choices[1:]] == ['111000', '119000']


def test_the_cash_bank_fallback_list(app, chart):
    from app.bank_accounts.service import cash_bank_leaf_account_choices
    from app.settings import AppSettings
    AppSettings.set_setting('cash_bank_parent_account_code', 'NO-SUCH-CODE')
    codes = [label.split(' ')[0] for _id, label in cash_bank_leaf_account_choices()]
    assert '119000' in codes and '110000' not in codes


def test_the_reference_pickers_agree(app, chart):
    from app.fixed_assets.services import leaf_accounts_by_type
    from app.opening_balances.utils import opening_account_choices
    from app.posting.control_accounts import get_postable_accounts
    assert [a.code for a in get_postable_accounts()] == ['111000', '119000']
    assert [a.code for a in leaf_accounts_by_type('Asset')] == ['111000', '119000']
    assert {r['code']: r['is_group'] for r in opening_account_choices()} == {
        '110000': True, '111000': False, '119000': False}
