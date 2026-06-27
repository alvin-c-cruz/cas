"""Integration tests for the General Journal screen/print/export routes."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _je(branch_id, dr, cr, amount, etype, num):
    e = JournalEntry(entry_number=num, entry_date=date(2026, 6, 10), description=f'{etype} entry',
                     entry_type=etype, branch_id=branch_id, status='posted',
                     total_debit=amount, total_credit=amount, reference=num)
    db.session.add(e); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=e.id, line_number=1, account_id=dr.id,
                                    debit_amount=amount, credit_amount=Decimal('0.00')))
    db.session.add(JournalEntryLine(entry_id=e.id, line_number=2, account_id=cr.id,
                                    debit_amount=Decimal('0.00'), credit_amount=amount))
    db.session.commit(); return e


def test_general_journal_renders_voucher_entries_only(client, db_session, main_branch,
                                                      admin_user, cash_account, revenue_account):
    _je(main_branch.id, cash_account, revenue_account, Decimal('100'), 'adjustment', 'JV-A')
    _je(main_branch.id, cash_account, revenue_account, Decimal('999'), 'purchase', 'JE-P')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-journal?date_from=2026-01-01&date_to=2026-12-31')
    assert resp.status_code == 200
    assert b'adjustment entry' in resp.data and b'999' not in resp.data


def test_general_journal_print_and_export(client, db_session, main_branch,
                                          admin_user, cash_account, revenue_account):
    _je(main_branch.id, cash_account, revenue_account, Decimal('100'), 'adjustment', 'JV-A')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    p = client.get('/reports/general-journal/print?date_from=2026-01-01&date_to=2026-12-31')
    assert p.status_code == 200 and b'GENERAL JOURNAL' in p.data
    x = client.get('/reports/general-journal/export?date_from=2026-01-01&date_to=2026-12-31')
    assert x.status_code == 200
    assert x.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
