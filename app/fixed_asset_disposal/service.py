"""Fixed asset disposal: dispose_fixed_asset (post) / void_fixed_asset_disposal
(reverse). See docs/superpowers/specs/2026-07-18-fixed-asset-disposal-design.md."""
from decimal import Decimal


def dispose_fixed_asset(fixed_asset_id, disposal_date, disposal_type, proceeds_amount,
                        proceeds_account_id, user_id, notes=None):
    """Retire a fixed asset: writes off cost + accumulated depreciation, books
    any gain/loss, and (daily convention only) a final depreciation catch-up
    for the partial disposal month. Posts one JE; flips the asset's status
    to 'disposed'.

    Raises ValueError if: the asset isn't 'active'; it already has a live
    (non-void) disposal; the accounting period is closed; disposal_type
    isn't sale/scrap/trade_in; or proceeds_amount > 0 with no
    proceeds_account_id.
    """
    from app import db
    from app.audit.utils import log_create
    from app.fixed_asset_depreciation.service import (
        compute_period_depreciation, get_depreciation_convention,
    )
    from app.fixed_asset_disposal.models import FixedAssetDisposal
    from app.fixed_assets.models import FixedAsset
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.periods.utils import validate_transaction_date
    from app.posting.control_accounts import get_control_account
    from app.utils import ph_now

    asset = db.session.get(FixedAsset, fixed_asset_id)
    if asset is None or asset.status != 'active':
        raise ValueError('Only an active fixed asset can be disposed.')

    existing = FixedAssetDisposal.query.filter_by(fixed_asset_id=fixed_asset_id) \
        .filter(FixedAssetDisposal.status != 'void').first()
    if existing:
        raise ValueError(f'Fixed asset {asset.code} already has a posted disposal.')

    if disposal_type not in ('sale', 'scrap', 'trade_in'):
        raise ValueError(f'Unknown disposal type: {disposal_type}')

    proceeds_amount = Decimal(str(proceeds_amount or 0))
    if disposal_type == 'scrap':
        proceeds_amount = Decimal('0')
        proceeds_account_id = None
    elif proceeds_amount > 0 and not proceeds_account_id:
        raise ValueError('A proceeds account is required when proceeds are greater than zero.')

    is_valid, error_message = validate_transaction_date(disposal_date, 'fixed asset disposal')
    if not is_valid:
        raise ValueError(error_message)

    prior_accumulated = asset.accumulated_depreciation
    final_depreciation_amount = Decimal('0.00')
    convention = get_depreciation_convention()
    if convention == 'daily':
        final_depreciation_amount = compute_period_depreciation(
            asset, prior_accumulated, disposal_date.year, disposal_date.month,
            convention='daily', proration_days_owned=disposal_date.day,
        )

    accumulated_depreciation_written_off = prior_accumulated + final_depreciation_amount
    cost_written_off = Decimal(str(asset.acquisition_cost))
    net_book_value_at_disposal = cost_written_off - accumulated_depreciation_written_off
    gain_loss_amount = proceeds_amount - net_book_value_at_disposal

    disposal = FixedAssetDisposal(
        fixed_asset_id=fixed_asset_id, disposal_date=disposal_date, disposal_type=disposal_type,
        proceeds_amount=proceeds_amount, proceeds_account_id=proceeds_account_id,
        final_depreciation_amount=final_depreciation_amount, cost_written_off=cost_written_off,
        accumulated_depreciation_written_off=accumulated_depreciation_written_off,
        net_book_value_at_disposal=net_book_value_at_disposal, gain_loss_amount=gain_loss_amount,
        status='posted', created_by_id=user_id, notes=notes,
    )
    db.session.add(disposal)
    db.session.flush()

    je = JournalEntry(
        entry_number=generate_entry_number(asset.branch_id), entry_date=disposal_date,
        description=f'Disposal — {asset.code} ({disposal_type})',
        entry_type='fixed_asset_disposal', branch_id=asset.branch_id, created_by_id=user_id,
        status='posted', posted_by_id=user_id, posted_at=ph_now(), is_balanced=False,
        total_debit=Decimal('0.00'), total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1

    def _line(account_id, amount, side, description):
        nonlocal line_num
        if account_id is None or amount == Decimal('0.00'):
            return
        dr = amount if side == 'debit' else Decimal('0.00')
        cr = amount if side == 'credit' else Decimal('0.00')
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=account_id,
            description=description, debit_amount=dr, credit_amount=cr,
        ))
        line_num += 1

    # NOTE: this Dr leg is prior_accumulated, NOT accumulated_depreciation_written_off --
    # the catch-up leg above's own implicit credit nets into this line, so it must not
    # double count (see the spec's "folds into the written-off figure above" note).
    _line(asset.depreciation_expense_account_id, final_depreciation_amount, 'debit',
         f'Final depreciation catch-up — {asset.code}')
    _line(asset.accumulated_depreciation_account_id, prior_accumulated, 'debit',
         f'Write off accumulated depreciation — {asset.code}')
    _line(proceeds_account_id, proceeds_amount, 'debit', f'Disposal proceeds — {asset.code}')
    _line(asset.cost_account_id, cost_written_off, 'credit', f'Write off cost — {asset.code}')

    gain_loss_account = get_control_account('gain_loss_on_disposal')
    if gain_loss_amount > 0:
        _line(gain_loss_account.id, gain_loss_amount, 'credit',
             f'Gain on disposal — {asset.code}')
    elif gain_loss_amount < 0:
        _line(gain_loss_account.id, -gain_loss_amount, 'debit',
             f'Loss on disposal — {asset.code}')

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Disposal JE is not balanced for asset {asset.code}.')

    disposal.journal_entry_id = je.id
    asset.status = 'disposed'
    db.session.commit()
    log_create('fixed_asset_disposal', disposal.id, asset.code, disposal.to_dict())
    return disposal


def void_fixed_asset_disposal(disposal, void_date, user_id):
    """Void a posted disposal: mirrors the source JE with Dr/Cr swapped (same
    pattern as Slice 2's reverse_depreciation_run / app/payroll/service.py's
    cancel reversal), flips the disposal to 'void', and restores the asset
    to 'active' (freeing its slot for a fresh disposal).

    Returns the reversal JournalEntry, or None if the disposal had no JE.

    Raises ValueError if disposal.status != 'posted'.
    """
    from app import db
    from app.audit.utils import log_update
    from app.fixed_assets.models import FixedAsset
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_jv_number
    from app.utils import ph_now

    if disposal.status != 'posted':
        raise ValueError(
            f'Only a posted disposal can be voided (this disposal is {disposal.status}).'
        )

    old = disposal.to_dict()
    source_je = disposal.journal_entry

    reversal_je = None
    if source_je is not None:
        reversal_je = JournalEntry(
            entry_number=generate_jv_number(source_je.branch_id), entry_date=void_date,
            description=f'Disposal Void — {disposal.fixed_asset.code}',
            reference=f'VOID-DISPOSAL-{disposal.id}', entry_type='fixed_asset_disposal_reversal',
            is_reversing=True, reversed_entry_id=source_je.id, branch_id=source_je.branch_id,
            created_by_id=user_id, status='posted', posted_by_id=user_id, posted_at=ph_now(),
            is_balanced=False, total_debit=Decimal('0.00'), total_credit=Decimal('0.00'),
        )
        db.session.add(reversal_je)
        db.session.flush()

        for i, src in enumerate(source_je.lines.all(), start=1):
            db.session.add(JournalEntryLine(
                entry_id=reversal_je.id, line_number=i, account_id=src.account_id,
                description=f'Void: {src.description}',
                debit_amount=src.credit_amount, credit_amount=src.debit_amount,
            ))
        db.session.flush()
        reversal_je.calculate_totals()

    disposal.status = 'void'
    asset = db.session.get(FixedAsset, disposal.fixed_asset_id)
    asset.status = 'active'
    db.session.commit()
    log_update('fixed_asset_disposal', disposal.id, asset.code, old, disposal.to_dict())
    return reversal_je
