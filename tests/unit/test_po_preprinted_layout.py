"""The PO layout declares its own identity and inherits behaviour from the base."""
import pytest

from app.purchase_orders import preprinted_layout as pl

pytestmark = [pytest.mark.unit]


def test_it_declares_the_po_setting_key():
    assert pl.LAYOUT_SETTING_KEY == 'po_preprinted_layout'


def test_it_declares_every_po_header_field():
    assert pl.FIELD_KEYS == [
        'po_no', 'order_date', 'expected_date', 'vendor_name', 'vendor_tin',
        'vendor_address', 'payment_terms', 'reference', 'vat_treatment', 'total_amount',
    ]


def test_every_field_has_a_label_and_a_default_box():
    for k in pl.FIELD_KEYS:
        assert k in pl.FIELD_LABELS, f'{k} has no label'
        assert k in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'], f'{k} has no default box'


def test_it_declares_the_po_line_columns():
    assert pl.COLUMN_KEYS == [
        'line_number', 'product', 'description', 'quantity', 'uom', 'unit_price', 'amount',
    ]
    for k in pl.COLUMN_KEYS:
        assert k in pl.COLUMN_LABELS, f'{k} has no label'


def test_a_foreign_field_is_rejected_by_the_inherited_sanitiser():
    """Control: PO must not accept a Sales Order field. This is what stops one
    document's stored layout leaking into another's."""
    out = pl.sanitize_layout({'fields': {'customer_name': {'x': 10, 'y': 10}}})
    assert 'customer_name' not in out['fields']
    assert set(out['fields']) == set(pl.FIELD_KEYS)


def test_defaults_place_every_field_inside_the_canvas():
    from app.common import preprinted_base as base
    for k, box in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'].items():
        assert 0 <= box['x'] <= base.CANVAS_W, k
        assert 0 <= box['y'] <= base.CANVAS_H, k
