"""Unit tests -- post-confirm amendment guards."""
import pytest
from decimal import Decimal
from app.sales_orders.revisions import validate_amendment

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


class _Line:
    def __init__(self, product_id, quantity, delivered):
        self.product_id = product_id
        self.quantity = Decimal(str(quantity))
        self._delivered = Decimal(str(delivered))


class _SO:
    def __init__(self, lines, billed=False):
        self.line_items = lines
        self.sales_invoice_id = 99 if billed else None


@pytest.fixture(autouse=True)
def _stub_open_qty(monkeypatch):
    """so_line_open_qty = ordered - delivered; stub delivered off the fake line."""
    import app.sales_orders.revisions as mod
    monkeypatch.setattr(mod, 'so_line_open_qty',
                        lambda item: item.quantity - item._delivered)


def test_increase_is_allowed():
    so = _SO([_Line(1, 3000, 3000)])
    assert validate_amendment(so, [{'product_id': 1, 'quantity': '7000'}]) == []


def test_reducing_below_delivered_is_refused():
    so = _SO([_Line(1, 3000, 3000)])
    errs = validate_amendment(so, [{'product_id': 1, 'quantity': '2000'}])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()


def test_reducing_to_exactly_delivered_is_allowed():
    so = _SO([_Line(1, 5000, 3000)])
    assert validate_amendment(so, [{'product_id': 1, 'quantity': '3000'}]) == []


def test_removing_a_line_with_deliveries_is_refused():
    so = _SO([_Line(1, 3000, 3000)])
    errs = validate_amendment(so, [])
    assert len(errs) == 1
    assert 'close' in errs[0].lower()


def test_removing_a_line_with_no_deliveries_is_allowed():
    so = _SO([_Line(1, 3000, 0)])
    assert validate_amendment(so, []) == []


def test_billed_so_allows_increase():
    so = _SO([_Line(1, 3000, 3000)], billed=True)
    assert validate_amendment(so, [{'product_id': 1, 'quantity': '7000'}]) == []


def test_billed_so_refuses_decrease():
    so = _SO([_Line(1, 5000, 1000)], billed=True)
    errs = validate_amendment(so, [{'product_id': 1, 'quantity': '4000'}])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()


def test_billed_so_refuses_line_removal():
    so = _SO([_Line(1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()


def test_adding_a_new_line_is_allowed_even_when_billed():
    so = _SO([_Line(1, 3000, 3000)], billed=True)
    assert validate_amendment(so, [{'product_id': 1, 'quantity': '3000'},
                                   {'product_id': 2, 'quantity': '500'}]) == []
