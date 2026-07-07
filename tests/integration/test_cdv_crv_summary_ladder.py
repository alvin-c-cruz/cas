"""The CDV/CRV Summary shows a self-consistent AP-parity VAT ladder.

Section B lines are VAT-inclusive, so listing a bare Input/Output VAT row below the
gross figure invited users to double-add. Fix (presentation-only): mirror the AP purchase
bill's ladder -- Gross -> Less: VAT -> Net of VAT -> Add: VAT (back) -> Less: WHT -> Net --
so every row is a real running step and the VAT is visibly stripped then restored.

Example: Direct Expenses 5,600.00 (incl. 600.00 VAT) -> Net of VAT 5,000.00; Net Cash 5,550.00.
"""
from decimal import Decimal
from datetime import date

import pytest

pytestmark = pytest.mark.integration


def login(client, u='admin', p='admin123'):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def _open(client, main_branch):
    login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id


class TestCdvSummaryLadder:
    @pytest.mark.cash_disbursements
    def test_cdv_detail_shows_vat_ladder(self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        from app.accounts.models import Account
        from app.cash_disbursements.models import CashDisbursementVoucher
        v = Vendor(code='LAD1', name='Meralco', tin='111-222-333-000', is_active=True)
        cash = Account(code='1011', name='Cash in Bank', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db_session.add_all([v, cash]); db_session.commit()
        cdv = CashDisbursementVoucher(
            branch_id=main_branch.id, cdv_number='CD-LAD-1', cdv_date=date(2026, 7, 7),
            vendor_id=v.id, vendor_name=v.name, payment_method='cash',
            cash_account_id=cash.id, status='posted',
            total_ap_applied=Decimal('0.00'), total_expense=Decimal('5600.00'),
            total_vat=Decimal('600.00'), total_wt=Decimal('50.00'),
            total_amount=Decimal('5550.00'), notes='electricity')
        db_session.add(cdv); db_session.commit()
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()

        assert 'Less: Input VAT' in body        # VAT stripped out
        assert 'Net of VAT' in body             # subtotal
        assert 'Add: Input VAT' in body         # VAT restored
        assert '5,000.00' in body               # Net of VAT = 5,600 - 600
        assert '5,600.00' in body               # gross Direct Expenses still shown
        assert 'Net Cash Disbursed' in body
        assert '5,550.00' in body               # unchanged total


class TestCrvSummaryLadder:
    @pytest.mark.cash_receipts
    def test_crv_detail_shows_vat_ladder(self, client, db_session, admin_user, main_branch):
        from app.customers.models import Customer
        from app.accounts.models import Account
        from app.cash_receipts.models import CashReceiptVoucher
        c = Customer(code='LADC1', name='ABC Corp', tin='444-555-666-000', is_active=True)
        cash = Account(code='1011', name='Cash in Bank', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db_session.add_all([c, cash]); db_session.commit()
        crv = CashReceiptVoucher(
            branch_id=main_branch.id, crv_number='CR-LAD-1', crv_date=date(2026, 7, 7),
            customer_id=c.id, customer_name=c.name, payment_method='cash',
            cash_account_id=cash.id, status='posted',
            total_ar_applied=Decimal('0.00'), total_revenue=Decimal('5600.00'),
            total_vat=Decimal('600.00'), total_wt=Decimal('50.00'),
            total_amount=Decimal('5550.00'), notes='service')
        db_session.add(crv); db_session.commit()
        _open(client, main_branch)
        body = client.get(f'/cash-receipts/{crv.id}').data.decode()

        assert 'Less: Output VAT' in body
        assert 'Net of VAT' in body
        assert 'Add: Output VAT' in body
        assert '5,000.00' in body
        assert '5,600.00' in body
        assert 'Net Cash Received' in body
        assert '5,550.00' in body
