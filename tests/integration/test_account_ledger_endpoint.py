import pytest
from datetime import date
pytestmark = [pytest.mark.integration]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_account_ledger_json(client, db_session, admin_user, main_branch):
    from app import db
    from app.accounts.models import Account
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from decimal import Decimal
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   classification='Current', normal_balance='debit', is_active=True)
    rev = Account(code='40101', name='Sales', account_type='Revenue', normal_balance='credit', is_active=True)
    db.session.add_all([cash, rev])
    db.session.commit()
    je = JournalEntry(entry_number='JE-1', entry_date=date(2026, 6, 10), description='d',
                      reference='JE-1', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', is_balanced=True, total_debit=Decimal('100'),
                      total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash.id,
                         debit_amount=Decimal('100'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=rev.id,
                         debit_amount=Decimal('0'), credit_amount=Decimal('100')),
    ])
    db.session.commit()
    login(client)
    _select_branch(client, main_branch.id)
    resp = client.get(
        f'/reports/account-ledger?account_id={cash.id}&start=2026-06-01&end=2026-06-30'
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['account']['code'] == '10101'
    assert len(data['lines']) == 1
    assert data['lines'][0]['debit'] == 100.0
    assert data['closing'] == 100.0


def test_account_ledger_requires_login(client, db_session):
    resp = client.get('/reports/account-ledger?account_id=1&start=2026-06-01&end=2026-06-30')
    assert resp.status_code in (302, 401)
