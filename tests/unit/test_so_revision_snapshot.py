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
           'product_id': 1 if code == 'P031' else 2,
           'product_code': code, 'product_name': name,
           'quantity': qty, 'unit_price': price,
           'unit_price_display': price, 'amount': None, 'amount_display': None,
           'vat_category': 'V12', 'vat_rate': '12.00',
           'uom_key': '1|', 'uom_display': 'pcs',
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


def test_money_formatter_keeps_two_decimals_where_s_collapses_them():
    from app.sales_orders.revisions import _money
    assert _s(Decimal('4.20')) == '4.2'          # canonical, for comparison
    assert _money(Decimal('4.20')) == '4.20'     # display, for the slip
    assert _money(Decimal('12600')) == '12600.00'


def test_negative_zero_serialises_identically_to_zero():
    """Decimal('-0') == Decimal('0') is True; unequal strings for equal values
    is exactly the failure mode this normalisation exists to prevent."""
    assert _s(Decimal('-0')) == _s(Decimal('0')) == '0'


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


def test_line_identity_survives_a_line_number_reassignment_on_reorder():
    """line_number is the per-order DISPLAY position and gets reassigned when
    lines are reordered; SalesOrderItem.id (line_id) is the only identity that
    survives it. The default `_line()` sets line_number == line_id, which makes
    a regression to line_number-keyed pairing invisible at the unit level
    unless the two are made to diverge explicitly, as here -- the ORM
    integration test (test_renumbering_lines_on_reorder_is_not_a_change) covers
    the same regression through real objects, but this pins it as a pure-dict
    unit test too."""
    prev = _snap([
        _line(1, line_number=1, code='P031', name='HTA PLASTIC TRAY', qty='3000'),
        _line(2, line_number=2, code='P022', name='GRAHAMS LONGTUB', qty='500'),
    ])
    new = _snap([
        _line(1, line_number=2, code='P031', name='HTA PLASTIC TRAY', qty='3000'),
        _line(2, line_number=1, code='P022', name='GRAHAMS LONGTUB', qty='500'),
    ])
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
        _snap([_line(1, qty=None, price=None, amount='100000.00',
                     amount_display='100000.00')]),
        _snap([_line(1, qty=None, price=None, amount='5000.00',
                     amount_display='5000.00')]))
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


def test_product_change_on_the_SAME_line_is_reported():
    """The amend route updates rows IN PLACE, so a product swap keeps the line
    id. Without product_id in the compared set this reported nothing, and the
    label printed the NEW product beside the OLD quantity."""
    prev = _snap([_line(1, code='P031', name='HTA PLASTIC TRAY')])
    new = _snap([_line(1, code='P022', name='GRAHAMS LONGTUB')])
    assert {'kind': 'line_field', 'line': 'P022 - GRAHAMS LONGTUB',
            'field': 'Product', 'old': 'HTA PLASTIC TRAY',
            'new': 'GRAHAMS LONGTUB'} in summarize_change(prev, new)['changes']


def test_a_line_without_an_id_fails_closed():
    """Silently dropping an unidentified line makes the diff UNDER-report --
    an added line would vanish from a revision carrying a reason and a PO."""
    bad = _line(1)
    bad['line_id'] = None
    with pytest.raises(ValueError, match='line_id'):
        summarize_change(_snap([]), _snap([bad]))


def test_amount_is_not_reported_when_quantity_already_explains_it():
    """amount is derived (qty x price) exactly as the header totals are, and
    those are already suppressed. Reporting it too double-counts one edit."""
    prev = _snap([_line(1, qty='3000', amount='12600.00',
                        amount_display='12600.00')])
    new = _snap([_line(1, qty='7000', amount='29400.00',
                       amount_display='29400.00')])
    changes = summarize_change(prev, new)['changes']
    assert changes == [{'kind': 'qty', 'line': 'P031 - HTA PLASTIC TRAY',
                        'old': '3000', 'new': '7000'}]


def test_free_text_uom_change_is_reported_when_the_fk_is_null_on_both_sides():
    """uom_text is a real nullable column used whenever unit_of_measure_id is
    null. '3000 pcs' and '3000 kg' are different manufacturing instructions."""
    prev = _snap([_line(1, uom_key='|pcs', uom_display='pcs')])
    new = _snap([_line(1, uom_key='|kg', uom_display='kg')])
    assert summarize_change(prev, new)['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'UOM', 'old': 'pcs', 'new': 'kg'}]


def test_money_is_displayed_at_two_decimal_places():
    """_s canonicalises for COMPARISON ('4.20' -> '4.2'), which is wrong on a
    printed slip. Display comes from the separate *_display fields."""
    out = summarize_change(
        _snap([_line(1, price='4.2', unit_price_display='4.20')]),
        _snap([_line(1, price='5', unit_price_display='5.00')]))
    assert out['changes'] == [{
        'kind': 'line_field', 'line': 'P031 - HTA PLASTIC TRAY',
        'field': 'Unit price', 'old': '4.20', 'new': '5.00'}]


def test_salesperson_change_is_reported():
    prev = _snap([_line(1)], salesperson_name='ANA REYES')
    new = _snap([_line(1)], salesperson_name='BEN CRUZ')
    assert {'kind': 'header', 'field': 'Salesperson',
            'old': 'ANA REYES', 'new': 'BEN CRUZ'} in summarize_change(prev, new)['changes']


def test_header_field_change_is_summarised():
    prev = _snap([_line(1)])
    new = _snap([_line(1)], expected_delivery_date='2026-08-20')
    assert {'kind': 'header', 'field': 'Expected delivery date',
            'old': '2026-08-10', 'new': '2026-08-20'} in summarize_change(prev, new)['changes']
