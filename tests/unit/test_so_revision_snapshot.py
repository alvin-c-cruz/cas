"""Unit tests -- SO revision snapshot + change summary."""
import pytest
from decimal import Decimal
from app.sales_orders.revisions import summarize_change, build_snapshot, _s

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


def _snap(lines, **header):
    base = {'so_number': '2026080001', 'expected_delivery_date': '2026-08-10',
            'customer_po_number': None, 'payment_terms': 'Net 60'}
    base.update(header)
    return {'header': base, 'lines': lines}


def _line(line_id, code='P031', name='HTA PLASTIC TRAY', qty='3000',
          price='4.20', **over):
    """A snapshot line. `line_id` is the SalesOrderItem row id -- the identity
    the diff matches on."""
    row = {'line_id': line_id, 'line_number': line_id,
           'product_code': code, 'product_name': name,
           'quantity': qty, 'unit_price': price, 'amount': None,
           'vat_category': 'V12', 'vat_rate': '12.00',
           'unit_of_measure_id': 1, 'uom_display': 'pcs',
           'delivery_date': None, 'delivery_site_id': None,
           'delivery_site_name': None, 'wt_id': None, 'wt_code': None,
           'line_status': 'open'}
    row.update(over)
    return row


# --- canonical serialisation (the seam a dict-only suite cannot see) --------

def test_decimal_from_db_and_from_form_serialise_identically():
    """Numeric(15,4) reads back as Decimal('3000.0000'); the form parser gives
    Decimal('3000'). If these serialise differently, every line of an amendment
    that changed NOTHING reports a fabricated change."""
    assert _s(Decimal('3000.0000')) == _s(Decimal('3000')) == '3000'
    assert _s(Decimal('4.2000')) == _s(Decimal('4.20')) == '4.2'


def test_large_integral_decimal_does_not_become_scientific_notation():
    """Decimal('3000').normalize() is Decimal('3E+3') -- format(..., 'f') is
    what keeps it readable."""
    assert _s(Decimal('3000')) == '3000'


# --- diffing ----------------------------------------------------------------

def test_quantity_increase_is_summarised():
    out = summarize_change(_snap([_line(1, qty='3000')]),
                           _snap([_line(1, qty='7000')]))
    assert out['changes'] == [{
        'kind': 'qty', 'line': 'P031 - HTA PLASTIC TRAY',
        'old': '3000', 'new': '7000'}]


def test_no_change_yields_empty_change_list():
    assert summarize_change(_snap([_line(1)]), _snap([_line(1)]))['changes'] == []


def test_added_line_is_summarised_as_added():
    out = summarize_change(
        _snap([_line(1)]),
        _snap([_line(1), _line(2, code='P022', name='GRAHAMS LONGTUB', qty='500')]))
    assert {'kind': 'added', 'line': 'P022 - GRAHAMS LONGTUB',
            'old': None, 'new': '500'} in out['changes']


def test_removed_line_is_summarised_as_removed():
    out = summarize_change(
        _snap([_line(1), _line(2, code='P022', name='GRAHAMS LONGTUB', qty='500')]),
        _snap([_line(1)]))
    assert out['changes'] == [{'kind': 'removed', 'line': 'P022 - GRAHAMS LONGTUB',
                               'old': '500', 'new': None}]


def test_product_change_reads_as_removed_plus_added_not_a_field_edit():
    """A different product is a different commitment: the old row goes, a new
    one arrives, so the ids differ and it reads as removed + added."""
    out = summarize_change(_snap([_line(1, code='P031', name='HTA PLASTIC TRAY')]),
                           _snap([_line(2, code='P022', name='GRAHAMS LONGTUB')]))
    assert sorted(c['kind'] for c in out['changes']) == ['added', 'removed']


def test_removing_the_FIRST_of_two_tranches_attributes_the_removal_correctly():
    """Position-based pairing fabricated a '3000 -> 2000' edit on the untouched
    survivor and attributed the removal to the wrong quantity."""
    prev = _snap([_line(1, qty='3000'), _line(2, qty='2000')])
    new = _snap([_line(2, qty='2000')])
    assert summarize_change(prev, new)['changes'] == [{
        'kind': 'removed', 'line': 'P031 - HTA PLASTIC TRAY',
        'old': '3000', 'new': None}]


def test_inserting_a_tranche_mid_list_reports_the_new_quantity():
    """Position-based pairing reported the NEW quantity as an edit and the OLD
    one as the addition; the real new tranche never appeared at all."""
    prev = _snap([_line(1, qty='3000'), _line(2, qty='2000')])
    new = _snap([_line(1, qty='3000'), _line(3, qty='999'), _line(2, qty='2000')])
    assert summarize_change(prev, new)['changes'] == [{
        'kind': 'added', 'line': 'P031 - HTA PLASTIC TRAY',
        'old': None, 'new': '999'}]


def test_reordering_lines_is_not_a_change():
    """Identity is the row id, so list order carries no meaning."""
    prev = _snap([_line(1, qty='3000'), _line(2, qty='2000')])
    new = _snap([_line(2, qty='2000'), _line(1, qty='3000')])
    assert summarize_change(prev, new)['changes'] == []


def test_editing_one_tranche_while_deleting_another_reports_both_truthfully():
    """The case that defeated positional pairing: an off-tail delete coinciding
    with an edit on a surviving line."""
    prev = _snap([_line(1, qty='100'), _line(2, qty='200')])
    new = _snap([_line(2, qty='250')])
    changes = summarize_change(prev, new)['changes']
    assert {'kind': 'qty', 'line': 'P031 - HTA PLASTIC TRAY',
            'old': '200', 'new': '250'} in changes
    assert {'kind': 'removed', 'line': 'P031 - HTA PLASTIC TRAY',
            'old': '100', 'new': None} in changes
    assert len(changes) == 2


def test_unit_price_change_is_reported():
    out = summarize_change(_snap([_line(1, price='4.20')]),
                           _snap([_line(1, price='5.00')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'Unit price', 'old': '4.20', 'new': '5.00'}]


def test_amount_only_change_is_reported():
    """Non-itemised lines carry an amount with no qty/price. Omitting `amount`
    from the compared set made a large money swing report as no change."""
    out = summarize_change(
        _snap([_line(1, qty=None, price=None, amount='100000.00')]),
        _snap([_line(1, qty=None, price=None, amount='5000.00')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'Amount', 'old': '100000.00', 'new': '5000.00'}]


def test_vat_rate_change_is_reported_even_when_the_category_name_is_unchanged():
    """Tax rates are edited in place, so a category name can stay constant while
    the rate behind it moves."""
    out = summarize_change(_snap([_line(1, vat_rate='12.00')]),
                           _snap([_line(1, vat_rate='10.00')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'VAT rate', 'old': '12.00', 'new': '10.00'}]


def test_delivery_site_change_between_two_same_named_sites_is_reported():
    """Sites are compared on id but DISPLAYED by name. CustomerDeliverySite has
    no unique constraint on (customer_id, name), so comparing names alone would
    hide a real change."""
    out = summarize_change(
        _snap([_line(1, delivery_site_id=3, delivery_site_name='WAREHOUSE')]),
        _snap([_line(1, delivery_site_id=5, delivery_site_name='WAREHOUSE')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'Delivery site', 'old': 'WAREHOUSE', 'new': 'WAREHOUSE'}]


def test_line_status_change_is_reported():
    out = summarize_change(_snap([_line(1, line_status='open')]),
                           _snap([_line(1, line_status='closed')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'Line status', 'old': 'open', 'new': 'closed'}]


def test_header_field_change_is_summarised():
    prev = _snap([_line(1)])
    new = _snap([_line(1)], expected_delivery_date='2026-08-20')
    assert {'kind': 'header', 'field': 'Expected delivery date',
            'old': '2026-08-10', 'new': '2026-08-20'} in summarize_change(prev, new)['changes']
