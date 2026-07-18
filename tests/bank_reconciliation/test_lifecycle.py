"""End-to-end reconciliation lifecycle (R-04 slice 3)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:bank_reconciliation', '1')
    AppSettings.set_setting('module_enabled:bank_accounts', '1')
    db_session.commit(); clear_module_config_cache()


def _grant_staff(staff_user, branch, db_session):
    staff_user.set_book_permissions({**staff_user.get_book_permissions(), 'bank_reconciliation': True})
    staff_user.set_branches([branch])
    db_session.commit()


def test_staff_cannot_reach_reconciliation(client, staff_user, db_session, main_branch, cash_account):
    _enable(db_session)
    _grant_staff(staff_user, main_branch, db_session)
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=main_branch.id, code='BA-AUTHZ', name='Authz',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.get(f'/bank-reconciliation/{ba.id}/register', follow_redirects=True)
    assert b'permission' in resp.data.lower() or resp.status_code in (302, 403)


def test_full_reconciliation_round_trip(client, admin_user, db_session, main_branch, cash_account,
                                        revenue_account):
    _enable(db_session)
    from app.bank_accounts.models import BankAccount
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    ba = BankAccount(branch_id=main_branch.id, code='BA-RT', name='RoundTrip',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()

    je = JournalEntry(entry_number='JE-RT-0001', entry_date=date(2026, 6, 15),
                      description='Deposit', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', total_debit=Decimal('1000.00'), total_credit=Decimal('1000.00'),
                      is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=cash_account.id,
                                     debit_amount=Decimal('1000.00'), credit_amount=0))
    db_session.add(je); db_session.commit()
    line_id = je.lines[0].id

    _login(client, admin_user, main_branch)

    # create a new draft reconciliation
    resp = client.post(f'/bank-reconciliation/{ba.id}/new', data={
        'statement_date': '2026-06-30', 'statement_ending_balance': '1000.00',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.bank_reconciliation.models import BankReconciliation
    rec = BankReconciliation.query.filter_by(bank_account_id=ba.id).first()
    assert rec is not None
    assert rec.beginning_balance == Decimal('0.00')   # first rec for this account -> BankAccount.opening_balance

    # work page reachable, then complete with the deposit line ticked
    resp = client.get(f'/bank-reconciliation/{rec.id}/work')
    assert resp.status_code == 200
    assert str(line_id).encode() in resp.data

    resp = client.post(f'/bank-reconciliation/{rec.id}/complete', data={
        'row_version': str(rec.row_version), 'ticked_line_ids': str(line_id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(rec)
    assert rec.status == 'completed'
    assert rec.adjusted_balance == Decimal('1000.00')

    # detail renders from the frozen snapshot
    resp = client.get(f'/bank-reconciliation/{rec.id}')
    assert resp.status_code == 200
    assert b'1,000.00' in resp.data or b'1000.00' in resp.data
