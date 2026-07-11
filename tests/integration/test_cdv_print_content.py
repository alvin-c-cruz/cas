"""Integration tests for the CDV print page (APV-parity reskin)."""
import pytest
from decimal import Decimal
from datetime import date
from app.settings import AppSettings
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Acme Supplies',
               check_payee_name='Acme Supplies', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def _expense_account(db_session):
    a = Account(code='60101', name='Office Supplies', account_type='Expense',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand', account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _posted_cdv(db_session, main_branch, admin_user, accountant_user,
                _vendor, _expense_account, _cash_account):
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CD-2026-06-0007',
        cdv_date=date(2026, 6, 14), vendor_id=_vendor.id, vendor_name=_vendor.name,
        vendor_tin='001-002-003', payment_method='cash',
        cash_account_id=_cash_account.id, notes='Test disbursement', status='posted',
        created_by_id=admin_user.id, posted_by_id=accountant_user.id,
        total_ap_applied=Decimal('0.00'), total_expense=Decimal('5600.00'),
        total_vat=Decimal('600.00'), total_wt=Decimal('560.00'),
        total_amount=Decimal('5040.00'),
    )
    db_session.add(cdv); db_session.flush()
    line = CDVExpenseLine(
        cdv_id=cdv.id, line_number=1, description='Bond paper',
        amount=Decimal('5600.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        account_id=_expense_account.id, wt_rate=Decimal('10.00'),
        wt_amount=Decimal('560.00'),
    )
    db_session.add(line); db_session.commit()
    return cdv


class TestCdvPrintContent:
    def test_no_auto_print_script(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert "addEventListener('load'" not in html

    def test_print_and_close_toolbar(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'onclick="window.print()"' in html
        # Close now closes the tab (f9fc814 / BUG-PRINT-CLOSE-NEWTAB-PARITY), no longer a
        # back-to-view anchor. Retargeted (not loosened) to the current markup.
        assert 'onclick="window.close()"' in html   # Close -> closes the tab
        assert '>Close</button>' in html

    def test_renders_company_name(self, client, db_session, admin_user, _posted_cdv):
        AppSettings.set_setting('company_name', 'Mabuhay Trading Inc.', 'system')
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'MABUHAY TRADING INC.' in html   # upper-cased header

    def test_peso_sign_rule(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert '₱0.00' in html         # AP Applied (first summary row)
        assert '₱5,040.00' in html     # Net Cash Disbursed (after divider)
        assert '₱5,600.00' not in html  # Direct Expenses + Section B line stay unsigned
        assert '₱600.00' not in html    # Input VAT + Section B VAT stay unsigned

    def test_four_signatory_boxes(self, client, db_session, admin_user, _posted_cdv):
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        for label in ('PREPARED BY', 'CHECKED BY', 'APPROVED BY', 'RECEIVED BY (PAYEE)'):
            assert label in html
        assert 'Admin User' in html        # created_by.full_name -> Prepared
        assert 'Accountant User' in html   # posted_by.full_name  -> Approved

    def test_draft_approved_box_blank(self, client, db_session, admin_user, _posted_cdv):
        # P-69 Task 7: the print route now enforces cd_print_access server-side
        # (default 'posted_only' would refuse a draft). This test is about the
        # Approved-by box rendering blank for a draft, not access control, so
        # widen the setting to keep exercising a draft GET.
        AppSettings.set_setting('cd_print_access', 'draft_and_posted', 'system')
        _posted_cdv.status = 'draft'
        _posted_cdv.posted_by_id = None
        db_session.commit()
        login(client)
        html = client.get(f'/cash-disbursements/{_posted_cdv.id}/print').data.decode()
        assert 'Admin User' in html            # Prepared still shows
        assert 'Accountant User' not in html   # Approved blank on a draft
