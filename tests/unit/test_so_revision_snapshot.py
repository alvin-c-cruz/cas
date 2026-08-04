"""Unit tests -- SO revision snapshot + change summary (pure functions)."""
import pytest
from app.sales_orders.revisions import summarize_change

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


def _snap(lines, **header):
    base = {'so_number': '2026080001', 'expected_delivery_date': '2026-08-10',
            'customer_po_number': None, 'payment_terms': 'Net 60'}
    base.update(header)
    return {'header': base, 'lines': lines}


def _line(code, name, qty, price='4.20', n=1):
    return {'line_number': n, 'product_code': code, 'product_name': name,
            'quantity': qty, 'unit_price': price}


def test_quantity_increase_is_summarised():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    new = _snap([_line('P031', 'HTA PLASTIC TRAY', '7000')])
    out = summarize_change(prev, new)
    assert out['changes'] == [{
        'kind': 'qty', 'line': 'P031 - HTA PLASTIC TRAY',
        'old': '3000', 'new': '7000'}]


def test_added_line_is_summarised_as_added():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    new = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000'),
                 _line('P022', 'GRAHAMS LONGTUB', '500', n=2)])
    out = summarize_change(prev, new)
    assert {'kind': 'added', 'line': 'P022 - GRAHAMS LONGTUB',
            'old': None, 'new': '500'} in out['changes']


def test_removed_line_is_summarised_as_removed():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000'),
                  _line('P022', 'GRAHAMS LONGTUB', '500', n=2)])
    new = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    out = summarize_change(prev, new)
    assert {'kind': 'removed', 'line': 'P022 - GRAHAMS LONGTUB',
            'old': '500', 'new': None} in out['changes']


def test_product_change_reads_as_removed_plus_added_not_a_field_edit():
    """Spec resolved edge case 1: a different product is a different commitment."""
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    new = _snap([_line('P022', 'GRAHAMS LONGTUB', '3000')])
    kinds = sorted(c['kind'] for c in summarize_change(prev, new)['changes'])
    assert kinds == ['added', 'removed']


def test_header_field_change_is_summarised():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    new = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')],
                expected_delivery_date='2026-08-20')
    assert {'kind': 'header', 'field': 'Expected delivery date',
            'old': '2026-08-10', 'new': '2026-08-20'} in summarize_change(prev, new)['changes']


def test_no_change_yields_empty_change_list():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    assert summarize_change(prev, dict(prev))['changes'] == []


def test_multiple_simultaneous_changes_all_reported():
    prev = _snap([_line('P031', 'HTA PLASTIC TRAY', '3000')])
    new = _snap([_line('P031', 'HTA PLASTIC TRAY', '7000'),
                 _line('P022', 'GRAHAMS LONGTUB', '500', n=2)],
                expected_delivery_date='2026-08-20')
    kinds = sorted(c['kind'] for c in summarize_change(prev, new)['changes'])
    assert kinds == ['added', 'header', 'qty']
