"""Unit tests for WHT per line item on PurchaseBillItem."""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from app.purchase_bills.models import PurchaseBillItem


@pytest.mark.usefixtures("app")
class TestPurchaseBillItemWht:
    def _make_item(self, **kwargs):
        defaults = dict(
            line_number=1,
            description='Office supplies',
            quantity=Decimal('2.0000'),
            unit_cost=Decimal('500.00'),
            vat_rate=Decimal('12.00'),
            wt_id=None,
            wt_rate=None,
        )
        defaults.update(kwargs)
        return PurchaseBillItem(**defaults)

    def test_wt_amount_zero_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        assert item.wt_amount == Decimal('0.00')

    def test_wt_amount_computed_from_line_total(self):
        # line_total = 2 * 500 = 1000; wt = 1000 * 10 / 100 = 100
        item = self._make_item(wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.wt_amount == Decimal('100.00')

    def test_calculate_amounts_still_sets_line_total_and_vat(self):
        item = self._make_item(wt_rate=Decimal('2.00'))
        item.calculate_amounts()
        assert item.line_total == Decimal('1000.00')
        assert item.vat_amount == Decimal('120.00')  # 1000 * 12%

    def test_to_dict_includes_wt_fields(self):
        item = self._make_item(wt_id=3, wt_rate=Decimal('10.00'))
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] == 3
        assert d['wt_rate'] == 10.0
        assert d['wt_amount'] == 100.0

    def test_to_dict_wt_none_when_no_wht(self):
        item = self._make_item()
        item.calculate_amounts()
        d = item.to_dict()
        assert d['wt_id'] is None
        assert d['wt_rate'] is None
        assert d['wt_amount'] == 0.0


# ── Integration tests (require DB) ──────────────────────────────────────────

@pytest.fixture
def wht_codes(db_session):
    from app.withholding_tax.models import WithholdingTax
    codes = [
        WithholdingTax(code='WC010', name='Professional Fees', rate=Decimal('10.00'), is_active=True),
        WithholdingTax(code='WC060', name='Contractors', rate=Decimal('2.00'), is_active=True),
    ]
    for c in codes:
        db_session.add(c)
    db_session.commit()
    return {c.code: c for c in codes}


@pytest.fixture
def test_vendor_with_wht(db_session, wht_codes):
    from app.vendors.models import Vendor
    vendor = Vendor(code='V099', name='WHT Vendor', is_active=True,
                    default_vat_category='VATABLE')
    vendor.withholding_taxes = list(wht_codes.values())
    db_session.add(vendor)
    db_session.commit()
    return vendor


@pytest.fixture
def gl_accounts_wht(db_session):
    from app.accounts.models import Account
    accounts = [
        Account(code='20101', name='AP - Trade', account_type='Liability', normal_balance='Credit'),
        Account(code='10501', name='Input VAT', account_type='Asset', normal_balance='Debit'),
        Account(code='20301', name='WT Payable', account_type='Liability', normal_balance='Credit'),
        Account(code='50999', name='Misc Expense', account_type='Expense', normal_balance='Debit'),
    ]
    for a in accounts:
        db_session.add(a)
    db_session.commit()
    return {a.code: a for a in accounts}


class TestPurchaseBillWhtIntegration:
    def _make_bill(self, db_session, admin_user, main_branch, test_vendor_with_wht,
                   gl_accounts_wht, wht_codes):
        from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
        bill = PurchaseBill(
            bill_number='PB-WHT-0001',
            bill_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            vendor_id=test_vendor_with_wht.id,
            vendor_name='WHT Vendor',
            payment_terms='Net 30',
            withholding_tax_rate=Decimal('0.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('0.00'),
            status='draft',
            branch_id=main_branch.id,
            created_by_id=admin_user.id,
        )
        db_session.add(bill)
        db_session.flush()

        item1 = PurchaseBillItem(
            bill_id=bill.id, line_number=1, description='Consultancy',
            quantity=Decimal('1.0000'), unit_cost=Decimal('5000.00'),
            vat_rate=Decimal('12.00'), vat_category='VATABLE',
            account_id=gl_accounts_wht['50999'].id,
            wt_id=wht_codes['WC010'].id,
            wt_rate=Decimal('10.00'),
        )
        item2 = PurchaseBillItem(
            bill_id=bill.id, line_number=2, description='Construction',
            quantity=Decimal('1.0000'), unit_cost=Decimal('10000.00'),
            vat_rate=Decimal('12.00'), vat_category='VATABLE',
            account_id=gl_accounts_wht['50999'].id,
            wt_id=wht_codes['WC060'].id,
            wt_rate=Decimal('2.00'),
        )
        item1.calculate_amounts()
        item2.calculate_amounts()
        bill.line_items.append(item1)
        bill.line_items.append(item2)
        bill.calculate_totals()
        db_session.commit()
        return bill

    def test_line_wt_amounts_computed(self, db_session, admin_user, main_branch,
                                      test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        items = sorted(bill.line_items, key=lambda i: i.line_number)
        # item1: 5000 * 10% = 500
        assert items[0].wt_amount == Decimal('500.00')
        # item2: 10000 * 2% = 200
        assert items[1].wt_amount == Decimal('200.00')

    def test_bill_withholding_tax_amount_sums_lines(self, db_session, admin_user, main_branch,
                                                     test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        # 500 + 200 = 700
        assert bill.withholding_tax_amount == Decimal('700.00')

    def test_bill_total_amount_deducts_wht_sum(self, db_session, admin_user, main_branch,
                                                test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        # subtotal=15000, vat=1800, total_before_wt=16800, wt=700, total=16100
        assert bill.subtotal == Decimal('15000.00')
        assert bill.vat_amount == Decimal('1800.00')
        assert bill.total_before_wt == Decimal('16800.00')
        assert bill.total_amount == Decimal('16100.00')

    def test_to_dict_includes_wt_fields(self, db_session, admin_user, main_branch,
                                         test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        items = sorted(bill.line_items, key=lambda i: i.line_number)
        d = items[0].to_dict()
        assert d['wt_id'] == wht_codes['WC010'].id
        assert d['wt_rate'] == 10.0
        assert d['wt_amount'] == 500.0

    def test_bill_to_dict_excludes_withholding_tax_rate(self, db_session, admin_user, main_branch,
                                                          test_vendor_with_wht, gl_accounts_wht, wht_codes):
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        d = bill.to_dict()
        assert 'withholding_tax_rate' not in d

    def test_void_je_uses_summed_wt_amount(self, db_session, admin_user, main_branch,
                                            test_vendor_with_wht, gl_accounts_wht, wht_codes):
        """Void JE DR side must equal total_amount + withholding_tax_amount (summed from lines)."""
        bill = self._make_bill(db_session, admin_user, main_branch,
                               test_vendor_with_wht, gl_accounts_wht, wht_codes)
        bill.status = 'posted'
        db_session.commit()
        from app.purchase_bills.views import _create_bill_void_je
        je = _create_bill_void_je(bill, date.today(), admin_user.id)
        total_debit = sum(l.debit_amount for l in je.lines)
        total_credit = sum(l.credit_amount for l in je.lines)
        assert total_debit == total_credit  # JE must balance
        assert bill.withholding_tax_amount == Decimal('700.00')
