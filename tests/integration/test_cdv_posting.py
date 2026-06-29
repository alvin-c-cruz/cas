"""Integration tests for CDV journal-entry posting (_post_cdv_je)."""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

pytestmark = [pytest.mark.integration]


def make_account(db_session, code, name, account_type='Asset',
                 classification='Current Asset', normal_balance='Debit'):
    acct = Account(code=code, name=name, account_type=account_type,
                   classification=classification, normal_balance=normal_balance,
                   is_active=True)
    db_session.add(acct)
    db_session.flush()
    return acct


def make_vendor(db_session, code='V001'):
    v = Vendor(code=code, name=f'Vendor {code}', is_active=True)
    db_session.add(v)
    db_session.flush()
    return v


def make_input_vat_category(db_session, code, rate, input_vat_account=None):
    cat = VATCategory(
        code=code, name=f'VAT {code}',
        rate=Decimal(str(rate)), is_active=True,
        input_vat_account_id=input_vat_account.id if input_vat_account else None,
    )
    db_session.add(cat)
    db_session.flush()
    return cat


def build_cdv(db_session, branch, vendor, cash_account,
              ap_lines=None, expense_lines=None, status='posted'):
    cdv = CashDisbursementVoucher(
        branch_id=branch.id,
        cdv_number='CD-2026-06-0001',
        cdv_date=date.today(),
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        payment_method='cash',
        cash_account_id=cash_account.id,
        notes='Test',
        status=status,
        total_ap_applied=Decimal('0.00'),
        total_expense=Decimal('0.00'),
        total_vat=Decimal('0.00'),
        total_wt=Decimal('0.00'),
        total_amount=Decimal('0.00'),
    )
    db_session.add(cdv)
    db_session.flush()

    for i, rl_kwargs in enumerate(expense_lines or [], start=1):
        el = CDVExpenseLine(
            cdv_id=cdv.id, line_number=i,
            description=rl_kwargs.get('description', 'Expense'),
            amount=Decimal(str(rl_kwargs.get('amount', 0))),
            vat_category=rl_kwargs.get('vat_category'),
            vat_rate=Decimal(str(rl_kwargs.get('vat_rate', 0))),
            line_total=Decimal(str(rl_kwargs.get('line_total', rl_kwargs.get('amount', 0)))),
            vat_amount=Decimal(str(rl_kwargs.get('vat_amount', 0))),
            account_id=rl_kwargs.get('account_id'),
            wt_amount=Decimal(str(rl_kwargs.get('wt_amount', 0))),
        )
        db_session.add(el)

    db_session.flush()
    db_session.refresh(cdv)
    cdv.calculate_totals()
    db_session.flush()
    return cdv


class TestCDVPosting:

    def _setup_base_accounts(self, db_session):
        ap = make_account(db_session, '20101', 'Accounts Payable - Trade',
                          account_type='Liability', classification='Current Liability',
                          normal_balance='Credit')
        wht_pay = make_account(db_session, '20301', 'WHT Payable - Expanded',
                               account_type='Liability', classification='Current Liability',
                               normal_balance='Credit')
        return ap, wht_pay

    def test_pure_negative_section_b_cdv(self, db_session, admin_user, main_branch):
        """Pure negative Section B (advance): Cr Expense 1000, Dr Cash 1000."""
        from app.cash_disbursements.views import _post_cdv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        expense_acct = make_account(db_session, '5001', 'Advance to Vendors',
                                    account_type='Asset', classification='Current Asset',
                                    normal_balance='Debit')
        vendor = make_vendor(db_session)

        cdv = build_cdv(db_session, main_branch, vendor, cash,
                        expense_lines=[{
                            'description': 'Advance applied',
                            'amount': -1000, 'line_total': -1000,
                            'vat_amount': 0, 'account_id': expense_acct.id,
                        }], status='posted')

        je = _post_cdv_je(cdv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"

        exp_line = next(l for l in je.lines if l.account_id == expense_acct.id)
        assert exp_line.credit_amount == Decimal('1000.00')
        assert exp_line.debit_amount == Decimal('0.00')

        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.debit_amount == Decimal('1000.00')
        assert cash_line.credit_amount == Decimal('0.00')

    def test_mixed_positive_negative_section_b_cdv(self, db_session, admin_user, main_branch):
        """Mixed +3000 and -1000 Section B: net cash credit = 2000."""
        from app.cash_disbursements.views import _post_cdv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        expense_acct = make_account(db_session, '5001', 'Expense',
                                    account_type='Expense', classification='Operating Expense',
                                    normal_balance='Debit')
        vendor = make_vendor(db_session, code='V002')

        cdv = build_cdv(db_session, main_branch, vendor, cash,
                        expense_lines=[
                            {'description': 'Expense', 'amount': 3000, 'line_total': 3000,
                             'vat_amount': 0, 'account_id': expense_acct.id},
                            {'description': 'Advance offset', 'amount': -1000, 'line_total': -1000,
                             'vat_amount': 0, 'account_id': expense_acct.id},
                        ], status='posted')

        je = _post_cdv_je(cdv, admin_user.id)
        db_session.commit()

        assert je.is_balanced
        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.credit_amount == Decimal('2000.00')
        assert cash_line.debit_amount == Decimal('0.00')

    def test_negative_section_b_with_vat_cdv(self, db_session, admin_user, main_branch):
        """Negative Section B line: bare abs(amount) only — no VAT extraction.
        Cr Expense 1120, Dr Cash 1120. No Input VAT line."""
        from app.cash_disbursements.views import _post_cdv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        expense_acct = make_account(db_session, '5001', 'Expense',
                                    account_type='Expense', classification='Operating Expense',
                                    normal_balance='Debit')
        input_vat_acct = make_account(db_session, '10301', 'Input VAT',
                                      account_type='Asset', classification='Current Asset',
                                      normal_balance='Debit')
        vendor = make_vendor(db_session, code='V003')
        make_input_vat_category(db_session, 'VAT12', rate=12, input_vat_account=input_vat_acct)

        # -1120 inclusive; new rule: post bare abs(amount), no VAT
        cdv = build_cdv(db_session, main_branch, vendor, cash,
                        expense_lines=[{
                            'description': 'Reversal w/ VAT',
                            'amount': -1120, 'line_total': -1120,
                            'vat_category': 'VAT12', 'vat_rate': 12,
                            'vat_amount': Decimal('-120.00'),
                            'account_id': expense_acct.id,
                        }], status='posted')
        cdv.total_vat = Decimal('-120.00')
        db_session.flush()

        je = _post_cdv_je(cdv, admin_user.id)
        db_session.commit()

        assert je.is_balanced

        # Bare abs(line_total) — no VAT extraction on negative lines
        exp_line = next(l for l in je.lines if l.account_id == expense_acct.id)
        assert exp_line.credit_amount == Decimal('1120.00')
        assert exp_line.debit_amount == Decimal('0.00')

        # No Input VAT line for negative lines
        je_lines = list(je.lines)
        vat_lines = [l for l in je_lines if l.account_id == input_vat_acct.id]
        assert len(vat_lines) == 0

        cash_line = next(l for l in je.lines if l.account_id == cash.id)
        assert cash_line.debit_amount == Decimal('1120.00')
        assert cash_line.credit_amount == Decimal('0.00')

    def test_negative_section_b_with_negative_wht_cdv(self, db_session, admin_user, main_branch):
        """Negative Section B: no WHT on negative lines — WHT line must be absent."""
        from app.cash_disbursements.views import _post_cdv_je

        _, wht_acct = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        expense_acct = make_account(db_session, '5001', 'Expense',
                                    account_type='Expense', classification='Operating Expense',
                                    normal_balance='Debit')
        vendor = make_vendor(db_session, code='V004')

        # -1000 gross with wt_amount=-20; new rule: negative lines have no WHT
        cdv = build_cdv(db_session, main_branch, vendor, cash,
                        expense_lines=[{
                            'description': 'Reversal w/ WHT',
                            'amount': -1000, 'line_total': -1000,
                            'vat_amount': 0, 'wt_amount': Decimal('-20.00'),
                            'account_id': expense_acct.id,
                        }], status='posted')
        db_session.flush()

        je = _post_cdv_je(cdv, admin_user.id)
        db_session.commit()

        assert je.is_balanced

        # No WHT line for negative lines
        wht_line = next((l for l in je.lines if l.account_id == wht_acct.id), None)
        assert wht_line is None

    def test_net_zero_vat_cancellation_cdv(self, db_session, admin_user, main_branch):
        """C1: +1120 and -1120 lines with same VAT category must not cancel Input VAT.
        After the parse fix, negative line vat_amount=0, so total_vat stays 120.
        Input VAT line must be posted; JE must be balanced."""
        from app.cash_disbursements.views import _post_cdv_je

        _, _ = self._setup_base_accounts(db_session)
        cash = make_account(db_session, '1001', 'Cash on Hand',
                            account_type='Asset', classification='Current Asset',
                            normal_balance='Debit')
        expense_acct = make_account(db_session, '5001', 'Expense',
                                    account_type='Expense', classification='Operating Expense',
                                    normal_balance='Debit')
        input_vat_acct = make_account(db_session, '10301', 'Input VAT',
                                      account_type='Asset', classification='Current Asset',
                                      normal_balance='Debit')
        vendor = make_vendor(db_session, code='V005')
        make_input_vat_category(db_session, 'VAT12', rate=12,
                                input_vat_account=input_vat_acct)

        # Positive line: VAT included, vat_amount=120
        # Negative line: vat_amount=0 (what the FIXED parse zeroes it to)
        cdv = build_cdv(db_session, main_branch, vendor, cash,
                        expense_lines=[
                            {
                                'description': 'Expense',
                                'amount': 1120, 'line_total': 1120,
                                'vat_category': 'VAT12', 'vat_rate': 12,
                                'vat_amount': Decimal('120.00'),
                                'account_id': expense_acct.id,
                            },
                            {
                                'description': 'Advance offset',
                                'amount': -1120, 'line_total': -1120,
                                'vat_category': 'VAT12', 'vat_rate': 12,
                                'vat_amount': Decimal('0.00'),  # fixed: negative line zeroed
                                'account_id': expense_acct.id,
                            },
                        ], status='posted')

        # total_vat must be 120 (positive only), not 0 (pre-fix bug)
        assert cdv.total_vat == Decimal('120.00'), (
            f'total_vat should be 120 (positive line only), got {cdv.total_vat}')

        je = _post_cdv_je(cdv, admin_user.id)
        db_session.commit()

        assert je.is_balanced, f"JE not balanced: dr={je.total_debit} cr={je.total_credit}"

        # Input VAT line must be present (C1 bug: it was absent because total_vat netted to 0)
        vat_line = next((l for l in je.lines if l.account_id == input_vat_acct.id), None)
        assert vat_line is not None, 'Input VAT JE line must be present for positive expense line'
        assert vat_line.debit_amount == Decimal('120.00')
