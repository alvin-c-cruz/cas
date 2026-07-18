"""Unit tests for AccountsPayableItem's 3-way variance properties (R-02 Phase 6).
No DB session needed -- these are pure Python properties over plain attribute values.
Needs the `app` fixture (not db_session) so the declarative mapper registry is fully
configured before AccountsPayableItem() is instantiated directly -- mirrors
tests/unit/test_accounts_payable_models.py's TestAccountsPayableItemCalculateAmounts."""
import pytest
from decimal import Decimal
from app.accounts_payable.models import AccountsPayableItem

pytestmark = [pytest.mark.usefixtures('app'), pytest.mark.unit]


def _item(**kwargs):
    defaults = dict(line_number=1, description='Test', amount=Decimal('100.00'))
    defaults.update(kwargs)
    return AccountsPayableItem(**defaults)


def test_price_variance_none_when_no_snapshot():
    item = _item(unit_price=Decimal('100.00'))
    assert item.price_variance is None


def test_price_variance_none_when_prices_match():
    item = _item(unit_price=Decimal('100.00'), matched_unit_price=Decimal('100.00'))
    assert item.price_variance is None


def test_price_variance_reports_the_difference():
    item = _item(unit_price=Decimal('120.00'), matched_unit_price=Decimal('100.00'))
    assert item.price_variance == Decimal('20.00')


def test_price_variance_reports_negative_difference():
    item = _item(unit_price=Decimal('80.00'), matched_unit_price=Decimal('100.00'))
    assert item.price_variance == Decimal('-20.00')


def test_quantity_variance_none_when_no_snapshot():
    item = _item(quantity=Decimal('10.0000'))
    assert item.quantity_variance is None


def test_quantity_variance_none_when_quantities_match():
    item = _item(quantity=Decimal('10.0000'), matched_quantity=Decimal('10.0000'))
    assert item.quantity_variance is None


def test_quantity_variance_reports_the_difference():
    item = _item(quantity=Decimal('8.0000'), matched_quantity=Decimal('10.0000'))
    assert item.quantity_variance == Decimal('-2.0000')


def test_has_variance_false_when_both_match():
    item = _item(unit_price=Decimal('100.00'), matched_unit_price=Decimal('100.00'),
                 quantity=Decimal('10'), matched_quantity=Decimal('10'))
    assert item.has_variance is False


def test_has_variance_true_when_only_price_differs():
    item = _item(unit_price=Decimal('120.00'), matched_unit_price=Decimal('100.00'),
                 quantity=Decimal('10'), matched_quantity=Decimal('10'))
    assert item.has_variance is True


def test_has_variance_true_when_only_quantity_differs():
    item = _item(unit_price=Decimal('100.00'), matched_unit_price=Decimal('100.00'),
                 quantity=Decimal('8'), matched_quantity=Decimal('10'))
    assert item.has_variance is True
