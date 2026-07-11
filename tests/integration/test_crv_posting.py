"""Integration tests for CRV journal-entry posting (_post_crv_je)."""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_vat_categories.models import SalesVATCategory
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
    """CRV _output_vat_buckets reads SalesVATCategory (not VATCategory).
    Seeds a SalesVATCategory so the CRV posting helper can resolve the output account."""
    cat = SalesVATCategory(
        code=code,
        name=f'VAT {code}',
        rate=Decimal(str(rate)),
        is_active=True,
        transaction_nature='regular',
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
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
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

    def test_vat_override_absorbed_into_output_vat_bucket(self, db_session, admin_user, main_branch):
        """When vat_override is active and total_vat > sum(per-line VAT), the diff
        is absorbed into the largest output-VAT bucket, not left as a residual."""
        from app.cash_receipts.views import _output_vat_buckets

        output_vat_acct = make_account(db_session, '20401', 'Output VAT',
                                       account_type='Liability',
                                       classification='Current Liability',
                                       normal_balance='Credit')
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session)
        make_vat_category(db_session, 'VAT12', rate=12, output_vat_account=output_vat_acct)
        self._setup_base_accounts(db_session)

        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Service',
                            'amount': 1120,
                            'line_total': 1120,
                            'vat_category': 'VAT12',
                            'vat_rate': 12,
                            'vat_amount': Decimal('120.00'),
                            'account_id': revenue_acct.id,
                        }], status='draft')
        # Override: user manually set total_vat to 130 (10 more than auto)
        crv.vat_override = True
        crv.total_vat = Decimal('130.00')
        db_session.flush()

        buckets = _output_vat_buckets(crv)
        total_bucket_vat = sum(amt for _, amt in buckets)
        assert total_bucket_vat == Decimal('130.00'), (
            f'Expected bucket total 130.00, got {total_bucket_vat}')

    def test_vat_override_negative_bucket_sign_aware(self, db_session, admin_user, main_branch):
        """When override drives a bucket negative, the negative bucket is returned (sign-aware; no raise)."""
        from app.cash_receipts.views import _output_vat_buckets

        output_vat_acct = make_account(db_session, '20401', 'Output VAT',
                                       account_type='Liability',
                                       classification='Current Liability',
                                       normal_balance='Credit')
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session)
        make_vat_category(db_session, 'VAT12', rate=12, output_vat_account=output_vat_acct)
        self._setup_base_accounts(db_session)

        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Service',
                            'amount': 1120,
                            'line_total': 1120,
                            'vat_category': 'VAT12',
                            'vat_rate': 12,
                            'vat_amount': Decimal('120.00'),
                            'account_id': revenue_acct.id,
                        }], status='draft')
        # Override: total_vat set to -5 → bucket absorbs diff (-5-120=-125) → bucket becomes -5
        crv.vat_override = True
        crv.total_vat = Decimal('-5.00')
        db_session.flush()

        buckets = _output_vat_buckets(crv)
        total_bucket_vat = sum(amt for _, amt in buckets)
        assert total_bucket_vat == Decimal('-5.00')

    def test_pure_negative_section_b_crv(self, db_session, admin_user, main_branch):
        """Pure negative Section B line: Dr Revenue 1000, Cr Cash 1000."""
        from app.cash_receipts.views import _post_crv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session, code='C002')

        # -1000: pure negative revenue reversal (no VAT)
        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Revenue reversal',
                            'amount': -1000,
                            'line_total': -1000,
                            'vat_amount': 0,
                            'account_id': revenue_acct.id,
                        }], status='posted')

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"

        rev_line = next(l for l in je.lines if l.account_id == revenue_acct.id)
        assert rev_line.debit_amount == Decimal('1000.00')
        assert rev_line.credit_amount == Decimal('0.00')

        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.credit_amount == Decimal('1000.00')
        assert cash_line.debit_amount == Decimal('0.00')


    def test_mixed_positive_negative_section_b_crv(self, db_session, admin_user, main_branch):
        """Mixed +3000 and -1000 Section B: net cash debit = 2000."""
        from app.cash_receipts.views import _post_crv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session, code='C003')

        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[
                            {'description': 'Fee', 'amount': 3000, 'line_total': 3000,
                             'vat_amount': 0, 'account_id': revenue_acct.id},
                            {'description': 'Reversal', 'amount': -1000, 'line_total': -1000,
                             'vat_amount': 0, 'account_id': revenue_acct.id},
                        ], status='posted')

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced
        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.debit_amount == Decimal('2000.00')
        assert cash_line.credit_amount == Decimal('0.00')


    def test_negative_section_b_with_vat_crv(self, db_session, admin_user, main_branch):
        """Negative Section B line: bare abs(amount) only — no VAT extraction.
        Dr Revenue 1120, Cr Cash 1120. No Output VAT line."""
        from app.cash_receipts.views import _post_crv_je

        _, _ = self._setup_base_accounts(db_session)
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
        customer = make_customer(db_session, code='C004')
        make_vat_category(db_session, 'VAT12', rate=12, output_vat_account=output_vat_acct)

        # -1120 inclusive; new rule: post bare abs(amount), no VAT
        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Reversal w/ VAT',
                            'amount': -1120,
                            'line_total': -1120,
                            'vat_category': 'VAT12',
                            'vat_rate': 12,
                            'vat_amount': Decimal('-120.00'),
                            'account_id': revenue_acct.id,
                        }], status='posted')
        crv.total_vat = Decimal('-120.00')
        db_session.flush()

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced

        # Bare abs(line_total) — no VAT extraction on negative lines
        rev_line = next(l for l in je.lines if l.account_id == revenue_acct.id)
        assert rev_line.debit_amount == Decimal('1120.00')
        assert rev_line.credit_amount == Decimal('0.00')

        # No Output VAT line for negative lines
        je_lines = list(je.lines)
        vat_lines = [l for l in je_lines if l.account_id == output_vat_acct.id]
        assert len(vat_lines) == 0

        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.credit_amount == Decimal('1120.00')
        assert cash_line.debit_amount == Decimal('0.00')


    def test_negative_section_b_with_negative_wht_crv(self, db_session, admin_user, main_branch):
        """Negative Section B: no WHT on negative lines — WHT line must be absent."""
        from app.cash_receipts.views import _post_crv_je

        _, wht_acct = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session, code='C005')

        # -1000 gross with wt_amount=-20; new rule: negative lines have no WHT
        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Reversal w/ WHT',
                            'amount': -1000,
                            'line_total': -1000,
                            'vat_amount': 0,
                            'wt_amount': Decimal('-20.00'),
                            'account_id': revenue_acct.id,
                        }], status='posted')
        db_session.flush()

        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced

        # No WHT line for negative lines
        wht_line = next((l for l in je.lines if l.account_id == wht_acct.id), None)
        assert wht_line is None

    def test_net_zero_vat_cancellation_crv(self, db_session, admin_user, main_branch):
        """C1: +1120 and -1120 lines with same VAT category must not cancel Output VAT.
        _parse_and_attach_revenue_lines zeroes vat_amount on negative lines, so
        total_vat stays 120. Output VAT line must be posted; JE must be balanced.
        Regression guard: if the zeroing guard is removed from the parse function,
        neg_line.vat_amount would be -120 and total_vat would net to 0, causing
        this test to fail on the vat_line assertion."""
        import json
        from app.cash_receipts.views import _parse_and_attach_revenue_lines, _post_crv_je

        _, _ = self._setup_base_accounts(db_session)
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
        customer = make_customer(db_session, code='C006')
        make_vat_category(db_session, 'VAT12', rate=12, output_vat_account=output_vat_acct)

        # Build a minimal CRV header; lines are added via the real parse function
        crv = CashReceiptVoucher(
            branch_id=main_branch.id,
            crv_number='CR-C1-TEST',
            crv_date=date.today(),
            customer_id=customer.id,
            customer_name=customer.name,
            payment_method='cash',
            cash_account_id=cash.id,
            notes='',
            status='draft',
            total_ar_applied=Decimal('0.00'),
            total_revenue=Decimal('0.00'),
            total_vat=Decimal('0.00'),
            total_wt=Decimal('0.00'),
            total_amount=Decimal('0.00'),
        )
        db_session.add(crv)
        db_session.flush()

        # Call the real parse function — this is the code path the zeroing guard lives in.
        # The negative line carries vat_category='VAT12' so calculate_amounts() would produce
        # vat_amount=-120 before the guard zeroes it.
        lines_json = json.dumps([
            {
                'amount': 1120,
                'account_id': str(revenue_acct.id),
                'vat_category': 'VAT12',
                'description': 'Service fee',
            },
            {
                'amount': -1120,
                'account_id': str(revenue_acct.id),
                'vat_category': 'VAT12',
                'description': 'Revenue reversal',
            },
        ])
        _parse_and_attach_revenue_lines(crv, lines_json)
        db_session.flush()

        assert len(crv.revenue_lines) == 2
        neg_line = next(l for l in crv.revenue_lines if l.amount < 0)

        # Regression guard: zeroing fix must have run inside the parse function
        assert neg_line.vat_amount == Decimal('0.00'), (
            f'Expected vat_amount=0 on negative line, got {neg_line.vat_amount}')

        # total_vat must be 120 (positive line only), not 0 (which the pre-fix bug produced)
        db_session.refresh(crv)
        crv.calculate_totals()
        db_session.flush()
        assert crv.total_vat == Decimal('120.00'), (
            f'total_vat should be 120 (positive line only), got {crv.total_vat}')

        crv.status = 'posted'
        db_session.flush()
        je = _post_crv_je(crv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"

        # Output VAT line must be present (C1 bug: it was absent because total_vat netted to 0)
        vat_line = next((l for l in je.lines if l.account_id == output_vat_acct.id), None)
        assert vat_line is not None, 'Output VAT JE line must be present for positive revenue line'
        assert vat_line.credit_amount == Decimal('120.00')

    def test_negative_line_totals_match_je_crv(self, db_session, admin_user, main_branch):
        """I1: _parse_and_attach_revenue_lines must zero vat_amount/wt_amount on negative lines.
        After parse, stored totals must reflect no VAT/WHT on negative lines."""
        import json
        from app.cash_receipts.views import _parse_and_attach_revenue_lines
        from app.withholding_tax.models import WithholdingTax

        _, wht_acct = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        revenue_acct = make_account(db_session, '4001', 'Sales Revenue',
                                    account_type='Income', classification='Operating Revenue',
                                    normal_balance='Credit')
        customer = make_customer(db_session, code='C007')

        # Create a WHT code at 10%
        wt = WithholdingTax(code='WC010', name='EWT 10%', rate=Decimal('10.00'), is_active=True)
        db_session.add(wt)
        db_session.flush()

        # Create a minimal CRV to hold lines
        from datetime import date
        crv = CashReceiptVoucher(
            branch_id=main_branch.id,
            crv_number='CR-I1-TEST',
            crv_date=date.today(),
            customer_id=customer.id,
            customer_name=customer.name,
            payment_method='cash',
            cash_account_id=cash.id,
            notes='',
            status='draft',
            total_ar_applied=Decimal('0.00'),
            total_revenue=Decimal('0.00'),
            total_vat=Decimal('0.00'),
            total_wt=Decimal('0.00'),
            total_amount=Decimal('0.00'),
        )
        db_session.add(crv)
        db_session.flush()

        # Parse a negative line with WHT set — fix should zero vat_amount and wt_amount
        lines_json = json.dumps([{
            'amount': -1000,
            'account_id': str(revenue_acct.id),
            'vat_category': None,
            'wt_id': str(wt.id),
            'description': 'Reversal',
        }])
        _parse_and_attach_revenue_lines(crv, lines_json)
        db_session.flush()

        assert len(crv.revenue_lines) == 1
        neg_line = crv.revenue_lines[0]

        # Fix: vat_amount and wt_amount must be 0 on a negative line
        assert neg_line.vat_amount == Decimal('0.00'), (
            f'Expected vat_amount=0 on negative line, got {neg_line.vat_amount}')
        assert neg_line.wt_amount == Decimal('0.00'), (
            f'Expected wt_amount=0 on negative line, got {neg_line.wt_amount}')

        # total_amount must equal the raw negative amount (no WHT offset)
        db_session.refresh(crv)
        crv.calculate_totals()
        db_session.flush()
        assert crv.total_amount == Decimal('-1000.00'), (
            f'Expected total_amount=-1000 (no WHT offset on negative line), got {crv.total_amount}')



# ---------------------------------------------------------------------------
# WHT override — backlog item 83
#
# `_post_crv_je` summed per-line `wt_amount` and never consulted `crv.wt_override`
# / `crv.total_wt`, even though `_apply_crv_overrides` persists both and the model's
# `total_amount` is computed FROM the override. Cash is the residual plug, so an
# overridden CRV still balanced while BOTH the Creditable-WHT leg and the Cash leg
# were wrong by (override - line_sum). Dr == Cr proves nothing here.
#
# CRV books a SINGLE 10212 leg (like SI), not per-ATC buckets:
# `WithholdingTax.receivable_account` is consumed nowhere in any posting path.
# ---------------------------------------------------------------------------

def _leg(je, code):
    """The (debit, credit) posted to `code`, or None if that account has no leg."""
    for line in je.lines:
        if line.account.code == code:
            return line.debit_amount, line.credit_amount
    return None


class TestCRVWhtOverride:

    def _fixture(self, db_session, main_branch, *, wt_amount=100, with_wht_account=True):
        """One 1,000.00 no-VAT revenue line carrying `wt_amount` of WHT."""
        ar = make_account(db_session, '10201', 'Accounts Receivable - Trade')
        if with_wht_account:
            make_account(db_session, '10212', 'Creditable WHT Receivable')
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand')
        revenue = make_account(db_session, '4001', 'Sales Revenue',
                               account_type='Income', classification='Operating Revenue',
                               normal_balance='Credit')
        customer = make_customer(db_session)
        crv = build_crv(db_session, main_branch, customer, cash,
                        revenue_lines=[{
                            'description': 'Service',
                            'amount': 1000, 'line_total': 1000,
                            'vat_amount': Decimal('0.00'),
                            'account_id': revenue.id,
                            'wt_amount': Decimal(str(wt_amount)),
                        }], status='draft')
        return crv

    @staticmethod
    def _override(db_session, crv, value):
        """Apply a header WHT override exactly as `_apply_crv_overrides` does."""
        crv.wt_override = True
        crv.total_wt = Decimal(str(value))
        crv.calculate_totals()          # honors the flag; recomputes total_amount
        db_session.flush()
        return crv

    def test_wt_override_posts_header_total_to_wht_leg(self, db_session, admin_user, main_branch):
        """The 10212 leg must equal crv.total_wt, and cash must equal crv.total_amount."""
        from app.cash_receipts.views import _post_crv_je

        crv = self._fixture(db_session, main_branch, wt_amount=100)
        self._override(db_session, crv, 75)
        assert crv.total_amount == Decimal('925.00')   # 1000 - 75

        je = _post_crv_je(crv, admin_user.id)
        db_session.flush()

        assert _leg(je, '10212') == (Decimal('75.00'), Decimal('0.00'))
        assert _leg(je, '1001') == (Decimal('925.00'), Decimal('0.00'))
        assert je.is_balanced

    def test_wt_override_pure_no_line_wht_still_posts_leg(self, db_session, admin_user, main_branch):
        """A pure override (no line carries WHT) must still book the WHT leg."""
        from app.cash_receipts.views import _post_crv_je

        crv = self._fixture(db_session, main_branch, wt_amount=0)
        self._override(db_session, crv, 50)

        je = _post_crv_je(crv, admin_user.id)
        db_session.flush()

        assert _leg(je, '10212') == (Decimal('50.00'), Decimal('0.00'))
        assert _leg(je, '1001') == (Decimal('950.00'), Decimal('0.00'))

    def test_wt_override_pure_missing_10212_raises(self, db_session, admin_user, main_branch):
        """Fail loudly rather than silently absorbing the WHT into cash."""
        from app.cash_receipts.views import _post_crv_je

        crv = self._fixture(db_session, main_branch, wt_amount=0, with_wht_account=False)
        self._override(db_session, crv, 50)

        with pytest.raises(ValueError, match='Creditable Withholding Tax'):
            _post_crv_je(crv, admin_user.id)

    def test_wt_override_zero_suppresses_wht_leg(self, db_session, admin_user, main_branch):
        """Overriding to 0 must drop the WHT leg, not post the line sum."""
        from app.cash_receipts.views import _post_crv_je

        crv = self._fixture(db_session, main_branch, wt_amount=50)
        self._override(db_session, crv, 0)

        je = _post_crv_je(crv, admin_user.id)
        db_session.flush()

        assert _leg(je, '10212') is None
        assert _leg(je, '1001') == (Decimal('1000.00'), Decimal('0.00'))

    def test_no_override_posts_line_sum_wht(self, db_session, admin_user, main_branch):
        """Pin the non-override path: it must stay byte-identical to the old behavior.

        There is no positive-WHT CRV posting test anywhere else in the suite.
        """
        from app.cash_receipts.views import _post_crv_je

        crv = self._fixture(db_session, main_branch, wt_amount=50)
        assert crv.wt_override is False
        assert crv.total_wt == Decimal('50.00')

        je = _post_crv_je(crv, admin_user.id)
        db_session.flush()

        assert _leg(je, '10212') == (Decimal('50.00'), Decimal('0.00'))
        assert _leg(je, '1001') == (Decimal('950.00'), Decimal('0.00'))

    def test_preview_matches_posted_je_under_wt_override(self, db_session, admin_user, main_branch):
        """The draft preview the user sees must agree with what posting will book."""
        from app.cash_receipts.views import _build_crv_je_preview

        crv = self._fixture(db_session, main_branch, wt_amount=100)
        self._override(db_session, crv, 75)
        crv.journal_entry = None        # force the recompute branch, not the stored-JE branch

        rows = _build_crv_je_preview(crv)
        by_code = {r['code']: r for r in rows}

        assert by_code['10212']['debit'] == Decimal('75.00')
        assert by_code['1001']['debit'] == Decimal('925.00')
