"""Regression tests for R-02 Phase 6: the AP detail/view page must show a small badge on
any line carrying a real price/quantity variance, and show NOTHING for a line with no
source snapshot or with matching values (zero variance)."""
from datetime import date
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem


def _seed_accounts():
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense', 'Expense', 'Debit'),
    ]:
        db.session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db.session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    return Account.query.filter_by(code='69903').first()


def _login_and_select_branch(client, user, branch):
    client.post('/login', data={'username': user.username, 'password': 'accountant123'},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _ap_with_line(db_session, branch, vendor, exp_account, **item_kwargs):
    ap = AccountsPayable(branch_id=branch.id, ap_number='AP-BADGE-0001',
                         ap_date=date(2026, 7, 18), due_date=date(2026, 8, 17),
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, payment_terms='Net 30', status='draft')
    defaults = dict(line_number=1, description='Test line', amount=Decimal('1000.00'),
                    account_id=exp_account.id)
    defaults.update(item_kwargs)
    ap.line_items.append(AccountsPayableItem(**defaults))
    db_session.add(ap); db_session.commit()
    return ap


def test_detail_shows_badge_when_price_varies(client, accountant_user, db_session, main_branch, vl_vendor):
    exp = _seed_accounts()
    ap = _ap_with_line(db_session, main_branch, vl_vendor, exp,
                       unit_price=Decimal('120.00'), quantity=Decimal('10'),
                       source_po_item_id=999, matched_unit_price=Decimal('100.00'),
                       matched_quantity=Decimal('10'))
    _login_and_select_branch(client, accountant_user, main_branch)
    resp = client.get(f'/accounts-payable/{ap.id}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Ordered @' in body and '120.00' in body and '100.00' in body


def test_detail_shows_no_badge_when_values_match(client, accountant_user, db_session, main_branch, vl_vendor):
    exp = _seed_accounts()
    ap = _ap_with_line(db_session, main_branch, vl_vendor, exp,
                       unit_price=Decimal('100.00'), quantity=Decimal('10'),
                       source_po_item_id=999, matched_unit_price=Decimal('100.00'),
                       matched_quantity=Decimal('10'))
    _login_and_select_branch(client, accountant_user, main_branch)
    resp = client.get(f'/accounts-payable/{ap.id}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Ordered @' not in body


def test_detail_shows_no_badge_for_manual_line(client, accountant_user, db_session, main_branch, vl_vendor):
    exp = _seed_accounts()
    ap = _ap_with_line(db_session, main_branch, vl_vendor, exp,
                       unit_price=Decimal('100.00'), quantity=Decimal('10'))  # no source_*_item_id
    _login_and_select_branch(client, accountant_user, main_branch)
    resp = client.get(f'/accounts-payable/{ap.id}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Ordered @' not in body
