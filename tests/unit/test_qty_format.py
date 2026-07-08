from types import SimpleNamespace
from decimal import Decimal
from app.utils import format_line_qty


def _item(qty, uom_name=None, uom_code=None, uom_text=None):
    uom = SimpleNamespace(name=uom_name, code=uom_code) if (uom_name or uom_code) else None
    return SimpleNamespace(quantity=qty, unit_of_measure=uom, uom_text=uom_text)


def test_pieces_qty_has_no_decimals():
    assert format_line_qty(_item(Decimal('2'), uom_name='Pieces')) == '2'
    assert format_line_qty(_item(Decimal('2'), uom_code='pcs')) == '2'
    assert format_line_qty(_item(Decimal('5'), uom_text='piece')) == '5'
    assert format_line_qty(_item(Decimal('1000'), uom_name='Pieces')) == '1,000'


def test_non_pieces_keeps_four_decimals():
    assert format_line_qty(_item(Decimal('2.5'), uom_name='Kilogram')) == '2.5000'
    assert format_line_qty(_item(Decimal('2'), uom_name='Liter')) == '2.0000'
    assert format_line_qty(_item(Decimal('2'))) == '2.0000'   # no UOM -> keep decimals


def test_none_qty_returns_blank():
    assert format_line_qty(_item(None, uom_name='Pieces')) == ''
    assert format_line_qty(_item(None), blank='-') == '-'
