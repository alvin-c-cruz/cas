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


#: Sentinel for `_amend(..., key=_OMIT)` -- posts the form with that key REMOVED
#: rather than blank. An absent key and an empty value are different requests,
#: and the two bugs pinned below (line_items defaulting to '[]', row_version's
#: WTForms obj-fallback) are both only reachable through absence.
_OMIT = object()


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

    def test_the_amendment_is_audited_under_the_amend_action(
            self, client, admin_user, approved_po):
        # The spec asks for action `amend`, not `update`: the audit log is where
        # an auditor separates "somebody edited a draft" from "somebody rewrote an
        # APPROVED document", and `update` collapses the two. approve() and the
        # draft edit() keep `update`, so the distinction is only worth anything if
        # the amendment is the one that differs -- asserted in both directions.
        from app.audit.models import AuditLog
        self._amend(client, approved_po)
        entry = (AuditLog.query
                 .filter_by(module='purchase_orders', action='amend',
                            record_id=approved_po.id)
                 .order_by(AuditLog.id.desc()).first())
        assert entry is not None, 'the amendment was not audited as an amendment'
        assert entry.user_id == admin_user.id
        assert 'Rev 1' in (entry.notes or '')
        assert not [e for e in AuditLog.query.filter_by(
            module='purchase_orders', action='update',
            record_id=approved_po.id).all() if 'Rev 1' in (e.notes or '')], (
            'the amendment was also logged as a plain update')

    # -- the role gate is the APPROVE-level gate, not the edit-level one ------

    def _approve_in_db(self, po, user, branch):
        """Flip *po* to approved without issuing a request, and give *user*
        access to *branch*.

        Deliberately NOT built on the `approved_po` fixture: that fixture POSTs
        /approve as admin, and flask_login caches the loaded user on `g` for the
        life of conftest's session-scoped app context -- so a test that has
        ALREADY issued a request can never switch roles (verified: the session
        cookie said viewer while the request still ran as admin). A role test's
        FIRST request must be made as the role under test.

        The branch assignment matters too: a non-admin with no assigned branch is
        force-logged-out by the branch-session guard before any view runs, which
        would "pass" a refusal test for entirely the wrong reason.
        """
        po.status = 'approved'
        user.branches.append(branch)
        db.session.commit()

    def test_a_staff_user_cannot_amend_an_approved_po(
            self, client, staff_user, branch_manila, draft_po):
        # THE critical gate case. `staff` may create and edit a DRAFT PO
        # (_role_gate admits them) but may NOT approve one (approve() admits only
        # accountant or full access). Gating amend on the edit-level rule
        # therefore lets a staff user rewrite an APPROVED PO -- quantity, total,
        # terms -- one second after somebody else approved it, with the revision
        # recorded in their name. An approval control that can be bypassed by
        # amending is not a control. The spec requires the module's existing
        # APPROVE-level role rule here.
        #
        # test_a_viewer_cannot_amend does NOT cover this: `viewer` is refused by
        # both the loose and the tight rule, so it passes either way.
        perms = staff_user.get_book_permissions()
        perms.update({'purchase_orders': True, 'products': True})
        staff_user.set_book_permissions(perms)
        self._approve_in_db(draft_po, staff_user, branch_manila)
        _login(client, staff_user, branch_manila)

        resp = self._amend(client, draft_po,
                           lines={draft_po.line_items[0].id: {'quantity': '10000'}})

        assert _revs(draft_po) == [], 'a refused amendment must write nothing'
        assert resp.request.path == '/purchase-orders'
        assert b'You do not have permission to perform this action.' in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.line_items[0].quantity == Decimal('10')
        assert po.total_amount == Decimal('50.00')

    def test_an_accountant_can_amend_an_approved_po(
            self, client, accountant_user, branch_manila, draft_po):
        # Control for the test above: the approve-level rule admits `accountant`,
        # so tightening the gate must not collapse it into "full access only".
        # Without this, "if current_user.role == 'admin'" would pass every other
        # test in this file (they all run as admin).
        self._approve_in_db(draft_po, accountant_user, branch_manila)
        _login(client, accountant_user, branch_manila)
        line_id = draft_po.line_items[0].id

        resp = self._amend(client, draft_po, lines={line_id: {'quantity': '25'}})

        assert resp.request.path == f'/purchase-orders/{draft_po.id}'
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.line_items[0].quantity == Decimal('25')
        revs = _revs(po)
        assert len(revs) == 1
        assert revs[-1].amended_by_id == accountant_user.id

    # -- an ABSENT line_items key is not an empty line list -------------------

    def test_a_post_that_omits_line_items_entirely_is_refused(
            self, client, admin_user, approved_po):
        # request.form.get('line_items', '[]') cannot tell "the field never
        # arrived" from "the user deleted every line". A POST without the key
        # therefore reads as a full clear-out and leaves an APPROVED PO with zero
        # lines and a 0.00 total -- a state approve() itself refuses (it demands
        # at least one priced line), reported to the user as a success.
        #
        # Not theoretical: this repo has already shipped the dropped-hidden-field
        # bug class once (BUG-DR-EDIT-FALSE-CONFLICT / memory
        # csrf-only-render-drops-hidden-fields), and the very template that
        # carries this hidden input is edited by the next task.
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, line_items=_OMIT)

        assert len(_revs(approved_po)) == before, 'a refused amendment must write nothing'
        assert b'did not reach the server' in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 1
        assert po.total_amount == Decimal('50.00')

    def test_an_explicitly_empty_line_items_still_reaches_the_validator(
            self, client, admin_user, approved_po_with_receipt):
        # Control for the refusal above: an explicit `[]` IS a real submission and
        # must be judged by validate_amendment on its own terms, not swallowed by
        # the absent-key guard. Here the guard that fires is the receipts guard,
        # with its own actionable message -- so the two cases stay distinguishable
        # and the fix cannot be over-tightened into "any empty list is malformed".
        #
        # The OUTCOME is asserted, not merely the message. Asserting only that the
        # receipts message appeared is what let C1 survive Task 4's review: this
        # test proved the `[]` path was REACHABLE, and was read as proof that the
        # path was SAFE -- while the same POST against a PO with no receipts
        # emptied it (see TestAnAmendmentMustLeaveAnApprovablePo below).
        po = approved_po_with_receipt
        before = len(_revs(po))
        resp = self._amend(client, po, line_items=json.dumps([]))

        assert b'already received' in resp.data
        assert b'did not reach the server' not in resp.data
        assert len(_revs(po)) == before
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po_with_receipt.id)
        assert len(po.line_items) == 1, 'a refused amendment must leave the lines alone'
        assert po.total_amount == Decimal('50.00')
        assert po.status == 'approved'

    def test_a_non_json_line_items_is_refused_not_a_500(
            self, client, admin_user, approved_po):
        # app/amendments/validation.py's contract is "a crafted POST must produce
        # messages, not a 500" -- but a non-JSON body never reaches the validator:
        # json.loads raises straight out of the view.
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, line_items='not json at all')

        assert resp.status_code == 200
        assert b'could not be read' in resp.data
        assert len(_revs(approved_po)) == before
        db.session.expire_all()
        assert len(db.session.get(PurchaseOrder, approved_po.id).line_items) == 1

    @pytest.mark.parametrize('crafted', ['123', 'true', 'false', '1.5', 'null',
                                         '"x"', '{"a": 1}'])
    def test_valid_json_that_is_not_a_list_is_refused_not_a_500(
            self, client, admin_user, approved_po, crafted):
        # M1 (final review). `json.loads` only refuses input that is not JSON at
        # all; `123`, `true` and `1.5` parse fine and then reach
        # parse_submission's `for line in (new_lines or [])`, which raises
        # TypeError: 'int' object is not iterable. validate_amendment is called
        # OUTSIDE the route's try block, so that is an unhandled 500 -- exactly
        # what validation.py's docstring says cannot happen.
        #
        # `null` is the same door as C1 by another route: it reaches the applier
        # as `items or []` and empties the PO.
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, line_items=crafted)

        assert resp.status_code == 200, 'a crafted line_items must not 500'
        assert b'could not be read' in resp.data
        assert len(_revs(approved_po)) == before
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 1
        assert po.total_amount == Decimal('50.00')

    def test_a_json_list_of_junk_still_reaches_the_validator(
            self, client, admin_user, approved_po):
        # Control for the parametrised refusal above, so the isinstance guard
        # cannot be over-tightened into "anything unusual is unreadable". A LIST
        # is a well-formed submission whatever it holds: each element is judged on
        # its own and gets the validator's per-element message, which is a
        # different (and more specific) refusal than "could not be read".
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, line_items=json.dumps([1, 2, None]))

        assert resp.status_code == 200
        assert b'expected a line object' in resp.data
        assert b'could not be read' not in resp.data
        assert len(_revs(approved_po)) == before

    # -- an amendment may not leave a PO in a shape approve() refuses ----------
    #
    # C1 (final review), Critical. Clicking the red `x` on every row posts an
    # explicit `[]`. That passes validate_amendment -- nothing is consumed, so the
    # removal branch allows it -- and left an APPROVED Purchase Order with zero
    # lines and a 0.00 total, reported to the user as a success, still returned by
    # billable_pos_for() and still printable. approve() refuses exactly that shape
    # one second earlier.
    #
    # The rule is now ONE predicate (PurchaseOrder.has_approvable_line), called by
    # approve() and enforced on the RESULT of an amendment, so the two cannot
    # drift. Both callers are pinned here: the amend direction (this rule is new)
    # and the approve direction (the rule is old, and the extraction must not have
    # changed it).

    def test_an_amendment_that_removes_every_line_is_refused(
            self, client, admin_user, approved_po):
        # The C1 case the old control test never covered: NO receipts, so no other
        # guard fires and the emptying reached the database.
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, line_items=json.dumps([]))

        assert resp.status_code == 200
        assert b'at least one line with a unit price' in resp.data
        assert len(_revs(approved_po)) == before, 'a refused amendment must write nothing'
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 1, 'the amendment emptied an approved PO'
        assert po.total_amount == Decimal('50.00')
        assert po.status == 'approved'

    def test_an_amendment_that_strips_the_last_unit_price_is_refused(
            self, client, admin_user, approved_po):
        # The other half of approve()'s rule: it demands a line with BOTH a unit
        # price and an amount above zero, not merely a line. calculate_amounts()
        # only recomputes when quantity AND unit price are both > 0, so a line can
        # legitimately keep a stale amount with no price at all.
        before = len(_revs(approved_po))
        line_id = approved_po.line_items[0].id
        resp = self._amend(client, approved_po,
                           lines={line_id: {'unit_price': '', 'amount': '0'}})

        assert b'at least one line with a unit price' in resp.data
        assert len(_revs(approved_po)) == before
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert po.line_items[0].unit_price == Decimal('5.00')
        assert po.total_amount == Decimal('50.00')

    def test_removing_one_of_two_lines_still_succeeds(
            self, client, admin_user, approved_po):
        # CONTROL for the two refusals above, asserting the OUTCOME rather than
        # the path: the new rule must refuse "no priced line left", not "fewer
        # lines than before". A refusal here would mean the fix over-tightened
        # into a blanket ban on shrinking a Purchase Order.
        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': None, 'product_id': None, 'description': 'bolt',
                      'quantity': '3', 'unit_price': '2.00', 'amount': '6.00',
                      'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, line_items=json.dumps(lines))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 2, 'precondition: two lines to remove one from'
        keep = po.line_items[0].id
        before = len(_revs(po))

        resp = self._amend(client, po, line_items=json.dumps(
            [line for line in json.loads(_payload(po)) if line['po_item_id'] == keep]))

        assert b'at least one line with a unit price' not in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert [li.id for li in po.line_items] == [keep]
        assert po.total_amount == Decimal('50.00')
        assert len(_revs(po)) == before + 1, 'an allowed amendment must be recorded'

    def test_an_amendment_that_zeroes_one_price_but_not_the_last_succeeds(
            self, client, admin_user, approved_po):
        # The second control, on the price half of the rule: ONE unpriced line is
        # fine as long as the order still carries a priced one -- which is exactly
        # what approve() allows (`any(...)`, not `all(...)`).
        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': None, 'product_id': None, 'description': 'bolt',
                      'quantity': '3', 'unit_price': '2.00', 'amount': '6.00',
                      'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, line_items=json.dumps(lines))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        priced, unpriced = po.line_items[0].id, po.line_items[1].id

        resp = self._amend(client, po,
                           lines={unpriced: {'unit_price': '', 'amount': '0'}})

        assert b'at least one line with a unit price' not in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert {li.id for li in po.line_items} == {priced, unpriced}
        assert po.total_amount == Decimal('50.00')

    def test_approve_still_refuses_a_po_with_no_priced_line(
            self, client, admin_user, draft_po):
        # CONTROL on the OTHER caller of the shared predicate. approve()'s
        # precondition had no test at all, so extracting it could have changed
        # approve()'s observable behaviour with nothing to notice.
        draft_po.line_items[0].unit_price = None
        draft_po.line_items[0].amount = Decimal('0.00')
        draft_po.calculate_totals()
        db.session.commit()

        resp = client.post(f'/purchase-orders/{draft_po.id}/approve',
                           follow_redirects=True)

        assert resp.status_code == 200
        assert b'Set a unit price on at least one line' in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.status == 'draft', 'an unpriced PO was approved'
        assert _revs(po) == [], 'a refused approval must write no Rev 0'

    def test_approve_still_accepts_a_po_with_a_priced_line(
            self, client, admin_user, draft_po):
        # ... and its control, so the test above cannot pass because approve() is
        # broken outright.
        resp = client.post(f'/purchase-orders/{draft_po.id}/approve',
                           follow_redirects=True)

        assert b'Set a unit price on at least one line' not in resp.data
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.status == 'approved'
        assert [r.revision_number for r in _revs(po)] == [0]

    # -- gaps the review's surviving mutations exposed -------------------------

    def test_an_amended_quantity_updates_the_header_total_and_the_snapshot(
            self, client, admin_user, approved_po):
        # calculate_totals() must run BEFORE write_revision. Without it the LINE
        # changes (calculate_amounts runs inside the applier) while
        # subtotal/vat_amount/total_amount stay stale -- and the revision then
        # freezes a header that contradicts its own lines, permanently, in the
        # record the whole feature exists to produce. Same failure shape as
        # posted-je-leg-vs-source-header-invariant.
        line_id = approved_po.line_items[0].id
        assert approved_po.total_amount == Decimal('50.00'), 'precondition: 10 x 5.00'

        self._amend(client, approved_po, lines={line_id: {'quantity': '25'}})
        db.session.expire_all()

        po = db.session.get(PurchaseOrder, approved_po.id)
        assert po.line_items[0].amount == Decimal('125.00')
        assert po.subtotal == Decimal('125.00')
        assert po.total_amount == Decimal('125.00')
        snap = json.loads(_revs(po)[-1].snapshot_json)
        assert Decimal(snap['header']['total_amount']) == Decimal('125.00')
        assert Decimal(snap['header']['subtotal']) == Decimal('125.00')

    def test_a_changed_header_field_is_applied_and_snapshotted(
            self, client, admin_user, approved_po):
        # Every other test posts the fixture's OWN header values back, so the
        # whole header-application block is vacuous: deleting it outright leaves
        # the file green. test_po_number_is_not_renumbered pins the exception
        # (po_number is deliberately not reassigned) while nothing pinned the rule.
        assert approved_po.payment_terms == 'Net 30'
        assert approved_po.notes == ''

        self._amend(client, approved_po, payment_terms='Net 60',
                    notes='vendor moved the delivery window', reference='REF-9')
        db.session.expire_all()

        po = db.session.get(PurchaseOrder, approved_po.id)
        assert po.payment_terms == 'Net 60'
        assert po.notes == 'vendor moved the delivery window'
        assert po.reference == 'REF-9'
        snap = json.loads(_revs(po)[-1].snapshot_json)
        assert snap['header']['payment_terms'] == 'Net 60'
        assert snap['header']['notes'] == 'vendor moved the delivery window'

    def test_a_line_id_from_another_po_cannot_be_rewritten(
            self, client, admin_user, branch_manila, vendor_acme, approved_po):
        # _apply_amended_po_lines' docstring calls the po.line_items-scoped lookup
        # a SECURITY property; this makes the claim testable. Swapping that lookup
        # for a global db.session.get(PurchaseOrderItem, item_id) is a ONE-LINE
        # change under which this exact POST rewrote the OTHER order's line
        # (10 -> 77) and emptied this one -- a cross-document write, HTTP 200,
        # success flash. Under the scoped lookup the foreign id simply falls
        # through to "not found" and becomes a new line on THIS order.
        other = _make_draft_po(branch_manila, vendor_acme, '00991')
        other_line_id = other.line_items[0].id
        assert other_line_id not in [li.id for li in approved_po.line_items]

        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': other_line_id, 'product_id': None,
                      'description': 'crafted', 'quantity': '77',
                      'unit_price': '5.00', 'amount': '385.00',
                      'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, line_items=json.dumps(lines))
        db.session.expire_all()

        other = db.session.get(PurchaseOrder, other.id)
        assert [li.id for li in other.line_items] == [other_line_id]
        assert other.line_items[0].quantity == Decimal('10')
        assert other.line_items[0].description == 'widget'
        assert other.line_items[0].purchase_order_id == other.id
        assert other.total_amount == Decimal('50.00')
        # ... and the foreign id landed as a NEW line on the amended order.
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 2

    def test_the_amend_form_renders_the_row_version_token(
            self, client, admin_user, approved_po):
        # A RENDER assertion, not a POST contract. The route reads the token from
        # the raw POST body (submitted_version()), so a template that stops
        # rendering the hidden field posts no token and false-conflicts every
        # amendment -- and a POST-contract test, which supplies the token itself,
        # structurally cannot see that. It is exactly why
        # BUG-DR-EDIT-FALSE-CONFLICT shipped green. Same guard as
        # tests/integration/test_csrf_only_forms_render_hidden_tokens.py, applied
        # to the rendered amend GET rather than statically to the template file.
        resp = client.get(f'/purchase-orders/{approved_po.id}/amend')
        assert resp.status_code == 200
        assert b'name="row_version"' in resp.data

    def test_a_post_with_no_row_version_key_is_refused(
            self, client, admin_user, approved_po):
        # The fail-open submitted_version() exists to stop: WTForms falls back to
        # the obj value for a field absent from formdata, so form.row_version.data
        # would return the PO's CURRENT version and claim_version() would succeed
        # on a request that never sent a token. test_a_stale_row_version_is_refused
        # posts an explicit 0, which defeats either spelling -- only an ABSENT key
        # tells them apart.
        before = len(_revs(approved_po))
        resp = self._amend(client, approved_po, row_version=_OMIT,
                           lines={approved_po.line_items[0].id: {'quantity': '25'}})

        assert len(_revs(approved_po)) == before
        assert b'changed' in resp.data.lower() or b'conflict' in resp.data.lower()
        db.session.expire_all()
        assert db.session.get(PurchaseOrder, approved_po.id).line_items[0].quantity == Decimal('10')

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
        # `key=_OMIT` removes the key entirely -- see the sentinel's comment.
        data = {k: v for k, v in data.items() if v is not _OMIT}
        return client.post(f'/purchase-orders/{po.id}/amend', data=data,
                           follow_redirects=True)
