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


def test_leaf_account_not_aggregated(client, db_session, admin_user, main_branch):
    """A postable leaf account drills into its own ledger (aggregated False)."""
    from app import db
    from app.accounts.models import Account
    leaf = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   classification='Current', normal_balance='debit', is_active=True)
    db.session.add(leaf)
    db.session.commit()
    login(client)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/account-ledger?account_id={leaf.id}&start=2026-06-01&end=2026-06-30')
    assert resp.status_code == 200
    assert resp.get_json().get('aggregated') is False


def test_parent_account_aggregates_descendant_leaves(client, db_session, admin_user, main_branch):
    """Clicking a parent GROUP line aggregates the ledgers of all its postable
    descendant leaves into one date-ordered ledger, signed by the parent's
    normal_balance, each line tagged with its child account."""
    from app import db
    from app.accounts.models import Account
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from decimal import Decimal

    parent = Account(code='40100', name='Sales', account_type='Revenue',
                     normal_balance='credit', is_active=True)               # group, no postings
    db.session.add(parent); db.session.commit()
    goods = Account(code='40101', name='Sales - Goods', account_type='Revenue',
                    normal_balance='credit', is_active=True, parent_id=parent.id)
    svc = Account(code='40102', name='Sales - Services', account_type='Revenue',
                  normal_balance='credit', is_active=True, parent_id=parent.id)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   classification='Current', normal_balance='debit', is_active=True)
    db.session.add_all([goods, svc, cash]); db.session.commit()

    def post(num, when, credit_acct, amount):
        amt = Decimal(str(amount))
        je = JournalEntry(entry_number=num, entry_date=when, description='sale',
                          reference=num, entry_type='adjustment', branch_id=main_branch.id,
                          status='posted', is_balanced=True, total_debit=amt, total_credit=amt)
        db.session.add(je); db.session.flush()
        db.session.add_all([
            JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash.id,
                             debit_amount=amt, credit_amount=Decimal('0')),
            JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                             debit_amount=Decimal('0'), credit_amount=amt),
        ])
        db.session.commit()

    post('JE-1', date(2026, 6, 5), goods, 100)
    post('JE-2', date(2026, 6, 10), svc, 60)

    login(client)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/account-ledger?account_id={parent.id}&start=2026-06-01&end=2026-06-30')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['aggregated'] is True
    assert data['account']['code'] == '40100'
    # both children's entries appear, in date order, tagged with their account
    assert len(data['lines']) == 2
    assert data['lines'][0]['account']['code'] == '40101'
    assert data['lines'][1]['account']['code'] == '40102'
    # credit-normal: running balance is credit-positive and accumulates across children
    assert data['lines'][0]['balance'] == 100.0
    assert data['lines'][1]['balance'] == 160.0
    assert data['closing'] == 160.0


def test_account_ledger_credit_normal_signing(client, db_session, admin_user, main_branch):
    """A credit-normal account's balance is signed credit-positive (credit − debit)."""
    from app import db
    from app.accounts.models import Account
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from decimal import Decimal
    rev = Account(code='40101', name='Sales', account_type='Revenue',
                  normal_balance='credit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   classification='Current', normal_balance='debit', is_active=True)
    db.session.add_all([rev, cash]); db.session.commit()
    je = JournalEntry(entry_number='JE-1', entry_date=date(2026, 6, 10), description='sale',
                      reference='JE-1', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', is_balanced=True, total_debit=Decimal('100'),
                      total_credit=Decimal('100'))
    db.session.add(je); db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash.id,
                         debit_amount=Decimal('100'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=rev.id,
                         debit_amount=Decimal('0'), credit_amount=Decimal('100')),
    ])
    db.session.commit()
    login(client)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/account-ledger?account_id={rev.id}&start=2026-06-01&end=2026-06-30')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['lines'][0]['credit'] == 100.0
    assert data['lines'][0]['balance'] == 100.0     # credit-positive, not -100
    assert data['closing'] == 100.0


def test_account_ledger_missing_account_id_returns_400(client, db_session, admin_user, main_branch):
    login(client)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/account-ledger?start=2026-06-01&end=2026-06-30')
    assert resp.status_code == 400


def test_account_ledger_requires_login(client, db_session):
    resp = client.get('/reports/account-ledger?account_id=1&start=2026-06-01&end=2026-06-30')
    assert resp.status_code in (302, 401)
