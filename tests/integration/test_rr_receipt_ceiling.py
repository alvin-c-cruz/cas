"""One receipt is weighed against each PO line AS A WHOLE, and every line it
carries must belong to the receipt's vendor.

The defect these pin exists independently of the vendor-first form.
`_parse_rr_lines` appends one ReceivingReportItem per payload entry with no
dedupe, and the approve guard asked its question once PER LINE against a ceiling
read from the DATABASE -- which by construction cannot see the siblings in the
same submission. Two lines of 6 against an open 10 therefore each answered
"6 <= 10" and 12 was received against 10 ordered. Same class as
BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION (purchase orders,
cas 66bf733f).

Nothing had hit it because `_submitted_existing_lines` collapses the payload into
a dict keyed by purchase_order_item_id, so the single-PO grid never emitted a
duplicate. That is a DISPLAY helper, not a guard.

Two of these are CONTROLS on the paths the fix must NOT change:
a naive "reject duplicate PO-line ids" passes the bug test and breaks receiving
several lines of one order, and an off-by-one rejects a split delivery that lands
exactly on the ceiling.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _approved_po(db_session, branch, vendor, number, quantities=(10,)):
    """An approved PO carrying one description-only line per entry in *quantities*.

    Description-only on purpose: stock posting is a no-op for an untracked line,
    so the approve tests exercise the guard rather than the GRNI posting engine.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    for i, qty in enumerate(quantities, start=1):
        po.line_items.append(PurchaseOrderItem(
            line_number=i, description=f'Cement {i}', quantity=Decimal(str(qty)),
            unit_price=Decimal('10'), amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _make_draft_rr(db_session, branch, header_po, pairs, number):
    """A draft RR built straight in the DB -- the shape a pre-existing over-receipt
    draft has when someone reaches the approve button. *pairs* is [(poi, qty), ...].

    Copied rather than imported: the RR helpers in
    tests/integration/test_receiving_reports_lifecycle.py are module-local, not
    conftest fixtures.
    """
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number,
                         receipt_date=date(2026, 7, 11), purchase_order_id=header_po.id,
                         vendor_id=header_po.vendor_id, vendor_name=header_po.vendor_name,
                         status='draft')
    for i, (poi, qty) in enumerate(pairs, start=1):
        rr.line_items.append(ReceivingReportItem(line_number=i, purchase_order_item_id=poi.id,
                                                 received_quantity=Decimal(str(qty))))
    db_session.add(rr); db_session.commit()
    return rr


def _post_rr(client, header_po, pairs, rr_number='RR-CEIL-0001'):
    """POST /receiving-reports/create with one payload entry per (poi, qty) pair."""
    lines = [{'purchase_order_item_id': poi.id, 'received_quantity': str(qty)}
             for poi, qty in pairs]
    return client.post('/receiving-reports/create', data={
        'vendor_id': str(header_po.vendor_id),
        'receipt_date': '2026-07-11',
        'remarks': '',
        'rr_number': rr_number,
        'lines': json.dumps(lines),
    }, follow_redirects=True)


def _post_edit(client, rr, pairs):
    lines = [{'purchase_order_item_id': poi.id, 'received_quantity': str(qty)}
             for poi, qty in pairs]
    return client.post(f'/receiving-reports/{rr.id}/edit', data={
        'vendor_id': str(rr.vendor_id),
        'receipt_date': '2026-07-11',
        'remarks': '',
        'rr_number': rr.rr_number,
        'row_version': str(rr.row_version),
        'lines': json.dumps(lines),
    }, follow_redirects=True)


@pytest.fixture
def po_open_10(db_session, main_branch, vl_vendor):
    """One approved PO, one line, 10 ordered and nothing yet received."""
    return _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-A', quantities=(10,))


@pytest.fixture
def po_two_lines(db_session, main_branch, vl_vendor):
    """One approved PO with TWO distinct lines, 10 open each."""
    return _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-B', quantities=(10, 10))


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='OTH-VEND', name='Other Vendor', tin='111-222-333-000')
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def po_other_vendor(db_session, main_branch, other_vendor):
    return _approved_po(db_session, main_branch, other_vendor, 'PO-CEIL-C', quantities=(10,))


@pytest.fixture
def po_other_branch(db_session, branch_manila, vl_vendor):
    """SAME vendor, DIFFERENT branch -- the case the vendor rule alone lets through."""
    return _approved_po(db_session, branch_manila, vl_vendor, 'PO-CEIL-MNL', quantities=(10,))


class TestTheCeilingSeesTheWholePayload:
    """At SAVE. Nothing may be written before the whole submission is known to fit."""

    def test_two_lines_on_one_po_line_summing_over_open_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """Each line is within the ceiling alone; together they are not."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]

        resp = _post_rr(client, po_open_10, [(poi, 6), (poi, 6)])

        assert resp.status_code == 200
        # State first: the defect is that the receipt gets WRITTEN, 12 against 10.
        assert ReceivingReport.query.count() == 0
        assert b'between them' in resp.data
        assert b'Lines 1, 2' in resp.data          # names EVERY contributing line

    def test_exactly_at_the_ceiling_is_allowed(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """CONTROL. A receiver splitting one PO line across two delivery dates is
        legitimate; an off-by-one that rejects the boundary is a real regression."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]

        _post_rr(client, po_open_10, [(poi, 4), (poi, 6)])

        assert ReceivingReport.query.count() == 1
        rr = ReceivingReport.query.one()
        assert [li.line_number for li in rr.line_items] == [1, 2]
        assert sum(li.received_quantity for li in rr.line_items) == Decimal('10')

    def test_two_DIFFERENT_po_lines_each_within_their_own_ceiling_pass(
            self, client, db_session, admin_user, main_branch, po_two_lines):
        """CONTROL. A naive 'reject duplicate PO-line ids' fix breaks this --
        which is the normal case of receiving several lines of one order."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        a, b = po_two_lines.line_items[0], po_two_lines.line_items[1]

        _post_rr(client, po_two_lines, [(a, 10), (b, 10)])

        assert ReceivingReport.query.count() == 1
        rr = ReceivingReport.query.one()
        assert {li.purchase_order_item_id for li in rr.line_items} == {a.id, b.id}

    def test_a_single_line_over_the_ceiling_is_still_refused(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The pre-existing one-line rule survives, and reads singular."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10, [(po_open_10.line_items[0], 11)])

        assert b'Line 1: only' in resp.data and b'Lines 1' not in resp.data
        assert ReceivingReport.query.count() == 0

    def test_an_already_received_quantity_narrows_the_ceiling(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The payload total is judged against what REMAINS open, not what was ordered."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]
        first = _make_draft_rr(db_session, main_branch, po_open_10, [(poi, 7)], 'RR-CEIL-PRIOR')
        first.status = 'approved'; db_session.commit()          # 7 committed, 3 open

        resp = _post_rr(client, po_open_10, [(poi, 2), (poi, 2)])

        assert ReceivingReport.query.count() == 1               # only the prior one
        assert b'between them' in resp.data

    def test_editing_a_draft_over_the_ceiling_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The save-time guard covers the edit path, not just create."""
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]
        rr = _make_draft_rr(db_session, main_branch, po_open_10, [(poi, 3)], 'RR-CEIL-EDIT')

        resp = _post_edit(client, rr, [(poi, 6), (poi, 6)])

        db_session.expire_all()
        assert [Decimal(str(li.received_quantity)) for li in rr.line_items] == [Decimal('3')]
        assert b'between them' in resp.data


class TestApproveSeesTheWholeReceipt:
    """A draft that ALREADY holds an over-receipt must not become approvable."""

    def test_approving_two_lines_summing_over_open_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10):
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]
        rr = _make_draft_rr(db_session, main_branch, po_open_10, [(poi, 6), (poi, 6)],
                            'RR-CEIL-APPR-1')

        resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'draft'                # 12 must not commit against 10 open
        assert b'between them' in resp.data

    def test_approving_exactly_at_the_ceiling_succeeds(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """CONTROL. The approve guard must not reject the boundary either."""
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]
        rr = _make_draft_rr(db_session, main_branch, po_open_10, [(poi, 4), (poi, 6)],
                            'RR-CEIL-APPR-2')

        client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'approved'

    def test_approving_two_DIFFERENT_po_lines_succeeds(
            self, client, db_session, admin_user, main_branch, po_two_lines):
        """CONTROL. Several lines of one order still approve."""
        _login(client, admin_user, main_branch)
        a, b = po_two_lines.line_items[0], po_two_lines.line_items[1]
        rr = _make_draft_rr(db_session, main_branch, po_two_lines, [(a, 10), (b, 10)],
                            'RR-CEIL-APPR-3')

        client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'approved'


class TestOneVendorPerReceipt:
    """Every line's purchase order must belong to the receipt's vendor.

    Enforced at SAVE, not by the picker: a raw POST bypasses a picker entirely.
    """

    def test_a_line_from_another_vendor_is_refused_at_the_route(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_vendor):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10, [(po_other_vendor.line_items[0], 1)])

        assert b'one vendor' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_mixed_vendor_payload_is_refused_even_when_every_qty_fits(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_vendor):
        """The over-receipt guard would pass this; only the vendor rule refuses it."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10,
                        [(po_open_10.line_items[0], 1), (po_other_vendor.line_items[0], 1)])

        assert b'one vendor' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_two_POs_of_the_SAME_vendor_are_accepted(
            self, client, db_session, admin_user, main_branch, vl_vendor, po_open_10):
        """CONTROL. This is the whole point of the rework -- one receipt, several
        orders of ONE vendor. A per-PO check would wrongly refuse it."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        second = _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-A2', quantities=(10,))

        _post_rr(client, po_open_10,
                 [(po_open_10.line_items[0], 5), (second.line_items[0], 5)])

        assert ReceivingReport.query.count() == 1
        rr = ReceivingReport.query.one()
        assert [po.po_number for po in rr.purchase_orders] == ['PO-CEIL-A', 'PO-CEIL-A2']

    def test_approving_a_cross_vendor_draft_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_vendor):
        """A draft that predates the guard must not become approvable."""
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_open_10,
                            [(po_other_vendor.line_items[0], 1)], 'RR-CEIL-XV')

        resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        assert b'one vendor' in resp.data
        db_session.refresh(rr)
        assert rr.status == 'draft'


class TestOneBranchPerReceipt:
    """Every line's purchase order must belong to the receipt's BRANCH.

    create() still branch-checks the HEADER PO, but the header column is on its way
    out; nothing looks at the branch of the PO a LINE names. A picker filter is not
    enforcement -- same reasoning the vendor rule already gets.
    """

    def test_a_line_from_another_branch_is_refused_at_the_route(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_branch):
        """Header PO in this branch, payload line from another branch's PO of the
        SAME vendor: the vendor rule passes it, only the branch rule refuses it."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10, [(po_other_branch.line_items[0], 1)])

        assert b'one branch' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_mixed_branch_payload_is_refused_even_when_every_qty_fits(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_branch):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10,
                        [(po_open_10.line_items[0], 1), (po_other_branch.line_items[0], 1)])

        assert b'one branch' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_lines_from_two_POs_of_THIS_branch_are_accepted(
            self, client, db_session, admin_user, main_branch, vl_vendor, po_open_10):
        """CONTROL. The rule compares each PO's branch to the RECEIPT's branch --
        an over-restriction that refuses a second in-branch order breaks the
        multi-PO receipt this whole feature exists for."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        second = _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-A3', quantities=(10,))

        _post_rr(client, po_open_10,
                 [(po_open_10.line_items[0], 5), (second.line_items[0], 5)])

        assert ReceivingReport.query.count() == 1
        rr = ReceivingReport.query.one()
        assert rr.branch_id == main_branch.id
        assert {po.branch_id for po in rr.purchase_orders} == {main_branch.id}

    def test_approving_a_cross_branch_draft_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10, po_other_branch):
        """A draft that predates the guard must not become approvable."""
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_open_10,
                            [(po_other_branch.line_items[0], 1)], 'RR-CEIL-XB')

        resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        assert b'one branch' in resp.data
        db_session.refresh(rr)
        assert rr.status == 'draft'


class TestOnlyAReceivablePOMayBeReceived:
    """Every line's purchase order must still be receivable.

    po_line_open_qty ignores PO status entirely, so a cancelled order's lines read
    as FULLY OPEN forever. That was masked while the form emitted only the header
    PO's lines and create() status-checked the header; cross-PO lines make it
    routine.
    """

    def test_a_line_from_a_cancelled_po_is_refused(
            self, client, db_session, admin_user, main_branch, vl_vendor, po_open_10):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        dead = _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-DEAD', quantities=(10,))
        dead.status = 'cancelled'; db_session.commit()

        resp = _post_rr(client, po_open_10, [(dead.line_items[0], 1)])

        assert b'cancelled' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_line_from_a_draft_po_is_refused(
            self, client, db_session, admin_user, main_branch, vl_vendor, po_open_10):
        """Nobody has approved this order yet -- its lines are not receivable."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        unapproved = _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-DRAFT',
                                  quantities=(10,))
        unapproved.status = 'draft'; db_session.commit()

        resp = _post_rr(client, po_open_10, [(unapproved.line_items[0], 1)])

        assert b'is draft' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_line_from_a_partially_received_po_is_accepted(
            self, client, db_session, admin_user, main_branch, vl_vendor, po_open_10):
        """CONTROL. RECEIVABLE_PO_STATUSES holds TWO statuses. Narrowing the rule to
        'approved' alone silently blocks every second delivery against an order."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        partial = _approved_po(db_session, main_branch, vl_vendor, 'PO-CEIL-PART',
                               quantities=(10,))
        partial.status = 'partially_received'; db_session.commit()

        _post_rr(client, po_open_10,
                 [(po_open_10.line_items[0], 5), (partial.line_items[0], 5)])

        assert ReceivingReport.query.count() == 1
        rr = ReceivingReport.query.one()
        assert [po.po_number for po in rr.purchase_orders] == ['PO-CEIL-A', 'PO-CEIL-PART']

    def test_approving_a_draft_whose_po_was_cancelled_is_refused(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The order died between drafting and approval; the receipt must not commit."""
        _login(client, admin_user, main_branch)
        rr = _make_draft_rr(db_session, main_branch, po_open_10,
                            [(po_open_10.line_items[0], 1)], 'RR-CEIL-DEADPO')
        po_open_10.status = 'cancelled'; db_session.commit()

        resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)

        assert b'cancelled' in resp.data
        db_session.refresh(rr)
        assert rr.status == 'draft'


class TestARefusedSaveKeepsWhatWasTyped:
    """A refusal must hand the receiver's own numbers back.

    Moving the ceiling/vendor/branch/status checks to SAVE made bounce-with-data the
    ROUTINE path: before, the only ValueError create() could raise was "Add at least
    one received line", where nothing typed existed to lose. Re-seeding the grid from
    `{}` empties every quantity because one of them was wrong.
    """

    def test_a_refused_create_re_renders_with_the_submitted_quantities(
            self, client, db_session, admin_user, main_branch, po_two_lines):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)
        a, b = po_two_lines.line_items[0], po_two_lines.line_items[1]

        resp = _post_rr(client, po_two_lines, [(a, 3), (b, 11)])   # b busts its ceiling

        assert ReceivingReport.query.count() == 0
        body = resp.data.decode()
        assert 'const EXISTING = {};' not in body        # the whole grid, wiped
        assert f'"{a.id}": 3.0' in body                  # the GOOD line survives
        assert f'"{b.id}": 11.0' in body                 # so does the one to correct

    def test_a_refused_edit_still_re_renders_with_the_submitted_quantities(
            self, client, db_session, admin_user, main_branch, po_two_lines):
        """CONTROL on the path this fix did not mean to change -- _render_edit
        already did this, and must keep doing it."""
        _login(client, admin_user, main_branch)
        a, b = po_two_lines.line_items[0], po_two_lines.line_items[1]
        rr = _make_draft_rr(db_session, main_branch, po_two_lines, [(a, 1)], 'RR-CEIL-BOUNCE')

        resp = _post_edit(client, rr, [(a, 3), (b, 11)])

        body = resp.data.decode()
        assert f'"{a.id}": 3.0' in body and f'"{b.id}": 11.0' in body


class TestEveryReceiptCarriesAtLeastOneLine:
    """The empty-payload refusal. Untested until now: deleting it left the whole
    receiving_reports marker green while an empty POST created a receipt with no
    lines at all."""

    def test_an_empty_payload_creates_nothing(
            self, client, db_session, admin_user, main_branch, po_open_10):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10, [])

        assert b'Add at least one received line' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_payload_of_only_zero_quantities_creates_nothing(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The grid posts a row per PO line; blank ones arrive as 0 and are dropped,
        so 'nothing typed' reaches the guard as an EMPTY kept list, not an empty
        payload."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = _post_rr(client, po_open_10, [(po_open_10.line_items[0], 0)])

        assert b'Add at least one received line' in resp.data
        assert ReceivingReport.query.count() == 0


class TestAMalformedPayloadIsRefusedCleanly:
    """The lines JSON is raw client input; a refusal must not leak Python's own text.

    The routes' `except ValueError as e: flash(str(e))` is a pipe from any ValueError
    the payload path raises straight onto the receiver's screen -- and
    json.JSONDecodeError, int()'s ValueError and Decimal's are all ValueErrors. Every
    shape below therefore has to be refused in OUR words before it gets there.
    """

    def _post_raw_lines(self, client, po, lines_json, rr_number='RR-CEIL-BAD'):
        return client.post('/receiving-reports/create', data={
            'vendor_id': str(po.vendor_id), 'receipt_date': '2026-07-11', 'remarks': '',
            'rr_number': rr_number, 'lines': lines_json,
        }, follow_redirects=True)

    def test_a_non_numeric_po_line_id_gets_a_clean_refusal(
            self, client, db_session, admin_user, main_branch, po_open_10):
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = client.post('/receiving-reports/create', data={
            'vendor_id': str(po_open_10.vendor_id),
            'receipt_date': '2026-07-11', 'remarks': '', 'rr_number': 'RR-CEIL-BAD',
            'lines': json.dumps([{'purchase_order_item_id': 'abc',
                                  'received_quantity': '1'}]),
        }, follow_redirects=True)

        assert b'invalid literal' not in resp.data       # int()'s own words, flashed verbatim
        assert b'not a valid reference' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_unparseable_json_never_shows_the_python_parser_its_own_words(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """json.JSONDecodeError SUBCLASSES ValueError, so it went out through the
        clean-refusal handler and the receiver read 'Expecting property name
        enclosed in double quotes: line 1 column 2 (char 1)'."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = self._post_raw_lines(client, po_open_10, '{not json at all')

        assert resp.status_code == 200
        assert b'Expecting' not in resp.data             # the json module's own words
        assert b'char 1' not in resp.data
        assert b'could not be read' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_a_json_array_of_non_dicts_is_refused_instead_of_500ing(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """`[1, 2, 3]`: `d.get(...)` raised AttributeError inside the route's try
        (swallowed into a generic flash) and AGAIN in `_submitted_existing_lines`
        while rendering the bounce -- OUTSIDE it, for an HTTP 500. The bare
        `except Exception` hid the first occurrence and let the second escape."""
        from app.receiving_reports.models import ReceivingReport
        _login(client, admin_user, main_branch)

        resp = self._post_raw_lines(client, po_open_10, '[1, 2, 3]')

        assert resp.status_code == 200                   # not the 500 this used to be
        assert b'Line 1' in resp.data and b'not a valid reference' in resp.data
        assert b'object has no attribute' not in resp.data
        assert ReceivingReport.query.count() == 0

    def test_the_edit_path_refuses_the_same_shapes(
            self, client, db_session, admin_user, main_branch, po_open_10):
        """The edit route runs the same payload path through the same bounce
        renderer, so it owns the same two holes."""
        _login(client, admin_user, main_branch)
        poi = po_open_10.line_items[0]
        rr = _make_draft_rr(db_session, main_branch, po_open_10, [(poi, 3)], 'RR-CEIL-BADEDIT')

        for payload in ('{not json at all', '[1, 2, 3]'):
            resp = client.post(f'/receiving-reports/{rr.id}/edit', data={
                'vendor_id': str(rr.vendor_id), 'receipt_date': '2026-07-11', 'remarks': '',
                'rr_number': rr.rr_number, 'row_version': str(rr.row_version),
                'lines': payload,
            }, follow_redirects=True)

            assert resp.status_code == 200, payload
            assert b'Expecting' not in resp.data, payload
            assert b'object has no attribute' not in resp.data, payload
            db_session.expire_all()
            assert [Decimal(str(li.received_quantity)) for li in rr.line_items] == [Decimal('3')]


class TestTheErrorHandlerIsNarrowAndCoversOnlyTheWrite:
    """Two separate defects lived in `except Exception:` wrapped around the whole
    body of create()/edit().

    1. It swallowed ANY internal failure into "An error occurred creating the
       Receiving Report." -- which is how this branch's own IndexError
       (`rr.purchase_orders[0]` on transient children) presented: as a routine
       refusal, from code that was simply broken.
    2. It also wrapped `log_create` and the `return redirect(...)`. Anything raised
       AFTER `db.session.commit()` therefore told the receiver the creation had
       failed for a receipt that exists, and the handler's own
       `db.session.rollback()` cannot un-commit it.

    They need separate pins: narrowing the handler alone does not move the audit
    call out of it, and moving the audit call out alone does not narrow the handler.
    """

    def test_an_unexpected_internal_failure_is_not_dressed_up_as_a_refusal(
            self, client, db_session, admin_user, main_branch, po_open_10, monkeypatch):
        """A bug in the save path must surface as a bug, not as a refusal the
        receiver will try to correct by retyping quantities."""
        from app.receiving_reports.models import ReceivingReport
        from app.receiving_reports import views as rr_views
        _login(client, admin_user, main_branch)

        def _boom(*a, **kw):
            raise RuntimeError('a defect in the save path')
        monkeypatch.setattr(rr_views, '_parse_rr_lines', _boom)

        with pytest.raises(RuntimeError):
            _post_rr(client, po_open_10, [(po_open_10.line_items[0], 4)])

        assert ReceivingReport.query.count() == 0

    def test_an_audit_log_db_failure_never_reports_a_creation_error(
            self, client, db_session, admin_user, main_branch, po_open_10, monkeypatch):
        """log_create writes to the database, so SQLAlchemyError is exactly what it
        can raise -- and that is exactly what the (correctly narrow) handler catches.
        The protection here is that it is no longer INSIDE the handler at all."""
        from sqlalchemy.exc import SQLAlchemyError
        from app.receiving_reports.models import ReceivingReport
        from app.receiving_reports import views as rr_views
        _login(client, admin_user, main_branch)

        def _boom(*a, **kw):
            raise SQLAlchemyError('audit log unavailable')
        monkeypatch.setattr(rr_views, 'log_create', _boom)

        with pytest.raises(SQLAlchemyError):
            _post_rr(client, po_open_10, [(po_open_10.line_items[0], 4)])

        assert ReceivingReport.query.count() == 1        # it really was created
        assert ReceivingReport.query.one().status == 'draft'


class TestPayloadGuardUnit:
    """The guard itself, called directly -- the message shape the routes surface."""

    def test_it_names_every_contributing_line_not_the_one_that_tipped_it_over(
            self, db_session, main_branch, po_open_10):
        from app.receiving_reports.views import assert_payload_within_open_qty
        poi = po_open_10.line_items[0]

        with pytest.raises(ValueError) as exc:
            assert_payload_within_open_qty([(poi.id, Decimal('3')), (poi.id, Decimal('3')),
                                            (poi.id, Decimal('6'))])

        msg = str(exc.value)
        assert 'Lines 1, 2, 3' in msg and 'between them' in msg

    def test_an_unknown_po_line_id_is_refused_by_position(
            self, db_session, main_branch, po_open_10):
        from app.receiving_reports.views import assert_payload_within_open_qty

        with pytest.raises(ValueError) as exc:
            assert_payload_within_open_qty([(po_open_10.line_items[0].id, Decimal('1')),
                                            (987654, Decimal('1'))])

        assert 'Line 2' in str(exc.value)

    def test_a_po_line_with_no_purchase_order_is_refused(self, db_session, main_branch):
        """The orphan row the `poi is None` rule already refuses, one level down.

        Guarding it only inside the vendor conditional made it fail OPEN: with no
        vendor to compare against, an ownerless line sailed through to the ceiling,
        where po_line_open_qty reads it as fully open. It is refused
        UNCONDITIONALLY -- a line whose order cannot be identified can be checked
        against nothing at all."""
        from app.purchase_orders.models import PurchaseOrderItem
        from app.receiving_reports.views import assert_payload_within_open_qty
        orphan = PurchaseOrderItem(purchase_order_id=987654, line_number=1,
                                   description='Orphan', quantity=Decimal('5'),
                                   unit_price=Decimal('10'), amount=Decimal('50'))
        db_session.add(orphan); db_session.commit()

        with pytest.raises(ValueError) as exc:
            assert_payload_within_open_qty([(orphan.id, Decimal('1'))], vendor_id=None)

        assert 'Line 1' in str(exc.value)
        assert 'not attached to a purchase order' in str(exc.value)
