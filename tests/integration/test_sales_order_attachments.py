"""Sales Orders accept file attachments: Customer PO, Signed SO, Signed JO, plus Other.

Owner request 2026-09-30: "there must be PO, signed SO and other documents
attachment feature for SO." Almost entirely REUSE -- `document_attachments` is
already polymorphic on (document_type, document_id) with a `kind` per named slot,
so this is a registry entry, template wiring, the confirm-time soft gate, and one
column (`approved_incomplete_slots`) that every other gated document already has.

What an SO does differently from a PO, each covered below:

  * Its approval step is called CONFIRM (POST /sales-orders/<id>/confirm), so the
    panel's advisory dialog must watch /confirm, and the wording must say
    "confirmed", not "approved".
  * The signed SO and signed JO only exist AFTER confirmation (the SO is printed
    and signed once confirmed), so a confirmed SO must still take uploads --
    through the amend path, for approve-level users, exactly as an approved PO.
"""
import datetime
import io
import json
from decimal import Decimal

import pytest

from app import db
from tests.integration._so_helpers import (  # noqa: F401  (autouse fixture)
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders, pytest.mark.attachments]

SLOT_KEYS = ['customer_po', 'signed_so', 'signed_jo']


def _so(db_session, customer, branch, number='SO-ATT-0001', status='draft'):
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 9, 30),
                    customer_id=customer.id, customer_name=customer.name,
                    branch_id=branch.id, status=status,
                    customer_po_number='RM-TEST-1')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


def _upload(client, so, kind='customer_po', filename='po.pdf', data=b'%PDF-1.4 fake'):
    return client.post(
        f'/attachments/sales_orders/{so.id}/upload',
        data={'kind': kind, 'attachments': (io.BytesIO(data), filename)},
        content_type='multipart/form-data', follow_redirects=True)


def _rows(so):
    from app.attachments.models import DocumentAttachment
    return (DocumentAttachment.query
            .filter_by(document_type='sales_orders', document_id=so.id)
            .order_by(DocumentAttachment.id).all())


def _as(client, user, branch):
    _login(client, user)
    _select_branch(client, branch.id)


def _staff_on(db_session, staff_user, branch):
    """The shared staff fixture has no branch; without one the branch gate bounces
    every request to the picker, and a refusal test would pass for that reason
    instead of the attachment rule."""
    staff_user.set_branches([branch])
    db_session.commit()
    return staff_user


class TestTheSlots:

    def test_the_registry_defines_the_three_required_slots_in_order(self):
        from app.attachments.registry import slots_for
        slots = slots_for('sales_orders')
        assert [s.key for s in slots] == SLOT_KEYS
        assert [s.label for s in slots] == ['Customer PO', 'Signed SO', 'Signed JO']
        assert all(s.required for s in slots)

    def test_the_detail_page_names_every_slot_and_offers_the_upload(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, admin_user, main_branch)
        body = client.get(f'/sales-orders/{so.id}').data.decode()
        for label in ('Customer PO', 'Signed SO', 'Signed JO'):
            assert label in body
        assert f'/attachments/sales_orders/{so.id}/upload' in body

    def test_the_edit_page_offers_the_panel(self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, admin_user, main_branch)
        body = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        assert f'/attachments/sales_orders/{so.id}/upload' in body

    def test_the_create_page_queues_files_on_a_multipart_form(
            self, client, admin_user, main_branch):
        _as(client, admin_user, main_branch)
        body = client.get('/sales-orders/create').data.decode()
        assert 'id="soForm" enctype="multipart/form-data"' in body
        assert 'id="createAttachments"' in body


class TestUploading:

    def test_the_customer_po_uploads_against_its_slot_on_a_draft(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, admin_user, main_branch)
        assert _upload(client, so).status_code == 200
        rows = _rows(so)
        assert [(r.kind, r.original_filename) for r in rows] == [('customer_po', 'po.pdf')]

    def test_staff_may_attach_while_the_order_is_a_draft(
            self, client, db_session, staff_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, _staff_on(db_session, staff_user, main_branch), main_branch)
        _upload(client, so, kind='signed_so', filename='signed.pdf')
        assert [r.kind for r in _rows(so)] == ['signed_so']

    def test_the_upload_is_audited_through_the_real_route(
            self, client, db_session, admin_user, main_branch):
        from app.audit.models import AuditLog
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, admin_user, main_branch)
        _upload(client, so, filename='audited-po.pdf')
        row = (AuditLog.query.filter_by(module='sales_orders_attachment')
               .order_by(AuditLog.id.desc()).first())
        assert row is not None, 'no audit row for the upload'
        assert 'audited-po.pdf' in (row.new_values or '')

    def test_an_unlabelled_file_is_kept_as_other(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch)
        _as(client, admin_user, main_branch)
        _upload(client, so, kind='', filename='certificate-of-analysis.pdf')
        rows = _rows(so)
        assert len(rows) == 1 and rows[0].kind is None

    def test_a_confirmed_order_still_takes_the_signed_copies_from_an_approver(
            self, client, db_session, accountant_user, main_branch):
        """The signed SO/JO only exist after confirmation, so confirmed must stay open."""
        so = _so(db_session, _customer(db_session), main_branch, status='confirmed')
        _as(client, accountant_user, main_branch)
        _upload(client, so, kind='signed_jo', filename='jo.pdf')
        assert [r.kind for r in _rows(so)] == ['signed_jo']

    def test_staff_cannot_attach_once_the_order_is_confirmed(
            self, client, db_session, staff_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch, status='confirmed')
        _as(client, _staff_on(db_session, staff_user, main_branch), main_branch)
        resp = _upload(client, so, kind='signed_so', filename='late.pdf')
        assert _rows(so) == []
        assert b'Attachments can no longer be added to this document.' in resp.data, \
            'refused for some other reason than the attachment rule'

    def test_a_cancelled_order_is_closed_to_uploads(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch, status='cancelled')
        _as(client, admin_user, main_branch)
        resp = _upload(client, so, filename='too-late.pdf')
        assert _rows(so) == []
        assert b'Attachments can no longer be added to this document.' in resp.data

    def test_files_queued_on_the_create_form_are_saved_with_the_new_order(
            self, client, db_session, admin_user, main_branch):
        from app.sales_orders.models import SalesOrder
        c = _customer(db_session); p = _product(db_session, code='ATT-P1')
        _as(client, admin_user, main_branch)
        lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                             'vat_category': None, 'vat_rate': '0'}])
        client.post('/sales-orders/create', data={
            'so_number': 'SO-ATT-Q1', 'order_date': '2026-09-30',
            'customer_id': str(c.id), 'customer_name': c.name, 'payment_terms': 'Net 30',
            'notes': '', 'line_items': lines,
            'attachments': [(io.BytesIO(b'%PDF-1.4 po'), 'customer-po.pdf')],
        }, content_type='multipart/form-data', follow_redirects=True)
        so = SalesOrder.query.filter_by(so_number='SO-ATT-Q1').first()
        assert so is not None, 'the order was not created'
        assert [r.original_filename for r in _rows(so)] == ['customer-po.pdf']


class TestConfirmIsASoftGate:

    def test_confirming_with_files_missing_goes_through_and_is_recorded(
            self, client, db_session, admin_user, main_branch):
        from app.audit.models import AuditLog
        so = _so(db_session, _customer(db_session), main_branch, number='SO-ATT-G1')
        _as(client, admin_user, main_branch)
        resp = client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
        db_session.refresh(so)
        assert so.status == 'confirmed', 'a missing file must not block confirmation'
        assert set(json.loads(so.approved_incomplete_slots)) == set(SLOT_KEYS)
        assert b'Customer PO' in resp.data, 'the warning names the missing files'
        notes = [a.notes or '' for a in AuditLog.query.filter_by(module='sales_orders').all()]
        assert any('missing' in n.lower() for n in notes)

    def test_confirming_a_complete_order_leaves_no_marker(
            self, client, db_session, admin_user, main_branch):
        from app.attachments.models import DocumentAttachment
        from app.utils import ph_now
        so = _so(db_session, _customer(db_session), main_branch, number='SO-ATT-G2')
        for kind in SLOT_KEYS:
            db.session.add(DocumentAttachment(
                document_type='sales_orders', document_id=so.id, kind=kind,
                original_filename=f'{kind}.pdf', stored_filename=f'{kind}-x.pdf',
                mime_type='application/pdf', file_size=10, uploaded_by_id=admin_user.id,
                uploaded_at=ph_now()))
        db.session.commit()
        _as(client, admin_user, main_branch)
        client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
        db_session.refresh(so)
        assert so.status == 'confirmed'
        assert so.approved_incomplete_slots is None

    def test_the_advisory_dialog_watches_the_confirm_button(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch, number='SO-ATT-G3')
        _as(client, admin_user, main_branch)
        body = client.get(f'/sales-orders/{so.id}').data.decode()
        assert r'/\/(approve|post|submit|confirm)$/' in body
        assert f'action="/sales-orders/{so.id}/confirm"' in body

    def test_an_order_confirmed_incomplete_says_confirmed_not_approved(
            self, client, db_session, admin_user, main_branch):
        so = _so(db_session, _customer(db_session), main_branch, number='SO-ATT-G4')
        _as(client, admin_user, main_branch)
        client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
        body = client.get(f'/sales-orders/{so.id}').data.decode()
        assert 'Incomplete — confirmed with 3 required files missing' in body
        assert 'recorded as confirmed with files missing' in body


class TestCompanySettings:

    def test_required_attachments_lists_the_sales_order(
            self, client, admin_user, main_branch):
        _as(client, admin_user, main_branch)
        body = client.get('/settings/attachment-slots').data.decode()
        assert 'Sales Order' in body
        for key in SLOT_KEYS:
            assert f'required:sales_orders:{key}' in body
