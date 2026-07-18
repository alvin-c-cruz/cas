from datetime import date
from decimal import Decimal
import pytest
from app.fixed_asset_depreciation.service import (
    get_depreciation_convention, compute_period_depreciation,
)


class _StubAsset:
    """A plain namespace standing in for FixedAsset -- compute_period_depreciation
    only reads these attributes, so a stub avoids DB setup for pure-formula tests."""
    def __init__(self, **kwargs):
        self.depreciation_method = kwargs.get('depreciation_method', 'straight_line')
        self.useful_life_months = kwargs.get('useful_life_months')
        self.declining_balance_rate = kwargs.get('declining_balance_rate')
        self.total_estimated_units = kwargs.get('total_estimated_units')
        self.salvage_value = kwargs.get('salvage_value', Decimal('0'))
        self.acquisition_cost = kwargs.get('acquisition_cost', Decimal('0'))
        self.acquisition_date = kwargs.get('acquisition_date')


def test_get_depreciation_convention_fail_soft_default(db_session):
    assert get_depreciation_convention() == 'full_month'


def test_get_depreciation_convention_reads_setting(db_session):
    from app.settings import AppSettings
    AppSettings.set_setting('fixed_asset_depreciation_convention', 'daily')
    db_session.commit()
    assert get_depreciation_convention() == 'daily'


def test_straight_line_monthly_amount():
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=60,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('60000.00'),
                       acquisition_date=date(2024, 1, 1))
    # (60000 - 0) / 60 = 1000.00/month; a period well after acquisition, full_month convention
    amount = compute_period_depreciation(asset, Decimal('12000.00'), 2026, 6,
                                         convention='full_month')
    assert amount == Decimal('1000.00')


def test_straight_line_final_period_true_up_never_overshoots():
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=60,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('60000.00'),
                       acquisition_date=date(2024, 1, 1))
    # 59500 already accumulated of a 60000 base -- only 500 left, even though the
    # straight monthly rate is 1000
    amount = compute_period_depreciation(asset, Decimal('59500.00'), 2026, 6,
                                         convention='full_month')
    assert amount == Decimal('500.00')


def test_fully_depreciated_asset_returns_zero():
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=60,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('60000.00'),
                       acquisition_date=date(2024, 1, 1))
    amount = compute_period_depreciation(asset, Decimal('60000.00'), 2026, 6,
                                         convention='full_month')
    assert amount == Decimal('0.00')


def test_declining_balance_uses_prior_net_book_value():
    asset = _StubAsset(depreciation_method='declining_balance', declining_balance_rate=Decimal('20'),
                       salvage_value=Decimal('1000.00'), acquisition_cost=Decimal('60000.00'),
                       acquisition_date=date(2024, 1, 1))
    # prior_accumulated=10000 -> prior NBV=50000; rate 20%/12 per month = 1.6667%/mo
    amount = compute_period_depreciation(asset, Decimal('10000.00'), 2026, 6,
                                         convention='full_month')
    expected = (Decimal('50000.00') * Decimal('20') / Decimal('100') / Decimal('12')
               ).quantize(Decimal('0.01'))
    assert amount == expected


def test_declining_balance_floors_at_salvage_value():
    asset = _StubAsset(depreciation_method='declining_balance', declining_balance_rate=Decimal('20'),
                       salvage_value=Decimal('1000.00'), acquisition_cost=Decimal('60000.00'),
                       acquisition_date=date(2024, 1, 1))
    # prior_accumulated already at the depreciable base (60000-1000=59000)
    amount = compute_period_depreciation(asset, Decimal('59000.00'), 2026, 6,
                                         convention='full_month')
    assert amount == Decimal('0.00')


def test_units_of_production_uses_units_used_kwarg():
    asset = _StubAsset(depreciation_method='units_of_production',
                       total_estimated_units=Decimal('10000'), salvage_value=Decimal('0'),
                       acquisition_cost=Decimal('50000.00'), acquisition_date=date(2024, 1, 1))
    # per-unit = 50000/10000 = 5.00; 200 units this period
    amount = compute_period_depreciation(asset, Decimal('0'), 2026, 6, convention='full_month',
                                         units_used=Decimal('200'))
    assert amount == Decimal('1000.00')


def test_units_of_production_with_no_units_used_is_zero():
    asset = _StubAsset(depreciation_method='units_of_production',
                       total_estimated_units=Decimal('10000'), salvage_value=Decimal('0'),
                       acquisition_cost=Decimal('50000.00'), acquisition_date=date(2024, 1, 1))
    amount = compute_period_depreciation(asset, Decimal('0'), 2026, 6, convention='full_month',
                                         units_used=None)
    assert amount == Decimal('0.00')


def test_full_month_convention_gives_full_amount_in_acquisition_month():
    """Acquired mid-month (Jan 20) -- full_month convention still gives the full
    monthly amount for that first period."""
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=12,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('12000.00'),
                       acquisition_date=date(2026, 1, 20))
    amount = compute_period_depreciation(asset, Decimal('0'), 2026, 1, convention='full_month')
    assert amount == Decimal('1000.00')  # 12000/12, no proration


def test_daily_convention_prorates_the_acquisition_month():
    """Acquired Jan 20 of a 31-day month -- daily convention prorates by
    days-owned/days-in-month for the acquisition month only."""
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=12,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('12000.00'),
                       acquisition_date=date(2026, 1, 20))
    amount = compute_period_depreciation(asset, Decimal('0'), 2026, 1, convention='daily')
    # days owned = Jan 20..31 inclusive = 12 days out of 31
    expected = (Decimal('1000.00') * Decimal('12') / Decimal('31')).quantize(Decimal('0.01'))
    assert amount == expected
    assert amount < Decimal('1000.00')


def test_daily_convention_does_not_prorate_a_later_period():
    """Proration only applies to the asset's OWN acquisition month -- a later
    period gets the full monthly amount under either convention."""
    asset = _StubAsset(depreciation_method='straight_line', useful_life_months=12,
                       salvage_value=Decimal('0'), acquisition_cost=Decimal('12000.00'),
                       acquisition_date=date(2026, 1, 20))
    amount = compute_period_depreciation(asset, Decimal('83.33'), 2026, 2, convention='daily')
    assert amount == Decimal('1000.00')
