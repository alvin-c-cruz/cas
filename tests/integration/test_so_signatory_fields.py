"""Per-document printed signatories on the Sales Order.

Owner directive 2026-08-21: the SO carries its own Prepared By / Noted By /
Approved By, typed on the form and printed on the document -- the same shape
PurchaseOrder uses, and explicitly NOT the company-wide-setting shape PR and RR
use. The owner chose the PO pattern: a new SO repeats what THAT user typed on
THEIR OWN last SO, and there is no company setting and no "Modify signatories"
button on the printout.

A blank is meaningful and is never back-filled: it prints an empty ruled line to
sign by hand. Signatories are NEVER derived from created_by / confirmed_by --
those are CAS users, while the people who sign are frequently not.
"""
import datetime
import json
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem, SIGNATORY_FIELDS

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

# Four since 2026-08-28 -- `checked_by` joined the set, SECOND.
SIGS = {'prepared_by': 'MARIA SANTOS',
        'checked_by': 'ANA LIM',
        'noted_by': 'JUAN DELA CRUZ',
        'approved_by': 'PEDRO REYES'}


def _post_so(client, customer, product, number, **extra):
    lines = json.dumps([{'product_id': str(product.id), 'quantity': '2',
                         'unit_price': '100.00', 'vat_category': None, 'vat_rate': '0'}])
    data = {'so_number': number, 'order_date': '2026-06-15',
            'customer_id': str(customer.id), 'customer_name': 'Acme',
            'payment_terms': 'Net 30', 'notes': '', 'line_items': lines}
    data.update(extra)
    return client.post('/sales-orders/create', data=data, follow_redirects=True)


def _bare_so(db_session, customer, main_branch, number, created_by_id=None,
             order_date=datetime.date(2026, 6, 15), **sigs):
    so = SalesOrder(so_number=number, order_date=order_date, customer_id=customer.id,
                    customer_name='Acme', branch_id=main_branch.id, status='draft',
                    created_by_id=created_by_id, **sigs)
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


# ── the columns ──────────────────────────────────────────────────────────────

def test_create_stores_every_signatory(client, db_session, admin_user, main_branch,
                                       sales_orders_module_enabled):
    c = _customer(db_session); p = _product(db_session, code='SF-1')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    _post_so(client, c, p, 'SO-SIG-0001', **SIGS)

    so = SalesOrder.query.filter_by(so_number='SO-SIG-0001').first()
    assert so is not None
    assert (so.prepared_by, so.checked_by, so.noted_by, so.approved_by) == (
        'MARIA SANTOS', 'ANA LIM', 'JUAN DELA CRUZ', 'PEDRO REYES')


def test_blank_signatory_is_stored_as_null_not_empty_string(client, db_session, admin_user,
                                                            main_branch,
                                                            sales_orders_module_enabled):
    """Blank stays blank -- and stays NULL, so it is distinguishable from a typed
    empty value and prints an empty ruled line."""
    c = _customer(db_session); p = _product(db_session, code='SF-2')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    _post_so(client, c, p, 'SO-SIG-0002',
             prepared_by='  MARIA SANTOS  ', checked_by='  ANA LIM  ',
             noted_by='   ', approved_by='')

    so = SalesOrder.query.filter_by(so_number='SO-SIG-0002').first()
    assert so.prepared_by == 'MARIA SANTOS'      # trimmed
    assert so.checked_by == 'ANA LIM'            # the new slot trims too
    assert so.noted_by is None                   # whitespace-only -> NULL
    assert so.approved_by is None


def test_edit_updates_the_signatories(client, db_session, admin_user, main_branch,
                                      sales_orders_module_enabled):
    c = _customer(db_session); p = _product(db_session, code='SF-3')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    _post_so(client, c, p, 'SO-SIG-0003', **SIGS)
    so = SalesOrder.query.filter_by(so_number='SO-SIG-0003').first()

    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post(f'/sales-orders/{so.id}/edit', data={
        'so_number': 'SO-SIG-0003', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines, 'row_version': str(so.row_version),
        'prepared_by': 'NEW PREPARER', 'checked_by': '', 'noted_by': '',
        'approved_by': 'PEDRO REYES',
    }, follow_redirects=True)

    db_session.refresh(so)
    assert so.prepared_by == 'NEW PREPARER'
    assert so.checked_by is None          # cleared, not left at the old value
    assert so.noted_by is None            # cleared, not left at the old value
    assert so.approved_by == 'PEDRO REYES'


# ── carry-forward prefill (the PO pattern) ───────────────────────────────────

def test_new_so_form_prefills_from_my_own_last_so(client, db_session, admin_user, main_branch,
                                                  sales_orders_module_enabled):
    _bare_so(db_session, _customer(db_session), main_branch, 'SO-SIG-PRE1',
             created_by_id=admin_user.id, **SIGS)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get('/sales-orders/create').get_data(as_text=True)

    assert 'value="MARIA SANTOS"' in html
    assert 'value="JUAN DELA CRUZ"' in html
    assert 'value="PEDRO REYES"' in html


def test_first_ever_so_prefills_blank_never_a_placeholder(client, db_session, admin_user,
                                                          main_branch,
                                                          sales_orders_module_enabled):
    """CONTROL: with no prior SO the three inputs render EMPTY.

    Without this, a prefill bug that injected any constant would still pass the
    positive test above.
    """
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get('/sales-orders/create').get_data(as_text=True)

    for field in SIGNATORY_FIELDS:
        assert f'name="{field}"' in html          # the input rendered at all
    assert 'value="MARIA SANTOS"' not in html
    assert 'System Administrator' not in html     # never derived from the CAS user
    assert admin_user.username not in html.split('<form')[-1]


def test_prefill_does_not_leak_another_users_signatories(client, db_session, admin_user,
                                                         accountant_user, main_branch,
                                                         sales_orders_module_enabled):
    """The carry-forward is PER USER.

    Mutation target: drop the created_by_id filter from next_so_signatories_for
    and this goes RED while the positive prefill test stays green.
    """
    _bare_so(db_session, _customer(db_session), main_branch, 'SO-SIG-OTHER',
             created_by_id=accountant_user.id, **SIGS)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get('/sales-orders/create').get_data(as_text=True)

    assert 'value="MARIA SANTOS"' not in html
    assert 'value="JUAN DELA CRUZ"' not in html


def test_last_is_by_id_not_by_order_date(client, db_session, admin_user, main_branch,
                                         sales_orders_module_enabled):
    """A BACKDATED order is still the most recently ENTERED one.

    Mutation target: order_by(order_date.desc()) instead of id.desc().
    """
    c = _customer(db_session)
    _bare_so(db_session, c, main_branch, 'SO-SIG-OLD', created_by_id=admin_user.id,
             order_date=datetime.date(2026, 6, 1), prepared_by='FIRST ENTERED')
    _bare_so(db_session, c, main_branch, 'SO-SIG-BACKDATED', created_by_id=admin_user.id,
             order_date=datetime.date(2026, 1, 1), prepared_by='LAST ENTERED')

    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get('/sales-orders/create').get_data(as_text=True)

    assert 'value="LAST ENTERED"' in html
    assert 'value="FIRST ENTERED"' not in html


# ── the printout ─────────────────────────────────────────────────────────────

def _sig_pairs(html):
    """[(role, printed name-or-hint), ...] in the order the printout renders them.

    The SO's box design puts the role caption on top and the ruled line beneath,
    so the name prints ON the line -- not above the caption the way PO does it.
    """
    import re
    return re.findall(
        r'<div class="sig-title">([^<]+)</div>\s*<div class="sig-line[^"]*">([^<]*)</div>', html)


def test_print_shows_the_stored_names_under_the_right_roles(client, db_session, admin_user,
                                                            main_branch,
                                                            sales_orders_module_enabled):
    so = _bare_so(db_session, _customer(db_session), main_branch, 'SO-SIG-PR1',
                  created_by_id=admin_user.id, **SIGS)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    assert _sig_pairs(html) == [('PREPARED BY', 'MARIA SANTOS'),
                                ('CHECKED BY', 'ANA LIM'),
                                ('NOTED BY', 'JUAN DELA CRUZ'),
                                ('APPROVED BY', 'PEDRO REYES')]


def test_print_blank_signatory_is_an_empty_line_not_a_placeholder(client, db_session, admin_user,
                                                                  main_branch,
                                                                  sales_orders_module_enabled):
    """A pre-feature SO (all NULL) prints four empty ruled lines.

    There is no company-setting fallback for the SO by owner decision, so NULL
    keeps the original "Name & Date" hint -- never a dash, never a derived user
    name, and never styled as though a name had printed.
    """
    so = _bare_so(db_session, _customer(db_session), main_branch, 'SO-SIG-PR2',
                  created_by_id=admin_user.id)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    pairs = _sig_pairs(html)
    assert [role for role, _ in pairs] == ['PREPARED BY', 'CHECKED BY',
                                           'NOTED BY', 'APPROVED BY']
    # The pre-existing hand-sign hint survives; it is a CAPTION, not a name.
    # This is also the shape EVERY other instance's orders keep: four blanks,
    # four ruled lines, nothing missing.
    assert [name for _, name in pairs] == ['Name &amp; Date'] * 4
    # Scoped to the APPLIED attribute, not the bare class name: the CSS rule
    # `.sig-box .sig-line--named` lives in the page's own <style> block, so a
    # substring assertion on the class name alone can never fail. (CLAUDE.md:
    # inline style/JS text leaks into the response and defeats absence tests.)
    assert 'class="sig-line sig-line--named"' not in html
    assert 'System Administrator' not in html
    assert admin_user.full_name not in html.split('sig-row')[-1]
