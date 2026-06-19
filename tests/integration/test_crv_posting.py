"""Integration tests for CRV journal-entry posting (_post_crv_je)."""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.vat_categories.models import VATCategory
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_account(db_session, code, name, account_type='Asset',
                 classification='Current Asset', normal_balance='Debit'):
    acct = Account(
        code=code,
        name=name,
        account_type=account_type,
        classification=classification,
        normal_balance=normal_balance,
        is_active=True,
    )
    db_session.add(acct)
    db_session.flush()
    return acct


def make_customer(db_session, code='C001'):
    c = Customer(code=code, name=f'Customer {code}', is_active=True)
    db_session.add(c)
    db_session.flush()
    return c


def make_invoice(db_session, customer, branch_id, balance=500):
    inv = SalesInvoice(
        branch_id=branch_id,
        invoice_number=f'SI-TEST-{balance}',
        invoice_date=date.today(),
        due_date=date.today(),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='posted',
        amount_paid=Decimal('0.00'),
        balance=Decimal(str(balance)),
        total_amount=Decimal(str(balance)),
        subtotal=Decimal(str(balance)),
        vat_amount=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.flush()
    return inv


def make_vat_category(db_session, code, rate, output_vat_account=None):
    cat = VATCategory(
        code=code,
        name=f'VAT {code}',
        rate=Decimal(str(rate)),
        is_active=True,
        output_vat_account_id=output_vat_account.id if output_vat_account else None,
    )
    db_session.add(cat)
    db_session.flush()
    return cat


def build_crv(db_session, branch, customer, cash_account,
              ar_lines=None, revenue_lines=None, status='posted'):
    """Build and persist a CashReceiptVoucher with totals calculated."""
    crv = CashReceiptVoucher(
        branch_id=branch.id,
        crv_number='CR-2026-06-0001',
        crv_date=date.today(),
        customer_id=customer.id,
        customer_name=customer.name,
        payment_method='cash',
        cash_account_id=cash_account.id,
        notes='',
        status=status,
        total_ar_applied=Decimal('0.00'),
        total_revenue=Decimal('0.00'),
        total_vat=Decimal('0.00'),
        total_wt=Decimal('0.00'),
        total_amount=Decimal('0.00'),
    )
    db_session.add(crv)
    db_session.flush()

    for i, (inv, amount_applied) in enumerate(ar_lines or [], start=1):
        line = CRVArLine(
            crv_id=crv.id,
            line_number=i,
            invoice_id=inv.id,
            invoice_number=inv.invoice_number,
            original_balance=inv.balance,
            amount_applied=Decimal(str(amount_applied)),
        )
        db_session.add(line)

    for i, rl_kwargs in enumerate(revenue_lines or [], start=1):
        rl = CRVRevenueLine(
            crv_id=crv.id,
            line_number=i,
            description=rl_kwargs.get('description', 'Revenue'),
            amount=Decimal(str(rl_kwargs.get('amount', 0))),
            vat_category=rl_kwargs.get('vat_category'),
            vat_rate=Decimal(str(rl_kwargs.get('vat_rate', 0))),
            line_total=Decimal(str(rl_kwargs.get('line_total', rl_kwargs.get('amount', 0)))),
            vat_amount=Decimal(str(rl_kwargs.get('vat_amount', 0))),
            account_id=rl_kwargs.get('account_id'),
            wt_amount=Decimal(str(rl_kwargs.get('wt_amount', 0))),
        )
        db_session.add(rl)

    db_session.flush()
    # Reload relationships then recalculate
    db_session.refresh(crv)
    crv.calculate_totals()
    db_session.flush()
    return crv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCRVPosting:

    def _setup_base_accounts(self, db_session):
        """Create the GL accounts needed by _post_crv_je."""
        ar = make_account(db_session, '10201', 'Accounts Receivable - Trade',
                          account_type='Asset', classification='Current Asset',
                          normal_balance='Debit')
        wht_recv = make_account(db_session, '10212', 'Creditable WHT Receivable',
                                account_type='Asset', classification='Current Asset',
                                normal_balance='Debit')
        return ar, wht_recv

    def test_ar_only_crv_is_balanced(self, db_session, admin_user, main_branch):
        """AR-only CRV: Cr AR 500 + Dr Cash 500 → balanced."""
        from app.cash_receipts.views import _post_crv_je

        ar_acct, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        customer = make_customer(db_session)
        inv = make_invoice(db_session, customer, main_branch.id, balance=500)

        crv = build_crv(db_session, main_branch, customer, cash,
                        ar_lines=[(inv, 500)], status='posted')

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"
        assert je.total_debit == je.total_credit
        assert je.total_debit == Decimal('500.00')

        # Cr AR 500
        ar_line = next(l for l in je.lines if l.account_id == ar_acct.id)
        assert ar_line.credit_amount == Decimal('500.00')
        assert ar_line.debit_amount == Decimal('0.00')

        # Dr Cash 500
        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.debit_amount == Decimal('500.00')
        assert cash_line.credit_amount == Decimal('0.00')

        assert je.entry_type == 'receipt'

    def test_direct_revenue_with_vat_is_balanced(self, db_session, admin_user, main_branch):
        """Direct revenue line 1120 incl 12% VAT → Cr Revenue 1000 + Cr Output VAT 120 + Dr Cash 1120."""
        from app.cash_receipts.views import _post_crv_je

        ar_acct, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        output_vat_acct = make_account(db_session, '20401', 'Output VAT',
                                       account_type='Liability',
                                       classification='Current Liability',
                                       normal_balance='Credit')
        customer = make_customer(db_session)
        make_vat_category(db_session, 'VAT12', rate=12, output_vat_account=output_vat_acct)

        # 1120 inclusive, vat = 120, net = 1000
        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Service fee',
                            'amount': 1120,
                            'line_total': 1120,
                            'vat_category': 'VAT12',
                            'vat_rate': 12,
                            'vat_amount': Decimal('120.00'),
                            'account_id': revenue_acct.id,
                        }], status='posted')
        # Force total_vat so _output_vat_buckets is triggered
        crv.total_vat = Decimal('120.00')
        db_session.flush()

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"
        assert je.total_debit == je.total_credit

        # Cr Revenue 1000 (net base)
        rev_line = next(l for l in je.lines if l.account_id == revenue_acct.id)
        assert rev_line.credit_amount == Decimal('1000.00')
        assert rev_line.debit_amount == Decimal('0.00')

        # Cr Output VAT 120
        vat_line = next(l for l in je.lines if l.account_id == output_vat_acct.id)
        assert vat_line.credit_amount == Decimal('120.00')
        assert vat_line.debit_amount == Decimal('0.00')

        # Dr Cash 1120
        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.debit_amount == Decimal('1120.00')
        assert cash_line.credit_amount == Decimal('0.00')

    def test_mixed_crv_is_balanced(self, db_session, admin_user, main_branch):
        """Mixed CRV (AR 500 + direct revenue 200 no VAT) → balanced."""
        from app.cash_receipts.views import _post_crv_je

        ar_acct, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session)
        inv = make_invoice(db_session, customer, main_branch.id, balance=500)

        crv = build_crv(db_session, main_branch, customer, cash,
                        ar_lines=[(inv, 500)],
                        revenue_lines=[{
                            'description': 'Misc revenue',
                            'amount': 200,
                            'line_total': 200,
                            'vat_category': None,
                            'vat_rate': 0,
                            'vat_amount': 0,
                            'account_id': revenue_acct.id,
                        }], status='posted')

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"
        assert je.total_debit == je.total_credit
        # Total = 500 (AR) + 200 (revenue) = 700 cash
        assert je.total_debit == Decimal('700.00')

    def test_missing_output_vat_account_raises_value_error(self, db_session, admin_user, main_branch):
        """Revenue line with VAT category that has no output_vat_account raises ValueError."""
        from app.cash_receipts.views import _post_crv_je

        ar_acct, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session)
        # No output_vat_account set
        make_vat_category(db_session, 'VATBAD', rate=12, output_vat_account=None)

        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Taxable service',
                            'amount': 1120,
                            'line_total': 1120,
                            'vat_category': 'VATBAD',
                            'vat_rate': 12,
                            'vat_amount': Decimal('120.00'),
                            'account_id': revenue_acct.id,
                        }], status='posted')
        crv.total_vat = Decimal('120.00')
        db_session.flush()

        with pytest.raises(ValueError, match="no Output Tax account"):
            _post_crv_je(crv, admin_user.id)
