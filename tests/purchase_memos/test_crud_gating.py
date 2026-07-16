"""Vendor Debit Memo: register CRUD + AP-line picker + module gating + lifecycle
(post/void) -- Task 4. Mirrors tests/integration/test_debit_note_flow.py +
test_credit_memo_lifecycle.py + test_sales_memos_gate.py, buy-side field names.

Because a Vendor Debit Memo REDUCES the referenced AP bill's balance (like the
sales-side CREDIT memo reduces AR -- see app/purchase_memos/je.py's module
docstring), the lifecycle assertions here mirror test_credit_memo_lifecycle.py's
'ap'-destination post/void pair, not the sales debit-note (which is its own
receivable and never touches the referenced SI)."""
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


def _setup(client, admin_user, main_branch, enable=True, bill_amount='1120'):
    coa = {}
    for k, args in {
        'ap': ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        'wt': ('20301', 'Withholding Tax Payable', 'Liability', 'Credit'),
        'invat': ('10213', 'Input VAT', 'Asset', 'Debit'),
        'pr': ('50103', 'Purchase Returns and Allowances', 'Expense', 'Credit'),
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
    AppSettings.set_setting(service.PURCHASE_RETURNS_KEY, '50103')
    AppSettings.set_setting(service.VENDOR_CREDITS_KEY, '20302')
    db.session.commit()
    if enable:
        _enable('vendor_debit_memos')

    v = Vendor(code='PMV1', name='Acme Supplier', tin='123-456-789-000', is_active=True)
    db.session.add(v); db.session.commit()
    amount = Decimal(bill_amount)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-PM-1',
                         ap_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                         payee_type='vendor', payee_id=v.id, vendor_id=v.id,
                         vendor_name=v.name, vendor_tin=v.tin, status='posted',
                         subtotal=amount, total_amount=amount, balance=amount)
    li = AccountsPayableItem(line_number=1, description='Goods purchased', amount=amount,
                             vat_category='V12', vat_rate=Decimal('12'), account_id=coa['exp'].id)
    li.calculate_amounts(); ap.line_items.append(li)
    db.session.add(ap); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return ap, li


def _create_memo(client, ap, li, amount='560', destination='ap'):
    return client.post('/vendor-debit-memos/create', data={
        'accounts_payable_id': ap.id, 'memo_date': '2026-07-10',
        'reason': 'Returned defective goods', 'destination': destination,
        'lines': json.dumps([{'accounts_payable_item_id': li.id, 'amount': amount}]),
    }, follow_redirects=True)


# -- (a) module gating: every route 404s when the module is off ------------------

def test_debit_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/vendor-debit-memos').status_code == 404


def test_debit_create_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/vendor-debit-memos/create').status_code == 404


def test_debit_ap_lines_blocked_when_module_off(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch, enable=False)
    assert client.get(f'/vendor-debit-memos/ap-lines/{ap.id}').status_code == 404


def test_debit_view_blocked_when_module_off(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch, enable=True)
    _create_memo(client, ap, li)
    memo = PurchaseMemo.query.first()
    AppSettings.set_setting('module_enabled:vendor_debit_memos', '0')
    from app.utils.cache_helpers import clear_module_config_cache
    db.session.commit(); clear_module_config_cache()
    assert client.get(f'/vendor-debit-memos/{memo.id}').status_code == 404
    assert client.get(f'/vendor-debit-memos/{memo.id}/print').status_code == 404
    assert client.post(f'/vendor-debit-memos/{memo.id}/post').status_code == 404
    assert client.post(f'/vendor-debit-memos/{memo.id}/void',
                       data={'void_reason': 'irrelevant test reason'}).status_code == 404


def test_settings_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/purchase-memos/settings').status_code == 404
    assert client.post('/purchase-memos/settings/accounts', data={}).status_code == 404


def test_registry_entry(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'vendor_debit_memos')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == []
    assert e['area'] == 'Purchases'
    assert 'purchase_memos.debit_' in e['endpoints']
    assert 'vendor_debit_memos' in all_permission_keys()


# -- (b) draft-create against a POSTED AP persists with computed totals ----------

def test_ap_lines_endpoint_returns_bill_lines(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    resp = client.get(f'/vendor-debit-memos/ap-lines/{ap.id}')
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
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    assert memo is not None and memo.status == 'draft'
    assert memo.memo_number.startswith('VDM-')
    assert memo.original_ap_number == 'AP-PM-1'
    assert memo.vendor_name == 'Acme Supplier'
    assert len(memo.line_items) == 1
    line = memo.line_items[0]
    assert line.accounts_payable_item_id == li.id
    assert line.account_id == li.account_id           # snapshot
    assert line.vat_category == 'V12'                  # snapshot
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
    assert PurchaseMemo.query.filter_by(memo_type='debit').first() is None


# -- (d) debit_post (accountant+) builds the JE + flips status; staff denied ------

def test_post_accountant_flips_status_builds_je_and_reduces_ap_balance(
        client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    resp = client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'posted'
    assert memo.journal_entry_id is not None and memo.journal_entry.status == 'posted'
    assert bill.balance == Decimal('560.00')            # 1120 - 560, reduced ONCE
    assert bill.status == 'partially_paid'
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='purchase_memos', action='post').first() is not None


def test_post_denied_for_staff(client, db_session, admin_user, staff_user, main_branch):
    """Staff cannot post, even with the module granted. Built via ORM (not the
    client) and logged in ONCE (as staff): Flask-Login caches the authenticated
    user on `g`, which is bound to the app context `db_session` keeps pushed for
    the whole test function -- so a mid-test client relogin would never actually
    re-invoke the user_loader and would silently keep testing as the FIRST user.
    See tests/purchase_memos/test_crud_gating.py module note."""
    from app.purchase_memos.models import PurchaseMemoItem, generate_purchase_memo_number
    ap, li = _setup(client, admin_user, main_branch)
    memo = PurchaseMemo(
        memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
        memo_date=date(2026, 7, 10), branch_id=main_branch.id,
        accounts_payable_id=ap.id, original_ap_number=ap.ap_number,
        vendor_id=ap.vendor_id, vendor_name=ap.vendor_name, vendor_tin=ap.vendor_tin,
        reason='Returned defective goods', destination='ap', status='draft')
    mline = PurchaseMemoItem(line_number=1, accounts_payable_item_id=li.id,
                             amount=Decimal('560'), vat_category='V12',
                             vat_rate=Decimal('12'), account_id=li.account_id)
    mline.calculate_amounts(); memo.line_items.append(mline); memo.calculate_totals()
    db.session.add(memo); db.session.commit()
    mid = memo.id

    # Grant staff the module (per_user) so the gate lets them reach the route --
    # isolates the role check inside debit_post from the module gate.
    staff_user.set_book_permissions(dict(staff_user.get_book_permissions(),
                                         vendor_debit_memos=True))
    db.session.commit()
    _login(client, staff_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.post(f'/vendor-debit-memos/{mid}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, mid)
    assert memo.status == 'draft'                        # blocked, unchanged
    assert memo.journal_entry_id is None


def test_cannot_post_twice(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)   # 2nd attempt
    bill = db.session.get(AccountsPayable, sid)
    assert bill.balance == Decimal('560.00')             # not reduced twice
    from app.journal_entries.models import JournalEntry
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    assert JournalEntry.query.filter_by(reference=memo.memo_number,
                                        entry_type='purchase').count() == 1


def test_post_over_limit_against_bill_balance_blocked(client, db_session, admin_user, main_branch):
    """The AP-balance reduction guard (mirror _apply_memo_to_ar's over-credit guard):
    a memo whose total exceeds the bill's OPEN balance at post time is rejected."""
    ap, li = _setup(client, admin_user, main_branch, bill_amount='560')
    sid = ap.id
    _create_memo(client, ap, li, amount='560')   # equals the whole bill, fine to CREATE
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    # Manually shrink the bill's open balance below the memo total (simulates a partial
    # payment applied between create and post) to exercise the guard deterministically.
    bill = db.session.get(AccountsPayable, sid)
    bill.amount_paid = Decimal('300.00'); bill.balance = Decimal('260.00')
    db.session.commit()
    resp = client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    assert memo.status == 'draft'                         # blocked, unchanged
    assert memo.journal_entry_id is None


def test_post_blocked_when_memo_date_in_closed_period(client, db_session, admin_user, main_branch):
    from app.periods.models import AccountingPeriod
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    db.session.add(AccountingPeriod(year=2026, month=7, status='closed'))
    db.session.commit()
    resp = client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'draft', 'a memo dated in a closed period must not post'
    assert memo.journal_entry_id is None
    assert bill.balance == Decimal('1120.00')             # bill untouched


# -- (e) debit_void on a posted memo reverses the AP-balance reduction (period-gated) --

def test_void_reverses_ap_balance_and_je(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    sid = ap.id
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    resp = client.post(f'/vendor-debit-memos/{memo.id}/void',
                       data={'void_reason': 'Wrong bill picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'voided'
    assert bill.balance == Decimal('1120.00') and bill.status == 'posted'
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
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    now = ph_now()
    db.session.add(AccountingPeriod(year=now.year, month=now.month, status='closed'))
    db.session.commit()
    resp = client.post(f'/vendor-debit-memos/{memo.id}/void',
                       data={'void_reason': 'Wrong bill picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    bill = db.session.get(AccountsPayable, sid)
    assert memo.status == 'posted', 'void must be blocked while the current period is closed'
    assert bill.balance == Decimal('560.00'), 'bill balance unchanged (no reversal happened)'


def test_void_requires_reason(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/vendor-debit-memos/{memo.id}/post', follow_redirects=True)
    resp = client.post(f'/vendor-debit-memos/{memo.id}/void',
                       data={'void_reason': 'short'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(PurchaseMemo, memo.id)
    assert memo.status == 'posted'   # blocked, min 10 chars


# -- views: list / detail / print -------------------------------------------------

def test_debit_list_shows_enter_button(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/vendor-debit-memos')
    assert resp.status_code == 200
    assert b'+ Enter Vendor Debit Memo' in resp.data


def test_debit_create_form_renders_single_lines_field(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/vendor-debit-memos/create')
    assert resp.status_code == 200
    assert resp.data.count(b'name="lines"') == 1
    assert b'Enter Vendor Debit Memo' in resp.data


def test_detail_renders_post_and_void_for_draft(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    resp = client.get(f'/vendor-debit-memos/{memo.id}')
    assert resp.status_code == 200
    assert f'/vendor-debit-memos/{memo.id}/post'.encode() in resp.data
    assert b'Void Vendor Debit Memo' in resp.data


def test_debit_print_renders(client, db_session, admin_user, main_branch):
    ap, li = _setup(client, admin_user, main_branch)
    _create_memo(client, ap, li, amount='560')
    memo = PurchaseMemo.query.filter_by(memo_type='debit').first()
    resp = client.get(f'/vendor-debit-memos/{memo.id}/print')
    assert resp.status_code == 200
    assert b'VENDOR DEBIT MEMO' in resp.data


# -- settings: adjudication 2 -----------------------------------------------------

def test_settings_save_persists_and_audits(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.post('/purchase-memos/settings/accounts', data={
        'purchase_returns_allowances_account_code': '50103',
        'vendor_credits_account_code': '20302'}, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('purchase_returns_allowances_account_code') == '50103'
    assert AppSettings.get_setting('vendor_credits_account_code') == '20302'
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='purchase_memos', action='assign_accounts').first() is not None


def test_settings_save_rejects_unknown_code(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    AppSettings.set_setting('purchase_returns_allowances_account_code', '')
    db.session.commit()
    client.post('/purchase-memos/settings/accounts', data={
        'purchase_returns_allowances_account_code': '99999',
        'vendor_credits_account_code': ''}, follow_redirects=True)
    assert AppSettings.get_setting('purchase_returns_allowances_account_code') in (None, '')


def test_settings_page_renders(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/purchase-memos/settings')
    assert resp.status_code == 200
    assert b'Purchase Memo Settings' in resp.data
