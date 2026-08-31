"""What the PRE-PRINTED PO overlay actually renders.

PhilGen runs po_print_form=preprinted, so this -- not print.html -- is the page they
print, onto real pre-printed stationery.

THE load-bearing assertion is still ALIGNMENT: every column stack must hold the same
number of cells. The columns are independently positioned divs whose rows line up for
no other reason, so any change that adds a row to one stack and not the others silently
slides that column's boxes down the page relative to the physical form.

What changed on 2026-08-31 (owner directive, from the annotated legacy pad PO 00984):
the overlay now DOES draw heading rows. Until then it deliberately did not, and this
file asserted "one cell per LINE". That was the right rule for the old design and is
the wrong rule for this one -- so it is RESTATED, not dropped: the stacks must still
all agree, but the count they agree on is now heading rows + item rows + one terminator.
Deleting the invariant instead of restating it would have thrown away the only guard
protecting registration against the pre-printed boxes.
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


def _po(db_session, main_branch, vendor, number, lines, **kw):
    """lines: [(line_number, description, amount), ...]"""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, branch_id=main_branch.id,
                       status='approved', **kw)
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


# --------------------------------------------------------------------------- #
# THE alignment invariant                                                      #
# --------------------------------------------------------------------------- #

def test_every_column_stack_holds_the_same_number_of_cells(client, db_session,
                                                           accountant_user, main_branch,
                                                           vl_vendor):
    """Registration guard. Stacks that disagree slide down the pre-printed form.

    Mutation target: emit the heading cell from only the description column (drop the
    blank spacer the other columns write) and this goes red immediately.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-1',
             [(1, 'A', 10), (2, 'B', 20), (3, 'A', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    counts = {k: len(v) for k, v in cols.items()}
    assert counts, 'no column stacks parsed -- the rest would be vacuous'
    assert len(set(counts.values())) == 1, f'column stacks disagree on row count: {counts}'


def test_the_row_count_is_headings_plus_lines_plus_one_terminator(client, db_session,
                                                                  accountant_user,
                                                                  main_branch, vl_vendor):
    """The count the stacks agree ON. 2 groups + 3 lines + 1 terminator = 6."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-1B',
             [(1, 'A', 10), (2, 'B', 20), (3, 'A', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert len(cols['line_number']) == 6, cols['line_number']


# --------------------------------------------------------------------------- #
# Grouping                                                                     #
# --------------------------------------------------------------------------- #

def test_lines_are_reordered_so_a_group_is_contiguous(client, db_session, accountant_user,
                                                      main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-2',
             [(1, 'ZINC', 10), (2, 'ALU', 20), (3, 'ZINC', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    #                 ZINC hd, 1,   3,   ALU hd, 2,   terminator
    assert cols['line_number'] == ['', '1', '3', '', '2', '']


def test_the_description_prints_as_a_group_HEADING_above_its_items(client, db_session,
                                                                   accountant_user,
                                                                   main_branch, vl_vendor):
    """The 2026-08-31 change. The remark heads its group and is blank on item rows --
    it is no longer printed on the item's own row at all."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-3',
             [(1, 'ZINC', 10), (2, 'ALU', 20), (3, 'ZINC', 30)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['description'] == ['ZINC', '', '', 'ALU', '', '- NOTHING FOLLOWS -']


def test_the_other_columns_still_carry_every_line(client, db_session, accountant_user,
                                                  main_branch, vl_vendor):
    """CONTROL: only the DESCRIPTION moved to a heading. Blanking a quantity or an
    amount on a line would understate the order on the supplier's copy."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-4',
             [(1, 'A', 10), (2, 'A', 20)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    #                        heading, 1,       2,       terminator
    assert cols['amount'] == ['', '10.00', '20.00', '']
    assert cols['line_number'] == ['', '1', '2', '']


def test_undescribed_lines_print_with_no_heading_row(client, db_session, accountant_user,
                                                     main_branch, vl_vendor):
    """A line with no remark must still print -- dropping it would lose a billable
    line off the supplier's copy -- but it gets no empty heading above it."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-6',
             [(1, '', 10), (2, '', 20)])
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['line_number'] == ['1', '2', ''], 'an empty heading row was drawn'
    assert cols['amount'] == ['10.00', '20.00', '']


# --------------------------------------------------------------------------- #
# Terminator                                                                   #
# --------------------------------------------------------------------------- #

def test_a_terminator_closes_the_grid_exactly_once(client, db_session, accountant_user,
                                                   main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-7',
             [(1, 'A', 10), (2, 'B', 20)])
    _login(client, accountant_user, main_branch)
    html = _overlay(client, po)

    assert html.count('- NOTHING FOLLOWS -') == 1, 'terminator printed more than once'
    cols = _columns(html)
    assert cols['description'][-1] == '- NOTHING FOLLOWS -', 'terminator is not the last row'
    # and it occupies a row in EVERY stack, blank elsewhere
    assert cols['amount'][-1] == ''
    assert cols['line_number'][-1] == ''


def test_no_subtotal_rows_are_introduced(client, db_session, accountant_user,
                                         main_branch, vl_vendor):
    """SURVIVES the 2026-08-31 change. Headings are now wanted; subtotals never were --
    the standard form has them, the pre-printed pad has no box for them.

    Mutation target: reuse print.html's approach wholesale and subtotal rows come with
    it, consuming boxes the pad does not have.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-5',
             [(1, 'A', 10), (2, 'B', 20)])
    _login(client, accountant_user, main_branch)
    html = _overlay(client, po)

    assert 'Subtotal' not in html
    assert 'class="grp"' not in html


# --------------------------------------------------------------------------- #
# PR # column                                                                  #
# --------------------------------------------------------------------------- #

def test_the_pr_number_column_prints_the_source_requisition(client, db_session,
                                                            accountant_user, main_branch,
                                                            vl_vendor):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(pr_number='PR-778', request_date=date(2026, 7, 1),
                         branch_id=main_branch.id, status='approved')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='widget',
                                             quantity=Decimal('1')))
    db.session.add(pr); db.session.commit()

    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-8', [(1, 'A', 10)])
    po.line_items[0].source_pr_item_id = pr.line_items[0].id
    db.session.commit()
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    #                      heading, item,     terminator
    assert cols['pr_number'] == ['', 'PR-778', '']


def test_a_directly_entered_line_prints_a_BLANK_pr_number(client, db_session,
                                                          accountant_user, main_branch,
                                                          vl_vendor):
    """CONTROL for the test above: without it, a PR # column that printed the same
    string on every row -- or crashed on a None source -- would still pass.

    A PO line entered straight, with no requisition behind it, is legitimate.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-9', [(1, 'A', 10)])
    assert po.line_items[0].source_pr_item_id is None, 'fixture no longer tests the None path'
    _login(client, accountant_user, main_branch)

    cols = _columns(_overlay(client, po))
    assert cols['pr_number'] == ['', '', '']


# --------------------------------------------------------------------------- #
# Currency label                                                               #
# --------------------------------------------------------------------------- #

def test_the_currency_code_prints_on_the_overlay(client, db_session, accountant_user,
                                                 main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-10', [(1, 'A', 10)],
             currency='USD')
    _login(client, accountant_user, main_branch)

    assert 'USD' in _overlay(client, po)


def test_php_prints_too_rather_than_being_suppressed_as_the_default(client, db_session,
                                                                    accountant_user,
                                                                    main_branch, vl_vendor):
    """CONTROL: the legacy pad prints PHP explicitly. A 'only show it when unusual'
    optimisation would make the default order's total unlabelled.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-OV-11', [(1, 'A', 10)])
    assert po.currency == 'PHP'
    _login(client, accountant_user, main_branch)

    assert 'PHP' in _overlay(client, po)
