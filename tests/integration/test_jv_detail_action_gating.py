"""The JV detail Post/Cancel forms were gated only by entry.status, so a staff/viewer
who can view a draft saw buttons the server rejects. Gate them by role too — mirror
the server's accountant_or_admin_required. BUG-JV-DETAIL-ACTION-BTNS-UNGATED."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account

pytestmark = [pytest.mark.integration]


def _draft_jv(branch):
    a1 = Account(code='10101', name='Cash on Hand', account_type='Asset',
                 normal_balance='Debit', is_active=True)
    a2 = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                 normal_balance='Debit', is_active=True)
    db.session.add_all([a1, a2]); db.session.commit()
    e = JournalEntry(entry_number='JV-2026-07-0001', entry_date=date(2026, 7, 8),
                     description='Test', entry_type='adjustment', branch_id=branch.id,
                     total_debit=Decimal('5000.00'), total_credit=Decimal('5000.00'),
                     is_balanced=True, status='draft')
    db.session.add(e); db.session.commit()
    db.session.add_all([
        JournalEntryLine(entry_id=e.id, line_number=1, account_id=a1.id,
                         debit_amount=Decimal('5000.00'), credit_amount=Decimal('0.00')),
        JournalEntryLine(entry_id=e.id, line_number=2, account_id=a2.id,
                         debit_amount=Decimal('0.00'), credit_amount=Decimal('5000.00')),
    ]); db.session.commit()
    return e


def _get_detail(client, branch, username, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    e = _draft_jv(branch)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    return e, client.get(f'/journal-entries/{e.id}').get_data(as_text=True)


def test_manager_sees_action_buttons(client, db_session, accountant_user, main_branch):
    accountant_user.set_branches([main_branch]); db.session.commit()
    e, html = _get_detail(client, main_branch, 'accountant', 'accountant123')
    assert f'/journal-entries/{e.id}/post' in html
    assert f'/journal-entries/{e.id}/cancel' in html


def test_admin_sees_action_buttons(client, db_session, admin_user, main_branch):
    e, html = _get_detail(client, main_branch, 'admin', 'admin123')
    assert f'/journal-entries/{e.id}/post' in html
    assert f'/journal-entries/{e.id}/cancel' in html


def test_staff_does_not_see_action_buttons(client, db_session, staff_user, main_branch):
    staff_user.set_branches([main_branch]); db.session.commit()
    e, html = _get_detail(client, main_branch, 'staff', 'staff123')
    assert f'/journal-entries/{e.id}/post' not in html
    assert f'/journal-entries/{e.id}/cancel' not in html


def test_viewer_does_not_see_action_buttons(client, db_session, viewer_user, main_branch):
    viewer_user.set_branches([main_branch]); db.session.commit()
    e, html = _get_detail(client, main_branch, 'viewer', 'viewer123')
    assert f'/journal-entries/{e.id}/post' not in html
    assert f'/journal-entries/{e.id}/cancel' not in html
