"""An approved PO can be amended; each amendment appends a revision.

The amend route is the buy-side mirror of sales_orders.amend(). The behaviour
this file exists to pin, in order of how expensive it is to get wrong:

1. The line applier UPDATES IN PLACE. A delete-and-rebuild (what edit() does)
   changes PurchaseOrderItem.id, which breaks revision-to-revision line matching
   AND orphans every ReceivingReportItem.purchase_order_item_id pointing at the
   old rows. SQLite FK enforcement is off app-wide, so that is silent
   corruption, not an error.
2. A refused amendment writes NOTHING -- no revision, no line change.
3. An amendment revises; it does not renumber, re-open, or re-approve.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s the route for every role, admin included. Mirrors
    test_purchase_orders_lifecycle.py's identically-named fixture."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    """Direct-session login. conftest's login_user posts through the real /login
    view, which does not select a branch -- with both main_branch (via
    db_with_data) and branch_manila active, the branch picker would swallow every
    request. _get_po_or_404 requires session['selected_branch_id'] == po.branch_id."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture(autouse=True)
def logged_in(client, admin_user, branch_manila):
    """Every test here (and the approved_po fixture's approve POST) needs an
    authenticated session scoped to the PO's branch."""
    _login(client, admin_user, branch_manila)


@pytest.fixture
def vendor_acme(db_with_data):
    from app.vendors.models import Vendor
    v = Vendor(code='V900', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v)
    db.session.commit()
    return v


def _make_draft_po(branch, vendor, number):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 5), status='draft',
                       vendor_id=vendor.id, vendor_name=vendor.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('10'),
        unit_price=Decimal('5.00'), amount=Decimal('50.00'),
        line_total=Decimal('50.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    po.calculate_totals()
    db.session.add(po)
    db.session.commit()
    return po


@pytest.fixture
def draft_po(db_with_data, branch_manila, vendor_acme):
    return _make_draft_po(branch_manila, vendor_acme, '00998')


@pytest.fixture
def approved_po(client, logged_in, db_with_data, branch_manila, vendor_acme):
    """Approved via the APPROVE ROUTE, not by assigning status='approved'.

    write_revision numbers `0 if prev is None else prev + 1`, so an amendment is
    Rev 1 only when Rev 0 already exists -- and Rev 0 is written by approve().
    A directly-constructed 'approved' row would make the first amendment Rev 0.
    """
    po = _make_draft_po(branch_manila, vendor_acme, '00997')
    resp = client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db.session.expire_all()
    assert po.status == 'approved', 'fixture precondition: the approve route ran'

    # An ID-REUSE GUARD, not scenery. SQLite assigns a new rowid as
    # max(rowid) + 1 PER TABLE, so deleting this PO's only line and re-inserting
    # it hands back the SAME id -- under which every "line ids are stable"
    # assertion passes even for a delete-and-rebuild applier (verified: the
    # rebuild mutation survived the whole file without this). A second PO whose
    # line sits at a HIGHER rowid, created AFTER this one, makes that reuse
    # impossible, so those assertions detect what they exist to detect.
    _make_draft_po(branch_manila, vendor_acme, '00990')
    return po


@pytest.fixture
def approved_po_with_receipt(client, approved_po):
    """approved_po plus one APPROVED Receiving Report for 4 of its 10 units."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(rr_number='RR-00997', receipt_date=date(2026, 8, 6),
                         purchase_order_id=approved_po.id,
                         vendor_name=approved_po.vendor_name, status='approved',
                         branch_id=approved_po.branch_id)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=approved_po.line_items[0].id,
        received_quantity=Decimal('4')))
    db.session.add(rr)
    db.session.commit()
    return approved_po


def _revs(po):
    return (DocumentRevision.query
            .filter_by(document_type='purchase_orders', document_id=po.id)
            .order_by(DocumentRevision.revision_number).all())


def _payload(po, overrides=None):
    """The line JSON the amend form posts, keyed on po_item_id -- the SAME
    identity the validator and the applier key on. `overrides` maps a line id to
    the fields to change on that line."""
    overrides = overrides or {}
    lines = [{'po_item_id': li.id, 'product_id': li.product_id,
              'description': li.description, 'quantity': str(li.quantity),
              'unit_price': str(li.unit_price), 'amount': str(li.amount),
              'vat_category': li.vat_category, 'vat_rate': str(li.vat_rate)}
             for li in po.line_items]
    for line in lines:
        line.update(overrides.get(line['po_item_id'], {}))
    return json.dumps(lines)


class TestPoAmend:
    def test_amending_an_approved_po_appends_rev_1(self, client, admin_user, approved_po):
        before = len(_revs(approved_po))
        assert before == 1, 'approve() must already have written Rev 0'
        resp = client.post(f'/purchase-orders/{approved_po.id}/amend', data={
            'po_number': approved_po.po_number,
            'order_date': '2026-08-05',
            'vendor_id': approved_po.vendor_id,
            'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30',
            'notes': '',
            'amend_reason': 'vendor corrected the unit price',
            'line_items': _payload(approved_po),
            'row_version': approved_po.row_version,
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        revs = _revs(approved_po)
        assert len(revs) == before + 1
        assert revs[-1].revision_number == 1
        assert revs[-1].reason == 'vendor corrected the unit price'
        assert revs[-1].amended_by_id == admin_user.id

    def test_the_amendment_snapshot_records_the_new_values(self, client, admin_user, approved_po):
        # Without this, an amendment could commit the change but snapshot the OLD
        # state -- a revision history that lies about what each revision contained.
        line_id = approved_po.line_items[0].id
        self._amend(client, approved_po, lines={line_id: {'quantity': '25'}})
        db.session.expire_all()
        snap = json.loads(_revs(approved_po)[-1].snapshot_json)
        assert Decimal(snap['lines'][0]['quantity']) == Decimal('25')
        assert snap['header']['status'] == 'approved'

    def test_status_is_unchanged_by_an_amendment(self, client, admin_user, approved_po):
        # An amendment revises; it does not re-open or re-approve.
        self._amend(client, approved_po)
        db.session.expire_all()
        assert db.session.get(PurchaseOrder, approved_po.id).status == 'approved'

    def test_po_number_is_not_renumbered(self, client, admin_user, approved_po):
        before = approved_po.po_number
        self._amend(client, approved_po, po_number='99999')
        db.session.expire_all()
        assert db.session.get(PurchaseOrder, approved_po.id).po_number == before

    def test_line_ids_are_stable_across_an_amendment(self, client, admin_user, approved_po):
        # UPDATE IN PLACE, not delete-and-rebuild: a rebuild orphans every
        # ReceivingReportItem.purchase_order_item_id with FK enforcement off.
        ids_before = sorted(li.id for li in approved_po.line_items)
        self._amend(client, approved_po,
                    lines={approved_po.line_items[0].id: {'quantity': '25'}})
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert sorted(li.id for li in po.line_items) == ids_before
        # ... and the edit actually landed, so the assertion above is not
        # satisfied by a no-op route that ignored the submission entirely.
        assert po.line_items[0].quantity == Decimal('25')

    def test_an_added_line_is_appended_without_disturbing_the_existing_ids(
            self, client, admin_user, approved_po):
        ids_before = sorted(li.id for li in approved_po.line_items)
        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': None, 'product_id': None, 'description': 'bolt',
                      'quantity': '3', 'unit_price': '2.00', 'amount': '6.00',
                      'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, line_items=json.dumps(lines))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 2
        assert sorted(li.id for li in po.line_items)[:1] == ids_before
        assert po.line_items[1].description == 'bolt'

    def test_a_line_with_no_receipts_can_be_removed(self, client, admin_user, approved_po):
        # Control for the removal guard below: with nothing received and nothing
        # referencing the line, removal is allowed -- so the refusal test proves
        # the guard, not a blanket ban on shrinking a PO.
        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': None, 'product_id': None, 'description': 'bolt',
                      'quantity': '3', 'unit_price': '2.00', 'amount': '6.00',
                      'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, line_items=json.dumps(lines))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 2, 'precondition: two lines to remove one from'
        keep = po.line_items[0].id
        self._amend(client, po, line_items=json.dumps(
            [line for line in json.loads(_payload(po)) if line['po_item_id'] == keep]))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert [li.id for li in po.line_items] == [keep]

    def test_a_draft_po_is_redirected_to_edit_not_amended(self, client, admin_user, draft_po):
        resp = self._amend(client, draft_po)
        assert _revs(draft_po) == []
        assert resp.request.path.endswith('/edit')

    def test_a_cancelled_po_cannot_be_amended(self, client, admin_user, approved_po):
        # AMEND_STATUSES is the gate; anything outside it is refused with its
        # status named, and writes nothing.
        approved_po.status = 'cancelled'
        db.session.commit()
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po)
        assert len(_revs(approved_po)) == before
        assert resp.request.path == f'/purchase-orders/{approved_po.id}'
        assert b'cannot be amended' in resp.data
        assert b'&#34;cancelled&#34;' in resp.data, 'the refusal must name the status'

    def test_a_reduction_below_received_is_refused_and_writes_no_revision(
            self, client, admin_user, approved_po_with_receipt):
        po = approved_po_with_receipt
        before = len(_revs(po))
        resp = self._amend(client, po, lines={po.line_items[0].id: {'quantity': '1'}})
        assert b'already received' in resp.data
        assert len(_revs(po)) == before, 'a refused amendment must write nothing'
        db.session.expire_all()
        assert db.session.get(PurchaseOrder, po.id).line_items[0].quantity == Decimal('10')

    def test_removing_a_received_line_is_refused_and_writes_no_revision(
            self, client, admin_user, approved_po_with_receipt):
        po = approved_po_with_receipt
        before = len(_revs(po))
        resp = self._amend(client, po, line_items=json.dumps([]))
        assert b'already received' in resp.data
        assert len(_revs(po)) == before
        db.session.expire_all()
        assert len(db.session.get(PurchaseOrder, po.id).line_items) == 1

    def test_a_reduction_to_exactly_the_received_qty_is_allowed(
            self, client, admin_user, approved_po_with_receipt):
        # Boundary control: the floor is `new < consumed`, not `new <= consumed`.
        po = approved_po_with_receipt
        self._amend(client, po, lines={po.line_items[0].id: {'quantity': '4'}})
        db.session.expire_all()
        assert db.session.get(PurchaseOrder, po.id).line_items[0].quantity == Decimal('4')

    def test_a_receipt_stays_attached_to_its_line_across_an_amendment(
            self, client, admin_user, approved_po_with_receipt):
        # This is WHY line ids must be stable. A rebuild does not error -- SQLite
        # FK enforcement is off app-wide -- it silently strands the RR line's
        # purchase_order_item_id, which reads back as "nothing was ever
        # received" and lets the next amendment cut the line below its receipts.
        from app.receiving_reports.models import ReceivingReportItem
        po = approved_po_with_receipt
        line_id = po.line_items[0].id
        assert po.consumed_qty(po.line_items[0]) == Decimal('4')

        self._amend(client, po, lines={line_id: {'quantity': '25'}})
        db.session.expire_all()

        po = db.session.get(PurchaseOrder, approved_po_with_receipt.id)
        assert po.line_items[0].id == line_id
        assert po.consumed_qty(po.line_items[0]) == Decimal('4')
        rr_item = ReceivingReportItem.query.one()
        assert db.session.get(PurchaseOrderItem, rr_item.purchase_order_item_id) is not None

    def test_a_reason_shorter_than_10_chars_is_refused(self, client, admin_user, approved_po):
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, amend_reason='typo')
        assert len(_revs(approved_po)) == before
        # The refusal must be VISIBLE. A WTForms field error only populates
        # form.<field>.errors; if the route does not flash it, this response is a
        # plain 200 indistinguishable from a success.
        assert b'at least 10 characters' in resp.data

    def test_a_stale_row_version_is_refused(self, client, admin_user, approved_po):
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, row_version=approved_po.row_version - 1)
        assert len(_revs(approved_po)) == before
        assert b'changed' in resp.data.lower() or b'conflict' in resp.data.lower()

    def test_a_viewer_cannot_amend(self, client, viewer_user, branch_manila, draft_po):
        # Deliberately built from draft_po and flipped in the DB rather than from
        # approved_po: flask_login caches the loaded user on `g`, and conftest's
        # session-scoped app context keeps that `g` alive across requests, so any
        # test that has ALREADY issued a request (approved_po's approve POST) can
        # no longer switch users. This test therefore issues its first request as
        # the viewer. Rev 0's absence is irrelevant here -- the role gate runs
        # before anything reads revisions.
        draft_po.status = 'approved'
        # A non-admin with no assigned branch is force-logged-out by the branch
        # session guard before any view runs -- which would "pass" this test for
        # entirely the wrong reason.
        viewer_user.branches.append(branch_manila)
        db.session.commit()
        _login(client, viewer_user, branch_manila)
        resp = self._amend(client, draft_po)
        assert _revs(draft_po) == []
        assert resp.request.path == '/purchase-orders'
        assert b'You do not have permission to perform this action.' in resp.data

    def test_a_po_in_another_branch_is_404(self, client, admin_user, main_branch, approved_po):
        _login(client, admin_user, main_branch)
        resp = client.post(f'/purchase-orders/{approved_po.id}/amend', data={})
        assert resp.status_code == 404
        assert _revs(approved_po) and len(_revs(approved_po)) == 1

    def test_the_amendment_is_audited(self, client, admin_user, approved_po):
        from app.audit.models import AuditLog
        self._amend(client, approved_po)
        entry = (AuditLog.query
                 .filter_by(module='purchase_orders', action='update',
                            record_id=approved_po.id)
                 .order_by(AuditLog.id.desc()).first())
        assert entry is not None
        assert entry.user_id == admin_user.id
        assert 'Rev 1' in (entry.notes or '')

    # -- helper -------------------------------------------------------------
    def _amend(self, client, po, lines=None, **overrides):
        data = {
            'po_number': po.po_number,
            'order_date': '2026-08-05',
            'vendor_id': po.vendor_id,
            'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30',
            'notes': '',
            'amend_reason': 'vendor corrected the quantity',
            'line_items': _payload(po, lines),
            'row_version': po.row_version,
        }
        data.update(overrides)
        return client.post(f'/purchase-orders/{po.id}/amend', data=data,
                           follow_redirects=True)
