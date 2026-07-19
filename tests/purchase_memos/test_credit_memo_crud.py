"""Vendor Credit Memo: register CRUD + AP-line picker + module gating + lifecycle
(post/void) -- mirrors tests/purchase_memos/test_crud_gating.py's Vendor Debit
Memo suite, adapted for the buy-side mirror of the sales Debit Note.

Because a Vendor Credit Memo INCREASES the referenced AP bill's balance (unlike
the debit memo, which reduces it -- see app/purchase_memos/je.py's module
docstring), the lifecycle assertions here check the bill's total_amount/balance
going UP, not down."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.purchase_memos.models import PurchaseMemo
from app.purchase_memos import service
from app.settings import AppSettings

from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration, pytest.mark.purchase_memos]


@pytest.fixture(autouse=True)
def _module_cache_isolation():
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


def _enable(*keys):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db.session.commit(); clear_module_config_cache()


def _setup(client, admin_user, main_branch, enable=True, bill_amount='1120', wt_rate=None):
    coa = {}
    for k, args in {
        'ap': ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        'wt': ('20301', 'Withholding Tax Payable', 'Liability', 'Credit'),
        'invat': ('10213', 'Input VAT', 'Asset', 'Debit'),
        'vc': ('20302', 'Vendor Credits', 'Liability', 'Credit'),
        'exp': ('50101', 'Purchases', 'Expense', 'Debit'),
        'cash': ('10110', 'Cash in Bank', 'Asset', 'Debit'),
    }.items():
        coa[k] = _acct(*args)
    db.session.commit()
    vat = VATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                      input_vat_account_id=coa['invat'].id, is_active=True)
    db.session.add(vat); db.session.commit()
    assign_control_accounts(db.session)   # default ap='20101', wht_payable='20301'
    AppSettings.set_setting(service.VENDOR_CREDITS_KEY, '20302')
    db.session.commit()
    if enable:
        _enable('vendor_credit_memos')

    v = Vendor(code='PMV2', name='Acme Supplier', tin='123-456-789-000', is_active=True)
    db.session.add(v); db.session.commit()
    amount = Decimal(bill_amount)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-PMC-1',
                         ap_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                         payee_type='vendor', payee_id=v.id, vendor_id=v.id,
                         vendor_name=v.name, vendor_tin=v.tin, status='posted',
                         subtotal=amount, total_amount=amount, balance=amount)
    li = AccountsPayableItem(line_number=1, description='Goods purchased', amount=amount,
                             vat_category='V12', vat_rate=Decimal('12'), account_id=coa['exp'].id,
                             wt_rate=(Decimal(str(wt_rate)) if wt_rate is not None else None))
    li.calculate_amounts(); ap.line_items.append(li)
    db.session.add(ap); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return ap, li


def _create_memo(client, ap, li, amount='560', destination='ap'):
    return client.post('/vendor-credit-memos/create', data={
        'accounts_payable_id': ap.id, 'memo_date': '2026-07-10',
        'reason': 'Freight surcharge billed after the fact', 'destination': destination,
        'lines': json.dumps([{'accounts_payable_item_id': li.id, 'amount': amount}]),
    }, follow_redirects=True)


# -- (a) module gating: every route 404s when the module is off, independently
# of vendor_debit_memos's own gate -------------------------------------------

def test_credit_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/vendor-credit-memos').status_code == 404


def test_credit_create_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/vendor-credit-memos/create').status_code == 404


def test_credit_ap_lines_blocked_when_module_off(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch, enable=False)
    assert client.get(f'/vendor-credit-memos/ap-lines/{ap.id}').status_code == 404


def test_credit_view_blocked_when_module_off(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch, enable=True)
    _create_memo(client, ap, li)
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    AppSettings.set_setting('module_enabled:vendor_credit_memos', '0')
    from app.utils.cache_helpers import clear_module_config_cache
    db.session.commit(); clear_module_config_cache()
    assert client.get(f'/vendor-credit-memos/{memo.id}').status_code == 404
    assert client.get(f'/vendor-credit-memos/{memo.id}/print').status_code == 404
    assert client.post(f'/vendor-credit-memos/{memo.id}/post').status_code == 404
    assert client.post(f'/vendor-credit-memos/{memo.id}/void',
                       data={'void_reason': 'irrelevant test reason'}).status_code == 404


def test_registry_entry(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'vendor_credit_memos')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == []
    assert e['area'] == 'Purchases'
    assert 'purchase_memos.credit_' in e['endpoints']
    assert 'vendor_credit_memos' in all_permission_keys()


def test_credit_memos_independent_of_debit_memos_gate(client, db_session, admin_user, main_branch):
    """vendor_credit_memos and vendor_debit_memos gate independently -- enabling
    ONLY vendor_credit_memos lets credit routes through while debit routes stay 404."""
    ap, li = _setup(client, admin_user, main_branch, enable=True)
    assert client.get('/vendor-credit-memos').status_code == 200
    assert client.get('/vendor-debit-memos').status_code == 404


def test_settings_accessible_with_only_credit_memos_enabled(client, db_session, admin_user, main_branch):
    """The shared settings page (assigns vendor_credits) must be reachable even
    when vendor_debit_memos is OFF and only vendor_credit_memos is on -- this is
    exactly the gap fixed by ungating settings in Task 1."""
    _setup(client, admin_user, main_branch, enable=True)
    assert client.get('/purchase-memos/settings').status_code == 200


# -- (b) draft-create against a POSTED AP persists with computed totals ----------

def test_ap_lines_endpoint_returns_bill_lines(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    resp = client.get(f'/vendor-credit-memos/ap-lines/{ap.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['vendor_name'] == 'Acme Supplier'
    assert len(data['lines']) == 1
    assert data['lines'][0]['debitable'] == 1120.0
    assert data['lines'][0]['accounts_payable_item_id'] == li.id


def test_create_persists_draft_with_computed_totals(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    resp = _create_memo(client, ap, li, amount='560')
    assert resp.status_code == 200
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    assert memo is not None and memo.status == 'draft'
    assert memo.memo_number.startswith('VCM-')
    assert memo.original_ap_number == 'AP-PMC-1'
    assert memo.vendor_name == 'Acme Supplier'
    assert len(memo.line_items) == 1
    line = memo.line_items[0]
    assert line.accounts_payable_item_id == li.id
    assert line.account_id == li.account_id
    assert line.vat_category == 'V12'
    assert line.amount == Decimal('560.00')
    assert line.vat_amount == Decimal('60.00')          # 560 - 560/1.12
    assert memo.subtotal == Decimal('560.00')
    assert memo.total_amount == Decimal('560.00')
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='purchase_memos', action='create').first() is not None


# -- (c) a line amount exceeding the referenced AP line is rejected --------------

def test_create_rejects_over_limit_line(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='2000')   # > 1120 bill line
    assert PurchaseMemo.query.filter_by(memo_type='credit').first() is None


# -- (d) credit_post (accountant+) builds the JE + flips status; staff denied ----

def test_post_accountant_flips_status_builds_je_and_increases_ap_balance(
        client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    resp = client.post(f'/vendor-credit-memos/{memo.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'posted'
    assert memo.journal_entry_id is not None and memo.journal_entry.status == 'posted'
    assert bill.total_amount == Decimal('1680.00')      # 1120 + 560
    assert bill.balance == Decimal('1680.00')            # unpaid, so balance == total
    assert bill.status == 'posted'
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='purchase_memos', action='post').first() is not None


def test_post_denied_for_staff(client, db_session, admin_user, staff_user, main_branch):
    from app.purchase_memos.models import PurchaseMemoItem, generate_purchase_memo_number
    ap, li = _setup(client, admin_user, main_branch)
    memo = PurchaseMemo(
        memo_type='credit', memo_number=generate_purchase_memo_number('credit'),
        memo_date=date(2026, 7, 10), branch_id=main_branch.id,
        accounts_payable_id=ap.id, original_ap_number=ap.ap_number,
        vendor_id=ap.vendor_id, vendor_name=ap.vendor_name, vendor_tin=ap.vendor_tin,
        reason='Freight surcharge', destination='ap', status='draft')
    mline = PurchaseMemoItem(line_number=1, accounts_payable_item_id=li.id,
                             amount=Decimal('560'), vat_category='V12',
                             vat_rate=Decimal('12'), account_id=li.account_id)
    mline.calculate_amounts(); memo.line_items.append(mline); memo.calculate_totals()
    db.session.add(memo); db.session.commit()
    mid = memo.id

    staff_user.set_book_permissions(dict(staff_user.get_book_permissions(),
                                         vendor_credit_memos=True))
    db.session.commit()
    _login(client, staff_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.post(f'/vendor-credit-memos/{mid}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, mid)
    assert memo.status == 'draft'
    assert memo.journal_entry_id is None


def test_post_blocked_when_memo_date_in_closed_period(client, db_session, admin_user, main_branch):
    from app.periods.models import AccountingPeriod
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    db.session.add(AccountingPeriod(year=2026, month=7, status='closed'))
    db.session.commit()
    resp = client.post(f'/vendor-credit-memos/{memo.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'draft', 'a memo dated in a closed period must not post'
    assert memo.journal_entry_id is None
    assert bill.total_amount == Decimal('1120.00')       # bill untouched


# -- (e) credit_void on a posted memo reverses the AP-balance increase (period-gated) --

def test_void_reverses_ap_balance_and_je(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    client.post(f'/vendor-credit-memos/{memo.id}/post', follow_redirects=True)
    resp = client.post(f'/vendor-credit-memos/{memo.id}/void',
                       data={'void_reason': 'Wrong bill picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'voided'
    assert bill.total_amount == Decimal('1120.00') and bill.balance == Decimal('1120.00')
    assert bill.status == 'posted'
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference=memo.memo_number,
                                        entry_type='reversal').first() is not None
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='purchase_memos', action='void').first() is not None


def test_void_blocked_when_current_period_closed(client, db_session, admin_user, main_branch):
    from app.periods.models import AccountingPeriod
    from app.utils import ph_now
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    client.post(f'/vendor-credit-memos/{memo.id}/post', follow_redirects=True)
    now = ph_now()
    db.session.add(AccountingPeriod(year=now.year, month=now.month, status='closed'))
    db.session.commit()
    resp = client.post(f'/vendor-credit-memos/{memo.id}/void',
                       data={'void_reason': 'Wrong bill picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'posted', 'void must be blocked while the current period is closed'
    assert bill.total_amount == Decimal('1680.00'), 'bill unchanged (no reversal happened)'


def test_void_requires_reason(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    client.post(f'/vendor-credit-memos/{memo.id}/post', follow_redirects=True)
    resp = client.post(f'/vendor-credit-memos/{memo.id}/void',
                       data={'void_reason': 'short'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    assert memo.status == 'posted'


# -- (f) employee-payee AP bills are excluded past the picker --------------------

def test_employee_payee_ap_excluded_from_picker_and_rejected(
        client, db_session, admin_user, main_branch):
    from app.employees.models import Employee
    ap, li = _setup(client, admin_user, main_branch)
    emp = Employee(employee_no='EMP-0002', first_name='Alvin', last_name='Cruz',
                   branch_id=main_branch.id)
    db.session.add(emp); db.session.commit()
    eap = AccountsPayable(
        branch_id=main_branch.id, ap_number='AP-EMP-2',
        ap_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
        payee_type='employee', payee_id=emp.id, vendor_id=None,
        vendor_name=emp.full_name, status='posted',
        subtotal=Decimal('1000'), total_amount=Decimal('1000'), balance=Decimal('1000'))
    eli = AccountsPayableItem(line_number=1, description='Reimbursement',
                              amount=Decimal('1000'), vat_rate=Decimal('0'),
                              account_id=li.account_id)
    eli.calculate_amounts(); eap.line_items.append(eli)
    db.session.add(eap); db.session.commit()
    eap_id, eli_id = eap.id, eli.id

    resp = client.get('/vendor-credit-memos/create')
    assert resp.status_code == 200
    assert b'AP-EMP-2' not in resp.data

    resp = client.post('/vendor-credit-memos/create', data={
        'accounts_payable_id': eap_id, 'memo_date': '2026-07-10',
        'reason': 'Tampered target bill', 'destination': 'ap',
        'lines': json.dumps([{'accounts_payable_item_id': eli_id, 'amount': '1000'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert PurchaseMemo.query.filter_by(original_ap_number='AP-EMP-2').first() is None
    assert b'can only reference a vendor bill, not an employee bill' in resp.data
    assert b'An error occurred' not in resp.data

    resp = client.get(f'/vendor-credit-memos/ap-lines/{eap_id}')
    assert resp.status_code == 404
    assert resp.get_json()['error'] == (
        'A Vendor Credit Memo can only reference a vendor bill, not an employee bill.')


# -- views: list / detail / print + destination-label copy ----------------------

def test_credit_list_shows_enter_button(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/vendor-credit-memos')
    assert resp.status_code == 200
    assert b'+ Enter Vendor Credit Memo' in resp.data


def test_credit_create_form_renders_single_lines_field_and_increase_wording(
        client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/vendor-credit-memos/create')
    assert resp.status_code == 200
    assert resp.data.count(b'name="lines"') == 1
    assert b'Enter Vendor Credit Memo' in resp.data
    assert b'Lines to credit' in resp.data
    assert b'Credit amount' in resp.data
    assert b'increase Accounts Payable' in resp.data
    assert b'reduce Accounts Payable' not in resp.data


def test_detail_renders_post_and_void_for_draft(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    resp = client.get(f'/vendor-credit-memos/{memo.id}')
    assert resp.status_code == 200
    assert f'/vendor-credit-memos/{memo.id}/post'.encode() in resp.data
    assert b'Void Vendor Credit Memo' in resp.data


def test_credit_print_renders(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='credit').first()
    resp = client.get(f'/vendor-credit-memos/{memo.id}/print')
    assert resp.status_code == 200
    assert b'VENDOR CREDIT MEMO' in resp.data


# -- sidebar visibility: module on/off -----------------------------------------

def test_sidebar_shows_vendor_credit_memos_link_when_enabled(client, db_session,
                                                              admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=True)
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    assert b'Vendor Credit Memos' in resp.data
    assert b'/vendor-credit-memos' in resp.data


def test_sidebar_hides_vendor_credit_memos_link_when_disabled(client, db_session,
                                                               admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    assert b'Vendor Credit Memos' not in resp.data
    assert b'/vendor-credit-memos' not in resp.data
