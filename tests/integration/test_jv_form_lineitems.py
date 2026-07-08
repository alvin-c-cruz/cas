"""JV entry-form line-item parity: search-select account + money fields.

The interactive behaviour (Choices dropdown, comma formatting, full-label chip) is
browser-verified; these assertions pin the server+template contract that enables it.
"""
import pytest
from app import db
from app.accounts.models import Account

pytestmark = pytest.mark.journal_entries


def _seed_coa():
    # A parent (has a child) + two leaves, so is_group derivation is exercised.
    parent = Account(code='10100', name='Cash and Cash Equivalents', account_type='Asset',
                     normal_balance='Debit', is_active=True)
    db.session.add(parent); db.session.commit()
    child = Account(code='10101', name='Cash on Hand', account_type='Asset',
                    normal_balance='Debit', is_active=True, parent_id=parent.id)
    leaf = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                   normal_balance='Debit', is_active=True)
    db.session.add_all([child, leaf]); db.session.commit()
    return parent, child, leaf


def test_create_form_accounts_carry_is_group_and_choices_wired(client, admin_user, main_branch, login_user):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    _seed_coa()
    html = client.get('/journal-entries/create').get_data(as_text=True)
    # accounts JSON feeds the picker and carries the derived is_group flag
    assert '"is_group"' in html
    # search-select + money helpers are loaded
    assert 'choices.min.js' in html
    assert 'jvAmtBlur' in html and 'jvAmtFocus' in html
    # money fields are text inputs (not type=number) so comma formatting works
    assert 'class="line-debit"' in html


def test_accounts_for_select_derives_is_group(client, admin_user, main_branch, login_user, app):
    from app.journal_entries.views import _accounts_for_select
    parent, child, leaf = _seed_coa()
    with app.test_request_context():
        rows = {a['code']: a for a in _accounts_for_select()}
    assert rows['10100']['is_group'] is True     # has a child -> group header
    assert rows['10101']['is_group'] is False    # leaf -> postable
    assert rows['10201']['is_group'] is False
