"""
Payroll calculation engine — statutory rate lookups and helpers.

All monetary values are Decimal, quantized to 2 places with ROUND_HALF_UP.
Lookups are fail-closed: they raise ValueError with friendly messages when no
effective row covers the requested date, never returning None silently.
"""

from decimal import Decimal, ROUND_HALF_UP
from app.payroll.tables_models import (
    SSSContributionTable, SSSContributionRow, PhilHealthRate,
    PagIbigRate, CompensationWHTBracket)
from app.posting.control_accounts import get_control_account, ControlAccountError   # noqa: F401 (re-exported)


def _q2(x):
    """Quantize a monetary value to 2 decimal places (ROUND_HALF_UP)."""
    return Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _effective(model, as_of):
    """Find the effective row for a given date.

    Returns the most recent row whose effective_from <= as_of and either
    effective_to is NULL or effective_to >= as_of. Returns None if no row
    covers the date.
    """
    return (model.query
            .filter(model.effective_from <= as_of)
            .filter((model.effective_to.is_(None)) | (model.effective_to >= as_of))
            .order_by(model.effective_from.desc()).first())


def effective_sss(as_of):
    """Fetch the SSS contribution table effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        SSSContributionTable with rows populated

    Raises:
        ValueError: if no SSS table is effective on as_of
    """
    tbl = _effective(SSSContributionTable, as_of)
    if tbl is None:
        raise ValueError(f"No SSS contribution table effective {as_of}. "
                         "Seed or assign the 2026 statutory tables first.")
    return tbl


def sss_row_for(tbl, monthly_comp):
    """Find the SSS contribution row matching a monthly compensation.

    Searches the table's rows (ordered ascending by comp_from) for the bracket
    containing monthly_comp. If monthly_comp is BELOW the lowest bracket's floor
    (comp_from), returns the lowest bracket (rows[0]). If monthly_comp is ABOVE
    every bracket's range (i.e. above the top, open-ended bracket's floor),
    returns the top bracket (rows[-1], comp_to is None).

    Args:
        tbl: SSSContributionTable
        monthly_comp: Decimal monthly compensation

    Returns:
        SSSContributionRow matching the salary bracket
    """
    for r in tbl.rows:
        if monthly_comp >= r.comp_from and (r.comp_to is None or monthly_comp <= r.comp_to):
            return r
    if monthly_comp < tbl.rows[0].comp_from:
        return tbl.rows[0]   # below the lowest bracket's floor -> lowest bracket
    return tbl.rows[-1]   # above all brackets -> top open bracket (comp_to is None)


def effective_philhealth(as_of):
    """Fetch the PhilHealth rate effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        PhilHealthRate

    Raises:
        ValueError: if no PhilHealth rate is effective on as_of
    """
    r = _effective(PhilHealthRate, as_of)
    if r is None:
        raise ValueError(f"No PhilHealth rate effective {as_of}.")
    return r


def effective_pagibig(as_of):
    """Fetch the Pag-IBIG rate effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        PagIbigRate

    Raises:
        ValueError: if no Pag-IBIG rate is effective on as_of
    """
    r = _effective(PagIbigRate, as_of)
    if r is None:
        raise ValueError(f"No Pag-IBIG rate effective {as_of}.")
    return r


def effective_wht_bracket(frequency, taxable, as_of):
    """Fetch the compensation WHT bracket matching frequency and taxable amount.

    Searches the CompensationWHTBracket table for rows of the given frequency
    effective on as_of (ordered ascending by bracket_no), then finds the bracket
    containing taxable. If taxable is BELOW the lowest bracket's floor
    (lower_bound), returns the lowest bracket (rows[0]). If taxable is ABOVE
    every bracket's range (i.e. above the top, open-ended bracket's floor),
    returns the top bracket (rows[-1], upper_bound is None).

    Args:
        frequency: bracket frequency (e.g., 'daily', 'weekly', 'monthly')
        taxable: Decimal taxable income
        as_of: date to look up

    Returns:
        CompensationWHTBracket matching the amount and frequency

    Raises:
        ValueError: if no bracket is effective for the frequency on as_of
    """
    rows = (CompensationWHTBracket.query
            .filter_by(frequency=frequency)
            .filter(CompensationWHTBracket.effective_from <= as_of)
            .filter((CompensationWHTBracket.effective_to.is_(None)) |
                    (CompensationWHTBracket.effective_to >= as_of))
            .order_by(CompensationWHTBracket.bracket_no).all())
    if not rows:
        raise ValueError(f"No {frequency} compensation WHT bracket effective {as_of}.")
    for b in rows:
        if taxable >= b.lower_bound and (b.upper_bound is None or taxable <= b.upper_bound):
            return b
    if taxable < rows[0].lower_bound:
        return rows[0]   # below the lowest bracket's floor -> lowest bracket
    return rows[-1]   # above all brackets -> top open bracket (upper_bound is None)


def compute_statutory(monthly_basis, as_of):
    """Compute SSS, PhilHealth, and Pag-IBIG contributions for a monthly basis.

    Pure function: reads the effective statutory tables via the effective_*/
    sss_row_for lookups above and combines them into actual contribution
    amounts (employee and employer shares). No DB writes.

    Args:
        monthly_basis: Decimal monthly compensation basis
        as_of: date to look up effective statutory rates for

    Returns:
        dict with Decimal values (all _q2-quantized):
        {sss_ee, sss_er, sss_ec, philhealth_ee, philhealth_er,
         pagibig_ee, pagibig_er, sss_msc}
    """
    sss_tbl = effective_sss(as_of)
    r = sss_row_for(sss_tbl, monthly_basis)

    ph = effective_philhealth(as_of)
    clamped = min(max(monthly_basis, ph.income_floor), ph.income_ceiling)
    ph_total = _q2(clamped * ph.premium_rate)
    ph_ee = _q2(ph_total * ph.ee_share)

    pi = effective_pagibig(as_of)
    base = min(monthly_basis, pi.mc_ceiling)
    ee_rate = pi.lower_ee_rate if monthly_basis <= pi.bracket_threshold else pi.upper_ee_rate

    return {
        'sss_msc': r.msc,
        'sss_ee': _q2(r.ee_amount + r.ee_wisp),
        'sss_er': _q2(r.er_amount + r.er_wisp),
        'sss_ec': _q2(r.ec_amount),
        'philhealth_ee': ph_ee,
        'philhealth_er': _q2(ph_total - ph_ee),
        'pagibig_ee': _q2(base * ee_rate),
        'pagibig_er': _q2(base * pi.er_rate),
    }


def compute_line(inputs):
    """Compute a full payroll line: gross, statutory, taxable comp, WHT, net pay.

    Pure function: dict-in/dict-out, no ORM objects as input, no DB writes
    beyond the read-only statutory-table lookups made by compute_statutory/
    effective_wht_bracket.

    Args:
        inputs: plain dict (no ORM) with keys:
            pay_basis ('monthly'/'daily'), monthly_rate, daily_rate (daily
            basis only -- defaults to monthly_rate if absent), days, hours,
            ot_pay, holiday_pay, taxable_allowance, nontax_allowance, is_mwe,
            pay_frequency ('monthly'/'semi_monthly'/'weekly'/'daily'),
            period_end (date), semi_timing
            ('second_cutoff'/'split_50_50'/'first_cutoff'), semi_period
            (1 or 2 -- semi-monthly only, read by _semi_applies_statutory).
            sss_loan_amortization, sss_loan_balance, pagibig_loan_amortization,
            pagibig_loan_balance (Task 11, all OPTIONAL -- default 0/absent
            means "no active loan of that type", exactly like every caller
            before Task 11 that never passes these keys at all; backward
            compatible with every pre-Task-11 call site).

    Returns:
        dict with Decimal values (all _q2-quantized):
        {basic_gross, gross_pay, statutory, taxable_comp, wht, wht_bracket_id,
         net_pay, sss_msc, sss_loan, pagibig_loan}
        'statutory' is the full dict returned by compute_statutory -- it is
        ALWAYS fully computed regardless of semi-monthly timing (compute_statutory
        has no notion of timing); only the EE amount folded into taxable_comp/
        net_pay is conditionally suppressed via _semi_applies_statutory.
        'sss_loan'/'pagibig_loan' are each min(amortization, balance), clamped
        at 0.00 -- a loan in its final month may owe less than a full
        scheduled amortization (balance < amortization), and a fully paid-off
        loan (balance=0) deducts exactly 0.00, never negative, never an error.

    MWE (minimum-wage earner) employees are WHT-exempt (taxable_comp = 0) but
    SSS/PhilHealth/Pag-IBIG still apply -- the MWE branch below only zeroes
    taxable_comp/wht, never the statutory dict or the 'ee' amount folded into
    net_pay. Loan amortization is deducted from net_pay the same way for MWE
    and non-MWE employees alike -- MWE exemption is a WHT-only concept.
    """
    freq = inputs['pay_frequency']
    as_of = inputs['period_end']
    rate = Decimal(inputs['monthly_rate'] or 0)
    if inputs['pay_basis'] == 'monthly':
        basic = rate if freq != 'semi_monthly' else _q2(rate / 2)
        monthly_basis = rate
    else:  # daily
        daily_rate = Decimal(inputs.get('daily_rate', rate) or 0)
        basic = _q2(daily_rate * Decimal(inputs['days'] or 0))
        monthly_basis = _q2(daily_rate * 22)   # statutory basis proxy for daily

    gross = _q2(basic + Decimal(inputs['ot_pay'] or 0) + Decimal(inputs['holiday_pay'] or 0)
                + Decimal(inputs['taxable_allowance'] or 0) + Decimal(inputs['nontax_allowance'] or 0))

    st = compute_statutory(monthly_basis, as_of)
    apply_stat = _semi_applies_statutory(freq, inputs['semi_timing'], inputs)
    ee = (st['sss_ee'] + st['philhealth_ee'] + st['pagibig_ee']) if apply_stat else Decimal('0.00')

    if inputs['is_mwe']:
        taxable = Decimal('0.00')
    else:
        taxable = _q2(gross - Decimal(inputs['nontax_allowance'] or 0) - ee)
        taxable = max(taxable, Decimal('0.00'))

    if inputs['is_mwe'] or taxable <= 0:
        wht, bracket_id = Decimal('0.00'), None
    else:
        b = effective_wht_bracket(freq, taxable, as_of)
        wht = _q2(b.base_tax + (taxable - b.lower_bound) * b.rate_on_excess)
        bracket_id = b.id

    sss_loan = _capped_loan_deduction(
        inputs.get('sss_loan_amortization', 0), inputs.get('sss_loan_balance', 0))
    pagibig_loan = _capped_loan_deduction(
        inputs.get('pagibig_loan_amortization', 0), inputs.get('pagibig_loan_balance', 0))

    net = _q2(gross - ee - wht - sss_loan - pagibig_loan)

    return {
        'basic_gross': basic,
        'gross_pay': gross,
        'statutory': st,
        'taxable_comp': taxable,
        'wht': wht,
        'wht_bracket_id': bracket_id,
        'sss_loan': sss_loan,
        'pagibig_loan': pagibig_loan,
        'net_pay': net,
        'sss_msc': st['sss_msc'],
    }


def _capped_loan_deduction(amortization, balance):
    """min(amortization, balance), clamped at 0.00.

    The clamp-at-0 matters for two edge cases: balance == 0 (fully paid off --
    min(amortization, 0) is already 0, the clamp is redundant but explicit)
    and a defensively-impossible negative balance (min() alone would return
    the negative balance, which would INCREASE net pay -- never correct)."""
    amortization = Decimal(amortization or 0)
    balance = Decimal(balance or 0)
    return max(Decimal('0.00'), _q2(min(amortization, balance)))


def _semi_applies_statutory(freq, timing, inputs):
    """Decide whether statutory (SSS/PhilHealth/Pag-IBIG) EE deductions apply
    on THIS cutoff, per the payroll_semi_monthly_timing setting.

    Non-semi-monthly frequencies always apply statutory (there's only one
    cutoff per period). For semi-monthly:
      - 'split_50_50': applies on BOTH cutoffs. This function only decides
        whether it applies, not how much -- a caller relying on split_50_50
        for a true 50/50 split is responsible for passing already-halved
        inputs (e.g. a halved monthly_rate); otherwise the full EE amount is
        folded in on each cutoff.
      - 'first_cutoff' / 'second_cutoff': applies only on the matching
        semi_period (1 or 2, from inputs['semi_period']).
    """
    if freq != 'semi_monthly':
        return True
    if timing == 'split_50_50':
        return True   # half applied each cutoff -- caller passes halved amounts if desired
    cutoff = inputs.get('semi_period')  # 1 or 2
    return (timing == 'first_cutoff' and cutoff == 1) or \
           (timing == 'second_cutoff' and cutoff == 2)


def post_payroll_je(run):
    """Build the balanced payroll accrual JE from a PayrollRun's header
    total_* buckets.

    Every non-plug leg is written straight from a header bucket, resolving
    its GL account via get_control_account(key) -- never a hardcoded code
    (fail-closed: raises ControlAccountError, a ValueError subclass, if a key
    is unassigned or its assigned code has no matching account). WISP is
    already folded into total_sss_ee/total_sss_er by compute_statutory, so no
    separate WISP leg exists.

    The 20501 (Accrued Salaries and Wages) credit leg is the GUARDED plug:
    computed as SUM(Dr) - SUM(Cr) of every other leg and asserted equal to
    run.total_net_pay BEFORE being written -- it must never silently absorb a
    per-bucket error (posted-je-leg-vs-source-header-invariant). Raises
    ValueError if the plug doesn't tie to net pay, or if the resulting entry
    isn't balanced.

    Args:
        run: PayrollRun with calculate_totals() already applied (its
            total_* columns populated).

    Returns:
        JournalEntry (flushed but not committed -- caller commits).

    Raises:
        ControlAccountError: a required payroll_* control account key is
            unassigned or misassigned.
        ValueError: the computed plug doesn't equal run.total_net_pay, or the
            entry doesn't balance.
    """
    from app import db
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number

    je_status = 'posted' if run.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(run.branch_id),
        entry_date=run.pay_date,
        description=f'Payroll Accrual — {run.run_number}',
        reference=run.run_number,
        entry_type='payroll_accrual',
        branch_id=run.branch_id,
        created_by_id=run.created_by_id,
        status=je_status,
        posted_by_id=run.posted_by_id if je_status == 'posted' else None,
        posted_at=run.posted_at if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    all_lines = []

    def _add_line(key, description, amount, side):
        nonlocal line_num
        amount = _q2(amount)
        if amount == Decimal('0.00'):
            return   # nothing to post for this bucket (e.g. no employee has an
                     # active loan this run, or 13th-month -- P3, not yet wired)
        account = get_control_account(key)
        dr = amount if side == 'debit' else Decimal('0.00')
        cr = amount if side == 'credit' else Decimal('0.00')
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=account.id,
            description=description, debit_amount=dr, credit_amount=cr,
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        line_num += 1

    # Debit legs: employer-side expense
    _add_line('payroll_salaries_expense',
              f'Salaries Expense — {run.run_number}',
              run.total_gross, 'debit')
    _add_line('payroll_sss_er_expense',
              f'SSS Employer Share — {run.run_number}',
              run.total_sss_er + run.total_sss_ec, 'debit')
    _add_line('payroll_philhealth_er_expense',
              f'PhilHealth Employer Share — {run.run_number}',
              run.total_philhealth_er, 'debit')
    _add_line('payroll_pagibig_er_expense',
              f'Pag-IBIG Employer Share — {run.run_number}',
              run.total_pagibig_er, 'debit')

    # Credit legs: payables (EE + ER combined where both share one control account)
    _add_line('payroll_wht_payable',
              f'Withholding Tax on Compensation Payable — {run.run_number}',
              run.total_wht, 'credit')
    _add_line('payroll_sss_payable',
              f'SSS Contributions Payable — {run.run_number}',
              run.total_sss_ee + run.total_sss_er + run.total_sss_ec, 'credit')
    _add_line('payroll_philhealth_payable',
              f'PhilHealth Contributions Payable — {run.run_number}',
              run.total_philhealth_ee + run.total_philhealth_er, 'credit')
    _add_line('payroll_pagibig_payable',
              f'Pag-IBIG Contributions Payable — {run.run_number}',
              run.total_pagibig_ee + run.total_pagibig_er, 'credit')
    _add_line('payroll_sss_loan_payable',
              f'SSS Loan Payable — {run.run_number}',
              run.total_sss_loan, 'credit')
    _add_line('payroll_pagibig_loan_payable',
              f'Pag-IBIG Loan Payable — {run.run_number}',
              run.total_pagibig_loan, 'credit')

    # Guarded plug: net pay MUST equal Dr - Cr of every other leg above --
    # never absorbed silently. Assert BEFORE writing the 20501 line.
    sum_dr = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_cr = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    plug = _q2(sum_dr - sum_cr)
    expected_net_pay = _q2(run.total_net_pay)
    if plug != expected_net_pay:
        raise ValueError(
            f"Payroll accrual plug ({plug}) does not equal run.total_net_pay "
            f"({expected_net_pay}) for run {run.run_number} -- the Accrued "
            f"Salaries leg was NOT posted. This means the header buckets "
            f"don't reconcile to net pay; check the run's totals before "
            f"posting."
        )

    accrued_account = get_control_account('payroll_accrued_salaries')
    plug_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num, account_id=accrued_account.id,
        description=f'Accrued Salaries and Wages — {run.run_number}',
        debit_amount=Decimal('0.00'), credit_amount=plug,
    )
    db.session.add(plug_line)
    all_lines.append(plug_line)

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"Payroll JE is not balanced (debit={je.total_debit}, "
            f"credit={je.total_credit}) for run {run.run_number}."
        )
    return je


def apply_loan_balances(run):
    """Decrement each EmployeeLoan referenced by `run`'s lines by the amount
    already computed and stored on that line (line.sss_loan/pagibig_loan --
    each already min(amortization, balance)-capped by compute_line as of the
    line's last calculate_amounts() call).

    Called exactly once, from payroll.views.post_run, INSIDE the transaction
    already protected by that route's claim_version lock on the PayrollRun
    itself (post_run claims the run's row_version before doing anything else).
    Idempotency across repeated calls is NOT this function's job -- it is the
    caller's single-call-per-post contract (mirrors post_payroll_je, which
    likewise assumes it is called exactly once per post).

    The decrement is a single SQL-side UPDATE (balance = balance - amount),
    not a Python read/subtract/reassign -- this closes the classic lost-update
    race for the arithmetic itself even without a per-loan optimistic lock:
    SQLite serializes writers, so two concurrent UPDATEs against the SAME
    EmployeeLoan row apply correctly one after another rather than one
    clobbering the other's read.

    KNOWN GAP, deliberately left open (see task-11-report.md): the AMOUNT
    being applied here was capped against the loan's balance back at
    calculate_amounts() time (whenever the draft was last saved/edited), not
    re-verified against the loan's CURRENT balance at this post moment. Two
    DIFFERENT payroll runs referencing the SAME employee's SAME loan, posted
    concurrently, could each independently cap against a balance snapshot
    that is already stale by the time this update runs -- the atomic UPDATE
    prevents the WRITE from being lost, but not a logically-stale CAP computed
    earlier by a different run. A single run's post/cancel cycle (the only
    thing this task builds and tests) cannot hit this. Flagged for a later
    task if it proves necessary in practice (e.g. a claim_version-style guard
    on EmployeeLoan itself, or re-clamping against a freshly-read balance at
    post time and re-syncing the run's total_sss_loan/total_pagibig_loan
    header buckets + the already-guarded JE plug to match).

    Args:
        run: PayrollRun being posted, with its lines' sss_loan/pagibig_loan/
            sss_loan_id/pagibig_loan_id already populated.
    """
    from app import db
    from app.payroll.models import EmployeeLoan

    for line in run.lines:
        if line.sss_loan_id and line.sss_loan and line.sss_loan > 0:
            db.session.execute(
                db.update(EmployeeLoan)
                .where(EmployeeLoan.id == line.sss_loan_id)
                .values(balance=EmployeeLoan.balance - line.sss_loan)
            )
        if line.pagibig_loan_id and line.pagibig_loan and line.pagibig_loan > 0:
            db.session.execute(
                db.update(EmployeeLoan)
                .where(EmployeeLoan.id == line.pagibig_loan_id)
                .values(balance=EmployeeLoan.balance - line.pagibig_loan)
            )


def restore_loan_balances(run):
    """Reverse apply_loan_balances(run): increments each referenced loan's
    balance back by the EXACT amount stored on the line -- never recomputed
    fresh. A loan's monthly_amortization could have been edited between post
    and cancel; re-deriving the reversal amount from TODAY's rate/balance
    would drift from what was actually decremented at post. Using the SAME
    stored line.sss_loan/pagibig_loan value for both apply and restore is
    what makes the round trip exact.

    Called exactly once, from payroll.views.cancel_run (a posted run being
    cancelled), inside the same transaction as the reversal JE. Also uses an
    atomic SQL-side UPDATE, for the same lost-update-avoidance reason as
    apply_loan_balances.

    NOT called from void_run: void_run's precondition (run.status == 'draft')
    makes it structurally impossible for a draft's loan balances to have ever
    been decremented -- apply_loan_balances only ever runs from post_run,
    which requires draft status to even begin (and flips it to 'posted' as
    its very first write). A draft run's lines DO carry computed
    sss_loan/pagibig_loan preview amounts (calculate_amounts() runs on every
    draft save), so calling restore here would incorrectly CREDIT a balance
    that was never debited -- unlike CDV's defensive JE-delete-if-present in
    void_run (harmless because a draft never has a real JE), this is not a
    safe no-op to add "just in case."

    Args:
        run: PayrollRun being cancelled, still carrying the lines/FKs/amounts
            from when it was posted.
    """
    from app import db
    from app.payroll.models import EmployeeLoan

    for line in run.lines:
        if line.sss_loan_id and line.sss_loan and line.sss_loan > 0:
            db.session.execute(
                db.update(EmployeeLoan)
                .where(EmployeeLoan.id == line.sss_loan_id)
                .values(balance=EmployeeLoan.balance + line.sss_loan)
            )
        if line.pagibig_loan_id and line.pagibig_loan and line.pagibig_loan > 0:
            db.session.execute(
                db.update(EmployeeLoan)
                .where(EmployeeLoan.id == line.pagibig_loan_id)
                .values(balance=EmployeeLoan.balance + line.pagibig_loan)
            )


def build_je_preview(run):
    """Read-only preview of the payroll accrual JE this run would produce if
    post_payroll_je() ran right now, built from the run's CURRENT header
    total_* buckets.

    Mirrors post_payroll_je's leg-construction shape (same buckets, same
    order) but is a pure read/render helper:
      - never persists anything -- no JournalEntry/JournalEntryLine created,
        no db.session writes at all;
      - resolves every account via get_control_account(key, required=False),
        so an unassigned control account yields a row with account=None
        (the caller/template renders a friendly placeholder) instead of
        raising ControlAccountError;
      - never asserts/raises on the plug tying to run.total_net_pay -- this
        is a preview, not a post. post_payroll_je() still enforces that
        guard for real (Task 10's job to call it).

    Args:
        run: PayrollRun with calculate_totals() already applied (its
            total_* columns populated).

    Returns:
        dict: {
            'rows': [{'key', 'label', 'account' (Account|None), 'debit',
                      'credit'}, ...],
            'total_debit': Decimal, 'total_credit': Decimal,
            'balanced': bool (total_debit == total_credit -- true by
                construction here, since the plug is computed as their
                difference before being appended),
            'net_pay_plug': Decimal (the Accrued Salaries credit leg --
                compare against run.total_net_pay to see whether the header
                buckets currently reconcile to net pay).
        }
        Zero-amount buckets are omitted from 'rows' (mirrors post_payroll_je's
        _add_line skip) except the final Accrued Salaries plug row, which
        always appears.
    """
    rows = []

    def _row(key, label, amount, side):
        amount = _q2(amount)
        if amount == Decimal('0.00'):
            return   # nothing to preview for this bucket (e.g. no employee has an
                     # active loan this run, or 13th-month -- P3, not yet wired)
        account = get_control_account(key, required=False)
        rows.append({
            'key': key, 'label': label, 'account': account,
            'debit': amount if side == 'debit' else Decimal('0.00'),
            'credit': amount if side == 'credit' else Decimal('0.00'),
        })

    # Debit legs: employer-side expense (same order as post_payroll_je)
    _row('payroll_salaries_expense', 'Salaries Expense', run.total_gross, 'debit')
    _row('payroll_sss_er_expense', 'SSS Employer Share Expense',
         run.total_sss_er + run.total_sss_ec, 'debit')
    _row('payroll_philhealth_er_expense', 'PhilHealth Employer Share Expense',
         run.total_philhealth_er, 'debit')
    _row('payroll_pagibig_er_expense', 'Pag-IBIG Employer Share Expense',
         run.total_pagibig_er, 'debit')

    # Credit legs: payables
    _row('payroll_wht_payable', 'Withholding Tax on Compensation Payable',
         run.total_wht, 'credit')
    _row('payroll_sss_payable', 'SSS Contributions Payable',
         run.total_sss_ee + run.total_sss_er + run.total_sss_ec, 'credit')
    _row('payroll_philhealth_payable', 'PhilHealth Contributions Payable',
         run.total_philhealth_ee + run.total_philhealth_er, 'credit')
    _row('payroll_pagibig_payable', 'Pag-IBIG Contributions Payable',
         run.total_pagibig_ee + run.total_pagibig_er, 'credit')
    _row('payroll_sss_loan_payable', 'SSS Loan Payable', run.total_sss_loan, 'credit')
    _row('payroll_pagibig_loan_payable', 'Pag-IBIG Loan Payable',
         run.total_pagibig_loan, 'credit')

    # Guarded-in-spirit-only plug: unlike post_payroll_je, this preview never
    # raises if it doesn't tie to run.total_net_pay -- it just shows whatever
    # the header buckets currently compute, so a caller (the detail view) can
    # render a live preview of a still-editable draft.
    sum_dr = sum((r['debit'] for r in rows), Decimal('0.00'))
    sum_cr = sum((r['credit'] for r in rows), Decimal('0.00'))
    plug = _q2(sum_dr - sum_cr)
    accrued_account = get_control_account('payroll_accrued_salaries', required=False)
    rows.append({
        'key': 'payroll_accrued_salaries', 'label': 'Accrued Salaries and Wages',
        'account': accrued_account, 'debit': Decimal('0.00'), 'credit': plug,
    })

    total_debit = sum((r['debit'] for r in rows), Decimal('0.00'))
    total_credit = sum((r['credit'] for r in rows), Decimal('0.00'))
    return {
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'balanced': total_debit == total_credit,
        'net_pay_plug': plug,
    }


def build_payroll_reversal_je(run, reversal_date, user_id):
    """Post a Dr<->Cr swapped reversal of a payroll run's accrual JE (cancel).

    Mirrors cash_disbursements._create_cdv_reversal_je: every leg from the
    original accrual JE (run.journal_entry) is copied onto a NEW JournalEntry
    with debit_amount and credit_amount swapped -- so an Expense-debit leg
    becomes a credit and a Payable-credit leg becomes a debit, exactly undoing
    the original accrual. The reversal is a General Journal entry (uses
    generate_jv_number, like CDV's cancel reversal), posts immediately
    (status='posted'), and is dated `reversal_date` -- the caller is
    responsible for having already confirmed that date's accounting period is
    open (mirrors CDV's cancel route checking the reversal date before calling
    this).

    Args:
        run: PayrollRun -- expected 'posted' with a linked journal_entry.
        reversal_date: date the reversal JE posts on.
        user_id: acting user -- recorded as both created_by and posted_by
            (the reversal posts immediately, same as CDV's cancel).

    Returns:
        JournalEntry (flushed but not committed -- caller commits).

    Raises:
        ValueError: run has no linked journal entry to reverse.
    """
    from app import db
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_jv_number
    from app.utils import ph_now

    source_je = run.journal_entry
    if source_je is None:
        raise ValueError(f'Payroll run {run.run_number} has no journal entry to reverse.')

    entry_number = generate_jv_number(run.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Payroll Cancel — {run.run_number} (reversal)',
        reference=f'CANCEL-{run.run_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=run.branch_id,
        created_by_id=user_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    for i, src in enumerate(source_je.lines.all(), start=1):
        rev = JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'Cancel: {src.description}',
            debit_amount=src.credit_amount,
            credit_amount=src.debit_amount,
        )
        db.session.add(rev)

    db.session.flush()
    je.calculate_totals()
    return je
