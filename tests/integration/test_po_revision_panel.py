"""Task 6: the revision-history panel on the Purchase Order detail page.

Every assertion is made on the **rendered GET** of `/purchase-orders/<id>`. A panel
that exists in the view's context but never reaches the page is invisible to any
test that inspects the context instead of the HTML (`csrf-only-render-drops-hidden-fields`
is the same shape one layer down), so nothing here reads `resp.context`.

Two things this file exists to hold, both of which a green render test can miss:

1. **The honesty distinction.** Rev 0 arrives from two places that are NOT equally
   trustworthy -- a live capture written by `approve()` at the moment of approval
   (reason IS NULL, genuinely what was approved), and a reconstruction written by
   migration `docrev_0002` from the row's CURRENT state (reason = that migration's
   marker). Captioning a reconstruction "Original approved order" is an affirmative
   false claim about a document users make decisions on. Both directions are pinned,
   and the marker is loaded FROM the migration module rather than retyped here, so a
   reworded migration cannot leave this file asserting a string nothing writes.

2. **The query shape.** The panel is fetched in ONE query. The failure mode is not a
   wrong render -- it is a page that renders perfectly while issuing a query per
   revision. That is measured by counting the SQL the request actually executes, not
   by reading the view.
"""
import importlib.util
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


# ── the migration's own marker, never retyped ────────────────────────────────

def _reconstructed_marker():
    """The `reason` string migration docrev_0002 actually writes for a backfilled
    Rev 0, read out of the migration module itself.

    Loaded rather than copied on purpose: a literal here would keep passing after
    the migration reworded its marker, and the test would then be asserting a
    sentence no row in any database contains. `migrations/versions/` is not a
    package, hence spec_from_file_location.
    """
    path = (Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
            / 'docrev_0002_backfill_po_rev0.py')
    assert path.exists(), f'the PO Rev 0 backfill migration moved: {path}'
    spec = importlib.util.spec_from_file_location('_docrev_0002_for_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    marker = mod.RECONSTRUCTED
    assert marker and 'reconstructed' in marker.lower(), (
        'docrev_0002.RECONSTRUCTED no longer reads as a reconstruction disclosure')
    return marker


RECONSTRUCTED = _reconstructed_marker()

#: What the page may say ONLY of a Rev 0 that was captured live at approval.
_ORIGINAL_CAPTION = 'Original approved order'


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s the route for every role, admin included."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    """Direct-session login -- conftest's login_user posts through /login, which
    does not select a branch, and the branch picker would then swallow every GET."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture(autouse=True)
def logged_in(client, admin_user, branch_manila):
    _login(client, admin_user, branch_manila)


@pytest.fixture
def vendor_acme(db_with_data):
    from app.vendors.models import Vendor
    v = Vendor(code='V900', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v)
    db.session.commit()
    return v


def _make_po(branch, vendor, number, status='approved'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 5), status=status,
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
def approved_po(db_with_data, branch_manila, vendor_acme):
    return _make_po(branch_manila, vendor_acme, '00997')


def _rev(po, number, reason=None, user=None, when=None, authorizing_reference=None,
         document_type=None):
    """Insert one revision row directly.

    Written straight to the table rather than through approve()/amend() because
    this file is about RENDERING revisions, and driving the real routes would both
    cache a user on `g` and make it impossible to pin an exact timestamp.
    `amended_at` is passed explicitly for the same reason.
    """
    r = DocumentRevision(
        document_type=document_type or po.DOCUMENT_TYPE,
        document_id=po.id,
        revision_number=number,
        snapshot_json='{"header": {}, "lines": []}',
        reason=reason,
        authorizing_reference=authorizing_reference,
        amended_by_id=user.id if user else None,
        amended_at=when or datetime(2026, 8, 9, 9, 0, 0),
        branch_id=po.branch_id)
    db.session.add(r)
    db.session.commit()
    return r


def _detail(client, po):
    resp = client.get(f'/purchase-orders/{po.id}')
    assert resp.status_code == 200
    return resp.data.decode()


@contextmanager
def _captured_sql():
    """Every SQL statement the enclosed block executes, in order.

    `expire_all()` first, and it is load-bearing rather than tidiness. Under the
    test client the request runs on the SAME session the fixtures built the rows
    in, so every User is already in its identity map -- a lazy `rev.amended_by`
    then resolves with NO SQL at all, and an N+1 that costs a query per revision
    in production is completely invisible here. Verified: without this line,
    deleting the view's `joinedload` changed nothing (13 passed, 51 statements at
    1 revision and 51 at 6). Expiring reproduces what production does on every
    request -- a fresh session that must actually go to the database.
    """
    stmts = []
    db.session.expire_all()
    engine = db.engine

    def _rec(conn, cursor, statement, parameters, context, executemany):
        stmts.append(statement)

    event.listen(engine, 'before_cursor_execute', _rec)
    try:
        yield stmts
    finally:
        event.remove(engine, 'before_cursor_execute', _rec)


def _hits(stmts, table):
    return [s for s in stmts if re.search(r'\bFROM\s+' + table + r'\b', s, re.I)]


#: Opening tag of one revision entry.
#:
#: Keyed on `data-revision`, NOT on the class attribute. The first version of this
#: helper matched `'<div class="so-rev '` -- including a trailing space that exists
#: only because the template writes `class="so-rev {% if %}so-rev-original{% endif %}"`.
#: A behaviour-IDENTICAL tidy of that attribute (moving the space inside the `{% if %}`)
#: made `_entries()` return only the Rev 0 entries, and two tests then failed blaming
#: the panel for a bug in this helper. Matching on the class prefix without the space
#: is not an option either: `<div class="so-rev` is also a prefix of this entry's own
#: `so-rev-head` and `so-rev-meta` children. `data-revision` exists to be a stable
#: handle and carries the revision number, so it survives any restyling -- including
#: the `.so-rev*` -> `.doc-rev*` sweep the panel's own comment contemplates.
_ENTRY_OPEN = '<div data-revision="'


def _entries(html):
    """The rendered revision entries, each as its own balanced `<div>` block.

    Written instead of the obvious `html[html.index('Revision history'):]` because
    that slice runs to the END OF THE PAGE, and everything after the panel -- the
    Cancel PO form, the modal -- embeds the PO's id in its action URL. Two POs
    therefore differ in that slice no matter what the panel says, which made the
    live-vs-reconstructed comparison below pass while proving nothing (verified:
    it survived the mutation that captions a reconstruction as the original).
    A depth-counting walk keeps the comparison to the entries themselves.
    """
    out, i = [], 0
    while True:
        start = html.find(_ENTRY_OPEN, i)
        if start == -1:
            return out
        depth, j = 0, start
        while True:
            nxt_open = html.find('<div', j)
            nxt_close = html.find('</div>', j)
            assert nxt_close != -1, 'unbalanced revision entry markup'
            if nxt_open != -1 and nxt_open < nxt_close:
                depth += 1
                j = nxt_open + len('<div')
            else:
                depth -= 1
                j = nxt_close + len('</div>')
                if depth == 0:
                    break
        out.append(html[start:j])
        i = j


def _entry(html, number):
    """The one rendered entry for revision *number*, by its stable handle."""
    matches = [e for e in _entries(html)
               if e.startswith('%s%d"' % (_ENTRY_OPEN, number))]
    assert len(matches) == 1, (
        'expected exactly one entry for Rev %d, found %d' % (number, len(matches)))
    return matches[0]


# ── the panel lists every revision ───────────────────────────────────────────

class TestThePanelListsEveryRevision:

    def test_every_revision_gets_its_own_entry_newest_first(
            self, client, approved_po, admin_user):
        """Three revisions -> three entries, in descending revision order.

        The count matters as much as the presence: a panel that renders only the
        latest revision, or only Rev 0, still shows the words "Revision history"
        and still shows a "Rev" heading. Positions are compared rather than mere
        membership so an ascending or unordered list is a failure -- the newest
        amendment is the one a reader needs first.
        """
        _rev(approved_po, 0, user=admin_user)
        _rev(approved_po, 1, reason='vendor corrected the quantity', user=admin_user)
        _rev(approved_po, 2, reason='delivery site changed to Cebu', user=admin_user)

        html = _detail(client, approved_po)

        assert len(_entries(html)) == 3, 'one rendered entry per revision'
        assert html.count('Rev 0') == 1, 'Rev 0 must appear exactly once'
        assert html.count('Rev 1') == 1, 'Rev 1 must appear exactly once'
        assert html.count('Rev 2') == 1, 'Rev 2 must appear exactly once'
        assert html.index('Rev 2') < html.index('Rev 1') < html.index('Rev 0'), (
            'revisions must be listed newest first')

    def test_only_this_documents_revisions_are_listed(
            self, client, approved_po, admin_user):
        """`document_id` is a plain Integer pointing at eight different tables, so
        id 1 of a Sales Order and id 1 of a Purchase Order collide unless the query
        filters on `document_type` too. A revision belonging to another document
        type with the same id must not appear on this page."""
        _rev(approved_po, 0, user=admin_user)
        _rev(approved_po, 1, reason='the PO reason, which belongs here',
             user=admin_user)
        _rev(approved_po, 5, reason='a SALES ORDER reason, which does not',
             user=admin_user, document_type='sales_orders')

        html = _detail(client, approved_po)

        assert 'the PO reason, which belongs here' in html
        assert 'a SALES ORDER reason, which does not' not in html, (
            'a revision of a different document type with the same id leaked in')
        assert 'Rev 5' not in html

    def test_a_document_whose_baseline_slot_is_empty_renders_honestly(
            self, client, approved_po, admin_user):
        """M2's user-visible half: an amendment of a document that has no Rev 0
        is numbered 1, and the baseline slot is left empty rather than filled with
        post-change state (see tests/unit/test_amendment_service.py).

        The page must therefore show a panel that starts at Rev 1 and claims
        nothing about an original it does not have. The absence of Rev 0 IS the
        honest statement: no capture of the approved document exists.
        """
        _rev(approved_po, 1, reason='vendor corrected the quantity', user=admin_user)

        html = _detail(client, approved_po)

        assert len(_entries(html)) == 1
        assert 'Rev 1' in html and 'Rev 0' not in html
        assert 'vendor corrected the quantity' in html
        assert _ORIGINAL_CAPTION not in html, (
            'the panel claimed an original approved order for a document that has '
            'no baseline revision')

    def test_a_po_with_no_revisions_shows_no_panel(self, client, approved_po):
        """Absence, paired with a positive control: the page itself rendered."""
        html = _detail(client, approved_po)
        assert approved_po.po_number in html, 'positive control -- the page rendered'
        assert 'Revision history' not in html
        assert 'Rev 0' not in html
        assert _entries(html) == []


# ── what each entry says ─────────────────────────────────────────────────────

class TestWhatEachEntrySays:

    def test_the_amendment_reason_is_shown_verbatim(
            self, client, approved_po, admin_user):
        """The reason is the only record of WHY an approved document changed. A
        panel that lists revisions without it is a list of dates."""
        _rev(approved_po, 0, user=admin_user)
        _rev(approved_po, 1, reason='vendor corrected the quantity', user=admin_user)
        _rev(approved_po, 2, reason='delivery site changed to Cebu', user=admin_user)

        html = _detail(client, approved_po)

        assert 'vendor corrected the quantity' in html
        assert 'delivery site changed to Cebu' in html

    def test_the_amending_user_is_named(self, client, approved_po, accountant_user):
        """Scoped to the panel, and NOT the admin.

        Asserted against the whole page with `admin_user` this test passed before
        the panel existed at all: the detail page already prints "Created by
        admin" in its footer. The amender here is a DIFFERENT user from the PO's
        creator, and only the panel slice is searched, so the assertion can only
        be satisfied by the revision entry itself.
        """
        _rev(approved_po, 0, user=accountant_user)
        _rev(approved_po, 1, reason='vendor corrected the quantity',
             user=accountant_user)

        entries = _entries(_detail(client, approved_po))

        assert len(entries) == 2
        assert all(accountant_user.username in e for e in entries)

    def test_a_revision_with_no_recorded_user_does_not_render_none(
            self, client, approved_po):
        """A backfilled Rev 0 has `amended_by_id` NULL -- there was no user. The
        cell must not render the string "None", which is what an unguarded
        `{{ rev.amended_by }}` emits."""
        _rev(approved_po, 0, reason=RECONSTRUCTED, user=None)

        entry, = _entries(_detail(client, approved_po))

        assert 'None' not in entry, (
            'a revision with no recorded user rendered the literal "None"')
        assert 'system' in entry

    def test_the_authorizing_reference_is_shown_when_present(
            self, client, approved_po, admin_user):
        """F3 (Task 6 review): RESERVED, deliberately, for slice 3.

        No production code path can produce this row today. The column exists
        (`DocumentRevision.authorizing_reference`, migration docrev_0001), the
        service accepts it as a kwarg, and nothing passes one:
        `PurchaseOrderAmendForm` has no such field on purpose (forms.py:53-56 --
        there is no PO analogue of SalesOrderAmendForm's `authorizing_po_number`).
        The rows below are inserted by this test, and only by this test.

        It is kept rather than deleted because the SO already has the field and
        slices 3-5 migrate the remaining seven document types onto this shared
        panel; the render exists so that the first document type to carry one does
        not have to rediscover it. Deleting the render would be a two-line change;
        deleting it silently, and finding out in slice 3, would not.

        Read as a spec, not as a regression test: it pins that the panel CAN show
        an authorising reference, not that any PO ever has one.
        """
        _rev(approved_po, 0, user=admin_user)
        _rev(approved_po, 1, reason='vendor corrected the quantity', user=admin_user,
             authorizing_reference='VENDOR-LETTER-2026-08-09')

        html = _detail(client, approved_po)

        assert 'VENDOR-LETTER-2026-08-09' in html


# ── the honesty distinction: live Rev 0 vs reconstructed Rev 0 ───────────────

class TestALiveRev0IsNotAReconstructedOne:
    """The two Rev 0 sources, pinned in both directions.

    Each test is the other's positive control, which is what stops either from
    passing vacuously: whatever the page says of a live Rev 0 it must NOT say of a
    reconstructed one, and vice versa.
    """

    def test_a_live_rev_0_is_captioned_as_the_original_capture(
            self, client, approved_po, admin_user):
        _rev(approved_po, 0, reason=None, user=admin_user)

        html = _detail(client, approved_po)

        assert _ORIGINAL_CAPTION in html, (
            'a Rev 0 captured live at approval IS the original approved document '
            'and should say so')
        assert RECONSTRUCTED not in html, (
            'a live capture must not be disclaimed as a reconstruction')

    def test_a_reconstructed_rev_0_discloses_that_it_is_not_an_original_capture(
            self, client, approved_po):
        """The single assertion this whole task exists for.

        A backfilled Rev 0 was rebuilt by migration docrev_0002 from the row's
        CURRENT state; if the PO was edited while still draft, it is NOT what was
        approved. Showing it under the same caption as a live capture is an
        affirmative false claim about a document users make decisions on.
        """
        _rev(approved_po, 0, reason=RECONSTRUCTED, user=None)

        html = _detail(client, approved_po)

        assert RECONSTRUCTED in html, (
            "the reconstruction disclosure the migration wrote into the row never "
            "reached the page -- the panel is presenting a rebuild as if it were "
            "captured at approval")
        assert _ORIGINAL_CAPTION not in html, (
            'a reconstructed Rev 0 was captioned as the original approved order')

    def test_a_reason_less_amendment_is_not_captioned_as_the_original(
            self, client, approved_po, admin_user):
        """F1 (Task 6 review). The caption's `rev.number == 0` guard was unpinned:
        mutating `{% elif rev.number == 0 %}` to `{% else %}` left all 13 tests
        green, and under that one-token change EVERY reason-less revision claims
        to be the original approved order -- including an amendment.

        It escaped because the fixture population was degenerate: every revision
        the file created with `number >= 1` also carried a reason, and every
        reason-less revision it created was Rev 0. This is the missing cell of
        that table.

        `write_revision(doc, user_id)`'s `reason` defaults to None and is
        validated nowhere in the service (the >= 10-char rule lives only in
        PurchaseOrderAmendForm), so one slice-3 route calling it without a reason
        is all it takes.
        """
        _rev(approved_po, 0, reason=None, user=admin_user)
        _rev(approved_po, 1, reason=None, user=admin_user)

        html = _detail(client, approved_po)

        assert html.count(_ORIGINAL_CAPTION) == 1, (
            'a reason-less AMENDMENT was captioned as the original approved order')
        assert _ORIGINAL_CAPTION in _entry(html, 0)
        assert _ORIGINAL_CAPTION not in _entry(html, 1)

    def test_the_two_rev_0_kinds_render_differently_on_the_same_page_shape(
            self, client, db_with_data, branch_manila, vendor_acme, admin_user):
        """Two Rev 0 rows identical in EVERY field except `reason`.

        Same revision number, same amender, same timestamp -- so the rendered
        entries can differ only because of where the Rev 0 came from. The
        real-world backfilled row also has a null amender, but holding that
        constant here is the point: with the user and the clock varying too, this
        comparison passes even when the caption is wrong, which is precisely the
        degenerate-fixture failure this slice has already paid for twice.
        """
        live_po = _make_po(branch_manila, vendor_acme, '00801')
        back_po = _make_po(branch_manila, vendor_acme, '00802')
        when = datetime(2026, 8, 9, 9, 0, 0)
        _rev(live_po, 0, reason=None, user=admin_user, when=when)
        _rev(back_po, 0, reason=RECONSTRUCTED, user=admin_user, when=when)

        live_entry, = _entries(_detail(client, live_po))
        back_entry, = _entries(_detail(client, back_po))

        assert live_entry != back_entry, (
            'a live Rev 0 and a reconstructed Rev 0 render identically -- the '
            'distinction exists in the database and is lost on the page')


# ── an empty-string reason is not a reason ───────────────────────────────────

class TestAnEmptyStringReasonIsTreatedAsAbsent:
    """F2 (Task 6 review), asked for by the Task 6 brief by name and never written.

    Mutating `{% if rev.reason %}` to `{% if rev.reason is not none %}` left all 13
    tests green, so nothing pinned which of the two the panel means.

    THE DECISION, recorded here because it is a judgement and not a fact: `''` is
    treated as ABSENT, i.e. today's truthiness test is correct and unchanged. An
    empty string carries no information -- there is nothing to quote, and rendering
    a pair of empty quotation marks tells a reader only that somebody's software
    lost something. `''` is also not reachable from `amend()` (DataRequired +
    Length(min=10), and DataRequired rejects whitespace-only), so the only way to
    produce one is a direct service call, where "no reason given" is exactly what
    happened. Both halves are pinned below so the choice cannot be flipped silently
    in either direction.
    """

    def test_an_empty_reason_on_rev_0_still_reads_as_the_original_capture(
            self, client, approved_po, admin_user):
        _rev(approved_po, 0, reason='', user=admin_user)

        entry = _entry(_detail(client, approved_po), 0)

        assert _ORIGINAL_CAPTION in entry, (
            "an empty string is not a reason -- a Rev 0 carrying one is still a "
            "baseline with nothing recorded against it")
        assert '&ldquo;' not in entry, (
            'the panel rendered an empty pair of quotation marks')

    def test_an_empty_reason_on_an_amendment_renders_no_meta_line(
            self, client, approved_po, admin_user):
        """The other half, and the one that keeps the caption honest: an
        amendment with an empty reason must NOT fall through to the Rev 0 caption
        either. It gets a head line and nothing else -- no quotation marks, and no
        claim about being the original."""
        _rev(approved_po, 0, reason=None, user=admin_user)
        _rev(approved_po, 1, reason='', user=admin_user)

        entry = _entry(_detail(client, approved_po), 1)

        assert '&ldquo;' not in entry, (
            'the panel rendered an empty pair of quotation marks')
        assert 'so-rev-meta' not in entry, (
            'an amendment with nothing recorded rendered a meta line anyway')
        assert _ORIGINAL_CAPTION not in entry


# ── timestamps ───────────────────────────────────────────────────────────────

class TestTheTimestampIsPhTime:

    def test_the_stored_ph_timestamp_is_rendered_as_stored_not_shifted(
            self, client, approved_po, admin_user):
        """`amended_at` defaults to `ph_now()` and lands on disk as a NAIVE
        PH-local datetime (no offset suffix -- see docrev_0002's `_ph_timestamp`).
        It is therefore already Philippine time, and must be formatted directly.

        Running it through `format_ph_datetime` would be the tempting mistake:
        that helper assumes a naive value is UTC and adds 8 hours, which turns an
        evening amendment into the NEXT DAY. The stored value below is 20:30 on
        Aug 9; a +8 shift makes it 04:30 on Aug 10, so both the wrong date and the
        wrong hour are asserted absent.
        """
        _rev(approved_po, 0, user=admin_user,
             when=datetime(2026, 8, 9, 20, 30, 0))

        entry, = _entries(_detail(client, approved_po))

        assert 'Aug 09, 2026' in entry, 'the amendment date is missing or shifted'
        assert '20:30' in entry, 'the amendment time is missing or shifted'
        assert 'Aug 10, 2026' not in entry, (
            'the timestamp was shifted a day forward -- a naive PH-local value was '
            'treated as UTC')
        assert '04:30' not in entry


# ── query shape ──────────────────────────────────────────────────────────────

class TestTheRevisionsAreFetchedInOneQuery:

    def test_three_revisions_cost_exactly_one_revisions_query(
            self, client, approved_po, admin_user):
        """Measured, not read: every statement the request executes is captured and
        the ones selecting from `document_revisions` are counted.

        Three revisions is the point -- with one revision a per-revision
        implementation issues one query too, and the test would pass on a shape it
        was written to reject.
        """
        _rev(approved_po, 0, user=admin_user)
        _rev(approved_po, 1, reason='vendor corrected the quantity', user=admin_user)
        _rev(approved_po, 2, reason='delivery site changed to Cebu', user=admin_user)

        _detail(client, approved_po)  # warm every memoized helper first
        with _captured_sql() as stmts:
            _detail(client, approved_po)

        rev_queries = _hits(stmts, 'document_revisions')
        assert len(rev_queries) == 1, (
            'the revision panel issued %d queries against document_revisions, not '
            'one:\n%s' % (len(rev_queries), '\n'.join(rev_queries)))

    def test_the_page_costs_the_same_number_of_queries_at_one_and_five_revisions(
            self, client, db_with_data, branch_manila, vendor_acme, admin_user,
            accountant_user, staff_user):
        """The N+1 this panel is most likely to grow is not the revision query at
        all -- it is `rev.amended_by`, one lazy User load per row. Counting total
        statements for an otherwise identical page at 1 and at 5 revisions catches
        any per-revision cost, whichever table it lands on.

        The five revisions are spread across three different users so a shared
        identity map cannot silently satisfy the lazy loads.

        F4 (Task 6 review): the count comparison alone rests entirely on
        `_captured_sql`'s `expire_all()`, one undefended line in a TEST helper --
        delete it as "cleanup" and the whole guard silently disarms (verified:
        deleting it, and deleting it together with the view's `joinedload`, both
        left 13/13 green). So the MECHANISM is asserted as well as the cost. The
        join assertion holds whatever happens to `expire_all()`, and dies the
        moment the `joinedload` goes -- which is the change that actually
        reintroduces the N+1 in production.
        """
        small = _make_po(branch_manila, vendor_acme, '00701')
        large = _make_po(branch_manila, vendor_acme, '00702')
        _rev(small, 0, user=admin_user)
        users = [admin_user, accountant_user, staff_user, accountant_user, admin_user]
        _rev(large, 0, user=admin_user)
        for n, u in enumerate(users, start=1):
            _rev(large, n, reason='amendment number %d for the record' % n, user=u)

        _detail(client, small); _detail(client, large)  # warm caches
        with _captured_sql() as small_stmts:
            _detail(client, small)
        with _captured_sql() as large_stmts:
            _detail(client, large)

        assert len(large_stmts) == len(small_stmts), (
            'a PO with 6 revisions costs %d statements against %d for a PO with 1 '
            '-- the panel is paying per revision.\nextra:\n%s'
            % (len(large_stmts), len(small_stmts),
               '\n'.join(large_stmts[len(small_stmts):])))
        assert any(re.search(r'LEFT OUTER JOIN\s+users', s, re.I)
                   for s in _hits(large_stmts, 'document_revisions')), (
            'the revisions query no longer joins users -- `rev.amended_by` is a '
            'lazy load again, one query per revision in production. The count '
            'assertion above cannot see this on its own: it depends on '
            '_captured_sql expiring the identity map first.\n%s'
            % '\n'.join(_hits(large_stmts, 'document_revisions')))
