from datetime import date
from decimal import Decimal
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account
from app.fixed_assets.services import create_fixed_asset


def _posted_jv(db_session, main_branch, debit_account, credit_account):
    entry = JournalEntry(entry_number='JV-2026-01-0001', entry_date=date(2026, 1, 12),
                         description='Capitalize self-constructed shelving',
                         branch_id=main_branch.id, status='posted',
                         total_debit=Decimal('30000'), total_credit=Decimal('30000'),
                         is_balanced=True)
    db_session.add(entry)
    db_session.flush()
    debit_line = JournalEntryLine(entry_id=entry.id, line_number=1, account_id=debit_account.id,
                                  description='Shelving', debit_amount=Decimal('30000'),
                                  credit_amount=Decimal('0'))
    credit_line = JournalEntryLine(entry_id=entry.id, line_number=2, account_id=credit_account.id,
                                   description='WIP clearing', debit_amount=Decimal('0'),
                                   credit_amount=Decimal('30000'))
    db_session.add_all([debit_line, credit_line])
    db_session.commit()
    return entry, debit_line, credit_line


def test_capitalize_link_shown_for_posted_debit_line(client, db_session, accountant_user,
                                                      main_branch, login_user):
    """Happy path: a posted JV's debit line gets the capitalize affordance."""
    debit_acct = Account(code='17306', name='Shelving', account_type='Asset',
                         normal_balance='Debit')
    credit_acct = Account(code='19001', name='WIP Clearing', account_type='Asset',
                          normal_balance='Debit')
    db_session.add_all([debit_acct, credit_acct])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv(db_session, main_branch, debit_acct, credit_acct)

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/journal-entries/{entry.id}')
    assert f'/fixed-assets/tag/jv/{entry.id}/{debit_line.id}'.encode() in resp.data


def test_capitalize_link_never_shown_for_credit_line(client, db_session, accountant_user,
                                                      main_branch, login_user):
    """A JV's credit line must never show the capitalize affordance, even though
    the sibling debit line on the SAME posted JV does."""
    debit_acct = Account(code='17306', name='Shelving', account_type='Asset',
                         normal_balance='Debit')
    credit_acct = Account(code='19001', name='WIP Clearing', account_type='Asset',
                          normal_balance='Debit')
    db_session.add_all([debit_acct, credit_acct])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv(db_session, main_branch, debit_acct, credit_acct)

    # Guard against a vacuous negative assertion: the two lines must be distinct rows.
    assert debit_line.id != credit_line.id

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/journal-entries/{entry.id}')
    assert f'/fixed-assets/tag/jv/{entry.id}/{debit_line.id}'.encode() in resp.data
    assert f'/fixed-assets/tag/jv/{entry.id}/{credit_line.id}'.encode() not in resp.data


def test_capitalize_link_hidden_once_tagged(client, db_session, accountant_user, main_branch,
                                            login_user):
    cost = Account(code='17306', name='Shelving', account_type='Asset', normal_balance='Debit')
    credit_acct = Account(code='19001', name='WIP Clearing', account_type='Asset',
                          normal_balance='Debit')
    accum = Account(code='17307', name='Accum Dep', account_type='Asset', normal_balance='Debit')
    exp = Account(code='60503', name='Dep Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, credit_acct, accum, exp])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv(db_session, main_branch, cost, credit_acct)
    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0040', name='Shelving', category_id=None,
        acquisition_source_type='jv', acquisition_source_id=entry.id,
        acquisition_source_line_id=debit_line.id, acquisition_date=date(2026, 1, 12),
        acquisition_cost=Decimal('30000'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/journal-entries/{entry.id}')
    assert f'/fixed-assets/tag/jv/{entry.id}/{debit_line.id}'.encode() not in resp.data
    assert f'/fixed-assets/tag/jv/{entry.id}/{credit_line.id}'.encode() not in resp.data
    assert b'FA-0040' in resp.data


def test_cancel_blocked_when_jv_debit_line_tagged(client, db_session, accountant_user,
                                                   main_branch, login_user):
    cost = Account(code='17306', name='Shelving', account_type='Asset', normal_balance='Debit')
    credit_acct = Account(code='19001', name='WIP Clearing', account_type='Asset',
                          normal_balance='Debit')
    accum = Account(code='17307', name='Accum Dep', account_type='Asset', normal_balance='Debit')
    exp = Account(code='60503', name='Dep Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, credit_acct, accum, exp])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv(db_session, main_branch, cost, credit_acct)
    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0040', name='Shelving', category_id=None,
        acquisition_source_type='jv', acquisition_source_id=entry.id,
        acquisition_source_line_id=debit_line.id, acquisition_date=date(2026, 1, 12),
        acquisition_cost=Decimal('30000'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/journal-entries/{entry.id}/cancel', follow_redirects=True)
    db_session.refresh(entry)
    assert entry.status == 'posted'
    assert b'FA-0040' in resp.data
