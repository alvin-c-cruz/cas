"""Unit tests for purchase bills summary helper."""
import pytest
from datetime import timedelta
from decimal import Decimal

from app.branches.models import Branch
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.utils import ph_now
pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]



def make_vendor(db_session, code='SV001', name='Summary Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True)
    db_session.add(v)
    db_session.flush()
    return v


def make_branch(db_session, code='BR2', name='Branch Two'):
    b = Branch(code=code, name=name, address='456 Side St',
               phone='000-000-0000', email='br2@test.com', is_active=True)
    db_session.add(b)
    db_session.flush()
    return b


def make_ap(db_session, vendor, branch, ap_number, due_date, status='posted',
              total_amount=Decimal('1000.00'), balance=None):
    today = ph_now().date()
    b = AccountsPayable(
        ap_number=ap_number,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='',
        vendor_address='',
        branch_id=branch.id,
        ap_date=today,
        due_date=due_date,
        status=status,
        subtotal=total_amount,
        vat_amount=Decimal('0.00'),
        total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=balance if balance is not None else total_amount,
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.mark.usefixtures('app')
class TestBillsSummary:
    def test_summary_buckets(self, db_session, main_branch):
        from app.accounts_payable.utils import compute_ap_summary
        vendor = make_vendor(db_session)
        today = ph_now().date()

        # Overdue (posted, due 10 days ago)
        make_ap(db_session, vendor, main_branch, 'S001',
                  due_date=today - timedelta(days=10),
                  total_amount=Decimal('100.00'))
        # Due soon (posted, due in 3 days)
        make_ap(db_session, vendor, main_branch, 'S002',
                  due_date=today + timedelta(days=3),
                  total_amount=Decimal('200.00'))
        # Outstanding but not overdue/due-soon (due in 30 days)
        make_ap(db_session, vendor, main_branch, 'S003',
                  due_date=today + timedelta(days=30),
                  total_amount=Decimal('400.00'))
        # Due today (boundary: inclusive lower bound of due-soon window)
        make_ap(db_session, vendor, main_branch, 'S005',
                  due_date=today,
                  total_amount=Decimal('50.00'))
        # Draft (not in outstanding)
        make_ap(db_session, vendor, main_branch, 'S004',
                  due_date=today, status='draft',
                  total_amount=Decimal('999.00'))
        db_session.commit()

        s = compute_ap_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('750.00')
        assert s['outstanding_count'] == 4
        assert s['overdue_total'] == Decimal('100.00')
        assert s['overdue_count'] == 1
        assert s['due_soon_total'] == Decimal('250.00')
        assert s['due_soon_count'] == 2
        assert s['draft_count'] == 1

    def test_partially_paid_included_with_balance(self, db_session, main_branch):
        from app.accounts_payable.utils import compute_ap_summary
        vendor = make_vendor(db_session, code='SV002')
        today = ph_now().date()

        make_ap(db_session, vendor, main_branch, 'S010',
                  due_date=today - timedelta(days=5), status='partially_paid',
                  total_amount=Decimal('1000.00'), balance=Decimal('400.00'))
        db_session.commit()

        s = compute_ap_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('400.00')
        assert s['overdue_total'] == Decimal('400.00')
        assert s['outstanding_count'] == 1

    def test_closed_statuses_excluded(self, db_session, main_branch):
        from app.accounts_payable.utils import compute_ap_summary
        vendor = make_vendor(db_session, code='SV003')
        today = ph_now().date()

        for i, status in enumerate(['paid', 'voided', 'cancelled']):
            make_ap(db_session, vendor, main_branch, f'S02{i}',
                      due_date=today - timedelta(days=5), status=status,
                      total_amount=Decimal('500.00'))
        db_session.commit()

        s = compute_ap_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('0.00')
        assert s['outstanding_count'] == 0
        assert s['overdue_count'] == 0

    def test_branch_scoping(self, db_session, main_branch):
        from app.accounts_payable.utils import compute_ap_summary
        vendor = make_vendor(db_session, code='SV004')
        other = make_branch(db_session)
        today = ph_now().date()

        make_ap(db_session, vendor, main_branch, 'S030',
                  due_date=today, total_amount=Decimal('100.00'))
        make_ap(db_session, vendor, other, 'S031',
                  due_date=today, total_amount=Decimal('900.00'))
        db_session.commit()

        s = compute_ap_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('100.00')
        assert s['outstanding_count'] == 1

    def test_empty_branch_returns_zeros(self, db_session, main_branch):
        from app.accounts_payable.utils import compute_ap_summary

        s = compute_ap_summary(main_branch.id)
        assert s['outstanding_total'] == Decimal('0.00')
        assert s['outstanding_count'] == 0
        assert s['overdue_count'] == 0
        assert s['due_soon_count'] == 0
        assert s['overdue_total'] == Decimal('0.00')
        assert s['due_soon_total'] == Decimal('0.00')
        assert s['draft_count'] == 0
