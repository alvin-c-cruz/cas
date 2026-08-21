"""What the PRE-PRINTED PO overlay actually renders once grouped.

Owner directive 2026-08-21. PhilGen runs po_print_form=preprinted, so this --
not print.html -- is the page they print.

The load-bearing assertion here is ALIGNMENT: every column stack must hold the
same number of cells, and that number must equal the line count. The columns
are independently positioned divs whose rows line up for no other reason, so a
grouping change that added a heading row to one stack would silently slide that
column's boxes down the page relative to the pre-printed form.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_preprinted(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    # the whole point of this file: the OVERLAY, not the standard form
    AppSettings.set_setting('po_print_form', 'preprinted')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po(db_session, main_branch, vendor, number, lines):
    """lines: [(line_number, description, amount), ...]"""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, branch_id=main_branch.id,
                       status='approved')
    db.session.add(po); db.session.flush()
    total = Decimal('0')
    for n, desc, amount in lines:
        amt = Decimal(str(amount))
        total += amt
        db.session.add(PurchaseOrderItem(
            purchase_order_id=po.id, line_number=n, description=desc,
            quantity=Decimal('1'), unit_price=amt, amount=amt, line_total=amt))
    po.total_amount = total
    db.session.commit()
    return po


def _overlay(client, po):
    r = client.get(f'/purchase-orders/{po.id}/print')
    assert r.status_code == 200, f'print route returned {r.status_code}'
    html = r.get_data(as_text=True)
    assert 'ppCanvas' in html, 'this is not the overlay -- the standard form rendered'
    return html


def _columns(html):
    """{col_key: [cell text, ...]} for every column stack.

    Sliced between successive `data-col=` markers rather than matched with a
    lazy `</div>` -- the stacks are nested divs, so a non-greedy match closes on
    the first inner cell and silently truncates the column. That produced a
    convincing-looking wrong answer on the first run of this file.
    """
    band = html[html.index('class="pp-lineitems"'):]
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'data-col="([^"]+)"', band)]
    out = {}
    for n, (pos, key) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(band)
        cells = re.findall(r'<div class="pp-cell"[^>]*>(.*?)</div>', band[pos:end], re.S)
        out[key] = [' '.join(c.split()) for c in cells]
    return out


def test_every_column_stack_has_one_cell_per_line(client, db_session, accountant_user,
                                                  main_branch, vl_vendor):
    """THE alignment invariant -- grouping must not add or drop a row anywhere."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-1',
             [(1, 'A', 10), (2, 'B', 20), (3, 'A', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    counts = {k: len(v) for k, v in cols.items()}
    assert counts, 'no column stacks parsed -- the rest would be vacuous'
    assert set(counts.values()) == {3}, f'column stacks disagree on row count: {counts}'


def test_lines_are_reordered_so_a_group_is_contiguous(client, db_session, accountant_user,
                                                      main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-2',
             [(1, 'ZINC', 10), (2, 'ALU', 20), (3, 'ZINC', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['line_number'] == ['1', '3', '2']


def test_the_description_prints_once_per_group(client, db_session, accountant_user,
                                               main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-3',
             [(1, 'ZINC', 10), (2, 'ALU', 20), (3, 'ZINC', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['description'] == ['ZINC', '', 'ALU']


def test_the_other_columns_still_carry_every_line(client, db_session, accountant_user,
                                                  main_branch, vl_vendor):
    """CONTROL: only the DESCRIPTION is de-duplicated. Blanking a quantity or an
    amount on a repeat line would understate the order on the supplier's copy."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-4',
             [(1, 'A', 10), (2, 'A', 20)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['description'] == ['A', '']
    assert cols['amount'] == ['10.00', '20.00']
    assert cols['line_number'] == ['1', '2']


def test_no_heading_or_subtotal_rows_are_introduced(client, db_session, accountant_user,
                                                    main_branch, vl_vendor):
    """The standard form gets headings and subtotals; the overlay must NOT.

    Mutation target: reuse the print.html approach here and the row count stops
    matching the pre-printed boxes.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-5',
             [(1, 'A', 10), (2, 'B', 20)])
    _login(client, accountant_user, main_branch)
    html = _overlay(client, po)

    assert 'Subtotal' not in html
    assert 'class="grp"' not in html
    assert len(_columns(html)['line_number']) == 2
