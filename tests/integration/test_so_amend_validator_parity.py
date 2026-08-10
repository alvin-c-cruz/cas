"""Sales Order amendment -- the two defect shapes fixed on the Purchase Order side.

Both were found by the whole-branch review of amendment slice 2 and fixed for PO in
`3c68a4ab`; the review's `m4` recorded that the SO copy of the validator still carried
them, because `app/sales_orders/revisions.py` and `app/amendments/validation.py` are
independent copies until the spec's slice 5 merges them.

  C1  An amendment can strip a confirmed Sales Order down to NO usable line and is
      reported as success. Unlike PO, SO's `confirm()` has no server-side priced-line
      precondition at all -- the ONLY "at least one line" rule lives in the form's JS
      (`sales_orders/form.html::validateForm`), which a crafted or JS-less POST never
      runs. So this is not "amend can reach a state confirm() refuses"; it is "neither
      route enforces the rule the UI claims".

  M1  `line_items` that is valid JSON but NOT a list (a scalar, or `null`) reaches
      `for line in (new_lines or [])` and raises TypeError out of the view -- a 500,
      contradicting validate_amendment's own "never raises" contract. SO is worse than
      PO was here: `json.loads` is called with no try at all, so even NON-JSON 500s,
      and it does so on the re-render path that runs for every POST.

The server-side minimum enforced here deliberately mirrors **SO's own** client-side
rule (a line needs a product and an amount > 0), NOT the stricter unit-price rule PO
borrowed from its `approve()`. Enforcing what this document already claims to require
is a closed guard; importing another document's rule would be a new business rule.
"""
import json
import pytest
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.revision_models import SalesOrderRevision

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


# --- fixtures (mirroring test_so_amendment.py) -------------------------------

@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if b is None:
        b = Branch(code='CORP', name='CORP')
        db_session.add(b)
        db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    return _customer(db_session)


@pytest.fixture
def product(db_session):
    _enable_products(db_session)
    return _product(db_session)


@pytest.fixture
def staff_user(db_session, branch):
    from app.users.models import User
    u = User(username='china', email='china@example.com', full_name='China',
             role='staff', is_active=True, branch_id=branch.id)
    u.set_password('uitest-Pass123!')
    u.set_book_permissions({'sales_orders': True, 'job_order_slips': True})
    db_session.add(u)
    db_session.flush()
    u.set_branches([branch])
    db_session.commit()
    return u


@pytest.fixture
def client(client, db_session, staff_user, branch):
    _login(client, staff_user)
    _select_branch(client, branch.id)
    return client


# --- helpers -----------------------------------------------------------------

def _confirmed_so(client, db_session, customer, product, qty,
                  so_number='2026080001', second_line_qty=None):
    line_list = [{'line_number': 1, 'product_id': product.id,
                  'quantity': str(qty), 'unit_price': '4.20',
                  'amount': str(qty * Decimal('4.20'))}]
    if second_line_qty is not None:
        line_list.append({'line_number': 2, 'product_id': product.id,
                          'quantity': str(second_line_qty), 'unit_price': '4.20',
                          'amount': str(second_line_qty * Decimal('4.20'))})
    client.post('/sales-orders/create', data={
        'so_number': so_number, 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': json.dumps(line_list)}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number=so_number).one()
    client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'confirmed'
    return so


def _revs(so):
    return (SalesOrderRevision.query.filter_by(sales_order_id=so.id)
            .order_by(SalesOrderRevision.revision_number).all())


def _amend(client, so, customer, line_items, omit_line_items=False, **over):
    data = {
        'so_number': so.so_number, 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'amend_reason': 'vendor corrected the order after review',
        'authorizing_po_number': 'PO-PARITY-1',
        'row_version': str(so.row_version),
    }
    if not omit_line_items:
        data['line_items'] = line_items
    data.update(over)
    return client.post(f'/sales-orders/{so.id}/amend', data=data,
                       follow_redirects=True)


def _payload(so, product, drop_ids=(), **line_over):
    out = []
    for li in so.line_items:
        if li.id in drop_ids:
            continue
        row = {'so_item_id': li.id, 'line_number': li.line_number,
               'product_id': li.product_id, 'quantity': str(li.quantity),
               'unit_price': str(li.unit_price), 'amount': str(li.amount)}
        row.update(line_over)
        out.append(row)
    return json.dumps(out)


# --- C1: an amendment may not strip the order of every usable line -----------

class TestSoAmendMinimumLine:

    def test_removing_every_line_is_refused(self, client, db_session, customer, product):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        resp = _amend(client, so, customer, json.dumps([]))
        assert resp.status_code == 200
        db_session.refresh(so)
        assert len(so.line_items) == 1, 'the order must not be left with no line'
        assert len(_revs(so)) == before, 'a refused amendment must write no revision'

    def test_the_refusal_leaves_the_order_byte_identical(
            self, client, db_session, customer, product):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before_total = so.total_amount
        before_qty = so.line_items[0].quantity
        _amend(client, so, customer, json.dumps([]))
        db_session.refresh(so)
        assert so.total_amount == before_total
        assert so.line_items[0].quantity == before_qty
        assert so.status == 'confirmed'

    def test_a_line_zeroed_to_no_amount_does_not_count_as_a_usable_line(
            self, client, db_session, customer, product):
        """SO's own client-side rule: every line needs a product AND amount > 0.

        Zeroing the QUANTITY is the reachable way to produce that shape.
        Submitting `amount: '0'` directly is NOT: `_assign_so_line_fields` ends
        with `item.calculate_amounts()`, which re-derives amount = qty x price
        whenever both are > 0, so a submitted zero is overwritten before the
        guard ever sees it. An earlier version of this test posted `amount='0'`
        with the quantity left at 3000 and passed for that reason alone --
        i.e. it was asserting the recomputation, not the guard.
        """
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        _amend(client, so, customer,
               _payload(so, product, quantity='0', amount='0'))
        db_session.refresh(so)
        assert len(_revs(so)) == before, 'a refused amendment must write no revision'
        assert so.line_items[0].quantity == Decimal('3000')
        assert so.line_items[0].amount == Decimal('12600.00')

    # --- CONTROL: the guard must not over-tighten into "no removal at all" ---

    def test_removing_some_but_not_all_lines_still_succeeds(
            self, client, db_session, customer, product):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'),
                           second_line_qty=Decimal('500'))
        assert len(so.line_items) == 2
        before = len(_revs(so))
        dropped = so.line_items[1].id
        _amend(client, so, customer, _payload(so, product, drop_ids=(dropped,)))
        db_session.refresh(so)
        assert len(so.line_items) == 1, 'partial removal must still be allowed'
        assert len(_revs(so)) == before + 1

    def test_an_ordinary_amendment_still_succeeds(
            self, client, db_session, customer, product):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        _amend(client, so, customer,
               _payload(so, product, quantity='7000', amount='29400.00'))
        db_session.refresh(so)
        assert so.line_items[0].quantity == Decimal('7000')
        assert len(_revs(so)) == before + 1


# --- M1: a malformed line_items payload is a message, never a 500 ------------

class TestSoAmendMalformedPayload:

    @pytest.mark.parametrize('raw', ['123', 'true', '1.5', '"a string"', 'null'])
    def test_a_non_list_line_items_is_refused_without_a_500(
            self, client, db_session, customer, product, raw):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        resp = _amend(client, so, customer, raw)
        assert resp.status_code == 200, 'a crafted payload must not 500'
        db_session.refresh(so)
        assert len(so.line_items) == 1
        assert len(_revs(so)) == before

    @pytest.mark.parametrize('raw', ['{not json', '[1,2', 'undefined'])
    def test_non_json_line_items_is_refused_without_a_500(
            self, client, db_session, customer, product, raw):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        resp = _amend(client, so, customer, raw)
        assert resp.status_code == 200, 'unparseable JSON must not 500'
        db_session.refresh(so)
        assert len(so.line_items) == 1
        assert len(_revs(so)) == before

    def test_an_absent_line_items_field_says_so_rather_than_blaming_the_user(
            self, client, db_session, customer, product):
        """A dropped hidden field must not be read as "the user cleared the grid".

        Asserting only "the order survived" is VACUOUS here, and provably so:
        with the absent-key branch removed, `submitted_lines` falls back to `[]`,
        every line is deleted, and the minimum-line guard refuses it anyway -- so
        the order still survives and such a test stays green. Mutation m4 caught
        exactly that.

        The two paths differ in what the operator is TOLD, which is the whole
        point: "the line items did not reach the server, reload" is a browser/
        transport problem they can act on, while "you must keep at least one
        line" blames them for an edit they never made. Pin the message.
        """
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        resp = _amend(client, so, customer, None, omit_line_items=True)
        assert resp.status_code == 200
        assert b'did not reach the server' in resp.data, (
            'an absent line_items must be reported as a transport failure, not '
            'as the user having deleted every line')
        assert b'must keep at least one line' not in resp.data
        db_session.refresh(so)
        assert len(so.line_items) == 1
        assert len(_revs(so)) == before

    # --- CONTROL: a well-formed LIST of junk keeps its per-element messages ---

    def test_a_list_containing_non_objects_still_gets_its_element_message(
            self, client, db_session, customer, product):
        so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
        before = len(_revs(so))
        resp = _amend(client, so, customer, json.dumps([1, 'x', None]))
        assert resp.status_code == 200
        assert b'Malformed submission' in resp.data, (
            'the list path must still reach the per-element check, not be '
            'swallowed by the new whole-payload guard')
        db_session.refresh(so)
        assert len(_revs(so)) == before
