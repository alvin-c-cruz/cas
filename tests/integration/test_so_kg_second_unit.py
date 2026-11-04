"""A second unit, KG, beside the selling unit on the Sales Order and the Job Order Slip.

Owner bug reports, 30 Oct 2026 (Philgen SO 0004, Memer Food Dealer):
  #3 "the SO and Job Order should have two UOM, because the PO is in PACK while the
      company measure it by KG. Total weight will be the same. There should also be two
      unit price, one for each UOM."
  #4 "Job order print has no UOM. adjust for the double UOM layout"

Owner's layout and answers, 4 Nov 2026 (Excel copy of the SO print, edited by him):
  - after Qty / UOM / Unit Price comes a second Qty / UOM / Unit Price, then Amount;
  - KG qty = qty x the product's "KG per unit" (a 100 g pack is 0.1), set once on the
    product master;  KG price = amount / KG qty  (his formulas: =H12/10, =R12/M12);
  - the 10 line rows are single-line height (his Excel), not the 51px rows of 31 Aug;
  - the SO screens show the KG figures too, computed, never typed.

Owner, later on 4 Nov 2026 ("the two UOM looks confusing"), from a sample he approved:
  - GROUPED HEADERS: "AS ORDERED" over Qty / Unit / Price, "BY WEIGHT" over Weight (kg) /
    Price per kg, then Amount. The repeated KG column goes -- the unit is in the header;
  - the weight columns are SHADED, so they read as the reference figures they are;
  - the TOTAL WEIGHT prints in the footer, under Weight, beside the total amount;
  - the Job Order slip and the SO screens use the SAME WORDS (Qty, Unit, Weight (kg),
    Price per kg).

SO 0004's real figures are the fixture: 2,000 PACKS @ 100.80 = 201,600.00 -> 200 KG @
1,008.00; 300 PACKS @ 67.20 = 20,160.00 -> 30 KG @ 672.00.
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

PRINT_COLUMNS = ['#', 'Product', 'Qty', 'Unit', 'Price', 'Weight (kg)', 'Price per kg', 'Amount']


def _uom(code):
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure.query.filter_by(code=code).first()
    if u is None:
        u = UnitOfMeasure(code=code, name=code, is_active=True)
        db.session.add(u); db.session.commit()
    return u


def _product(name, kg_per_unit):
    from app.products.models import Product
    p = Product(name=name, kg_per_unit=kg_per_unit, default_unit_of_measure_id=_uom('PACKS').id,
                is_active=True)
    db.session.add(p); db.session.commit()
    return p


def _so_0004(db_session, branch, mango_factor=Decimal('0.1'), papaya_factor=Decimal('0.1'),
             status='confirmed'):
    c = _customer(db_session)
    packs = _uom('PACKS')
    mango = _product('A ONE DRIED MANGO SLICES 100g', mango_factor)
    papaya = _product('A ONE DRIED PAPAYA CHUNKS 100g', papaya_factor)
    so = SalesOrder(so_number='SO-KG-0004', order_date=datetime.date(2026, 10, 28),
                    customer_id=c.id, customer_name='MEMER FOOD DEALER', customer_po_number='3057',
                    branch_id=branch.id, payment_terms='Net 30', status=status)
    db.session.add(so); db.session.flush()
    for n, (p, qty, price) in enumerate([(mango, '2000', '100.80'), (papaya, '300', '67.20')], 1):
        item = SalesOrderItem(sales_order_id=so.id, line_number=n, product_id=p.id,
                              quantity=Decimal(qty), unit_price=Decimal(price),
                              unit_of_measure_id=packs.id, vat_category='V12', vat_rate=Decimal('12'))
        item.calculate_amounts()
        db.session.add(item)
    db.session.flush()
    so.calculate_totals()
    db.session.commit()
    return so


# ---- the arithmetic, on the SO line ----------------------------------------------------

def test_kg_quantity_is_the_quantity_times_the_products_kg_per_unit(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    mango, papaya = so.line_items
    assert mango.kg_quantity == Decimal('200')
    assert papaya.kg_quantity == Decimal('30')


def test_kg_unit_price_is_the_amount_over_the_kg_quantity(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    mango, papaya = so.line_items
    assert mango.amount == Decimal('201600.00')
    assert mango.kg_unit_price == Decimal('1008.00')
    assert papaya.kg_unit_price == Decimal('672.00')


def test_the_kg_price_rounds_half_up_to_centavos(db_session, main_branch):
    """1,000.00 over 3 KG is 333.333...; a price is two decimals, rounded half up."""
    so = _so_0004(db_session, main_branch)
    line = so.line_items[0]
    line.amount = Decimal('1000.00')
    line.quantity = Decimal('30')          # x 0.1 = 3 KG
    assert line.kg_unit_price == Decimal('333.33')


def test_a_product_without_kg_per_unit_has_no_kg_figures(db_session, main_branch):
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    papaya = so.line_items[1]
    assert papaya.kg_quantity is None
    assert papaya.kg_unit_price is None


def test_a_line_without_quantity_has_no_kg_figures(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    line = so.line_items[0]
    line.quantity = None
    assert line.kg_quantity is None
    assert line.kg_unit_price is None


def test_the_order_weight_is_the_sum_of_its_lines(db_session, main_branch):
    so = _so_0004(db_session, main_branch)
    assert so.total_kg == Decimal('230')


def test_the_order_has_no_weight_when_a_line_has_none(db_session, main_branch):
    """A sum over only some lines would read as the order's weight and be wrong, so the
    total is blank instead (Claude's judgment, 4 Nov 2026 -- the owner may overrule)."""
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    assert so.total_kg is None


def test_an_order_without_lines_has_no_weight(db_session, main_branch):
    c = _customer(db_session)
    so = SalesOrder(so_number='SO-KG-EMPTY', order_date=datetime.date(2026, 11, 4),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.commit()
    assert so.total_kg is None


def test_the_product_dict_carries_kg_per_unit(db_session):
    """The SO form's product list is built from Product.to_dict(); the screen computes
    the KG columns from this value."""
    p = _product('KG DICT 100g', Decimal('0.1'))
    assert p.to_dict()['kg_per_unit'] == 0.1
    q = _product('KG DICT NONE', None)
    assert q.to_dict()['kg_per_unit'] is None


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
    data = {'name': 'KG FORM MANGO 100g', 'description': '', 'default_unit_of_measure_id': '',
            'default_unit_price': '', 'default_account_id': '', 'category_id': '',
            'standard_cost': '', 'is_active': '1'}
    data.update(extra)
    return data


def test_the_product_form_shows_kg_per_unit(client, db_session, admin_user, main_branch, products_on):
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get('/products/create').get_data(as_text=True)
    assert 'name="kg_per_unit"' in html
    assert 'KG per unit' in html


def test_creating_and_editing_a_product_keeps_kg_per_unit(client, db_session, admin_user,
                                                          main_branch, products_on):
    from app.products.models import Product
    from app.audit.models import AuditLog
    _login(client, admin_user); _select_branch(client, main_branch.id)
    client.post('/products/create', data=_product_post(kg_per_unit='0.1'))
    p = Product.query.filter_by(name='KG FORM MANGO 100g').first()
    assert p is not None and p.kg_per_unit == Decimal('0.1')

    client.post(f'/products/{p.id}/edit', data=_product_post(kg_per_unit='0.25'))
    db.session.refresh(p)
    assert p.kg_per_unit == Decimal('0.25')
    # the change is in the audit trail's before/after
    row = (AuditLog.query.filter_by(module='products', record_id=p.id, action='update')
           .order_by(AuditLog.id.desc()).first())
    assert row is not None
    assert json.loads(row.old_values)['kg_per_unit'] == 0.1
    assert json.loads(row.new_values)['kg_per_unit'] == 0.25

    client.post(f'/products/{p.id}/edit', data=_product_post(kg_per_unit=''))
    db.session.refresh(p)
    assert p.kg_per_unit is None


@pytest.mark.parametrize('bad', ['0', '-0.1'])
def test_kg_per_unit_must_be_above_zero(client, db_session, admin_user, main_branch, products_on, bad):
    from app.products.models import Product
    _login(client, admin_user); _select_branch(client, main_branch.id)
    client.post('/products/create', data=_product_post(name=f'KG BAD {bad}', kg_per_unit=bad))
    assert Product.query.filter_by(name=f'KG BAD {bad}').first() is None


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
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    """Papaya has no KG per unit: one line with a weight, one without."""
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    return so, _print(client, admin_user, main_branch, so)


def test_the_print_columns_are_as_ordered_then_by_weight_then_amount(printed):
    so, page = printed
    assert _print_columns(_particulars(page)) == PRINT_COLUMNS


def test_the_group_banners_head_their_columns(printed):
    so, page = printed
    thead = re.search(r'<thead>.*?</thead>', _particulars(page), re.S).group(0)
    assert re.search(r'<th colspan="3"[^>]*>AS ORDERED</th>', thead)
    assert re.search(r'<th colspan="2"[^>]*>BY WEIGHT</th>', thead)


def test_a_line_prints_its_weight_and_price_per_kg(printed):
    """No "KG" in the line any more: the unit is in the column header."""
    so, page = printed
    mango = _cells(_body_rows(_particulars(page))[0])
    assert mango == ['1', 'A ONE DRIED MANGO SLICES 100g', '2,000', 'PACKS', '100.80',
                     '200', '1,008.00', '201,600.00']


def test_a_line_whose_product_has_no_kg_per_unit_leaves_the_weight_cells_blank(printed):
    so, page = printed
    papaya = _cells(_body_rows(_particulars(page))[1])
    assert papaya[2:5] == ['300', 'PACKS', '67.20']
    assert papaya[5:7] == ['', '']
    assert papaya[7] == '20,160.00'


def test_every_print_body_row_has_eight_cells(printed):
    so, page = printed
    counts = {len(re.findall(r'<td', r)) for r in _body_rows(_particulars(page))}
    assert counts == {8}


def test_the_weight_columns_are_shaded_on_every_row(printed):
    """Data rows and the blank grid alike, so the band runs the height of the table."""
    so, page = printed
    for row in _body_rows(_particulars(page)):
        tds = re.findall(r'<td([^>]*)>', row)
        assert [i for i, a in enumerate(tds) if 'wt' in _classes(a)] == [5, 6], row
    heads = re.findall(r'<th\b([^>]*)>(.*?)</th>', _particulars(page), re.S)
    shaded = [label for attrs, label in heads if 'wt' in _classes(attrs)]
    assert shaded == ['BY WEIGHT', 'Weight (kg)', 'Price per kg']


def test_the_shading_survives_printing(printed):
    """Browsers drop backgrounds when printing unless told not to."""
    so, page = printed
    rule = re.search(r'\.particulars \.wt \{[^}]*\}', page)
    assert rule, 'no rule for the shaded weight cells'
    assert re.search(r'background:\s*#[0-9a-fA-F]{3,6}', rule.group(0))
    assert re.search(r'(?<!-)print-color-adjust:\s*exact', rule.group(0))


def test_the_total_row_prints_the_total_weight_under_weight(client, db_session, admin_user,
                                                           main_branch, sales_orders_module_enabled):
    so = _so_0004(db_session, main_branch)            # both lines have a weight
    foot = _foot(_print(client, admin_user, main_branch, so))
    assert _cells(foot) == ['Total', '230', '', '221,760.00']
    assert re.search(r'<td colspan="5"[^>]*>Total</td>', foot)


def test_the_total_weight_is_blank_when_a_line_has_no_weight(printed):
    so, page = printed
    assert _cells(_foot(page)) == ['Total', '', '', '221,760.00']


def test_the_print_rows_are_single_line_height(printed):
    so, page = printed
    m = re.search(r'table\.particulars tbody td\s*\{\s*height:\s*([\d.]+)px', page)
    assert m and float(m.group(1)) == 22     # single line: just above the ~21.6px content


# ---- the SO screens --------------------------------------------------------------------

def test_the_so_detail_shows_weight_and_price_per_kg(client, db_session, admin_user, main_branch,
                                                     sales_orders_module_enabled):
    """The printout's words, not "KG" / "Price / KG"."""
    so = _so_0004(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    page = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    heads = [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<th\b[^>]*>.*?</th>', page, re.S)]
    assert 'Weight (kg)' in heads and 'Price per kg' in heads
    assert 'KG' not in heads and 'Price / KG' not in heads
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', page))
    assert '200 KG' in text or re.search(r'\b200\b.*1,008\.00', text)
    assert '1,008.00' in text and '672.00' in text


def test_the_so_form_has_the_kg_columns_and_the_factor(client, db_session, admin_user, main_branch,
                                                         sales_orders_module_enabled):
    so = _so_0004(db_session, main_branch, status='draft')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    page = client.get(f'/sales-orders/{so.id}/edit').get_data(as_text=True)
    thead = re.search(r'<thead>.*?</thead>', page[page.index('Unit Price') - 2000:], re.S).group(0)
    heads = [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<th\b[^>]*>.*?</th>', thead, re.S)]
    assert 'Weight (kg)' in heads and 'Price per kg' in heads
    assert 'KG' not in heads and 'Price / KG' not in heads
    assert '"kg_per_unit": 0.1' in page or '"kg_per_unit":0.1' in page
    assert 'function refreshKg' in page


# ---- the Job Order Slip ----------------------------------------------------------------

def test_the_job_order_slip_prints_the_weight_beside_the_ordered_unit(client, db_session, admin_user,
                                                                      main_branch, sales_orders_module_enabled):
    """The printout's words: Qty, Unit, Weight (kg). Seven columns, every row."""
    so = _so_0004(db_session, main_branch, papaya_factor=None)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    page = client.get(f'/sales-orders/{so.so_number}/print-job-order').get_data(as_text=True)
    table = re.search(r'<table class="jo-table".*?</table>', page, re.S).group(0)
    headers = [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<th\b[^>]*>.*?</th>', table, re.S)]
    assert headers == ['Qty', 'Unit', 'Weight (kg)', 'Description', 'PO Number',
                       'Delivery Date', 'Remarks']
    rows = re.findall(r'<tr>\s*<td class="qty">.*?</tr>', table, re.S)
    mango, papaya = _cells(rows[0]), _cells(rows[1])
    assert mango[:3] == ['2,000', 'PACKS', '200']
    assert papaya[:3] == ['300', 'PACKS', '']
    body = re.search(r'<tbody.*?</tbody>', table, re.S).group(0)
    assert {len(re.findall(r'<td', r)) for r in re.findall(r'<tr[^>]*>.*?</tr>', body, re.S)} == {7}
    # still unpriced: the slip goes to production
    assert '100.80' not in table and '1,008.00' not in table
