"""Unit tests -- post-confirm amendment guards."""
import pytest
from decimal import Decimal
from app.sales_orders.revisions import validate_amendment

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


class _FakeProduct:
    def __init__(self, code):
        self.code = code


class _Line:
    """Stands in for a SalesOrderItem. It carries `product` and `id` because the
    real one always does -- a fake missing what the real object has pushes
    defensive code into production to satisfy the test rather than reality."""
    def __init__(self, item_id, product_id, quantity, delivered,
                 code=None, line_status='open'):
        self.id = item_id
        self.line_number = item_id
        self.product_id = product_id
        self.quantity = Decimal(str(quantity))
        self._delivered = Decimal(str(delivered))
        self.product = _FakeProduct(code or 'P%03d' % product_id)
        self.line_status = line_status


class _SO:
    def __init__(self, lines, billed=False):
        self.line_items = lines
        self.sales_invoice_id = 99 if billed else None


def _sub(item_id, qty):
    return {'so_item_id': item_id, 'quantity': str(qty)}


@pytest.fixture(autouse=True)
def _stub_open_qty(monkeypatch):
    """so_line_open_qty = ordered - delivered, read off the fake line."""
    import app.sales_orders.revisions as mod
    monkeypatch.setattr(mod, 'so_line_open_qty',
                        lambda item: item.quantity - item._delivered)


def test_increase_is_allowed():
    so = _SO([_Line(1, 1, 3000, 3000)])
    assert validate_amendment(so, [_sub(1, 7000)]) == []


def test_reducing_below_delivered_is_refused():
    so = _SO([_Line(1, 1, 3000, 3000)])
    errs = validate_amendment(so, [_sub(1, 2000)])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()


def test_reducing_to_exactly_delivered_is_allowed():
    """Boundary is strict `<`, not `<=`."""
    so = _SO([_Line(1, 1, 5000, 3000)])
    assert validate_amendment(so, [_sub(1, 3000)]) == []


def test_removing_a_line_with_deliveries_is_refused():
    so = _SO([_Line(1, 1, 3000, 3000)])
    errs = validate_amendment(so, [])
    assert len(errs) == 1
    assert 'close' in errs[0].lower()


def test_removing_a_line_with_no_deliveries_is_allowed():
    so = _SO([_Line(1, 1, 3000, 0)])
    assert validate_amendment(so, []) == []


def test_billed_so_allows_increase():
    so = _SO([_Line(1, 1, 3000, 3000)], billed=True)
    assert validate_amendment(so, [_sub(1, 7000)]) == []


def test_billed_so_refuses_decrease():
    so = _SO([_Line(1, 1, 5000, 1000)], billed=True)
    errs = validate_amendment(so, [_sub(1, 4000)])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()


def test_billed_so_refuses_line_removal():
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()


def test_adding_a_new_line_is_allowed_even_when_billed():
    """A new line has no so_item_id and guards nothing existing."""
    so = _SO([_Line(1, 1, 3000, 3000)], billed=True)
    assert validate_amendment(
        so, [_sub(1, 3000), {'so_item_id': None, 'quantity': '500'}]) == []


# --- hostile input ------------------------------------------------------------

def test_two_tranches_of_one_product_are_guarded_INDEPENDENTLY():
    """THE exploit. Aggregating by product let a caller zero a fully-delivered
    tranche while a sibling absorbed the total, and the guard saw a legal sum."""
    so = _SO([_Line(1, 1, 3000, 3000),      # fully delivered
              _Line(2, 1, 2000, 0)])        # untouched sibling, same product
    errs = validate_amendment(so, [_sub(1, 0), _sub(2, 5000)])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()
    # Pin down WHICH refusal fired. A per-product-keyed mutant treats row 1 as
    # simply absent from the submission (since it reads a `product_id` key that
    # no longer exists on a `so_item_id`-shaped payload) and produces the
    # "cannot remove a line" refusal instead -- same '3000'/'delivered' text,
    # wrong reason, and it would wrongly fire even if row 1 had been submitted
    # at a value >= 0 rather than truly reduced. The correct per-row guard
    # instead sees row 1 present at its OWN submitted value (0) and refuses on
    # "new quantity ... below ... delivered", so assert on that value and
    # exclude the "remove" phrasing.
    assert 'new quantity 0' in errs[0]
    assert 'remove' not in errs[0].lower()


def test_non_numeric_ids_and_quantities_do_not_raise():
    """Contract: return messages, never raise. A crafted POST must not 500."""
    so = _SO([_Line(1, 1, 3000, 3000)])
    for bad in ([{'so_item_id': 'abc', 'quantity': '500'}],
                [{'so_item_id': 1, 'quantity': 'xyz'}],
                [{'so_item_id': None, 'quantity': None}],
                [{}]):
        result = validate_amendment(so, bad)
        assert isinstance(result, list)


def test_a_negative_quantity_is_refused_like_any_other_reduction():
    so = _SO([_Line(1, 1, 3000, 3000)])
    errs = validate_amendment(so, [_sub(1, -5)])
    assert len(errs) == 1
    assert 'delivered' in errs[0].lower()


def test_duplicate_so_item_id_is_refused_rather_than_silently_resolved():
    so = _SO([_Line(1, 1, 3000, 0)])
    errs = validate_amendment(so, [_sub(1, 100), _sub(1, 9000)])
    assert any('same original row' in e for e in errs)


def test_a_closed_line_gets_its_own_message_not_a_delivered_claim():
    """so_line_open_qty returns 0 for a closed line, which would otherwise make
    _delivered_qty read as the full ordered amount and produce a refusal
    claiming everything was delivered when nothing may have been."""
    so = _SO([_Line(1, 1, 3000, 0, line_status='closed')])
    errs = validate_amendment(so, [_sub(1, 1000)])
    assert len(errs) == 1
    assert 'closed' in errs[0].lower()
    assert 'delivered' not in errs[0].lower()
