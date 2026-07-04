"""Integration tests for the CD_CHECK print_check route (P-69 check-printing Task 7).

Covers: the route's gate ordering (payment method, module, can_print status,
missing serial, zero amount, unconfigured layout), audit logging, and — the
highest-stakes assertions — that the printed check face value (cdv.total_amount)
actually ties out to the posted journal entry's cash-account credit leg, both
in the normal case and under a wt_override.
"""
from decimal import Decimal
from datetime import date

import pytest
from app import db
from app.audit.models import AuditLog
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.preprinted_forms.models import PrintLayout
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_disbursements.views import _post_cdv_je

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    from flask import g
    if hasattr(g, '_login_user'):
        del g._login_user


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.fixture
def logged_in_branch_client(client, db_session, admin_user, main_branch):
    """Admin logged in with main_branch selected (admin has access to all branches)."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    return client


@pytest.fixture
def preprinted_module_enabled(db_session):
    AppSettings.set_setting('module_enabled:preprinted_forms', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='CHKV001', name='Check Vendor',
               check_payee_name='Check Vendor', is_active=True)
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture
def _ap_account(db_session):
    """Accounts Payable - Trade (20101) — _post_cdv_je requires this unconditionally."""
    a = Account(code='20101', name='Accounts Payable - Trade',
                account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def _wt_account(db_session):
    """WHT Payable - Expanded (20301) — required only when total_wt != 0."""
    a = Account(code='20301', name='WHT Payable - Expanded',
                account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def cd_check_default_layout(db_session):
    """Active Default CD_CHECK layout with a background image and one placed field.

    background_image='x.png' is sufficient — render_preprinted (no test=True)
    never opens the file.
    """
    layout = PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True,
                          background_image='x.png',
                          page_width_mm=Decimal('178.00'), page_height_mm=Decimal('84.00'))
    layout.set_fields([
        {'key': 'total', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
    ])
    layout.set_line_band({})
    db.session.add(layout)
    db.session.commit()
    return layout


def _make_cdv(main_branch, vendor, cash_account, *, payment_method='check',
              check_number='00123', status='draft', total_amount=Decimal('0.00'),
              cdv_number=None):
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number=cdv_number or f'CD-2026-07-{CashDisbursementVoucher.query.count() + 1:04d}',
        cdv_date=date(2026, 7, 1),
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        payment_method=payment_method,
        check_number=check_number,
        check_date=date(2026, 7, 1) if payment_method == 'check' else None,
        check_bank='Test Bank' if payment_method == 'check' else None,
        cash_account_id=cash_account.id,
        notes='',
        status=status,
        total_amount=total_amount,
    )
    db.session.add(cdv)
    db.session.commit()
    return cdv


@pytest.fixture
def ready_check_cdv(db_session, main_branch, _vendor, cash_account, expense_account,
                     _ap_account, preprinted_module_enabled, cd_check_default_layout,
                     admin_user):
    """A posted check CDV with a real posted JE, whose cash-account credit
    equals total_amount (no overrides) — the money-correctness baseline."""
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CD-2026-07-9001',
        cdv_date=date(2026, 7, 1),
        vendor_id=_vendor.id,
        vendor_name=_vendor.name,
        payment_method='check',
        check_number='00123',
        check_date=date(2026, 7, 1),
        check_bank='Test Bank',
        cash_account_id=cash_account.id,
        notes='',
        status='draft',
        created_by_id=admin_user.id,
    )
    exp_line = CDVExpenseLine(
        line_number=1, description='Office rent', amount=Decimal('1234.50'),
        vat_category=None, vat_rate=Decimal('0.00'),
        account_id=expense_account.id,
    )
    exp_line.calculate_amounts()
    cdv.expense_lines.append(exp_line)
    db.session.add(cdv)
    db.session.flush()
    cdv.calculate_totals()
    assert cdv.total_amount == Decimal('1234.50')
    cdv.status = 'posted'
    je = _post_cdv_je(cdv, admin_user.id)
    cdv.journal_entry_id = je.id
    cdv.posted_by_id = admin_user.id
    db.session.commit()
    return cdv


@pytest.fixture
def cash_method_cdv(db_session, main_branch, _vendor, cash_account):
    return _make_cdv(main_branch, _vendor, cash_account, payment_method='cash',
                      check_number=None, status='posted', total_amount=Decimal('500.00'),
                      cdv_number='CD-2026-07-9002')


@pytest.fixture
def draft_check_cdv(db_session, main_branch, _vendor, cash_account, preprinted_module_enabled):
    return _make_cdv(main_branch, _vendor, cash_account, payment_method='check',
                      check_number='00050', status='draft', total_amount=Decimal('500.00'),
                      cdv_number='CD-2026-07-9003')


@pytest.fixture
def check_cdv_no_number(db_session, main_branch, _vendor, cash_account, preprinted_module_enabled):
    return _make_cdv(main_branch, _vendor, cash_account, payment_method='check',
                      check_number=None, status='posted', total_amount=Decimal('500.00'),
                      cdv_number='CD-2026-07-9004')


@pytest.fixture
def check_cdv_zero_amount(db_session, main_branch, _vendor, cash_account, preprinted_module_enabled):
    return _make_cdv(main_branch, _vendor, cash_account, payment_method='check',
                      check_number='00051', status='posted', total_amount=Decimal('0.00'),
                      cdv_number='CD-2026-07-9005')


@pytest.fixture
def check_cdv_no_layout(db_session, main_branch, _vendor, cash_account, preprinted_module_enabled):
    """Passes all voucher-level gates but no CD_CHECK layout exists at all."""
    return _make_cdv(main_branch, _vendor, cash_account, payment_method='check',
                      check_number='00052', status='posted', total_amount=Decimal('500.00'),
                      cdv_number='CD-2026-07-9006')


@pytest.fixture
def wt_override_check_cdv(db_session, main_branch, _vendor, cash_account, expense_account,
                           _ap_account, _wt_account, admin_user):
    """A check CDV where total_wt is manually overridden to diverge from the
    sum of line-level wt_amount — mirrors what _apply_cdv_overrides does on a
    real POST when the user supplies a manual WHT figure.
    """
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CD-2026-07-9101',
        cdv_date=date(2026, 7, 1),
        vendor_id=_vendor.id,
        vendor_name=_vendor.name,
        payment_method='check',
        check_number='00200',
        check_date=date(2026, 7, 1),
        check_bank='Test Bank',
        cash_account_id=cash_account.id,
        notes='',
        status='draft',
        created_by_id=admin_user.id,
    )
    exp_line = CDVExpenseLine(
        line_number=1, description='Professional fee', amount=Decimal('1000.00'),
        vat_category=None, vat_rate=Decimal('0.00'), wt_rate=Decimal('5.00'),
        account_id=expense_account.id,
    )
    exp_line.calculate_amounts()
    cdv.expense_lines.append(exp_line)
    db.session.add(cdv)
    db.session.flush()
    cdv.calculate_totals()
    real_line_wt = sum(Decimal(str(l.wt_amount or 0)) for l in cdv.expense_lines)
    assert real_line_wt == Decimal('50.00')  # 1000 * 5%

    # Manual override: user types a WHT figure that differs from the actual
    # line-level computation (mirrors _apply_cdv_overrides).
    cdv.wt_override = True
    cdv.total_wt = Decimal('75.00')  # deliberately different from real_line_wt (50.00)
    cdv.total_amount = cdv.total_ap_applied + cdv.total_expense - cdv.total_wt

    cdv.status = 'posted'
    je = _post_cdv_je(cdv, admin_user.id)
    cdv.journal_entry_id = je.id
    cdv.posted_by_id = admin_user.id
    db.session.commit()
    return cdv


# ---------------------------------------------------------------------------
# Route gate tests
# ---------------------------------------------------------------------------

def test_print_check_returns_pdf(logged_in_branch_client, ready_check_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and len(r.data) > 200


def test_print_check_blocks_cash(logged_in_branch_client, cash_method_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{cash_method_cdv.id}/print-check',
                                     follow_redirects=True)
    assert b'not a check payment' in r.data


def test_print_check_blocks_draft_under_posted_only(logged_in_branch_client, draft_check_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{draft_check_cdv.id}/print-check',
                                     follow_redirects=True)
    assert r.request.path.endswith(str(draft_check_cdv.id))  # bounced back to the CDV view
    assert b'not allowed' in r.data.lower()


def test_print_check_blocks_missing_serial(logged_in_branch_client, check_cdv_no_number):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_no_number.id}/print-check',
                                     follow_redirects=True)
    assert b'check number' in r.data.lower()


def test_print_check_blocks_zero_amount(logged_in_branch_client, check_cdv_zero_amount):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_zero_amount.id}/print-check',
                                     follow_redirects=True)
    assert b'zero or negative' in r.data.lower()


def test_print_check_flashes_when_unconfigured(logged_in_branch_client, check_cdv_no_layout):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_no_layout.id}/print-check',
                                     follow_redirects=True)
    assert r.status_code == 200 and b'check layout' in r.data.lower()  # never a 500 / voucher fallthrough


def test_print_check_writes_audit(logged_in_branch_client, ready_check_cdv, db_session):
    logged_in_branch_client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    e = AuditLog.query.filter_by(action='print_check',
                                  record_identifier=ready_check_cdv.cdv_number).first()
    assert e is not None and e.module == 'cash_disbursement'


# ---------------------------------------------------------------------------
# Money tie-out tests (highest stakes)
# ---------------------------------------------------------------------------

def test_check_amount_ties_out_to_posted_je(ready_check_cdv):
    # words==figure is tautological (same attr). The independent check is the posted JE cash leg.
    from app.preprinted_forms.field_catalog import amount_in_words, _fmt_money
    je = ready_check_cdv.journal_entry
    cash_credit = sum(l.credit_amount or 0 for l in je.lines
                      if l.account_id == ready_check_cdv.cash_account_id)
    assert Decimal(str(cash_credit)) == Decimal(str(ready_check_cdv.total_amount))
    assert _fmt_money(ready_check_cdv.total_amount) == '1,234.50'
    assert amount_in_words(ready_check_cdv.total_amount).startswith('One Thousand Two Hundred Thirty-Four')


def test_check_amount_ties_out_under_wt_override(wt_override_check_cdv):
    # A CDV whose total_wt was overridden so total_amount != sum of line wt_amounts:
    # the printed face value must still equal the posted JE cash credit, or the tie-out fails.
    je = wt_override_check_cdv.journal_entry
    cash_credit = sum(l.credit_amount or 0 for l in je.lines
                      if l.account_id == wt_override_check_cdv.cash_account_id)
    assert Decimal(str(cash_credit)) == Decimal(str(wt_override_check_cdv.total_amount))
