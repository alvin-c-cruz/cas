"""A Sales Order's header fields stay saveable when its lines are not.

Owner report 2026-09-22, on live SO 00001E: neither /edit nor /amend would let the
notes be changed.

THE CAUSE
---------
Saving was gated on LINE validity at both ends, for a change that touches no line:

  * client: validateForm() in sales_orders/form.html owns the Update button, which
    is rendered disabled and only ever enabled there. It refuses unless every line
    has a product and an amount above zero.
  * server: _assign_so_line_fields raises 'Line N: select a product.' -- so
    relaxing only the button would have moved the failure, not removed it. The
    edit path rebuilds every line from the submission and the amend path applies
    them in place, so both reach that raise.

SalesOrderItem.product_id is nullable, so an order carrying a line with no product
is legal in the database and prints fine. Its header was simply unreachable.

THE RULE
--------
When the submitted lines are byte-identical to the ones on load, the form posts
`lines_unchanged=1` and the server does not touch the lines at all. Line
validation exists to stop bad line data being written; if no line is being
written, it has nothing to protect.

The flag is FAIL-SAFE by construction and the tests below pin that: it can only
ever cause a submission's lines to be IGNORED in favour of what is already stored.
It can never cause unvalidated lines to be written, so a client that lies about it
-- or is tampered with -- cannot corrupt line data.

AUDIT
-----
`notes` was saved by both routes but named in neither's audited field list, so a
notes-only change wrote an audit row showing nothing changed. Same for the other
header fields the routes write. Fixed here, and pinned, because an unauditable
edit is exactly what this change makes easy to perform.
"""
import json

import pytest
from datetime import date
from decimal import Decimal

from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision
from app.audit.models import AuditLog

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if b is None:
        b = Branch(code='CORP', name='CORP')
        db_session.add(b); db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    return _customer(db_session)


@pytest.fixture
def product(db_session):
    _enable_products(db_session)
    return _product(db_session)


@pytest.fixture
def logged_in(client, db_session, admin_user, branch):
    _login(client, admin_user)
    _select_branch(client, branch.id)
    return admin_user


def _so(db_session, branch, customer, status='draft', number='HDR-1',
        product=None, notes='ORIGINAL NOTE'):
    """An order whose single line has NO product -- legal, since product_id is
    nullable, and the exact shape that made the header unreachable."""
    so = SalesOrder(branch_id=branch.id, so_number=number,
                    order_date=date(2026, 9, 22), status=status,
                    customer_id=customer.id, customer_name=customer.name,
                    payment_terms='Net 60', notes=notes)
    so.line_items.append(SalesOrderItem(
        line_number=1, quantity=Decimal('5'), unit_price=Decimal('10.00'),
        amount=Decimal('50.00'),
        product_id=(product.id if product else None)))
    db_session.add(so); db_session.commit()
    return so


def _lines_of(so):
    """The submission shape the form posts, built from what is stored."""
    return json.dumps([{'so_item_id': li.id, 'line_number': li.line_number,
                        'product_id': li.product_id,
                        'quantity': str(li.quantity) if li.quantity is not None else None,
                        'unit_price': str(li.unit_price) if li.unit_price is not None else None,
                        'amount': str(li.amount)}
                       for li in so.line_items])


def _edit(client, so, notes, lines, unchanged=True, **extra):
    data = {'so_number': so.so_number, 'order_date': '2026-09-22',
            'customer_id': str(so.customer_id), 'payment_terms': 'Net 60',
            'notes': notes, 'line_items': lines,
            'row_version': str(so.row_version)}
    if unchanged:
        data['lines_unchanged'] = '1'
    data.update(extra)
    return client.post(f'/sales-orders/{so.id}/edit', data=data,
                       follow_redirects=True)


def _amend(client, so, notes, lines, unchanged=True, **extra):
    data = {'so_number': so.so_number, 'order_date': '2026-09-22',
            'customer_id': str(so.customer_id), 'payment_terms': 'Net 60',
            'notes': notes, 'line_items': lines,
            'amend_reason': 'Correcting the note recorded at confirmation',
            'row_version': str(so.row_version)}
    if unchanged:
        data['lines_unchanged'] = '1'
    data.update(extra)
    return client.post(f'/sales-orders/{so.id}/amend', data=data,
                       follow_redirects=True)


class TestEditingOnlyTheHeader:

    def test_notes_save_on_an_order_whose_line_has_no_product(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer)
        resp = _edit(client, so, 'CORRECTED NOTE', _lines_of(so))
        assert resp.status_code == 200
        db_session.refresh(so)
        assert so.notes == 'CORRECTED NOTE'

    def test_the_line_is_left_exactly_as_it_was(
            self, client, db_session, branch, customer, logged_in):
        """Not merely "still invalid" -- the SAME ROW. The edit path normally
        deletes and rebuilds every line, which would renumber ids and reset
        line_status; skipping it must skip all of that."""
        so = _so(db_session, branch, customer)
        line_id = so.line_items[0].id
        _edit(client, so, 'CORRECTED NOTE', _lines_of(so))
        db_session.expire(so, ['line_items'])
        assert len(so.line_items) == 1
        assert so.line_items[0].id == line_id
        assert so.line_items[0].product_id is None
        assert so.line_items[0].amount == Decimal('50.00')

    def test_without_the_flag_the_old_refusal_still_stands(
            self, client, db_session, branch, customer, logged_in):
        """The relaxation is opt-in. A submission that claims to carry line
        changes is still validated line by line, so nothing is loosened for the
        ordinary path."""
        so = _so(db_session, branch, customer)
        resp = _edit(client, so, 'SHOULD NOT SAVE', _lines_of(so), unchanged=False)
        assert b'select a product' in resp.data
        db_session.refresh(so)
        assert so.notes == 'ORIGINAL NOTE'

    def test_a_valid_order_still_saves_line_changes_normally(
            self, client, db_session, branch, customer, product, logged_in):
        """Control: the flag is absent on a real line edit, and lines still get
        written."""
        so = _so(db_session, branch, customer, number='HDR-OK', product=product)
        lines = json.dumps([{'so_item_id': so.line_items[0].id, 'line_number': 1,
                             'product_id': product.id, 'quantity': '9',
                             'unit_price': '10.00', 'amount': '90.00'}])
        _edit(client, so, 'note', lines, unchanged=False)
        db_session.expire(so, ['line_items'])
        assert so.line_items[0].quantity == Decimal('9')
        assert so.line_items[0].amount == Decimal('90.00')


class TestTheFlagCannotWriteLines:
    """The security property. The flag's only power is to make the server IGNORE
    the submitted lines, so lying about it cannot put unvalidated data in the
    database -- the fail-safe direction."""

    def test_different_lines_sent_with_the_flag_are_ignored(
            self, client, db_session, branch, customer, product, logged_in):
        so = _so(db_session, branch, customer, number='HDR-LIE', product=product)
        original_qty = so.line_items[0].quantity
        forged = json.dumps([{'so_item_id': so.line_items[0].id, 'line_number': 1,
                              'product_id': product.id, 'quantity': '99999',
                              'unit_price': '1.00', 'amount': '99999.00'}])
        _edit(client, so, 'note', forged, unchanged=True)
        db_session.expire(so, ['line_items'])
        assert so.line_items[0].quantity == original_qty, \
            'the flag let a forged line through -- it must only ever ignore lines'

    def test_extra_lines_sent_with_the_flag_are_ignored(
            self, client, db_session, branch, customer, product, logged_in):
        so = _so(db_session, branch, customer, number='HDR-LIE2', product=product)
        forged = json.dumps([
            {'so_item_id': so.line_items[0].id, 'line_number': 1,
             'product_id': product.id, 'quantity': '5', 'unit_price': '10.00',
             'amount': '50.00'},
            {'so_item_id': None, 'line_number': 2, 'product_id': product.id,
             'quantity': '1', 'unit_price': '1.00', 'amount': '1.00'},
        ])
        _edit(client, so, 'note', forged, unchanged=True)
        db_session.expire(so, ['line_items'])
        assert len(so.line_items) == 1

    def test_an_empty_line_list_with_the_flag_does_not_empty_the_order(
            self, client, db_session, branch, customer, product, logged_in):
        """The shape has_usable_line() exists to stop. With the flag it cannot
        even be attempted, because the lines are never touched."""
        so = _so(db_session, branch, customer, number='HDR-EMPTY', product=product)
        _edit(client, so, 'note', json.dumps([]), unchanged=True)
        db_session.expire(so, ['line_items'])
        assert len(so.line_items) == 1


class TestAmendingOnlyTheHeader:

    def _confirmed(self, db_session, branch, customer, number='HDR-A1', product=None):
        so = _so(db_session, branch, customer, status='confirmed',
                 number=number, product=product)
        db_session.commit()
        return so

    def test_notes_amend_on_an_order_whose_line_has_no_product(
            self, client, db_session, branch, customer, logged_in):
        so = self._confirmed(db_session, branch, customer)
        resp = _amend(client, so, 'AMENDED NOTE', _lines_of(so))
        assert resp.status_code == 200
        db_session.refresh(so)
        assert so.notes == 'AMENDED NOTE'
        assert so.status == 'confirmed', 'an amendment must not change the status'

    def test_it_still_writes_a_revision(
            self, client, db_session, branch, customer, logged_in):
        """A header-only amendment is still an amendment. Skipping the line
        application must not skip the audit trail the module is built on."""
        so = self._confirmed(db_session, branch, customer, number='HDR-A2')
        before = SalesOrderRevision.query.filter_by(sales_order_id=so.id).count()
        _amend(client, so, 'AMENDED NOTE', _lines_of(so))
        after = SalesOrderRevision.query.filter_by(sales_order_id=so.id).all()
        assert len(after) == before + 1
        assert after[-1].reason == 'Correcting the note recorded at confirmation'

    def test_the_line_keeps_its_identity_and_status(
            self, client, db_session, branch, customer, logged_in):
        so = self._confirmed(db_session, branch, customer, number='HDR-A3')
        line_id = so.line_items[0].id
        _amend(client, so, 'AMENDED NOTE', _lines_of(so))
        db_session.expire(so, ['line_items'])
        assert so.line_items[0].id == line_id
        assert so.line_items[0].product_id is None

    def test_the_amend_reason_is_still_required(
            self, client, db_session, branch, customer, logged_in):
        """The flag relaxes the LINE gate and nothing else."""
        so = self._confirmed(db_session, branch, customer, number='HDR-A4')
        resp = _amend(client, so, 'AMENDED NOTE', _lines_of(so), amend_reason='')
        db_session.refresh(so)
        assert so.notes == 'ORIGINAL NOTE'


class TestTheHeaderChangesAreAudited:
    """notes was written by both routes and named in neither's audited fields, so
    a notes-only change wrote a row asserting nothing changed."""

    def _last(self, so):
        return (AuditLog.query
                .filter_by(module='sales_orders', record_id=so.id)
                .order_by(AuditLog.id.desc()).first())

    def test_an_edit_records_the_note_before_and_after(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer, number='HDR-AUD1')
        _edit(client, so, 'CORRECTED NOTE', _lines_of(so))
        row = self._last(so)
        assert row is not None
        assert 'ORIGINAL NOTE' in (row.old_values or '')
        assert 'CORRECTED NOTE' in (row.new_values or '')

    def test_an_amendment_records_the_note_before_and_after(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer, status='confirmed',
                 number='HDR-AUD2')
        db_session.commit()
        _amend(client, so, 'AMENDED NOTE', _lines_of(so))
        row = self._last(so)
        assert row is not None
        assert 'ORIGINAL NOTE' in (row.old_values or '')
        assert 'AMENDED NOTE' in (row.new_values or '')

    def test_the_other_written_header_fields_are_audited_too(
            self, client, db_session, branch, customer, logged_in):
        """Same defect, same fix: these were all assigned by the route and
        invisible in the trail."""
        so = _so(db_session, branch, customer, number='HDR-AUD3')
        _edit(client, so, 'note', _lines_of(so),
              payment_terms='Net 15', reference='REF-9', customer_po_number='CPO-7')
        row = self._last(so)
        for expected in ('Net 15', 'REF-9', 'CPO-7'):
            assert expected in (row.new_values or ''), \
                '%s is saved but not audited' % expected


class TestTheFormShipsTheMachineryTheServerExpects:
    """The two halves have to agree. The server's relaxation is unreachable if the
    form never posts the flag, and the button stays disabled if the snapshot is
    never taken -- neither of which a server-side test would notice."""

    def test_the_edit_page_posts_the_flag(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer, number='HDR-FORM1')
        body = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        assert 'name="lines_unchanged"' in body

    def test_the_edit_page_snapshots_its_lines_on_load(
            self, client, db_session, branch, customer, logged_in):
        """Guarded by `{% if so %}`, so this must be present on edit and absent
        on create -- a new order has nothing to leave alone."""
        so = _so(db_session, branch, customer, number='HDR-FORM2')
        body = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        assert 'initialLinesSnapshot = serializeLines();' in body

    def test_the_amend_page_posts_the_flag_too(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer, status='confirmed',
                 number='HDR-FORM3')
        db_session.commit()
        body = client.get(f'/sales-orders/{so.id}/amend').data.decode()
        assert 'name="lines_unchanged"' in body
        assert 'initialLinesSnapshot = serializeLines();' in body

    def test_the_create_page_takes_no_snapshot(
            self, client, db_session, branch, customer, logged_in):
        body = client.get('/sales-orders/create').data.decode()
        assert 'name="lines_unchanged"' in body
        assert 'initialLinesSnapshot = serializeLines();' not in body

    def test_the_button_is_validated_on_load_not_only_on_a_line_change(
            self, client, db_session, branch, customer, logged_in):
        """validateForm() was reachable on load only through
        addLineItem -> updateDerivedAmount, so an order with NO lines never
        validated and its Update button sat disabled with an empty hint --
        disabled for a reason the page never gave."""
        so = _so(db_session, branch, customer, number='HDR-FORM4')
        body = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        # The applied call, at top level after initItems() -- not the definition
        # and not a call from inside another function.
        assert '\nvalidateForm();' in body
