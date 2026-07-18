"""Depreciation computation, run orchestration, and posting/reversal (R-05
Slice 2). See docs/superpowers/specs/2026-07-18-fixed-asset-depreciation-design.md."""
import calendar
from decimal import Decimal


def get_depreciation_convention():
    """'full_month' or 'daily'. Fail-soft to 'full_month' (the more common PH
    SME default) if the accountant hasn't picked one yet -- never blocks a run."""
    from app.settings import AppSettings
    return AppSettings.get_setting('fixed_asset_depreciation_convention', default='full_month')


def compute_period_depreciation(asset, prior_accumulated, period_year, period_month,
                                convention='full_month', units_used=None):
    """The pure per-method formula for one asset's one period.

    Args:
        asset: a FixedAsset (or any object exposing the same attributes --
            depreciation_method, useful_life_months, declining_balance_rate,
            total_estimated_units, salvage_value, acquisition_cost,
            acquisition_date).
        prior_accumulated: Decimal -- accumulated depreciation BEFORE this
            period (asset.accumulated_depreciation as of the prior period).
        period_year, period_month: the period being computed.
        convention: 'full_month' | 'daily' -- governs proration in the
            asset's own acquisition month only.
        units_used: Decimal, units-of-production only -- units consumed this
            period. Ignored for every other method.

    Returns:
        Decimal, quantized to 2 places -- 0.00 if the asset is already fully
        depreciated (prior_accumulated >= depreciable base) or (for
        units-of-production) units_used is None/zero.
    """
    prior_accumulated = Decimal(str(prior_accumulated))
    acquisition_cost = Decimal(str(asset.acquisition_cost))
    salvage_value = Decimal(str(asset.salvage_value or 0))
    depreciable_base = acquisition_cost - salvage_value
    remaining = depreciable_base - prior_accumulated
    if remaining <= Decimal('0'):
        return Decimal('0.00')

    if asset.depreciation_method == 'straight_line':
        monthly = depreciable_base / Decimal(asset.useful_life_months)
        amount = monthly
    elif asset.depreciation_method == 'declining_balance':
        prior_net_book_value = acquisition_cost - prior_accumulated
        monthly_rate = Decimal(str(asset.declining_balance_rate)) / Decimal('100') / Decimal('12')
        amount = prior_net_book_value * monthly_rate
    elif asset.depreciation_method == 'units_of_production':
        if not units_used:
            return Decimal('0.00')
        per_unit = depreciable_base / Decimal(str(asset.total_estimated_units))
        amount = per_unit * Decimal(str(units_used))
    else:
        raise ValueError(f'Unknown depreciation method: {asset.depreciation_method}')

    is_acquisition_month = (period_year == asset.acquisition_date.year
                            and period_month == asset.acquisition_date.month)
    if is_acquisition_month and convention == 'daily':
        days_in_month = calendar.monthrange(period_year, period_month)[1]
        days_owned = days_in_month - asset.acquisition_date.day + 1
        amount = amount * Decimal(days_owned) / Decimal(days_in_month)

    amount = min(amount, remaining)
    return amount.quantize(Decimal('0.01'))


def compute_depreciation_preview(branch_id, period_year, period_month, units_used_by_asset=None):
    """Compute this period's depreciation for every eligible FixedAsset in a
    branch. Nothing is written to the DB -- pure computation for the preview
    step (the new-run view) and reused verbatim by post_depreciation_run so
    the posted amounts are guaranteed identical to what was previewed.

    An asset not yet acquired as of the LAST day of this period is excluded
    entirely (it doesn't exist in the books yet). A disposed asset never
    matches the branch_id query below (status='active' filter) -- Slice 3
    owns flipping that status. A fully-depreciated active asset IS included,
    at a computed amount of 0.00 -- never silently hidden.
    """
    from datetime import date
    from app.fixed_assets.models import FixedAsset

    units_used_by_asset = units_used_by_asset or {}
    convention = get_depreciation_convention()
    period_end = date(period_year, period_month, calendar.monthrange(period_year, period_month)[1])

    assets = FixedAsset.query.filter_by(branch_id=branch_id, status='active') \
        .filter(FixedAsset.acquisition_date <= period_end) \
        .order_by(FixedAsset.code).all()

    rows = []
    for asset in assets:
        prior_accumulated = asset.accumulated_depreciation
        units_used = (units_used_by_asset.get(asset.id)
                     if asset.depreciation_method == 'units_of_production' else None)
        amount = compute_period_depreciation(
            asset, prior_accumulated, period_year, period_month,
            convention=convention, units_used=units_used,
        )
        accumulated_after = prior_accumulated + amount
        net_book_value_after = Decimal(str(asset.acquisition_cost)) - accumulated_after
        rows.append({
            'asset': asset,
            'prior_accumulated': prior_accumulated,
            'depreciation_amount': amount,
            'accumulated_after': accumulated_after,
            'net_book_value_after': net_book_value_after,
            'units_used': units_used,
            'needs_units_input': (asset.depreciation_method == 'units_of_production'
                                  and not units_used),
        })
    return rows


def post_depreciation_run(branch_id, period_year, period_month, units_used_by_asset, user_id):
    """Post a depreciation run: creates the DepreciationRun + DepreciationEntry
    rows and (if any asset has a nonzero amount) one account-grouped JE.

    Raises ValueError if a live (non-reversed) run already exists for this
    (branch_id, period_year, period_month), if the period is closed, or if
    the resulting JE doesn't balance.
    """
    from collections import defaultdict
    from datetime import date
    from app import db
    from app.audit.utils import log_create
    from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.periods.utils import validate_transaction_date
    from app.utils import ph_now

    existing = DepreciationRun.query.filter_by(
        branch_id=branch_id, period_year=period_year, period_month=period_month,
    ).filter(DepreciationRun.status != 'reversed').first()
    if existing:
        raise ValueError(
            f'A depreciation run already exists for this branch/period '
            f'(status={existing.status}). Reverse it first to re-run.'
        )

    period_end = date(period_year, period_month, calendar.monthrange(period_year, period_month)[1])
    is_valid, error_message = validate_transaction_date(period_end, 'depreciation run')
    if not is_valid:
        raise ValueError(error_message)

    rows = compute_depreciation_preview(branch_id, period_year, period_month, units_used_by_asset)

    run = DepreciationRun(branch_id=branch_id, period_year=period_year, period_month=period_month,
                          status='posted', run_date=ph_now(), created_by_id=user_id)
    db.session.add(run)
    db.session.flush()

    entries = []
    for row in rows:
        entry = DepreciationEntry(
            run_id=run.id, fixed_asset_id=row['asset'].id,
            depreciation_amount=row['depreciation_amount'],
            accumulated_depreciation_after=row['accumulated_after'],
            net_book_value_after=row['net_book_value_after'], units_used=row['units_used'],
        )
        db.session.add(entry)
        entries.append((row, entry))
    db.session.flush()

    expense_totals = defaultdict(Decimal)
    accum_totals = defaultdict(Decimal)
    for row, entry in entries:
        if entry.depreciation_amount == Decimal('0.00'):
            continue
        asset = row['asset']
        expense_totals[asset.depreciation_expense_account_id] += entry.depreciation_amount
        accum_totals[asset.accumulated_depreciation_account_id] += entry.depreciation_amount

    if expense_totals:
        je = JournalEntry(
            entry_number=generate_entry_number(branch_id), entry_date=period_end,
            description=f'Depreciation — {period_year}-{period_month:02d}',
            entry_type='depreciation', branch_id=branch_id, created_by_id=user_id,
            status='posted', posted_by_id=user_id, posted_at=ph_now(), is_balanced=False,
            total_debit=Decimal('0.00'), total_credit=Decimal('0.00'),
        )
        db.session.add(je)
        db.session.flush()

        line_num = 1
        for account_id, amount in expense_totals.items():
            db.session.add(JournalEntryLine(
                entry_id=je.id, line_number=line_num, account_id=account_id,
                description=f'Depreciation Expense — {period_year}-{period_month:02d}',
                debit_amount=amount, credit_amount=Decimal('0.00'),
            ))
            line_num += 1
        for account_id, amount in accum_totals.items():
            db.session.add(JournalEntryLine(
                entry_id=je.id, line_number=line_num, account_id=account_id,
                description=f'Accumulated Depreciation — {period_year}-{period_month:02d}',
                debit_amount=Decimal('0.00'), credit_amount=amount,
            ))
            line_num += 1
        db.session.flush()

        je.calculate_totals()
        if not je.is_balanced:
            raise ValueError(
                f'Depreciation JE is not balanced (debit={je.total_debit}, '
                f'credit={je.total_credit}) for branch {branch_id} '
                f'{period_year}-{period_month:02d}.'
            )
        run.journal_entry_id = je.id

    db.session.commit()
    log_create('fixed_asset_depreciation', run.id,
              f'{branch_id}/{period_year}-{period_month:02d}', run.to_dict())
    return run
