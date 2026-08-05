"""Unit tests -- post-confirm amendment guards."""
import pytest
from decimal import Decimal
from app.sales_orders.revisions import validate_amendment

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]

#: Stored unit price on every fake line, and the default a submitted line
#: echoes back. Shared by _Line and _sub so "unchanged price" is expressed in
#: one place -- if they drifted, every quantity test would silently become a
#: price test as well.
DEFAULT_PRICE = '4.20'

#: Sentinel for "omit the unit_price key entirely", which is NOT the same as
#: submitting an empty/None price and NOT the same as submitting the stored one.
_OMIT = object()


class _FakeProduct:
    def __init__(self, code):
        self.code = code


class _Line:
    """Stands in for a SalesOrderItem. It carries `product` and `id` because the
    real one always does -- a fake missing what the real object has pushes
    defensive code into production to satisfy the test rather than reality."""
    def __init__(self, item_id, product_id, quantity, delivered,
                 code=None, line_status='open', unit_price=DEFAULT_PRICE):
        self.id = item_id
        self.line_number = item_id
        self.product_id = product_id
        self.quantity = Decimal(str(quantity))
        self._delivered = Decimal(str(delivered))
        self.product = _FakeProduct(code or 'P%03d' % product_id)
        self.line_status = line_status
        self.unit_price = (Decimal(str(unit_price))
                           if unit_price is not None else None)


class _SO:
    def __init__(self, lines, billed=False):
        self.line_items = lines
        self._billed = billed
        # Kept only to prove it is IGNORED: billed-ness is derived from the order's
        # Delivery Receipts, never read off this column (nothing in the app writes
        # it). Deliberately set to the OPPOSITE of _billed so any code that went
        # back to reading it would invert every billed test in this file rather
        # than pass by luck.
        self.sales_invoice_id = None if billed else 99


def _sub(item_id, qty, price=DEFAULT_PRICE):
    """A submitted line. `price` defaults to _Line's stored price so that the
    quantity-focused tests below submit an UNCHANGED price -- the amend form
    always posts unit_price for every line, so a payload omitting it is a
    price change to NULL, not a neutral one (see the omitted-price test)."""
    line = {'so_item_id': item_id, 'quantity': str(qty)}
    if price is not _OMIT:
        line['unit_price'] = str(price) if price is not None else None
    return line


@pytest.fixture(autouse=True)
def _stub_open_qty(monkeypatch):
    """so_line_open_qty = ordered - delivered, read off the fake line.

    Also stub _has_any_dr_reference to False for every fake line: this file
    proves branching logic against dict-shaped fakes with no real DB rows
    behind them (that is the whole point -- see test_so_amendment_guards_orm.py's
    module docstring), so a fake line's `id` never corresponds to a real
    DeliveryReceiptItem row. The guard's own behaviour (a DRAFT DR blocking
    removal) is proved against the real ORM/DB in
    tests/integration/test_so_amendment.py instead.
    """
    import app.sales_orders.revisions as mod
    monkeypatch.setattr(mod, 'so_line_open_qty',
                        lambda item: item.quantity - item._delivered)
    monkeypatch.setattr(mod, '_has_any_dr_reference', lambda item: False)
    # so_is_billed queries the DR table for real; these fakes have no rows behind
    # them, so it is stubbed off the fake's own flag -- same treatment as the two
    # derivations above. The real derivation is proved against the ORM/DB in
    # tests/integration/test_so_billed_derivation.py and, for the amendment guards
    # specifically, in test_so_amendment_guards_orm.py.
    monkeypatch.setattr(mod, 'so_is_billed', lambda so: so._billed)


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


# ── unit price on a billed order (owner directive 2026-08-05) ───────────────
#
# Quantity and price are guarded ASYMMETRICALLY on a billed order, on purpose.
# An INCREASE in quantity adds units that were never invoiced and can be billed
# later, so it is allowed. Unit price has no such spare room: it applies to the
# units ALREADY on the invoice, so a rise contradicts that invoice exactly as
# much as a cut does. Hence "frozen in both directions" below.

def test_billed_so_refuses_a_price_cut():
    """The case this guard was added for: 4.20 -> 0.01 on an invoiced line."""
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [_sub(1, 3000, price='0.01')])
    assert len(errs) == 1
    assert 'price' in errs[0].lower() and 'billed' in errs[0].lower()
    assert '4.20' in errs[0]  # tells the user what the invoice says


def test_billed_so_refuses_a_price_rise():
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [_sub(1, 3000, price='99.00')])
    assert len(errs) == 1
    assert 'price' in errs[0].lower()


def test_billed_so_allows_an_unchanged_price_written_differently():
    """4.2 and 4.20 are the SAME price. Comparing formatted strings instead of
    Decimals would refuse this and make the guard unusable in practice."""
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    assert validate_amendment(so, [_sub(1, 3000, price='4.2')]) == []
    assert validate_amendment(so, [_sub(1, 3000, price='4.2000')]) == []


def test_unbilled_so_allows_a_price_change():
    """The freeze is scoped to BILLED orders -- a confirmed-but-uninvoiced order
    can still be repriced, which is the whole point of amendment."""
    so = _SO([_Line(1, 1, 3000, 0)])
    assert validate_amendment(so, [_sub(1, 3000, price='0.01')]) == []


def test_billed_so_refuses_an_omitted_price():
    """VALIDATION MIRRORS APPLICATION. _assign_so_line_fields writes
    item.unit_price = _so_line_dec(d.get('unit_price')), so a payload with no
    unit_price key NULLs the price. That is a change, and must be refused --
    otherwise the one payload shape that erases the price is the one shape the
    guard waves through."""
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [_sub(1, 3000, price=_OMIT)])
    assert len(errs) == 1
    assert 'price' in errs[0].lower()


def test_billed_so_refuses_an_unreadable_price():
    """Same reasoning: the applier's _so_line_dec turns garbage into None, so
    garbage is a change to NULL, not a no-op."""
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    for bad in ('xyz', '', 'null', None, 'NaN'):
        errs = validate_amendment(so, [_sub(1, 3000, price=bad)])
        assert len(errs) == 1, 'price %r should be refused, got %r' % (bad, errs)
        assert 'price' in errs[0].lower()


def test_billed_so_freezes_price_on_a_CLOSED_line():
    """Branch ORDER is load-bearing: the closed-line branch `continue`s, so a
    price check placed after it would never run for a closed line. A closed line
    on a billed order is still invoiced -- closing abandons its remaining
    QUANTITY, it does not unbill what was already sold."""
    so = _SO([_Line(1, 1, 3000, 0, line_status='closed')], billed=True)
    errs = validate_amendment(so, [_sub(1, 3000, price='0.01')])
    assert any('price' in e.lower() for e in errs), errs


def test_a_removed_line_gets_the_removal_message_not_a_price_message():
    """A line absent from the payload has no submitted price to compare, and
    already has its own refusal. Emitting a price error too would be noise."""
    so = _SO([_Line(1, 1, 3000, 0)], billed=True)
    errs = validate_amendment(so, [])
    assert len(errs) == 1
    assert 'price' not in errs[0].lower()


def test_price_and_quantity_violations_are_reported_TOGETHER():
    """Independent guards -- the user should see both problems in one pass
    rather than fixing one and rediscovering the other."""
    so = _SO([_Line(1, 1, 5000, 1000)], billed=True)
    errs = validate_amendment(so, [_sub(1, 4000, price='0.01')])
    assert len(errs) == 2
    assert any('price' in e.lower() for e in errs)
    assert any('quantity' in e.lower() for e in errs)


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


def test_hostile_payloads_never_raise():
    """Contract: return messages, never raise. A crafted POST must not 500.

    'NaN' and 'Infinity' are the interesting ones -- Decimal() ACCEPTS both, so
    the parse guard does not fire and a later ordered comparison against a quiet
    NaN signals InvalidOperation.
    """
    so = _SO([_Line(1, 1, 3000, 3000)])
    for bad in ([{'so_item_id': 'abc', 'quantity': '500'}],
                [{'so_item_id': 1, 'quantity': 'xyz'}],
                [{'so_item_id': 1, 'quantity': 'NaN'}],
                [{'so_item_id': 1, 'quantity': 'sNaN'}],
                [{'so_item_id': 1, 'quantity': 'Infinity'}],
                [{'so_item_id': 1, 'quantity': '-Infinity'}],
                [{'so_item_id': None, 'quantity': None}],
                [{}],
                ['not-a-dict'],
                [None],
                [[1, 2]],
                None,
                []):
        result = validate_amendment(so, bad)
        assert isinstance(result, list)


def test_an_unreadable_quantity_is_refused_not_treated_as_zero():
    """The applier (_dec in views.py) writes NULL for the same garbage, so
    coercing to 0 here would validate a number that never gets stored --
    validation must mirror application. Zero is also the most destructive value
    to guess."""
    so = _SO([_Line(1, 1, 3000, 0)])          # undelivered, unbilled
    errs = validate_amendment(so, [{'so_item_id': 1, 'quantity': 'xyz'}])
    assert len(errs) == 1
    assert 'could not read' in errs[0].lower()


def test_infinity_is_not_accepted_as_a_legal_increase():
    so = _SO([_Line(1, 1, 3000, 0)])
    errs = validate_amendment(so, [{'so_item_id': 1, 'quantity': 'Infinity'}])
    assert len(errs) == 1
    assert 'could not read' in errs[0].lower()


def test_a_quantity_larger_than_the_column_can_hold_is_refused():
    """is_finite() does not catch this: Decimal('1E+9999') is finite, just far
    bigger than Numeric(15,4). SQLite does not enforce column precision, so such
    a value is stored verbatim as `inf` and every later so_line_open_qty
    computation on that line becomes infinite. The guard is the only bound."""
    so = _SO([_Line(1, 1, 3000, 0)])
    errs = validate_amendment(so, [{'so_item_id': 1, 'quantity': '1E+9999'}])
    # Exactly ONE message. Overloading None for "unparseable" and "out of range"
    # produced a second, false "could not read" alongside it.
    assert len(errs) == 1
    assert 'out of range' in errs[0].lower()
    assert 'could not read' not in errs[0].lower()


def test_the_largest_storable_quantity_is_still_accepted():
    """Boundary: the ceiling refuses what the column cannot hold, not what it can."""
    so = _SO([_Line(1, 1, 3000, 0)])
    assert validate_amendment(
        so, [{'so_item_id': 1, 'quantity': '99999999999.9999'}]) == []


def test_a_non_dict_line_is_reported_not_crashed_on():
    so = _SO([_Line(1, 1, 3000, 0)])
    errs = validate_amendment(so, ['garbage'])
    assert any('malformed' in e.lower() for e in errs)
