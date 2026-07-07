"""Integration tests for the CDV pre-printed print form: the cd_print_form setting,
the print-route branch + save route, and the JE face (combined/separated, no TOTAL row,
Section B expenses shown, Section A + Summary absent)."""
import pytest

from app.settings import AppSettings
pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


VALID_FORM_DATA = {
    'company_name': 'Acme Trading Corp.', 'trade_name': 'Acme',
    'company_tin': '123-456-789-000', 'tin_branch_code': '000', 'rdo_code': '050',
    'vat_registration_type': 'VAT', 'company_address': '123 Rizal Ave, Manila',
    'postal_code': '1000', 'phone': '02-8123-4567', 'email': 'info@acme.ph',
    'fiscal_year_start': '01', 'officer_president': 'Juan Dela Cruz',
    'officer_treasurer': 'Maria Santos', 'officer_secretary': 'Pedro Reyes',
}


class TestCdPrintFormSetting:
    def test_default_is_current_when_unset(self, db_session):
        assert AppSettings.get_setting('cd_print_form', 'current') == 'current'

    def test_settings_page_renders_cd_print_form_control(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'cd_print_form' in resp.data

    def test_admin_post_persists_cd_print_form(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA); data['cd_print_form'] = 'preprinted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('cd_print_form') == 'preprinted'


def _cdv_with_je(db_session, main_branch, balanced=True):
    """A posted CDV with one Section B expense line + a journal entry.

    Balanced: Dr Utilities 5,000 + Dr Input VAT 600 ; Cr WHT Payable 100 + Cr Cash 5,500.
    Unbalanced: drops the WHT credit so Dr 5,600 != Cr 5,500.
    """
    from decimal import Decimal
    from datetime import date
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    vendor = Vendor(code='CDVV1', name='Meralco Payee Inc.', tin='333-444-555-000', is_active=True)
    db_session.add(vendor); db_session.commit()

    def acct(code, name, atype, nb):
        a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
        db_session.add(a); db_session.commit(); return a
    utilities = acct('5030', 'Utilities Expense', 'Expense', 'debit')
    input_vat = acct('1160', 'Input VAT', 'Asset', 'debit')
    wht_pay = acct('2040', 'Withholding Tax Payable', 'Liability', 'credit')
    cash = acct('1010', 'Cash in Bank', 'Asset', 'debit')

    je = JournalEntry(entry_number='JE-CDV-1', entry_date=date(2026, 7, 7),
                      description='CDV JE', entry_type='disbursement', branch_id=main_branch.id,
                      status='posted', total_debit=Decimal('5600'),
                      total_credit=Decimal('5600') if balanced else Decimal('5500'),
                      is_balanced=balanced)
    db_session.add(je); db_session.commit()
    lines = [
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=utilities.id,
                         debit_amount=Decimal('5000'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=input_vat.id,
                         debit_amount=Decimal('600'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=4, account_id=cash.id,
                         debit_amount=Decimal('0'), credit_amount=Decimal('5500')),
    ]
    if balanced:
        lines.insert(2, JournalEntryLine(entry_id=je.id, line_number=3, account_id=wht_pay.id,
                                         debit_amount=Decimal('0'), credit_amount=Decimal('100')))
    for l in lines:
        db_session.add(l)
    db_session.commit()

    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='CDV-PP-1',
                                  cdv_date=date(2026, 7, 7), vendor_id=vendor.id,
                                  vendor_name=vendor.name, vendor_tin=vendor.tin,
                                  payment_method='check', check_number='CHK-001',
                                  cash_account_id=cash.id, status='posted',
                                  total_expense=Decimal('5600'), total_amount=Decimal('5500'),
                                  journal_entry_id=je.id, notes='July electricity')
    cdv.expense_lines.append(CDVExpenseLine(line_number=1, description='Electricity - July',
                                            quantity=Decimal('1'), unit_price=Decimal('5600'),
                                            line_total=Decimal('5600'), amount=Decimal('5600'),
                                            account_id=utilities.id))
    db_session.add(cdv); db_session.commit()
    return cdv


class TestCdPrintRoutes:
    def _open(self, client, main_branch):
        login(client)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id

    def test_preprinted_renders_positioned_canvas(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        cdv = _cdv_with_je(db_session, main_branch)
        self._open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()
        assert 'pp-canvas' in body
        assert 'CDV-PP-1' in body                    # cdv number
        assert 'Meralco Payee Inc.' in body          # pay-to
        assert 'Electricity - July' in body          # Section B expense line
        assert '<div class="pp-lineitems"' in body   # Section B band present

    def test_hidden_refuses_print_route(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_print_form', 'hidden', 'admin')
        cdv = _cdv_with_je(db_session, main_branch)
        self._open(client, main_branch)
        resp = client.get(f'/cash-disbursements/{cdv.id}/print', follow_redirects=False)
        assert resp.status_code == 302

    def test_combined_je_face_no_total_row_no_summary(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        cdv = _cdv_with_je(db_session, main_branch)
        self._open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()
        import re
        combined = re.search(r'<div class="([^"]*)"\s+data-je="combined"', body)
        assert combined and 'pp-je-inactive' not in combined.group(1)
        assert 'Input VAT' in body and 'Withholding Tax Payable' in body   # distinct named legs
        assert '5,000.00' in body and '600.00' in body                     # debits-first amounts
        assert '<tr class="pp-je-total">' not in body   # NO JE TOTAL row (match element, not CSS)
        assert 'SECTION A' not in body                  # Section A (AP bills) not on the voucher
        assert 'data-el="net_cash_disbursed"' not in body   # no Summary block

    def test_separated_mode_renders_debit_and_credit_bands(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        cdv = _cdv_with_je(db_session, main_branch)
        from app.cash_disbursements.preprinted_layout import save_layout
        save_layout({'journalEntry': {'mode': 'separated'}}, 'admin', branch_id=main_branch.id)
        self._open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()
        import re
        deb = re.search(r'<div class="([^"]*)"\s+data-je="debit"', body)
        cred = re.search(r'<div class="([^"]*)"\s+data-je="credit"', body)
        comb = re.search(r'<div class="([^"]*)"\s+data-je="combined"', body)
        assert deb and 'pp-je-inactive' not in deb.group(1)
        assert cred and 'pp-je-inactive' not in cred.group(1)
        assert comb and 'pp-je-inactive' in comb.group(1)

    def test_untied_je_refused(
            self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        cdv = _cdv_with_je(db_session, main_branch, balanced=False)
        self._open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()
        assert '<table class="pp-je-table">' not in body
        assert 'UNBALANCED' in body

    def test_save_layout_requires_full_access(
            self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        login(client, username='staff', password='staff123')
        resp = client.post('/cash-disbursements/print-layout',
                           json={'fields': {'cdv_no': {'x': 5, 'y': 5}}})
        assert resp.status_code == 403

    def test_save_layout_roundtrips_sanitized(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/cash-disbursements/print-layout',
                           json={'fields': {'cdv_no': {'x': 321, 'y': 88}}, 'evil': 'nope'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['layout']['fields']['cdv_no']['x'] == 321
        assert 'evil' not in data['layout']
