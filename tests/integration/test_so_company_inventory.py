"""COMPANY INVENTORY: the line in the unit the company keeps its stock in, beside the line as
ordered, on the Sales Order and the Job Order Slip.

History:
  - Owner bug reports #3/#4, 30 Oct 2026 (Philgen SO 0004, Memer Food Dealer): the PO is in
    PACKS, the company measures it in KG; two units, two unit prices, same total.
  - 4 Nov 2026: built as a fixed second unit, KG ("KG per unit" on the product), under a
    shaded "BY WEIGHT" banner (owner's Excel layout, then his approved grouped-header sample).
  - 5 Nov 2026, owner on the live print of SO 0005: "the BY WEIGHT column should also have Qty
    Unit and Price. because there are items that uses different UOM, ei. Cans", then "change
    BY WEIGHT to Company Inventory". Design he approved the same day:
      * the product carries an INVENTORY UNIT (any unit: KG, CANS ...) and an INVENTORY QTY
        PER UNIT (0.1 KG for a 100 g pack, 24 CANS for a box of 24); kg_per_unit migrates
        as unit KG;
      * the line shows qty x factor | the inventory unit | amount / that qty, under a
        COMPANY INVENTORY banner laid out like AS ORDERED (Qty | Unit | Price);
      * the footer total shows only when every line has an inventory figure in ONE unit;
      * blank when the product has none, when the line is already in the inventory unit, or
        (Claude's judgment, told to the owner) when the line is typed in a unit other than the
        product's own selling unit -- the factor counts per that unit, so the figure would be
        wrong.

SO 0004's real figures are the KG fixture: 2,000 PACKS @ 100.80 = 201,600.00 -> 200 KG @
1,008.00; 300 PACKS @ 67.20 = 20,160.00 -> 30 KG @ 672.00. The cans case: 10 BOX @ 1,200.00 =
12,000.00 of a box of 24 cans -> 240 CANS @ 50.00.
"""
import datetime
import html as html_mod
import json
import re
from decimal import Decimal

import pytest

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _print_columns,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

PRINT_COLUMNS = ['#', 'Product', 'Qty', 'Unit', 'Price', 'Qty', 'Unit', 'Price', 'Amount']
SCREEN_HEADS = ['Inventory Qty', 'Inventory Unit', 'Inventory Price']


def _uom(code):
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure.query.filter_by(code=code).first()
    if u is None:
        u = UnitOfMeasure(code=code, name=code, is_active=True)
        db.session.add(u); db.session.commit()
    return u


def _product(name, factor, inventory_unit='KG', selling_unit='PACKS'):
    from app.products.models import Product
    p = Product(name=name,
                default_unit_of_measure_id=_uom(selling_unit).id if selling_unit else None,
                inventory_unit_id=_uom(inventory_unit).id if factor is not None else None,
                inventory_qty_per_unit=factor, is_active=True)
    db.session.add(p); db.session.commit()
    return p


def _line(so, n, product, qty, price, unit='PACKS', uom_text=None):
    item = SalesOrderItem(sales_order_id=so.id, line_number=n, product_id=product.id,
                          quantity=Decimal(qty), unit_price=Decimal(price),
                          unit_of_measure_id=_uom(unit).id if unit else None, uom_text=uom_text,
                          vat_category='V12', vat_rate=Decimal('12'))
    item.calculate_amounts()
    db.session.add(item)
    return item


def _so(db_session, branch, number='SO-INV-0004', status='confirmed'):
    c = _customer(db_session)
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 10, 28),
                    customer_id=c.id, customer_name='MEMER FOOD DEALER', customer_po_number='3057',
                    branch_id=branch.id, payment_terms='Net 30', status=status)
    db.session.add(so); db.session.flush()
    return so


def _finish(so):
    db.session.flush()
    so.calculate_totals()
    db.session.commit()
    return so


def _so_0004(db_session, branch, mango_factor=Decimal('0.1'), papaya_factor=Decimal('0.1'),
             status='confirmed'):
    so = _so(db_session, branch, status=status)
    _line(so, 1, _product('A ONE DRIED MANGO SLICES 100g', mango_factor), '2000', '100.80')
    _line(so, 2, _product('A ONE DRIED PAPAYA CHUNKS 100g', papaya_factor), '300', '67.20')
    return _finish(so)


def _juice_box(factor=Decimal('24')):
    return _product('MANGO JUICE BOX (24 CANS)', factor, inventory_unit='CANS', selling_unit='BOX')


# ---- the arithmetic, on the SO line ----------------------------------------------------

def test_the_inventory_quantity_is_the_quantity_times_the_products_factor(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    mango, papaya = so.line_items
    assert mango.inventory_quantity == Decimal('200')
    assert papaya.inventory_quantity == Decimal('30')
    assert mango.inventory_unit_code == 'KG'


def test_the_inventory_unit_is_whatever_the_product_keeps_its_stock_in(db_session, main_branch):
    """The owner's case: a box of 24 cans, counted in CANS -- not a weight."""
    so = _so(db_session, main_branch)
    _line(so, 1, _juice_box(), '10', '1200.00', unit='BOX')
    line = _finish(so).line_items[0]
    assert line.inventory_quantity == Decimal('240')
    assert line.inventory_unit_code == 'CANS'
    assert line.inventory_unit_price == Decimal('50.00')


def test_the_inventory_price_is_the_amount_over_the_inventory_quantity(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    mango, papaya = so.line_items
    assert mango.amount == Decimal('201600.00')
    assert mango.inventory_unit_price == Decimal('1008.00')
    assert papaya.inventory_unit_price == Decimal('672.00')


def test_the_inventory_price_rounds_half_up_to_centavos(db_session, main_branch):
    """1,000.00 over 3 KG is 333.333...; a price is two decimals, rounded half up."""
    so = _so_0004(db_session, main_branch)
    line = so.line_items[0]
    line.amount = Decimal('1000.00')
    line.quantity = Decimal('30')          # x 0.1 = 3 KG
    assert line.inventory_unit_price == Decimal('333.33')


def test_a_product_without_an_inventory_unit_has_no_inventory_figures(db_session, main_branch):
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    papaya = so.line_items[1]
    assert papaya.inventory_quantity is None
    assert papaya.inventory_unit_code is None
    assert papaya.inventory_unit_price is None


def test_a_line_without_quantity_has_no_inventory_figures(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    line = so.line_items[0]
    line.quantity = None
    assert line.inventory_quantity is None
    assert line.inventory_unit_price is None


def test_a_line_already_in_the_inventory_unit_has_no_second_figure(db_session, main_branch):
    """SO 0005: the lines are sold in KG already -- a second KG column would only repeat them."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('DRIED MANGO REGULAR', Decimal('1'), selling_unit=None), '50', '800.00',
          unit='KG')
    line = _finish(so).line_items[0]
    assert line.inventory_quantity is None
    assert line.inventory_unit_code is None


def test_a_line_typed_in_another_unit_than_the_products_has_no_inventory_figures(db_session, main_branch):
    """The factor counts per the product's own unit (24 cans per BOX). A line sold by the CASE
    would be multiplied by the wrong number, so it shows nothing rather than a wrong figure."""
    so = _so(db_session, main_branch)
    _line(so, 1, _juice_box(), '10', '1200.00', unit='CASE')
    line = _finish(so).line_items[0]
    assert line.inventory_quantity is None
    assert line.inventory_unit_price is None


def test_a_product_whose_own_unit_is_its_inventory_unit_converts_other_units(db_session, main_branch):
    """Philgen product 616 (A ONE DRIED PAPAYA CHUNKS 100g) has KG as its unit in the master
    but is ordered in PACKS (SO 0004 line 2). KG cannot be the unit the factor counts per --
    nobody converts KG into KG -- so the 'another unit' guard does not apply: 300 PACKS x 0.1
    = 30 KG. A line typed in KG is still blank (already in the inventory unit)."""
    so = _so(db_session, main_branch)
    papaya = _product('A ONE DRIED PAPAYA CHUNKS 100g', Decimal('0.1'), selling_unit='KG')
    _line(so, 1, papaya, '300', '67.20', unit='PACKS')
    _line(so, 2, papaya, '30', '672.00', unit='KG')
    in_packs, in_kg = _finish(so).line_items
    assert in_packs.inventory_quantity == Decimal('30')
    assert in_packs.inventory_unit_price == Decimal('672.00')
    assert in_kg.inventory_quantity is None


def test_a_free_text_unit_is_compared_by_its_code(db_session, main_branch):
    """With the UOM master off a line carries only typed text; 'packs' is the product's PACKS."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('TYPED UNIT MANGO 100g', Decimal('0.1')), '2000', '100.80',
          unit=None, uom_text='packs')
    _line(so, 2, _product('TYPED UNIT PAPAYA 100g', Decimal('0.1')), '20', '1000.00',
          unit=None, uom_text='kg')
    typed_packs, typed_kg = _finish(so).line_items
    assert typed_packs.inventory_quantity == Decimal('200')
    assert typed_kg.inventory_quantity is None


def test_a_product_without_a_selling_unit_still_converts(db_session, main_branch):
    """Many Philgen products have no default unit; there is nothing to disagree with."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('NO SELLING UNIT JUICE', Decimal('24'), inventory_unit='CANS',
                          selling_unit=None), '10', '1200.00', unit='BOX')
    assert _finish(so).line_items[0].inventory_quantity == Decimal('240')


def test_the_order_total_is_the_sum_in_the_one_inventory_unit(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    assert so.inventory_total == Decimal('230')
    assert so.inventory_total_unit == 'KG'


def test_the_order_has_no_inventory_total_when_a_line_has_none(db_session, main_branch):
    """A sum over only some lines would read as the order's total and be wrong."""
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    assert so.inventory_total is None
    assert so.inventory_total_unit is None


def test_the_order_has_no_inventory_total_when_the_units_differ(db_session, main_branch):
    """200 KG and 240 CANS do not add up to anything."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('MIXED MANGO 100g', Decimal('0.1')), '2000', '100.80')
    _line(so, 2, _juice_box(), '10', '1200.00', unit='BOX')
    so = _finish(so)
    assert so.inventory_total is None
    assert so.inventory_total_unit is None


def test_an_order_without_lines_has_no_inventory_total(db_session, main_branch):
    so = _finish(_so(db_session, main_branch, number='SO-INV-EMPTY', status='draft'))
    assert so.inventory_total is None


def test_the_product_dict_carries_the_inventory_unit_and_factor(db_session):
    """The SO form's product list is built from Product.to_dict(); the screen computes the
    COMPANY INVENTORY columns from these values."""
    d = _juice_box().to_dict()
    assert d['inventory_unit_code'] == 'CANS'
    assert d['inventory_unit_id'] == _uom('CANS').id
    assert d['inventory_qty_per_unit'] == 24.0
    assert 'kg_per_unit' not in d
    blank = _product('INV DICT NONE', None).to_dict()
    assert blank['inventory_unit_id'] is None and blank['inventory_qty_per_unit'] is None


# ---- the product master ----------------------------------------------------------------

@pytest.fixture
def products_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache(); clear_uom_cache()
    yield
    clear_module_config_cache(); clear_uom_cache()


def _product_post(**extra):
    data = {'name': 'INV FORM MANGO 100g', 'description': '', 'default_unit_of_measure_id': '',
            'default_unit_price': '', 'default_account_id': '', 'category_id': '',
            'standard_cost': '', 'inventory_unit_id': '', 'inventory_qty_per_unit': '',
            'is_active': '1'}
    data.update(extra)
    return data


def _signed_in(client, admin_user, main_branch):
    _login(client, admin_user); _select_branch(client, main_branch.id)


def test_the_product_form_shows_the_inventory_unit_and_factor(client, db_session, admin_user,
                                                             main_branch, products_on):
    _uom('CANS')
    _signed_in(client, admin_user, main_branch)
    html = client.get('/products/create').get_data(as_text=True)
    assert re.search(r'<select[^>]*name="inventory_unit_id"', html)
    assert 'name="inventory_qty_per_unit"' in html
    assert 'Inventory Unit' in html and 'Inventory Qty per Unit' in html
    assert 'name="kg_per_unit"' not in html and 'KG per unit' not in html


def test_creating_and_editing_a_product_keeps_its_inventory_unit(client, db_session, admin_user,
                                                                 main_branch, products_on):
    from app.products.models import Product
    from app.audit.models import AuditLog
    kg, cans = _uom('KG'), _uom('CANS')
    _signed_in(client, admin_user, main_branch)
    client.post('/products/create', data=_product_post(inventory_unit_id=str(kg.id),
                                                       inventory_qty_per_unit='0.1'))
    p = Product.query.filter_by(name='INV FORM MANGO 100g').first()
    assert p is not None
    assert (p.inventory_unit_id, p.inventory_qty_per_unit) == (kg.id, Decimal('0.1'))

    client.post(f'/products/{p.id}/edit', data=_product_post(inventory_unit_id=str(cans.id),
                                                             inventory_qty_per_unit='24'))
    db.session.refresh(p)
    assert (p.inventory_unit_id, p.inventory_qty_per_unit) == (cans.id, Decimal('24'))
    row = (AuditLog.query.filter_by(module='products', record_id=p.id, action='update')
           .order_by(AuditLog.id.desc()).first())
    assert row is not None
    old, new = json.loads(row.old_values), json.loads(row.new_values)
    assert (old['inventory_unit_code'], old['inventory_qty_per_unit']) == ('KG', 0.1)
    assert (new['inventory_unit_code'], new['inventory_qty_per_unit']) == ('CANS', 24.0)

    client.post(f'/products/{p.id}/edit', data=_product_post())
    db.session.refresh(p)
    assert p.inventory_unit_id is None and p.inventory_qty_per_unit is None


@pytest.mark.parametrize('bad', ['0', '-0.1'])
def test_the_inventory_qty_per_unit_must_be_above_zero(client, db_session, admin_user, main_branch,
                                                       products_on, bad):
    from app.products.models import Product
    _signed_in(client, admin_user, main_branch)
    client.post('/products/create', data=_product_post(name=f'INV BAD {bad}',
                                                       inventory_unit_id=str(_uom('KG').id),
                                                       inventory_qty_per_unit=bad))
    assert Product.query.filter_by(name=f'INV BAD {bad}').first() is None


@pytest.mark.parametrize('unit, qty', [('KG', ''), ('', '0.1')])
def test_the_unit_and_its_quantity_go_together(client, db_session, admin_user, main_branch,
                                               products_on, unit, qty):
    """A unit with no quantity converts nothing; a quantity with no unit has no meaning."""
    from app.products.models import Product
    _signed_in(client, admin_user, main_branch)
    resp = client.post('/products/create', data=_product_post(
        name='INV HALF', inventory_unit_id=str(_uom(unit).id) if unit else '',
        inventory_qty_per_unit=qty))
    assert Product.query.filter_by(name='INV HALF').first() is None
    assert 'Inventory' in resp.get_data(as_text=True)


@pytest.mark.parametrize('with_unit', [False, True], ids=['no-unit', 'cans'])
def test_an_edit_that_leaves_the_inventory_fields_out_keeps_them(client, db_session, admin_user,
                                                                 main_branch, products_on, with_unit):
    """A post without the two fields (an older screen, a partial post) changes what it names and
    keeps the stored unit -- it is not refused as 'not a valid choice'. Seen in the full suite,
    5 Nov 2026: eight product-edit tests saved nothing, because the form turned a product's
    stored None into the text 'None', which is not in the list."""
    p = _juice_box() if with_unit else _product('NO INVENTORY UNIT PRODUCT', None)
    _signed_in(client, admin_user, main_branch)
    data = _product_post(name=f'{p.name} RENAMED')
    del data['inventory_unit_id'], data['inventory_qty_per_unit']
    client.post(f'/products/{p.id}/edit', data=data)
    db.session.refresh(p)
    assert p.name.endswith(' RENAMED')
    if with_unit:
        assert (p.inventory_unit.code, p.inventory_qty_per_unit) == ('CANS', Decimal('24'))
    else:
        assert p.inventory_unit_id is None and p.inventory_qty_per_unit is None


def test_a_unit_that_is_not_in_the_list_is_refused(client, db_session, admin_user, main_branch,
                                                   products_on):
    from app.products.models import Product
    _signed_in(client, admin_user, main_branch)
    client.post('/products/create', data=_product_post(name='INV UNKNOWN UNIT',
                                                       inventory_unit_id='999999',
                                                       inventory_qty_per_unit='2'))
    assert Product.query.filter_by(name='INV UNKNOWN UNIT').first() is None


def test_the_edit_page_shows_the_factor_without_trailing_zeros(client, db_session, admin_user,
                                                               main_branch, products_on):
    """The column holds six places; the owner should read 24 and 0.1, not 24.000000."""
    box = _juice_box()
    pack = _product('TRAILING ZEROS 100g', Decimal('0.1'))
    _signed_in(client, admin_user, main_branch)
    for p, shown in [(box, '24'), (pack, '0.1')]:
        html = client.get(f'/products/{p.id}/edit').get_data(as_text=True)
        m = re.search(r'<input[^>]*name="inventory_qty_per_unit"[^>]*>', html)
        assert m and f'value="{shown}"' in m.group(0), m and m.group(0)


# ---- the SO printout -------------------------------------------------------------------

def _particulars(page):
    m = re.search(r'<table class="particulars".*?</table>', page, re.S)
    assert m, 'the particulars table did not render'
    return m.group(0)


def _cells(row_html):
    return [html_mod.unescape(re.sub(r'<[^>]+>', '', c)).strip()
            for c in re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.S)]


def _body_rows(table):
    body = re.search(r'<tbody.*?</tbody>', table, re.S).group(0)
    return re.findall(r'<tr[^>]*>.*?</tr>', body, re.S)


def _foot(page):
    return re.search(r'<tfoot.*?</tfoot>', _particulars(page), re.S).group(0)


def _classes(attrs):
    m = re.search(r'class="([^"]*)"', attrs)
    return set(m.group(1).split()) if m else set()


def _print(client, admin_user, main_branch, so):
    _signed_in(client, admin_user, main_branch)
    return client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    """Mango in KG, papaya with no inventory unit, the juice box in CANS."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('A ONE DRIED MANGO SLICES 100g', Decimal('0.1')), '2000', '100.80')
    _line(so, 2, _product('A ONE DRIED PAPAYA CHUNKS 100g', None), '300', '67.20')
    _line(so, 3, _juice_box(), '10', '1200.00', unit='BOX')
    so = _finish(so)
    return so, _print(client, admin_user, main_branch, so)


def test_the_print_columns_are_as_ordered_then_company_inventory_then_amount(printed):
    so, page = printed
    assert _print_columns(_particulars(page)) == PRINT_COLUMNS


def test_the_group_banners_head_their_columns(printed):
    so, page = printed
    thead = re.search(r'<thead>.*?</thead>', _particulars(page), re.S).group(0)
    assert re.search(r'<th colspan="3"[^>]*>AS ORDERED</th>', thead)
    assert re.search(r'<th colspan="3"[^>]*>COMPANY INVENTORY</th>', thead)
    assert 'BY WEIGHT' not in page and 'Weight (kg)' not in page and 'Price per kg' not in page


def test_a_line_prints_its_inventory_qty_unit_and_price(printed):
    so, page = printed
    rows = _body_rows(_particulars(page))
    assert _cells(rows[0]) == ['1', 'A ONE DRIED MANGO SLICES 100g', '2,000', 'PACKS', '100.80',
                               '200', 'KG', '1,008.00', '201,600.00']
    assert _cells(rows[2]) == ['3', 'MANGO JUICE BOX (24 CANS)', '10', 'BOX', '1,200.00',
                               '240', 'CANS', '50.00', '12,000.00']


def test_a_line_without_an_inventory_unit_leaves_its_cells_blank(printed):
    """Blank, not an em dash: nothing is missing, the line simply has no second unit."""
    so, page = printed
    papaya = _cells(_body_rows(_particulars(page))[1])
    assert papaya[2:5] == ['300', 'PACKS', '67.20']
    assert papaya[5:8] == ['', '', '']
    assert papaya[8] == '20,160.00'


def test_every_print_body_row_has_nine_cells(printed):
    so, page = printed
    counts = {len(re.findall(r'<td', r)) for r in _body_rows(_particulars(page))}
    assert counts == {9}


def test_the_inventory_columns_are_shaded_on_every_row(printed):
    """Data rows and the blank grid alike, so the band runs the height of the table."""
    so, page = printed
    for row in _body_rows(_particulars(page)):
        tds = re.findall(r'<td([^>]*)>', row)
        assert [i for i, a in enumerate(tds) if 'inv' in _classes(a)] == [5, 6, 7], row
    heads = re.findall(r'<th\b([^>]*)>(.*?)</th>', _particulars(page), re.S)
    shaded = [label for attrs, label in heads if 'inv' in _classes(attrs)]
    assert shaded == ['COMPANY INVENTORY', 'Qty', 'Unit', 'Price']


def test_the_shading_survives_printing(printed):
    """Browsers drop backgrounds when printing unless told not to."""
    so, page = printed
    rule = re.search(r'\.particulars \.inv \{[^}]*\}', page)
    assert rule, 'no rule for the shaded inventory cells'
    assert re.search(r'background:\s*#[0-9a-fA-F]{3,6}', rule.group(0))
    assert re.search(r'(?<!-)print-color-adjust:\s*exact', rule.group(0))


def test_the_total_row_prints_the_inventory_total_and_its_unit(client, db_session, admin_user,
                                                               main_branch, sales_orders_module_enabled):
    so = _so_0004(db_session, main_branch)            # both lines in KG
    foot = _foot(_print(client, admin_user, main_branch, so))
    assert _cells(foot) == ['Total', '230', 'KG', '', '221,760.00']
    assert re.search(r'<td colspan="5"[^>]*>Total</td>', foot)


def test_the_inventory_total_is_blank_when_the_lines_do_not_share_one_unit(printed):
    so, page = printed
    assert _cells(_foot(page)) == ['Total', '', '', '', '233,760.00']


def test_the_print_rows_are_single_line_height(printed):
    so, page = printed
    m = re.search(r'table\.particulars tbody td\s*\{\s*height:\s*([\d.]+)px', page)
    assert m and float(m.group(1)) == 22     # single line: just above the ~21.6px content


# ---- the SO screens --------------------------------------------------------------------

def _heads(html_part):
    return [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<th\b[^>]*>.*?</th>', html_part, re.S)]


def test_the_so_detail_shows_the_inventory_columns(client, db_session, admin_user, main_branch,
                                                   sales_orders_module_enabled):
    so = _so(db_session, main_branch)
    _line(so, 1, _juice_box(), '10', '1200.00', unit='BOX')
    so = _finish(so)
    _signed_in(client, admin_user, main_branch)
    page = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    heads = _heads(page)
    assert all(h in heads for h in SCREEN_HEADS), heads
    assert 'Weight (kg)' not in heads and 'Price per kg' not in heads
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', page))
    assert re.search(r'\b240 CANS 50\.00\b', text), 'the line in CANS is not on the detail screen'


def test_the_so_form_has_the_inventory_columns_and_the_product_factor(client, db_session, admin_user,
                                                                      main_branch, sales_orders_module_enabled):
    so = _so_0004(db_session, main_branch, status='draft')
    _signed_in(client, admin_user, main_branch)
    page = client.get(f'/sales-orders/{so.id}/edit').get_data(as_text=True)
    thead = re.search(r'<thead>.*?</thead>', page[page.index('Unit Price') - 2000:], re.S).group(0)
    heads = _heads(thead)
    assert all(h in heads for h in SCREEN_HEADS), heads
    assert 'Weight (kg)' not in heads and 'Price per kg' not in heads
    assert re.search(r'"inventory_qty_per_unit":\s*0\.1', page)
    assert re.search(r'"inventory_unit_code":\s*"KG"', page)
    assert 'function refreshInventory' in page and 'kg_per_unit' not in page


# ---- the Job Order Slip ----------------------------------------------------------------

def test_the_job_order_slip_prints_the_inventory_qty_and_unit(client, db_session, admin_user,
                                                              main_branch, sales_orders_module_enabled):
    """Unpriced, as before -- the slip goes to production. Eight columns, every row."""
    so = _so(db_session, main_branch)
    _line(so, 1, _product('A ONE DRIED MANGO SLICES 100g', Decimal('0.1')), '2000', '100.80')
    _line(so, 2, _product('A ONE DRIED PAPAYA CHUNKS 100g', None), '300', '67.20')
    _line(so, 3, _juice_box(), '10', '1200.00', unit='BOX')
    so = _finish(so)
    _signed_in(client, admin_user, main_branch)
    page = client.get(f'/sales-orders/{so.so_number}/print-job-order').get_data(as_text=True)
    table = re.search(r'<table class="jo-table".*?</table>', page, re.S).group(0)
    assert _heads(table) == ['Qty', 'Unit', 'Inventory Qty', 'Inventory Unit', 'Description',
                             'PO Number', 'Delivery Date', 'Remarks']
    rows = re.findall(r'<tr>\s*<td class="qty">.*?</tr>', table, re.S)
    assert [_cells(r)[:4] for r in rows[:3]] == [['2,000', 'PACKS', '200', 'KG'],
                                                 ['300', 'PACKS', '', ''],
                                                 ['10', 'BOX', '240', 'CANS']]
    body = re.search(r'<tbody.*?</tbody>', table, re.S).group(0)
    assert {len(re.findall(r'<td', r)) for r in re.findall(r'<tr[^>]*>.*?</tr>', body, re.S)} == {8}
    assert '100.80' not in table and '1,008.00' not in table and '50.00' not in table
