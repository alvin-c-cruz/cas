from datetime import date
from decimal import Decimal
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.fixed_assets.services import create_fixed_asset


def _posted_cdv(db_session, main_branch, account):
    vendor = Vendor(code='V-0001', name='Cash Vendor')
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   normal_balance='Debit')
    db_session.add_all([vendor, cash])
    db_session.commit()
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='CDV-2026-01-0001',
                                  cdv_date=date(2026, 1, 9), vendor_id=vendor.id,
                                  vendor_name=vendor.name, cash_account_id=cash.id,
                                  status='posted')
    db_session.add(cdv)
    db_session.flush()
    line = CDVExpenseLine(cdv_id=cdv.id, line_number=1, description='Power Tool',
                          amount=Decimal('9500'), line_total=Decimal('9500'),
                          account_id=account.id)
    db_session.add(line)
    db_session.commit()
    return cdv, line


def test_capitalize_link_shown_for_posted_untagged_cdv_line(client, db_session, accountant_user,
                                                             main_branch, login_user):
    acct = Account(code='17304', name='Tools & Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    cdv, line = _posted_cdv(db_session, main_branch, acct)

    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/cash-disbursements/{cdv.id}')
    assert f'/fixed-assets/tag/cdv/{cdv.id}/{line.id}'.encode() in resp.data


def test_cancel_blocked_when_cdv_line_tagged(client, db_session, accountant_user, main_branch,
                                             login_user):
    cost = Account(code='17304', name='Tools & Equipment', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17305', name='Accum Dep', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60502', name='Dep Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    cdv, line = _posted_cdv(db_session, main_branch, cost)
    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0030', name='Power Tool', category_id=None,
        acquisition_source_type='cdv', acquisition_source_id=cdv.id,
        acquisition_source_line_id=line.id, acquisition_date=date(2026, 1, 9),
        acquisition_cost=Decimal('9500'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
        'cancel_reason': 'testing the guard',
    }, follow_redirects=True)
    db_session.refresh(cdv)
    assert cdv.status == 'posted'
    assert b'FA-0030' in resp.data
