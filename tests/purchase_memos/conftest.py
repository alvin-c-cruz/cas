"""Fixtures for the purchase_memos (Vendor Debit Memo) test suite.

Thin wrappers/adapters over the shared fixtures in tests/conftest.py (main_branch,
revenue_account, db_session) plus a purchase-side vendor + posted AccountsPayable
bill fixture (`a_posted_ap`), mirroring the sales-side `posted_ap_v12sv`-style
fixtures already used elsewhere in this suite.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db


@pytest.fixture
def app_ctx(db_session):
    """Alias for db_session -- an app context with tables created, matching the
    fixture name the purchase_memos test brief expects."""
    yield db_session


@pytest.fixture
def one_branch(main_branch):
    """Alias for main_branch -- the fixture name the purchase_memos test brief expects."""
    return main_branch


@pytest.fixture
def a_vendor(db_session):
    """A vendor to use as the posted AP bill's payee."""
    from app.vendors.models import Vendor
    vendor = Vendor(code='PM-VEND', name='Purchase Memo Vendor', tin='111-222-333-000')
    db_session.add(vendor)
    db_session.commit()
    return vendor


@pytest.fixture
def a_posted_ap(db_session, one_branch, revenue_account, a_vendor):
    """One posted Accounts Payable bill, one V12/regular line -- the bill a
    PurchaseMemo (Vendor Debit Memo) references and partially reverses."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=one_branch.id,
        ap_number='AP-PM-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=a_vendor.id,
        vendor_id=a_vendor.id,
        vendor_name=a_vendor.name,
        vendor_tin=a_vendor.tin,
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Goods purchased',
        amount=Decimal('1120.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill
