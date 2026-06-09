"""Unit tests for vendor AP aging and WHT YTD helpers."""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.withholding_tax.models import WithholdingTax
from app.utils import ph_now


def make_vendor(db_session, code='TV001', name='Test Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True)
    db_session.add(v)
    db_session.flush()
    return v


def make_wht(db_session, code, name, rate):
    """Create a WithholdingTax record for use in tests (no seed data in test DB)."""
    wt = WithholdingTax(code=code, name=name, rate=rate, is_active=True)
    db_session.add(wt)
    db_session.flush()
    return wt


def make_bill(db_session, vendor, branch, bill_number, due_date, status='posted',
              total_amount=Decimal('1000.00')):
    today = ph_now().date()
    b = PurchaseBill(
        bill_number=bill_number,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='',
        vendor_address='',
        branch_id=branch.id,
        bill_date=today,
        due_date=due_date,
        status=status,
        subtotal=total_amount,
        vat_amount=Decimal('0.00'),
        total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=total_amount,
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.mark.usefixtures('app')
class TestApAging:
    def test_aging_buckets(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session)
        today = ph_now().date()

        make_bill(db_session, vendor, main_branch, 'B001',
                  due_date=today + timedelta(days=5),
                  total_amount=Decimal('100.00'))   # current
        make_bill(db_session, vendor, main_branch, 'B002',
                  due_date=today - timedelta(days=15),
                  total_amount=Decimal('200.00'))   # 1-30
        make_bill(db_session, vendor, main_branch, 'B003',
                  due_date=today - timedelta(days=45),
                  total_amount=Decimal('300.00'))   # 31-60
        make_bill(db_session, vendor, main_branch, 'B004',
                  due_date=today - timedelta(days=75),
                  total_amount=Decimal('400.00'))   # 61-90
        make_bill(db_session, vendor, main_branch, 'B005',
                  due_date=today - timedelta(days=100),
                  total_amount=Decimal('500.00'))   # 90+
        db_session.commit()

        aging = compute_ap_aging(vendor.id)
        assert aging['current'] == Decimal('100.00')
        assert aging['1_30'] == Decimal('200.00')
        assert aging['31_60'] == Decimal('300.00')
        assert aging['61_90'] == Decimal('400.00')
        assert aging['90_plus'] == Decimal('500.00')
        assert aging['total'] == Decimal('1500.00')

    def test_aging_excludes_closed_statuses(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session, code='TV002')
        today = ph_now().date()
        overdue = today - timedelta(days=10)

        for i, status in enumerate(['draft', 'voided', 'cancelled', 'paid']):
            make_bill(db_session, vendor, main_branch, f'B00{6+i}',
                      due_date=overdue, status=status,
                      total_amount=Decimal('999.00'))
        db_session.commit()

        aging = compute_ap_aging(vendor.id)
        assert aging['total'] == Decimal('0.00')

    def test_aging_includes_partially_paid_bills(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session, code='TV006')
        today = ph_now().date()
        overdue = today - timedelta(days=10)

        # partially_paid bill with remaining balance of 400
        b = make_bill(db_session, vendor, main_branch, 'B100',
                      due_date=overdue, status='partially_paid',
                      total_amount=Decimal('1000.00'))
        b.balance = Decimal('400.00')
        db_session.commit()

        aging = compute_ap_aging(vendor.id)
        assert aging['1_30'] == Decimal('400.00')
        assert aging['total'] == Decimal('400.00')

    def test_aging_empty_vendor(self, db_session, main_branch):
        from app.vendors.utils import compute_ap_aging
        vendor = make_vendor(db_session, code='TV003')
        db_session.commit()
        aging = compute_ap_aging(vendor.id)
        assert aging['current'] == Decimal('0.00')
        assert aging['1_30'] == Decimal('0.00')
        assert aging['31_60'] == Decimal('0.00')
        assert aging['61_90'] == Decimal('0.00')
        assert aging['90_plus'] == Decimal('0.00')
        assert aging['total'] == Decimal('0.00')


@pytest.mark.usefixtures('app')
class TestWhtYtd:
    def test_wht_ytd_current_year_only(self, db_session, main_branch):
        from app.vendors.utils import compute_wht_ytd

        vendor = make_vendor(db_session, code='TV004')
        wt = make_wht(db_session, code='WC010', name='Professionals 10%', rate=Decimal('10.00'))

        today = ph_now().date()
        prior_year_date = date(today.year - 1, 6, 1)

        # Current year bill with WHT
        bill_current = make_bill(db_session, vendor, main_branch, 'B010',
                                 due_date=today, status='posted',
                                 total_amount=Decimal('1000.00'))
        item_current = PurchaseBillItem(
            bill_id=bill_current.id,
            line_number=1,
            description='Service', quantity=1, unit_cost=Decimal('1000.00'),
            vat_rate=Decimal('0.00'), vat_amount=Decimal('0.00'),
            line_total=Decimal('1000.00'),
            wt_id=wt.id, wt_rate=wt.rate,
            wt_amount=Decimal('100.00'),
        )
        db_session.add(item_current)

        # Prior year bill — must be excluded
        bill_prior = make_bill(db_session, vendor, main_branch, 'B011',
                               due_date=prior_year_date, status='posted',
                               total_amount=Decimal('500.00'))
        bill_prior.bill_date = prior_year_date  # override to prior year
        db_session.flush()
        item_prior = PurchaseBillItem(
            bill_id=bill_prior.id,
            line_number=1,
            description='Old Service', quantity=1, unit_cost=Decimal('500.00'),
            vat_rate=Decimal('0.00'), vat_amount=Decimal('0.00'),
            line_total=Decimal('500.00'),
            wt_id=wt.id, wt_rate=wt.rate,
            wt_amount=Decimal('50.00'),
        )
        db_session.add(item_prior)
        db_session.commit()

        result = compute_wht_ytd(vendor.id)
        assert len(result) == 1
        assert result[0]['code'] == 'WC010'
        assert result[0]['total'] == Decimal('100.00')

    def test_wht_ytd_groups_by_code(self, db_session, main_branch):
        from app.vendors.utils import compute_wht_ytd

        vendor = make_vendor(db_session, code='TV005')
        wt010 = make_wht(db_session, code='WC010', name='Professionals 10%', rate=Decimal('10.00'))
        wt060 = make_wht(db_session, code='WC060', name='Contractors 2%', rate=Decimal('2.00'))

        today = ph_now().date()
        bill = make_bill(db_session, vendor, main_branch, 'B020',
                         due_date=today, status='posted',
                         total_amount=Decimal('2000.00'))
        db_session.add(PurchaseBillItem(
            bill_id=bill.id, line_number=1, description='Prof Fees', quantity=1,
            unit_cost=Decimal('1000.00'), vat_rate=Decimal('0.00'),
            vat_amount=Decimal('0.00'), line_total=Decimal('1000.00'),
            wt_id=wt010.id, wt_rate=wt010.rate, wt_amount=Decimal('100.00'),
        ))
        db_session.add(PurchaseBillItem(
            bill_id=bill.id, line_number=2, description='Contractor', quantity=1,
            unit_cost=Decimal('1000.00'), vat_rate=Decimal('0.00'),
            vat_amount=Decimal('0.00'), line_total=Decimal('1000.00'),
            wt_id=wt060.id, wt_rate=wt060.rate, wt_amount=Decimal('20.00'),
        ))
        db_session.commit()

        result = compute_wht_ytd(vendor.id)
        codes = {r['code']: r['total'] for r in result}
        assert len(result) == 2
        assert codes['WC010'] == Decimal('100.00')
        assert codes['WC060'] == Decimal('20.00')
