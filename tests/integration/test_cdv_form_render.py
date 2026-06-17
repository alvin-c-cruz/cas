"""Render + CRUD coverage for the CDV create/edit FORM TEMPLATE.

The existing test_cdv_views.py suite POSTs form data but never renders
cash_disbursements/form.html, so a Jinja error in the template would slip
through. These tests render the form in both create and edit mode (the
surface changed when the header was aligned to the APV layout) and walk a
create -> read -> update-render -> void cycle, asserting the audit trail.

Accounting actions run as an ACCOUNTANT (not admin) per project testing rule.
"""
import json
import pytest
from datetime import date

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.cash_disbursements.models import CashDisbursementVoucher
from app.audit.models import AuditLog
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def setup_accounts(db_session):
    ap   = Account(code='20101', name='AP Trade',      account_type='Liability', normal_balance='credit', is_active=True)
    wt   = Account(code='20301', name='WHT Payable',   account_type='Liability', normal_balance='credit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand',  account_type='Asset',     normal_balance='debit',  is_active=True)
    exp  = Account(code='60101', name='Office Supplies', account_type='Expense', normal_balance='debit',  is_active=True)
    db_session.add_all([ap, wt, cash, exp])
    db_session.commit()
    return ap, wt, cash, exp


def make_vendor(db_session):
    v = Vendor(code='CDV01', name='CDV Vendor', check_payee_name='CDV Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def create_draft_cdv(client, vendor, cash_account, expense_lines):
    return client.post('/cash-disbursements/create', data={
        'cdv_number': 'CD-REND-0001',
        'cdv_date': ph_now().date().isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash_account.id,
        'notes': 'Render-test particulars',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps(expense_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestCDVFormRender:
    def test_create_page_renders_apv_aligned_header(self, client, db_session, accountant_user, main_branch):
        login(client, 'accountant', 'accountant123')
        setup_accounts(db_session)
        make_vendor(db_session)

        resp = client.get('/cash-disbursements/create')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8', 'replace')
        # New APV-aligned header structure.
        assert 'page-cash-disbursement' in html
        assert 'form-main-grid' in html
        assert 'vendor-step-card' in html
        assert 'Step 1' in html
        assert 'line-items-locked' in html

    def test_create_then_edit_renders_done_state(self, client, db_session, accountant_user, main_branch):
        login(client, 'accountant', 'accountant123')
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        # CREATE (draft) ----------------------------------------------------
        expense_lines = [{'description': 'Office supplies', 'amount': 1000.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        resp = create_draft_cdv(client, vendor, cash, expense_lines)
        assert resp.status_code == 200

        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-REND-0001').first()
        assert cdv is not None and cdv.status == 'draft'

        # Audit: create logged.
        log = AuditLog.query.filter_by(module='cash_disbursement', action='create').first()
        assert log is not None

        # READ (view) -------------------------------------------------------
        assert client.get(f'/cash-disbursements/{cdv.id}').status_code == 200

        # UPDATE-render (edit GET) — renders form.html with cdv set ----------
        resp = client.get(f'/cash-disbursements/{cdv.id}/edit')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8', 'replace')
        # Edit mode shows the vendor card already "done" with the vendor name.
        assert 'vendor-step-card--done' in html
        assert 'header-fields--active' in html
        assert vendor.name in html

    def test_void_removes_draft_and_logs_audit(self, client, db_session, accountant_user, main_branch):
        login(client, 'accountant', 'accountant123')
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Supplies', 'amount': 500.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-REND-0001').first()

        client.post(f'/cash-disbursements/{cdv.id}/void',
                    data={'void_reason': 'Render-test cleanup — voiding'},
                    follow_redirects=True)
        db_session.refresh(cdv)
        assert cdv.status == 'voided'

        log = AuditLog.query.filter_by(module='cash_disbursement', action='void').first()
        assert log is not None
