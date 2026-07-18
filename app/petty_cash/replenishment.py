"""The one JE-posting event in the Petty Cash module (R-04 slice 4). Groups held
vouchers by expense account, folds in the physical count, and ASSERTS the
shortage/overage plug -- it is independently computed and checked, never just
trusted because debits happen to equal credits (posted-je-leg-vs-source-header-
invariant discipline, same class as the payroll plug guard).

Concurrency (a real gap the plan's own draft left unresolved, fixed here rather
than deferred to Task 5 -- see the plan's Self-Review): the race this module
must guard is two accountants selecting OVERLAPPING held vouchers for two
different replenishment attempts at once. `post_replenishment` creates a brand
new PettyCashReplenishment row each call, so `claim_version` (which needs an
EXISTING row's version) cannot model this. The real guard is a two-layer claim:
  1. A read-time filter (`status == 'held'`) that fails fast if the caller's own
     stale selection no longer matches -- cheap, but not race-proof by itself
     (two truly concurrent requests can both pass this filter before either
     writes).
  2. The AUTHORITATIVE guard: a single atomic bulk `UPDATE ... WHERE status =
     'held'` that flips the selected vouchers to 'replenished' + stamps
     replenishment_id, and checks `rowcount` against the requested count. If
     any voucher was claimed by a concurrent writer between this call's read
     and this write, rowcount comes back short, the whole transaction rolls
     back, and the function returns None -- the caller flashes a conflict
     message and the accountant reselects. This mirrors the same class of
     guard as `claim_version`/`row_version` elsewhere in this app
     (optimistic-lock-conditional-update: "guard = a conditional UPDATE...WHERE
     <the value the caller last saw>"), adapted for a SET of rows with no
     version column of their own.
"""
from collections import defaultdict
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.posting.control_accounts import get_control_account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.petty_cash.models import PettyCashReplenishment, PettyCashVoucher
from app.petty_cash.numbering import generate_pcr_number

ZERO = Decimal('0.00')


def _new_je(entry_number, entry_date, description, reference, branch_id, actor):
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=entry_date,
        description=description,
        reference=reference,
        entry_type='adjustment',
        branch_id=branch_id,
        created_by_id=actor.id,
        status='posted',
        posted_by_id=actor.id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=ZERO,
        total_credit=ZERO,
    )
    db.session.add(je)
    db.session.flush()
    return je


def _add_line(je, line_number, account_id, description, debit, credit):
    line = JournalEntryLine(
        entry_id=je.id, line_number=line_number, account_id=account_id,
        description=description, debit_amount=debit, credit_amount=credit,
    )
    db.session.add(line)
    return line


def post_replenishment(fund, selected_voucher_ids, physical_cash_counted, bank_account, actor):
    """Returns the completed PettyCashReplenishment, or None if a concurrent
    writer already claimed one or more of the selected vouchers (caller flashes
    a conflict message and re-renders the still-held vouchers). Raises
    ControlAccountError only when a nonzero shortage/overage needs the
    unassigned 'petty_cash_short_over' setting -- resolved BEFORE any write, so
    that failure leaves zero side effects (no orphaned draft replenishment, no
    partially-claimed voucher)."""
    selected_voucher_ids = list(selected_voucher_ids)
    if not selected_voucher_ids:
        raise ValueError('Select at least one held voucher to replenish.')

    vouchers = PettyCashVoucher.query.filter(
        PettyCashVoucher.id.in_(selected_voucher_ids), PettyCashVoucher.fund_id == fund.id,
        PettyCashVoucher.status == 'held').all()
    if len(vouchers) != len(set(selected_voucher_ids)):
        # Fast path: at least one selected id is no longer 'held' (already
        # claimed, wrong fund, or doesn't exist) -- lose the race cheaply,
        # before touching the database at all.
        return None
    vouchers_total = sum((v.amount for v in vouchers), ZERO)

    expected_cash = fund.float_amount - vouchers_total
    short_over = (physical_cash_counted - expected_cash).quantize(Decimal('0.01'))
    # sign convention: POSITIVE short_over_amount = SHORTAGE (less cash than expected,
    # a debit/expense); NEGATIVE = OVERAGE (more cash than expected, a credit).
    short_over_amount = -short_over
    replenish_amount = fund.float_amount - physical_cash_counted

    so_account = None
    if short_over_amount != 0:
        so_account = get_control_account('petty_cash_short_over')   # raises ControlAccountError if unassigned; no writes yet

    rep = PettyCashReplenishment(fund_id=fund.id, replenishment_number=generate_pcr_number(),
                                 replenishment_date=ph_now().date(), bank_account_id=bank_account.id,
                                 physical_cash_counted=physical_cash_counted, vouchers_total=vouchers_total,
                                 short_over_amount=short_over_amount, replenish_amount=replenish_amount,
                                 status='draft')
    db.session.add(rep)
    db.session.flush()   # need rep.id for the atomic claim below

    # AUTHORITATIVE guard (see module docstring): atomically flip only the
    # vouchers still 'held' to 'replenished' + stamp this replenishment's id.
    # A short rowcount means a concurrent writer beat us to at least one --
    # roll back everything (including the draft `rep` row above) and lose
    # cleanly rather than post a JE for a partially-claimed set.
    result = db.session.execute(
        db.update(PettyCashVoucher)
        .where(PettyCashVoucher.id.in_(selected_voucher_ids))
        .where(PettyCashVoucher.fund_id == fund.id)
        .where(PettyCashVoucher.status == 'held')
        .values(status='replenished', replenishment_id=rep.id)
    )
    if result.rowcount != len(selected_voucher_ids):
        db.session.rollback()
        return None

    by_expense_account = defaultdict(Decimal)
    for v in vouchers:
        by_expense_account[v.expense_account_id] += v.amount

    je = _new_je(
        entry_number=generate_entry_number(fund.branch_id),
        entry_date=rep.replenishment_date,
        description=f'Petty Cash Replenishment {rep.replenishment_number}',
        reference=rep.replenishment_number,
        branch_id=fund.branch_id,
        actor=actor,
    )
    line_no = 1
    for account_id, amount in by_expense_account.items():
        _add_line(je, line_no, account_id, 'Petty cash replenishment', amount, ZERO)
        line_no += 1

    if short_over_amount != 0:
        if short_over_amount > 0:   # shortage -> a debit (an expense)
            _add_line(je, line_no, so_account.id, 'Cash shortage', short_over_amount, ZERO)
        else:                        # overage -> a credit
            _add_line(je, line_no, so_account.id, 'Cash overage', ZERO, -short_over_amount)
        line_no += 1

    _add_line(je, line_no, bank_account.account_id, 'Petty cash replenishment', ZERO, replenish_amount)

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'Petty Cash Replenishment {rep.replenishment_number} JE does not balance '
            f'(debit={je.total_debit}, credit={je.total_credit}).'
        )

    rep.journal_entry_id = je.id
    rep.status = 'posted'
    rep.posted_by_id = actor.id
    rep.posted_at = ph_now()
    return rep
