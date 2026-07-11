"""Integration tests: JV print_entry route honors the jv_print_form setting
(current/preprinted/hidden), and the full-access-gated layout-save route.
"""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.journal_entries]


def _login(client, u, p):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def _posted_jv(db_session, main_branch, admin_user):
    """Minimal posted JournalEntry with two balanced lines for print rendering."""
    from decimal import Decimal
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.accounts.models import Account
    from app.utils import ph_now
    dr = Account.query.filter_by(code='60101').first() or Account(
        code='60101', name='Test Expense', account_type='Expense',
        normal_balance='Debit', is_active=True)
    cr = Account.query.filter_by(code='10101').first() or Account(
        code='10101', name='Test Cash on Hand', account_type='Asset',
        normal_balance='Debit', is_active=True)
    db_session.add_all([dr, cr]); db_session.flush()
    je = JournalEntry(
        entry_number=generate_entry_number(main_branch.id), entry_date=ph_now().date(),
        description='Test JV', reference='JV-TEST', entry_type='adjustment',
        branch_id=main_branch.id, created_by_id=admin_user.id, status='posted',
        posted_by_id=admin_user.id, posted_at=ph_now(), is_balanced=True,
        total_debit=Decimal('100.00'), total_credit=Decimal('100.00'))
    db_session.add(je); db_session.flush()
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=dr.id,
        description='dr', debit_amount=Decimal('100.00'), credit_amount=Decimal('0.00')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=cr.id,
        description='cr', debit_amount=Decimal('0.00'), credit_amount=Decimal('100.00')))
    db_session.commit()
    return je


def test_print_current_renders_standard_form(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('jv_print_form', 'current')
    entry = _posted_jv(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/journal-entries/{entry.id}/print')
    assert resp.status_code == 200
    assert b'pp-canvas' not in resp.data  # not the pre-printed canvas


def test_print_preprinted_renders_overlay(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('jv_print_form', 'preprinted')
    entry = _posted_jv(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/journal-entries/{entry.id}/print')
    assert resp.status_code == 200
    assert b'pp-canvas' in resp.data  # the pre-printed canvas element


def test_print_hidden_is_refused(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('jv_print_form', 'hidden')
    entry = _posted_jv(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/journal-entries/{entry.id}/print', follow_redirects=False)
    assert resp.status_code in (302, 403)  # refused (mirror print_ap's hidden handling)


def test_save_layout_requires_full_access(client, db_session, admin_user, staff_user, main_branch):
    staff_user.set_branches([main_branch]); db_session.commit()
    _login(client, 'staff', 'staff123')
    resp = client.post('/journal-entries/print-layout', json={'paper': 'letter'})
    assert resp.status_code == 403


def test_save_layout_persists_for_admin(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.post('/journal-entries/print-layout', json={'paper': 'letter'})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
