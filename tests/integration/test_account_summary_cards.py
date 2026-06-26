"""COA summary cards split expenses into COGS vs Opex and roll the FS types up
correctly (the single legacy 'Expense'/'Revenue' keys no longer match the rich
account_type values, which made the Expenses card read 0)."""
import re

import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user, main_branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def _card_count(html, key):
    m = re.search(rf'id="count-{re.escape(key)}">\s*(\d+)\s*<', html)
    return int(m.group(1)) if m else None


def _group_and_leaf(db_session, gcode, lcode, acct_type):
    """A non-postable group header + one postable leaf of the given FS type."""
    from app.accounts.models import Account
    g = Account(code=gcode, name=f'{gcode} group', account_type=acct_type,
                normal_balance='debit', is_active=True)
    db_session.add(g)
    db_session.flush()
    leaf = Account(code=lcode, name=f'{lcode} leaf', account_type=acct_type,
                   normal_balance='debit', is_active=True, parent_id=g.id)
    db_session.add(leaf)


def test_summary_category_map():
    from app.accounts.account_types import SUMMARY_CATEGORY
    assert SUMMARY_CATEGORY['Cost of Goods Sold'] == 'COGS'
    assert SUMMARY_CATEGORY['Selling Expense'] == 'Opex'
    assert SUMMARY_CATEGORY['Administrative Expense'] == 'Opex'
    assert SUMMARY_CATEGORY['Other Expense'] == 'Opex'
    assert SUMMARY_CATEGORY['Income Tax Expense'] == 'Opex'
    assert SUMMARY_CATEGORY['Other Income'] == 'Revenue'
    assert SUMMARY_CATEGORY['Contra-Revenue'] == 'Revenue'
    assert SUMMARY_CATEGORY['Asset'] == 'Asset'


def test_cogs_and_opex_cards_count_separately(
        client, db_session, accountant_user, main_branch):
    """One COGS leaf + two Opex leaves (Selling + Admin) -> COGS card = 1, Opex card = 2,
    and the single 'Expenses' card is replaced by the COGS/Opex pair."""
    _group_and_leaf(db_session, '50120', '50121', 'Cost of Goods Sold')
    _group_and_leaf(db_session, '50210', '50211', 'Selling Expense')
    _group_and_leaf(db_session, '50220', '50226', 'Administrative Expense')
    db_session.commit()
    _login(client, accountant_user, main_branch, 'accountant123')

    resp = client.get('/accounts/')
    assert resp.status_code == 200
    html = resp.data.decode()

    assert _card_count(html, 'COGS') == 1
    assert _card_count(html, 'Opex') == 2
    # the old single Expenses card is gone (split into COGS + Opex)
    assert 'id="count-Expense"' not in html
    # rows carry the summary category so the tabs split COGS vs Opex
    assert 'data-type="COGS"' in html
    assert 'data-type="Opex"' in html
