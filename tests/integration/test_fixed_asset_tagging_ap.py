from datetime import date
from decimal import Decimal
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.accounts.models import Account
from app.fixed_assets.services import create_fixed_asset


def _posted_ap(db_session, main_branch, account):
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-2026-01-0005',
                         ap_date=date(2026, 1, 8), due_date=date(2026, 2, 8),
                         vendor_name='Vendor Y', status='posted')
    db_session.add(ap)
    db_session.flush()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Server',
                               amount=Decimal('120000'), line_total=Decimal('120000'),
                               account_id=account.id)
    db_session.add(item)
    db_session.commit()
    return ap, item


def test_capitalize_link_shown_for_posted_untagged_line(client, db_session, accountant_user,
                                                          main_branch, login_user):
    # normal_balance is NOT NULL on Account -- the brief's fixture omitted it.
    acct = Account(code='17301', name='IT Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    ap, item = _posted_ap(db_session, main_branch, acct)

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/accounts-payable/{ap.id}')
    assert f'/fixed-assets/tag/ap_bill/{ap.id}/{item.id}'.encode() in resp.data


def test_capitalize_link_hidden_once_tagged(client, db_session, accountant_user, main_branch,
                                            login_user):
    cost = Account(code='17301', name='IT Equipment', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17302', name='Accum Dep', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60501', name='Dep Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    ap, item = _posted_ap(db_session, main_branch, cost)
    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0020', name='Server', category_id=None,
        acquisition_source_type='ap_bill', acquisition_source_id=ap.id,
        acquisition_source_line_id=item.id, acquisition_date=date(2026, 1, 8),
        acquisition_cost=Decimal('120000'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/accounts-payable/{ap.id}')
    assert f'/fixed-assets/tag/ap_bill/{ap.id}/{item.id}'.encode() not in resp.data
    assert b'FA-0020' in resp.data


def test_cancel_blocked_when_line_tagged(client, db_session, accountant_user, main_branch,
                                         login_user):
    cost = Account(code='17301', name='IT Equipment', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17302', name='Accum Dep', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60501', name='Dep Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    ap, item = _posted_ap(db_session, main_branch, cost)
    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0021', name='Server', category_id=None,
        acquisition_source_type='ap_bill', acquisition_source_id=ap.id,
        acquisition_source_line_id=item.id, acquisition_date=date(2026, 1, 8),
        acquisition_cost=Decimal('120000'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/accounts-payable/{ap.id}/cancel', data={
        'cancel_reason': 'testing the guard', 'reversal_date': '2026-01-08',
    }, follow_redirects=True)
    db_session.refresh(ap)
    assert ap.status == 'posted'  # unchanged
    assert b'FA-0021' in resp.data
