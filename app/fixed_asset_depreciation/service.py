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
