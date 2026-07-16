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


# --- Task 3 (post_purchase_memo_je) fixtures -------------------------------------
#
# CTRL/leg mirror the sales-side `_legs(je)` pattern used in
# tests/integration/test_credit_memo_je.py, adapted to the brief's
# `leg(je, code=..., id=..., input_vat=...)` helper shape.

CTRL = {
    'ap_trade': '20101',
    'wht_payable': '20301',
    'purchase_returns': '50103',
    'vendor_credits': '20302',
    'input_vat': '10213',
}


def leg(je, code=None, id=None, input_vat=False):
    """Return the single JournalEntryLine matching `code` (Account.code), `id`
    (Account.id -- for a dynamically-chosen cash account), or the fixed input-VAT
    account (CTRL['input_vat']) when input_vat=True. Raises AssertionError if no
    line (or more than one) matches -- a tie-out test must bind to exactly one leg."""
    from app.journal_entries.models import JournalEntryLine
    from app.accounts.models import Account
    if input_vat:
        code = CTRL['input_vat']
    matches = []
    for l in JournalEntryLine.query.filter_by(entry_id=je.id).all():
        if id is not None:
            if l.account_id == id:
                matches.append(l)
            continue
        acct = db.session.get(Account, l.account_id)
        if acct is not None and acct.code == code:
            matches.append(l)
    assert len(matches) == 1, f'Expected exactly 1 leg for code={code} id={id}, found {len(matches)}'
    return matches[0]


def _acct(code, name, atype, nb):
    from app.accounts.models import Account
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


@pytest.fixture
def memo_coa(db_session):
    """Builds the COA + VAT category + control-account/AppSettings assignments
    post_purchase_memo_je needs: AP-Trade/WHT-Payable via app.posting.control_accounts
    (mirrors sales' ar_trade/creditable_wht), Purchase Returns/Vendor Credits via
    app.purchase_memos.service.resolve_memo_account (Task 2's verified mirror of
    sales_memos.service), and a V12 VATCategory whose input_vat_account feeds
    app.posting.purchase_vat.input_vat_buckets."""
    from app.vat_categories.models import VATCategory
    from app.settings import AppSettings
    from app.purchase_memos import service
    from tests.conftest import assign_control_accounts

    coa = {
        'ap': _acct(CTRL['ap_trade'], 'Accounts Payable - Trade', 'Liability', 'Credit'),
        'wt': _acct(CTRL['wht_payable'], 'Withholding Tax Payable', 'Liability', 'Credit'),
        'invat': _acct(CTRL['input_vat'], 'Input VAT', 'Asset', 'Debit'),
        'pr': _acct(CTRL['purchase_returns'], 'Purchase Returns and Allowances', 'Expense', 'Credit'),
        'vc': _acct(CTRL['vendor_credits'], 'Vendor Credits', 'Liability', 'Credit'),
        'cash': _acct('10110', 'Cash in Bank', 'Asset', 'Debit'),
    }
    db.session.commit()
    db.session.add(VATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                               input_vat_account_id=coa['invat'].id, is_active=True))
    db.session.commit()
    assign_control_accounts(db.session, ap=CTRL['ap_trade'], wht_payable=CTRL['wht_payable'])
    AppSettings.set_setting(service.PURCHASE_RETURNS_KEY, CTRL['purchase_returns'])
    AppSettings.set_setting(service.VENDOR_CREDITS_KEY, CTRL['vendor_credits'])
    return coa


def _make_posted_ap_and_memo(db_session, one_branch, a_vendor, coa, ap_number,
                             destination, subtotal, vat, wht):
    """Shared builder: one posted AP bill (big enough to absorb the return) +
    one posted PurchaseMemo (debit) referencing it, with header totals set
    directly (bypassing PurchaseMemoItem.calculate_amounts, which derives from
    wt_rate/quantity rather than an exact target wht) so the fixture can hit
    the brief's exact subtotal/vat/wht numbers."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, generate_purchase_memo_number

    net = Decimal(str(subtotal))
    vat = Decimal(str(vat))
    wht = Decimal(str(wht))
    gross = net + vat

    bill_gross = gross * 5  # bill big enough that a partial return never overdraws it
    bill = AccountsPayable(
        branch_id=one_branch.id, ap_number=ap_number,
        ap_date=date(2026, 2, 15), due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=a_vendor.id,
        vendor_id=a_vendor.id, vendor_name=a_vendor.name, vendor_tin=a_vendor.tin,
        status='posted', subtotal=bill_gross, total_amount=bill_gross,
        amount_paid=Decimal('0.00'), balance=bill_gross,
    )
    item = AccountsPayableItem(
        line_number=1, description='Goods purchased', amount=bill_gross,
        vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
        line_total=bill_gross, vat_amount=(vat * 5), account_id=coa['pr'].id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()

    memo = PurchaseMemo(
        memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
        vendor_id=a_vendor.id, accounts_payable_id=bill.id, original_ap_number=bill.ap_number,
        vendor_name=a_vendor.name, branch_id=one_branch.id, memo_date=bill.ap_date,
        destination=destination, reason='return', status='posted',
        cash_account_id=(coa['cash'].id if destination == 'cash_refund' else None),
    )
    db_session.add(memo)
    db_session.flush()
    mitem = PurchaseMemoItem(
        purchase_memo_id=memo.id, accounts_payable_item_id=item.id, line_number=1,
        amount=gross, line_total=gross, vat_category='V12', vat_rate=Decimal('12.00'),
        vat_amount=vat, wt_amount=wht, account_id=coa['pr'].id,
    )
    memo.line_items.append(mitem)
    memo.calculate_totals()
    db_session.add(memo)
    db_session.commit()
    return memo


@pytest.fixture
def posted_ap_factory(db_session, one_branch, a_vendor, memo_coa):
    """Factory: posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='0')
    -> a posted PurchaseMemo (debit) referencing a posted AP bill, with the
    Purchase-memo/AP-memo control accounts + Purchase Returns/Vendor Credits all
    assigned (via memo_coa)."""
    counter = {'n': 0}

    def _make(destination='ap', subtotal='1000', vat='120', wht='0'):
        counter['n'] += 1
        return _make_posted_ap_and_memo(
            db_session, one_branch, a_vendor, memo_coa, f'AP-PM-{counter["n"]:04d}',
            destination, subtotal, vat, wht)
    return _make


@pytest.fixture
def posted_ap_factory_no_ctrl(db_session, one_branch, a_vendor):
    """Like posted_ap_factory, but Purchase Returns & Allowances / Vendor Credits
    are left UNASSIGNED (AP-Trade/WHT-Payable control accounts ARE assigned) --
    isolates the friendly-error path to service.resolve_memo_account, per the
    Task 3 interface correction."""
    from app.vat_categories.models import VATCategory
    from tests.conftest import assign_control_accounts

    coa = {
        'ap': _acct(CTRL['ap_trade'], 'Accounts Payable - Trade', 'Liability', 'Credit'),
        'wt': _acct(CTRL['wht_payable'], 'Withholding Tax Payable', 'Liability', 'Credit'),
        'invat': _acct(CTRL['input_vat'], 'Input VAT', 'Asset', 'Debit'),
        'pr': _acct(CTRL['purchase_returns'], 'Purchase Returns and Allowances', 'Expense', 'Credit'),
        'vc': _acct(CTRL['vendor_credits'], 'Vendor Credits', 'Liability', 'Credit'),
        'cash': _acct('10110', 'Cash in Bank', 'Asset', 'Debit'),
    }
    db.session.commit()
    db.session.add(VATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                               input_vat_account_id=coa['invat'].id, is_active=True))
    db.session.commit()
    assign_control_accounts(db.session, ap=CTRL['ap_trade'], wht_payable=CTRL['wht_payable'])
    # Deliberately NOT assigning purchase_returns_allowances_account_code /
    # vendor_credits_account_code.

    def _make(destination='ap', subtotal='1000', vat='120', wht='0'):
        return _make_posted_ap_and_memo(
            db_session, one_branch, a_vendor, coa, 'AP-PM-NOCTRL-0001',
            destination, subtotal, vat, wht)
    return _make
