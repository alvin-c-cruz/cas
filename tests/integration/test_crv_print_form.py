"""Integration tests for the CRV pre-printed print form: the cr_print_form
setting (P2) and the print-route branch + save route (P3)."""
import pytest

from app.settings import AppSettings
pytestmark = [pytest.mark.cash_receipts, pytest.mark.integration]


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


class TestCrPrintFormSetting:
    def test_default_is_current_when_unset(self, db_session):
        assert AppSettings.get_setting('cr_print_form', 'current') == 'current'

    def test_settings_page_renders_cr_print_form_control(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'cr_print_form' in resp.data          # the select name is present

    def test_admin_post_persists_cr_print_form(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['cr_print_form'] = 'preprinted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('cr_print_form') == 'preprinted'

    def test_accountant_cannot_set_cr_print_form(
            self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        data = dict(VALID_FORM_DATA)
        data['cr_print_form'] = 'preprinted'
        client.post('/settings', data=data, follow_redirects=True)
        # admin_panel_required: non-admin can't write the setting
        assert AppSettings.get_setting('cr_print_form', 'current') == 'current'


def _posted_crv(db_session, main_branch, cash_account):
    """A posted CRV collecting ₱5,000 against one open invoice."""
    from decimal import Decimal
    from datetime import date
    from app.customers.models import Customer
    from app.sales_invoices.models import SalesInvoice
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    from app.utils import ph_now
    cust = Customer(code='PPC1', name='Preprint Payer Inc.', tin='111-222-333-000',
                    is_active=True)
    db_session.add(cust); db_session.commit()
    inv = SalesInvoice(invoice_number='SI-PP-1', invoice_date=date(2026, 7, 1),
                       due_date=date(2026, 7, 31), customer_id=cust.id,
                       customer_name=cust.name, branch_id=main_branch.id, status='posted',
                       subtotal=Decimal('11200'), vat_amount=Decimal('1200'),
                       total_amount=Decimal('11200'), amount_paid=Decimal('5000'),
                       balance=Decimal('6200'))
    db_session.add(inv); db_session.commit()
    crv = CashReceiptVoucher(branch_id=main_branch.id, crv_number='CRV-PP-1',
                             crv_date=date(2026, 7, 7), customer_id=cust.id,
                             customer_name=cust.name, cash_account_id=cash_account.id,
                             status='posted', total_ar_applied=Decimal('5000'),
                             total_amount=Decimal('5000'))
    crv.ar_lines.append(CRVArLine(line_number=1, invoice_id=inv.id,
                                  invoice_number=inv.invoice_number,
                                  original_balance=Decimal('11200'),
                                  amount_applied=Decimal('5000')))
    db_session.add(crv); db_session.commit()
    return crv


class TestCrPrintRoutes:
    def test_preprinted_renders_positioned_canvas(
            self, client, db_session, admin_user, main_branch, cash_account):
        AppSettings.set_setting('cr_print_form', 'preprinted', 'admin')
        crv = _posted_crv(db_session, main_branch, cash_account)
        login(client)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        resp = client.get(f'/cash-receipts/{crv.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'pp-canvas' in body             # the positioned-canvas marker
        assert 'CRV-PP-1' in body              # crv number
        assert 'Preprint Payer Inc.' in body   # payer
        assert 'SI-PP-1' in body               # AR-collection line invoice #

    def test_hidden_refuses_print_route(
            self, client, db_session, admin_user, main_branch, cash_account):
        AppSettings.set_setting('cr_print_form', 'hidden', 'admin')
        crv = _posted_crv(db_session, main_branch, cash_account)
        login(client)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        resp = client.get(f'/cash-receipts/{crv.id}/print', follow_redirects=False)
        assert resp.status_code == 302

    def test_save_layout_requires_full_access(
            self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        login(client, username='staff', password='staff123')
        resp = client.post('/cash-receipts/print-layout',
                           json={'fields': {'crv_no': {'x': 5, 'y': 5}}})
        assert resp.status_code == 403

    def test_save_layout_roundtrips_sanitized(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/cash-receipts/print-layout',
                           json={'fields': {'crv_no': {'x': 321, 'y': 88}},
                                 'evil': 'nope'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['layout']['fields']['crv_no']['x'] == 321
        assert 'evil' not in data['layout']
