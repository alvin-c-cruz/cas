"""Integration tests for the APV pre-printed print form: the ap_print_form
setting and the print-route branch + save route (Phase 2)."""
import pytest

from app.settings import AppSettings
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


VALID_FORM_DATA = {
    'company_name': 'Acme Trading Corp.',
    'trade_name': 'Acme',
    'company_tin': '123-456-789-000',
    'tin_branch_code': '000',
    'rdo_code': '050',
    'vat_registration_type': 'VAT',
    'company_address': '123 Rizal Ave, Manila',
    'postal_code': '1000',
    'phone': '02-8123-4567',
    'email': 'info@acme.ph',
    'fiscal_year_start': '01',
    'officer_president': 'Juan Dela Cruz',
    'officer_treasurer': 'Maria Santos',
    'officer_secretary': 'Pedro Reyes',
}


class TestApPrintFormSetting:
    def test_default_is_current_when_unset(self, db_session):
        assert AppSettings.get_setting('ap_print_form', 'current') == 'current'

    def test_settings_page_renders_ap_print_form_control(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'ap_print_form' in resp.data          # the select name is present

    def test_admin_post_persists_ap_print_form(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['ap_print_form'] = 'preprinted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('ap_print_form') == 'preprinted'

    def test_accountant_cannot_set_ap_print_form(
            self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        data = dict(VALID_FORM_DATA)
        data['ap_print_form'] = 'preprinted'
        client.post('/settings', data=data, follow_redirects=True)
        # admin_panel_required: non-admin can't write the setting
        assert AppSettings.get_setting('ap_print_form', 'current') == 'current'


def _posted_apv(db_session, main_branch):
    """A posted APV: one 11,200 VAT-inclusive line to a vendor."""
    from decimal import Decimal
    from datetime import date
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    vendor = Vendor(code='PPV1', name='Preprint Supplier Inc.', tin='111-222-333-000',
                    is_active=True)
    db_session.add(vendor); db_session.commit()
    expense = Account(code='5010', name='Office Supplies', account_type='Expense',
                      normal_balance='debit', is_active=True)
    db_session.add(expense); db_session.commit()
    ap = AccountsPayable(ap_number='APV-PP-1', ap_date=date(2026, 7, 7),
                         due_date=date(2026, 8, 6), vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin=vendor.tin,
                         vendor_invoice_number='SUP-INV-9', branch_id=main_branch.id,
                         status='posted', subtotal=Decimal('11200'),
                         vat_amount=Decimal('1200'), total_before_wt=Decimal('11200'),
                         withholding_tax_amount=Decimal('200'),
                         total_amount=Decimal('11000'))
    ap.line_items.append(AccountsPayableItem(line_number=1, description='Bond paper',
                                             quantity=Decimal('10'), unit_price=Decimal('1120'),
                                             line_total=Decimal('11200'),
                                             account_id=expense.id))
    db_session.add(ap); db_session.commit()
    return ap


class TestApPrintRoutes:
    def test_preprinted_renders_positioned_canvas(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        ap = _posted_apv(db_session, main_branch)
        login(client)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'pp-canvas' in body                 # the positioned-canvas marker
        assert 'APV-PP-1' in body                  # apv number
        assert 'Preprint Supplier Inc.' in body    # vendor
        assert 'Bond paper' in body                # a particulars line
        assert '11,000.00' in body                 # net payable

    def test_current_renders_standard_form(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('ap_print_form', 'current', 'admin')
        ap = _posted_apv(db_session, main_branch)
        login(client)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'pp-canvas' not in body             # NOT the pre-printed canvas
        assert 'ACCOUNTS PAYABLE VOUCHER' in body  # the standard form header

    def test_save_layout_requires_full_access(
            self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        login(client, username='staff', password='staff123')
        resp = client.post('/accounts-payable/print-layout',
                           json={'fields': {'apv_no': {'x': 5, 'y': 5}}})
        assert resp.status_code == 403

    def test_save_layout_roundtrips_sanitized(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/accounts-payable/print-layout',
                           json={'fields': {'apv_no': {'x': 321, 'y': 88}},
                                 'evil': 'nope'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['layout']['fields']['apv_no']['x'] == 321
        assert 'evil' not in data['layout']
