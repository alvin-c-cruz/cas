"""
Acceptance tests for the opening-balance feature (Task 8 / P-67).

These tests exercise EXISTING machinery — no new app code is expected.

  AC-5: test_input_vat_carry_over_opening_in_balance_as_of
    Posts an opening_balance JE that debits an Input Tax Carry Over asset
    account and verifies the balance appears in generate_trial_balance
    as-of the period start (the read P-65 VAT settlement will mirror).

  AC-4: test_mid_year_ytd_opening_close_ties_out
    Posts a mid-year opening with YTD P&L (revenue 8000 cr, expense 3000 dr,
    cash 5000 dr) dated 2025-06-30, then closes fiscal year 2025 and asserts:
      - IS net_income == 5000.0
      - Year-end close tie-out passes (close.net_income == IS net_income)
      - Full-year net income lands in Retained Earnings (code 30201)

CRITICAL: if either test FAILS, the failure is a real gap to discuss —
do NOT patch app code to make it pass (project rule).
"""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.reports.financial import generate_trial_balance

pytestmark = [pytest.mark.integration]

# Reuse helpers from the main integration module.
from tests.integration.test_opening_balances import (
    _login, _select_branch, _save_payload, _make_postable,
)


def test_input_vat_carry_over_opening_in_balance_as_of(
        client, db_session, admin_user, main_branch, revenue_account):
    """AC-5: Input Tax Carry Over opening debit appears in the as-of balance read.

    The trial_balance row keys are 'debit_balance' / 'credit_balance' (confirmed in
    generate_trial_balance in app/reports/financial.py).
    """
    # --- Arrange ---
    # Create carry-over account (asset) with a parent so it is a postable leaf.
    carry_parent = Account(
        code='GRP-1190', name='Input VAT Group',
        account_type='Asset', normal_balance='Debit', is_active=True,
    )
    db.session.add(carry_parent)
    db.session.flush()
    carry = Account(
        code='1190', name='Input Tax Carry Over',
        account_type='Asset', normal_balance='Debit',
        is_active=True, parent_id=carry_parent.id,
    )
    db.session.add(carry)
    db.session.commit()

    # revenue_account from conftest is top-level (no parent_id) → group; give it a parent.
    _make_postable(db_session, revenue_account)

    # --- Act ---
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    # Opening balance: carry-over asset debit 5000, revenue credit 5000 (balanced).
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (carry.id, '5000.00', '0'),
        (revenue_account.id, '0', '5000.00'),
    ]))
    client.post('/opening-balances/post')

    # --- Assert ---
    # Trial balance as-of period end includes the opening entry (entry_date <= as_of_date).
    tb = generate_trial_balance(as_of_date=date(2026, 1, 31), branch_id=main_branch.id)
    row = next((r for r in tb['accounts'] if r['code'] == '1190'), None)
    assert row is not None, (
        "Input Tax Carry Over (code 1190) not found in trial balance — "
        "opening_balance entry is not included in the as-of balance read."
    )
    # carry is a debit-normal Asset: net balance = debit_sum - credit_sum = 5000 > 0
    # → debit_balance = 5000, credit_balance = 0.
    assert float(row['debit_balance']) == 5000.0, (
        f"Expected debit_balance=5000.0 for carry-over account, got {row['debit_balance']!r}. "
        f"Full row: {row}"
    )


def test_mid_year_ytd_opening_close_ties_out(client, db_session, admin_user, main_branch):
    """AC-4: Mid-year YTD P&L opening → year-end close tie-out holds.

    generate_income_statement signature: (start_date, end_date, branch_id=None)
    service.close_fiscal_year(year, user_id) → list[FiscalYearClose]

    Uses year 2025 (today 2026-07-01 > Dec 31 2025, so assert_closeable passes).
    """
    from app.year_end import service
    from app.reports.financial import generate_income_statement

    # --- Arrange ---
    # Accounts with proper IS_TYPES so year-end nominal_balances picks them up.
    # RE (30201) and Income Summary (30301) are required by close_fiscal_year by exact code.
    re = Account(code='30201', name='Retained Earnings', account_type='Equity',
                 normal_balance='Credit', is_active=True)
    isum = Account(code='30301', name='Current-Year Earnings', account_type='Equity',
                   normal_balance='Credit', is_active=True)
    cash = Account(code='10101', name='Cash', account_type='Asset',
                   normal_balance='Debit', is_active=True)
    rev = Account(code='40001', name='Service Revenue', account_type='Revenue',
                  normal_balance='Credit', is_active=True)
    exp = Account(code='50201', name='Rent Expense', account_type='Administrative Expense',
                  normal_balance='Debit', is_active=True)
    db.session.add_all([re, isum, cash, rev, exp])
    db.session.flush()

    # Only the accounts that appear in the opening JE need to be postable leaves.
    # RE and isum are not in the opening entry; year-end service addresses them directly.
    _make_postable(db_session, cash, rev, exp)

    # --- Act: post mid-year opening ---
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    # Revenue 8000 cr, Expense 3000 dr, Cash 5000 dr → balanced (8000 = 8000).
    # Net income = 8000 - 3000 = 5000.
    client.post('/opening-balances/save', data=_save_payload('2025-06-30', [
        (cash.id, '5000.00', '0'),
        (exp.id, '3000.00', '0'),
        (rev.id, '0', '8000.00'),
    ]))
    client.post('/opening-balances/post')

    # --- Assert: IS includes the opening P&L ---
    # _period_balance excludes only 'closing'/'closing_reversal' entry types —
    # 'opening_balance' is included, so revenue and expense are counted in the IS.
    is_2025 = generate_income_statement(
        date(2025, 1, 1), date(2025, 12, 31), branch_id=main_branch.id,
    )
    assert float(is_2025['net_income']) == 5000.0, (
        f"Expected IS net_income=5000.0 for 2025, got {is_2025['net_income']}. "
        "Opening P&L may not be included in the Income Statement."
    )

    # --- Act: year-end close ---
    # assert_closeable: Dec 31 2025 <= today (2026-07-01) ✓; no prior year data ✓.
    closes = service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    assert len(closes) == 1, f"Expected 1 branch close record, got {len(closes)}"
    close = closes[0]

    # --- Assert: tie-out ---
    expected_net = Decimal(str(is_2025['net_income']))
    assert close.net_income == expected_net, (
        f"Year-end close net_income ({close.net_income}) does not match "
        f"IS net_income ({expected_net}) — internal tie-out FAILED. "
        "This is a real gap to discuss (not to patch inline)."
    )

    # --- Assert: net income landed in Retained Earnings ---
    # Closing JE3: dr Income Summary 5000, cr Retained Earnings 5000.
    # RE net (debit - credit) should be -5000 (credit balance of 5000).
    d_re, c_re = service._posted_sums(re.id, date(2025, 12, 31), main_branch.id)
    assert (d_re - c_re) == Decimal('-5000.00'), (
        f"Expected Retained Earnings net (d-c) = -5000.00, got {d_re - c_re}. "
        "Net income may not have landed in RE."
    )
