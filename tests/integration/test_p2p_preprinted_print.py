"""Pre-printed print routing and gating for the P2P documents.

Asserted on the RENDERED GET, never by posting a payload the test built itself:
a POST-contract test structurally cannot see a template that failed to render a
field (this is how BUG-DR-EDIT-FALSE-CONFLICT shipped green in this codebase).
"""
import re
from datetime import date
from decimal import Decimal

import pytest
from flask import g

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders, pytest.mark.purchase_requests, pytest.mark.receiving_reports]


def _set_modules(db_session, **states):
    from app.utils.cache_helpers import clear_module_config_cache
    for key, on in states.items():
        AppSettings.set_setting(f'module_enabled:{key}', '1' if on else '0')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture(autouse=True)
def p2p_modules_enabled(db_session):
    """All three P2P modules are optional (default_enabled=False) -- without this,
    enforce_module_access 404s every route in this file for every role, admin
    included, and each gate test below would 'pass' for the wrong reason.

    purchase_requests and receiving_reports both `depends_on: ['purchase_orders']`,
    so enabling them without purchase_orders would leave them off anyway."""
    _set_modules(db_session, products=True, purchase_orders=True,
                 purchase_requests=True, receiving_reports=True)
    yield
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()


def _login(client, user, branch):
    # Flask-Login memoises the resolved user on `g` (`g._login_user`) and only
    # calls its user_loader when that attribute is ABSENT. `g` normally dies with
    # the request -- but conftest's `app`/`db_session` fixtures keep an app context
    # pushed for the whole test, and Flask reuses an already-pushed app context for
    # the same app instead of creating a per-request one. So the cache outlives
    # every request in a test: once ANY request has run (a fixture that approves a
    # document through its own route, say), writing a new `_user_id` into the
    # session changes nothing and the next request still runs as the FIRST user.
    # Dropping the memo here is what makes this helper actually switch users; it is
    # a no-op before the first request.
    g.pop('_login_user', None)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


# ── PO fixtures ──────────────────────────────────────────────────────────────
# Copied from tests/integration/test_po_amend_ui.py (module-local there, not in
# conftest). They are built on `branch_manila`, NOT `main_branch`, so every
# _login() in this file must use branch_manila or the PO is invisible to the
# session branch and _get_po_or_404 aborts 404.

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
def approved_po(db_with_data, branch_manila, vendor_acme):
    po = _make_draft_po(branch_manila, vendor_acme, '00997')
    po.status = 'approved'
    db.session.commit()
    return po


@pytest.fixture
def cancelled_po(db_with_data, branch_manila, vendor_acme):
    """`cancelled` is a real member of VALID_PO_STATUSES and purchase_orders.cancel()
    is a live route -- this is not a hypothetical state."""
    po = _make_draft_po(branch_manila, vendor_acme, '00996')
    po.status = 'cancelled'
    db.session.commit()
    return po


def _grant_po_access(user, branch, db_session):
    """Give a non-full-access user the module permission and the PO's branch.

    Without BOTH, enforce_module_access / validate_branch_session redirect before the
    view under test ever runs, and the assertion would 'pass' on a 302 that says
    nothing about what it claims to check (memory feedback-outer-gate-masks-inner-guard)."""
    perms = user.get_book_permissions()
    perms.update({'purchase_orders': True, 'products': True})
    user.set_book_permissions(perms)
    if branch not in user.branches:
        user.branches.append(branch)
    db_session.commit()


#: The overlay canvas, asserted by its ID.
#:
#: Never assert the rendered overlay by its CLASS (`'pp-canvas' in body`): every
#: overlay hardcodes `.pp-canvas { position: relative; ... }` in its own inline
#: <style>, so that substring is present even with the canvas <div> deleted
#: outright -- the positive controls written that way could not fail. `id="ppCanvas"`
#: appears only on the element itself.
#:
#: The NEGATIVE direction (`b'pp-canvas' not in resp.data` on the standard
#: print.html) is a real assertion and deliberately keeps the class form:
#: print.html contains the string nowhere, in markup or in CSS.
CANVAS = 'id="ppCanvas"'


def _element(body, key):
    """The full opening tag of the overlay element for *key*, or None."""
    m = re.search(r'<div[^>]*data-el="%s"[^>]*>' % re.escape(key), body)
    return m.group(0) if m else None


def _body_paper(body):
    """`layout.paper` as reported by the rendered <body> TAG, or None.

    Never assert `'data-paper="X"' in body`: every overlay's inline CSS hardcodes
    `body:not([data-paper="continuous"]) .pp-margin-guide { display: none; }`, so
    that substring is present on EVERY render whatever layout.paper actually holds.
    A cross-wire assertion written that way is satisfied by the stylesheet alone --
    which is how the sibling-isolation check below stayed green against a
    receiving_reports save route wired to purchase_requests.save_layout."""
    m = re.search(r'<body[^>]*\sdata-paper="([^"]*)"', body)
    return m.group(1) if m else None


class TestTheLoginHelperSwitchesIdentity:
    """`_login` silently underwrites EVERY role assertion in this file.

    If its `g.pop('_login_user')` is dropped, Flask-Login keeps serving the first
    user who made a request (see the helper's own comment) and every gate test below
    quietly becomes an assertion about that user instead of the one it names -- a
    staff-is-refused test would 'pass' while running as admin. That mutation was held
    only incidentally, by one test written for an unrelated reason; this pins it
    directly."""

    def test_a_second_login_changes_who_the_server_serves(
            self, client, db_session, admin_user, staff_user, branch_manila,
            approved_po):
        _grant_po_access(staff_user, branch_manila, db_session)
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        # A request MUST run as admin BEFORE the switch: `g._login_user` is populated
        # by a request, so a switch asserted without one would pass against the
        # broken helper too (it is a no-op before the first request).
        _login(client, admin_user, branch_manila)
        assert 'data-can-edit="true"' in client.get(
            f'/purchase-orders/{approved_po.id}/print').data.decode()
        _login(client, staff_user, branch_manila)
        assert 'data-can-edit="false"' in client.get(
            f'/purchase-orders/{approved_po.id}/print').data.decode(), \
            '_login did not switch identity -- still served as the first user'


class TestPurchaseOrderPrintForm:

    def test_current_renders_the_standard_form(self, client, db_session, admin_user,
                                               branch_manila, approved_po):
        AppSettings.set_setting('po_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data, 'rendered the pre-printed overlay instead'
        # Positive control: the standard form really rendered.
        assert approved_po.po_number.encode() in resp.data

    def test_preprinted_renders_the_overlay_with_every_declared_field(
            self, client, db_session, admin_user, branch_manila, approved_po):
        from app.purchase_orders.preprinted_layout import FIELD_KEYS
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert CANVAS in body
        for key in FIELD_KEYS:
            assert f'data-el="{key}"' in body, f'{key} is not rendered on the overlay'

    def test_the_overlay_emits_each_field_s_declared_width(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """`w` is MANDATORY on every field of a preprinted_base document and the PO
        declaration sets 500/200/150. The SO macro this template was copied from
        emits only left/top/font-size/font-weight, so a straight copy drops `w`
        entirely: it never reaches the page, and the designer's serializer
        (boxWidth() reads el.style.width) then posts `w: undefined`, silently
        collapsing every declared width back to the default on the first save."""
        from app.purchase_orders.preprinted_layout import (
            DEFAULT_PO_PREPRINTED_LAYOUT, FIELD_KEYS)
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            expected = DEFAULT_PO_PREPRINTED_LAYOUT['fields'][key]['w']
            assert f'width:{expected}px' in tag, \
                f'{key} rendered without its declared width: {tag}'

    def test_the_overlay_loads_the_shared_designer_assets(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The shared core, not a ninth per-document copy -- and cache-busted, since
        a static asset linked with no ?v= caches indefinitely."""
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        assert 'css/preprinted_designer.css?v=1' in body
        assert 'js/preprinted_designer.js?v=1' in body
        assert 'po_preprinted_designer' not in body, 'made a ninth per-document copy'
        assert "initPreprintedDesigner({ saveUrl: '/purchase-orders/print-layout' })" in body

    def test_the_overlay_renders_the_designer_s_dom_contract(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """preprinted_designer.js names these ids as its contract with the template
        ('Do not rename any of them') and returns false without #ppCanvas /
        #editLayoutBtn -- i.e. an Edit button that silently does nothing."""
        from app.common.preprinted_base import TEXT_KEYS
        from app.purchase_orders.preprinted_layout import COLUMN_KEYS
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        for element_id in ('ppCanvas', 'editLayoutBtn', 'ppPaper', 'ppFontFamily',
                           'ppDateFormat', 'ppFieldControls', 'ppColControls',
                           'ppPageStyle'):
            assert f'id="{element_id}"' in body, f'#{element_id} is missing'
        for key in COLUMN_KEYS:
            assert f'data-col="{key}"' in body, f'column {key} is missing'
        for key in TEXT_KEYS:
            assert f'data-text="{key}"' in body, f'signatory text {key} is missing'
        # Emitted as markup, not as an autoescaped string (which would render
        # `data-signatory=&#34;1&#34;`).
        assert body.count('data-signatory="1"') == len(TEXT_KEYS)
        assert 'data-signatory=&#34;' not in body

    def test_every_field_carries_its_designer_label(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """preprinted_designer.js:248 builds each element's checkbox caption from
        `el.dataset.label || key` -- drop data-label from the field() macro and edit
        mode degrades to raw storage keys ('vendor_tin', 'vat_treatment') in the
        control panel the user is meant to read. Part of the DOM contract above,
        which was otherwise unpinned: removing data-label left the suite green."""
        from app.purchase_orders.preprinted_layout import FIELD_KEYS, FIELD_LABELS
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            # The declared label, not merely SOME data-label: a macro that emitted
            # data-label="{{ key }}" would satisfy a bare-presence assertion while
            # showing exactly the raw keys this contract exists to avoid.
            assert f'data-label="{FIELD_LABELS[key]}"' in tag, \
                f'{key} rendered without its declared designer label: {tag}'

    def test_a_non_full_access_user_is_offered_no_edit_layout_button(
            self, client, db_session, staff_user, branch_manila, approved_po):
        """`can_edit_layout` is has_full_access (admin/chief accountant) -- the same
        rule save_print_layout enforces with a 403. Not a security hole on its own,
        but a staff user shown an 'Edit Layout' button would drag a layout around and
        discover only at Save that the server refuses it. Mutating the flag to True
        left the suite green."""
        _grant_po_access(staff_user, branch_manila, db_session)
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, staff_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the overlay itself rendered -- staff may PRINT.
        assert CANVAS in body
        assert 'id="editLayoutBtn"' not in body
        assert 'data-can-edit="false"' in body

    def test_a_full_access_user_is_offered_the_edit_layout_button(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The control for the assertion above."""
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        assert 'id="editLayoutBtn"' in body
        assert 'data-can-edit="true"' in body

    @pytest.mark.parametrize('stored,printed', [
        ('inclusive', 'VAT Inclusive'),
        ('exclusive', 'VAT Exclusive'),
        ('zero_rated', 'Zero-Rated'),
    ])
    def test_vat_treatment_prints_its_human_label_not_the_stored_token(
            self, client, db_session, admin_user, branch_manila, approved_po,
            stored, printed):
        """`vat_treatment` is stored as a token ('zero_rated'), which is not
        something a supplier should read off a printed order. The overlay must
        print the same wording PurchaseOrderForm's own SelectField shows --
        form, detail and print must share the document's jargon.

        All three values are exercised on purpose: one case alone would also
        pass against a template that hardcoded that one label.
        """
        approved_po.vat_treatment = stored
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        cell = re.search(r'data-el="vat_treatment"[^>]*>([^<]*)<', body)
        assert cell, 'the vat_treatment box is not rendered on the overlay'
        assert cell.group(1).strip() == printed

    def test_hidden_refuses_and_redirects(self, client, db_session, admin_user,
                                          branch_manila, approved_po):
        AppSettings.set_setting('po_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert b'Purchase Order printing is not enabled.' in resp.data


class TestPurchaseOrderOverlayLineValues:
    """The PO overlay's line-item cells, asserted on their VALUE.

    `uom_box`, `product_bolt` and `_column_cells` are declared further down the file
    with the Purchase Requisition fixtures -- module-level fixtures and helpers are
    resolved by name at call time, not by source order, and PO/PR/RR deliberately
    share ONE set so a divergence between the three overlays shows up as a
    disagreement between tests written against identical inputs."""

    def test_the_uom_column_prints_the_unit_code_not_its_long_name(
            self, client, db_session, admin_user, branch_manila, approved_po,
            uom_box):
        """OWNER DECISION (2026-08-16): all three P2P overlays print
        `unit_of_measure.code`. The PO shipped printing `.name`, so the same order
        printed 'Carton' where PR/RR printed 'BOX'. The pre-printed uom box is 50px
        wide by default (DEFAULT_PO_PREPRINTED_LAYOUT), which a unit NAME overruns on
        real stationery -- and the PO's own on-screen surfaces already use the code
        (`PurchaseOrderItem.uom_display`, purchase_orders/models.py:259)."""
        AppSettings.set_setting('po_print_form', 'preprinted')
        approved_po.line_items[0].unit_of_measure_id = uom_box.id
        db_session.commit()
        # Guard the guard: if code and name were ever made the same word (or differed
        # only in case) the assertion below would hold against BOTH expressions.
        assert uom_box.code != uom_box.name
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        cells = _column_cells(body)
        assert cells['uom'] == [uom_box.code]
        assert uom_box.name not in cells['uom']

    def test_the_uom_column_falls_back_to_the_line_s_free_text(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The other half of the expression PR/RR use: a PO line may carry a
        free-text `uom_text` instead of a UnitOfMeasure FK (both columns are
        nullable -- purchase_orders/models.py:213-214). Without this, a template
        that dropped the fallback and emitted only `.code` would still pass the
        test above."""
        AppSettings.set_setting('po_print_form', 'preprinted')
        line = approved_po.line_items[0]
        line.unit_of_measure_id = None
        line.uom_text = 'PAIL'
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        assert _column_cells(body)['uom'] == ['PAIL']

    def test_a_line_with_neither_prints_an_empty_uom_cell(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """`_make_draft_po` builds its line with neither -- the tail of the chain
        (`or ''`) must render an empty cell, not 'None'."""
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        assert _column_cells(body)['uom'] == ['']


class TestPrintAccessGate:
    """po_print_access defaults to approved_only: a DRAFT purchase order must not
    be printable, because a draft PO sent to a supplier is a commercial problem.
    Tested in BOTH directions, and at the ROUTE -- a hidden button is not access
    control."""

    #: The route's refusal flash, asserted verbatim. The brief's own draft of this
    #: test asserted `b'<table' not in resp.data or b'not enabled' in resp.data`,
    #: which cannot pass: the redirect lands on detail.html, which DOES contain a
    #: <table> (the line items), and 'not enabled' is the *print form* message, not
    #: this one. A refusal must be proven by the refusal, not by absence.
    REFUSAL = b'A draft Purchase Order cannot be printed. Approve it first.'

    #: Every PO status that must PRINT. `VALID_PO_STATUSES` (purchase_orders/views.py:35)
    #: has five members; `draft` and `cancelled` are pinned as refusals elsewhere in this
    #: class and in TestCancelledIsNeverPrintable, and these are the other three.
    #:
    #: Only `approved` was pinned until 2026-08-16, and the gap was not theoretical: the
    #: route predicate `po.status == 'draft'` mutated to `po.status != 'approved'` left
    #: the whole suite GREEN, because nothing anywhere built a PO in either of the other
    #: two states. The button gate carries the same predicate, so the existing
    #: route-agrees-with-button tests could not see it either -- both sides would have
    #: been wrong together, consistently.
    #:
    #: `closed` is set today by purchase_billing.py:62 (a fully billed order), and it is
    #: the state a PO spends the REST OF ITS LIFE in -- refusing it would mean a buyer
    #: cannot reprint any order they have finished paying for. `partially_received` is a
    #: declared member that no code path assigns yet (PurchaseOrder.AMEND_STATUSES says
    #: so explicitly, and receiving_reports.RECEIVABLE_PO_STATUSES already accepts it),
    #: so it is pinned here to fix the behaviour BEFORE that transition ships rather than
    #: leave it to whichever branch happens to add the writer.
    PRINTABLE_STATUSES = ['approved', 'partially_received', 'closed']

    def test_a_draft_is_refused_at_the_route(self, client, db_session, admin_user,
                                             branch_manila, draft_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert self.REFUSAL in resp.data

    def test_a_draft_is_refused_even_when_the_form_is_preprinted(
            self, client, db_session, admin_user, branch_manila, draft_po):
        """The two settings are independent axes; switching the FORM must not
        reopen the ACCESS gate."""
        AppSettings.set_setting('po_print_access', 'approved_only')
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert self.REFUSAL in resp.data

    @pytest.mark.parametrize('status', PRINTABLE_STATUSES)
    def test_a_non_draft_non_cancelled_po_is_allowed(
            self, client, db_session, admin_user, branch_manila, approved_po, status):
        """The control, across the WHOLE printable axis (see PRINTABLE_STATUSES).

        Without it the gate could refuse everything and the refusal tests above would
        still pass; with only `approved` on it, the gate could refuse the two states a
        PO spends most of its life in and the suite would still pass."""
        approved_po.status = status
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        # A 200 alone would also be returned by a redirect that was not followed;
        # assert the print surface really rendered and carries no refusal.
        assert self.REFUSAL not in resp.data
        assert TestCancelledIsNeverPrintable.REFUSAL not in resp.data
        assert approved_po.po_number.encode() in resp.data

    def test_a_draft_is_allowed_when_the_gate_is_relaxed(
            self, client, db_session, admin_user, branch_manila, draft_po):
        """The other control: the gate must read the SETTING, not hardcode
        'drafts never print'."""
        AppSettings.set_setting('po_print_access', 'draft_and_approved')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print')
        assert resp.status_code == 200
        assert self.REFUSAL not in resp.data

    def test_the_print_button_is_hidden_on_a_draft_detail_page(
            self, client, db_session, admin_user, branch_manila, draft_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the page really rendered, so the absence below is not
        # a 302/404/empty body passing for a hidden button.
        assert draft_po.po_number in body
        assert f'/purchase-orders/{draft_po.id}/print' not in body

    @pytest.mark.parametrize('status', PRINTABLE_STATUSES)
    def test_the_print_button_is_shown_on_a_printable_detail_page(
            self, client, db_session, admin_user, branch_manila, approved_po, status):
        """The button gate (purchase_orders/detail.html:20-21) restates the route's
        predicate, so it is pinned across the SAME axis -- a mutation applied to both
        (they are the identical expression) must not be able to leave the pair
        agreeing with each other and wrong."""
        approved_po.status = status
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the page really rendered, so the presence below is read
        # off a real detail page and not a redirect that happens to contain the URL.
        assert approved_po.po_number in body
        assert f'/purchase-orders/{approved_po.id}/print' in body

    def test_the_print_button_is_hidden_when_the_form_is_hidden(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """Mirrors sales_invoices/detail.html:109 and accounts_payable/detail.html:111
        -- a 'hidden' print form removes the button as well as refusing the route."""
        AppSettings.set_setting('po_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}').data.decode()
        assert approved_po.po_number in body
        assert f'/purchase-orders/{approved_po.id}/print' not in body


class TestCancelledIsNeverPrintable:
    """A CANCELLED purchase order must not print at ANY setting -- unlike draft, it is
    not an axis po_print_access governs.

    Neither print surface shows status: print.html carries no status text and the
    pre-printed overlay is data-only by design (it prints onto the client's own
    stationery). So a cancelled PO on paper is indistinguishable from a live order --
    a buyer cancels PO 00998, prints it, and the supplier ships against it. Every
    sibling excludes cancelled explicitly in BOTH branches of its gate:
    sales_invoices/detail.html:110-111, accounts_payable/detail.html:112-113,
    cash_disbursements/detail.html:77-78, payroll/detail.html:80-81."""

    REFUSAL = b'A cancelled Purchase Order cannot be printed.'

    #: Both directions of the ACCESS setting, plus the unset default. The relaxed
    #: value is the load-bearing case: it is the one that used to let a cancelled PO
    #: through, and a strict-only test would pass against the broken code.
    ACCESS_VALUES = ['approved_only', 'draft_and_approved', None]

    @pytest.mark.parametrize('access', ACCESS_VALUES)
    def test_a_cancelled_po_is_refused_at_the_route(
            self, client, db_session, admin_user, branch_manila, cancelled_po, access):
        if access is not None:
            AppSettings.set_setting('po_print_access', access)
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{cancelled_po.id}/print',
                          follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert self.REFUSAL in resp.data

    @pytest.mark.parametrize('access', ACCESS_VALUES)
    def test_a_cancelled_po_is_refused_even_when_the_form_is_preprinted(
            self, client, db_session, admin_user, branch_manila, cancelled_po, access):
        """The reviewer's exact probe: po_print_form='preprinted' returned 200 with
        `pp-canvas` on a cancelled PO."""
        if access is not None:
            AppSettings.set_setting('po_print_access', access)
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{cancelled_po.id}/print',
                          follow_redirects=True)
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data
        assert self.REFUSAL in resp.data

    def test_the_cancelled_refusal_is_not_the_draft_wording(
            self, client, db_session, admin_user, branch_manila, cancelled_po):
        """'Approve it first' is wrong and unactionable for a cancelled order."""
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{cancelled_po.id}/print',
                          follow_redirects=True)
        assert TestPrintAccessGate.REFUSAL not in resp.data
        assert self.REFUSAL in resp.data

    @pytest.mark.parametrize('access', ACCESS_VALUES)
    def test_the_print_button_is_hidden_on_a_cancelled_detail_page(
            self, client, db_session, admin_user, branch_manila, cancelled_po, access):
        if access is not None:
            AppSettings.set_setting('po_print_access', access)
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{cancelled_po.id}')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the page really rendered, so the absence below is not a
        # 302/404/empty body passing for a hidden button.
        assert cancelled_po.po_number in body
        assert f'/purchase-orders/{cancelled_po.id}/print' not in body


class TestPrintAccessGateIsDefaultDeny:
    """The gate's polarity. The exemption requires an EXACT 'draft_and_approved'
    match; every other stored value -- unrecognised, stale, junk, or absent -- denies.

    The original `== 'approved_only'` spelling was fail-OPEN: any other value opened
    it (verified: a 'posted_only' left over from the shared PRINT_ACCESS_CHOICES let a
    draft PO print, 200). Every existing gate in this codebase is written the other
    way round -- sales_invoices/views.py:1401-1403, cash_disbursements/views.py:1354-1355,
    cash_receipts/views.py:1317-1318, payroll/views.py:121-122."""

    #: 'posted_only' is the realistic accident (the shared constant's value, which the
    #: PO control cannot emit but a hand-edited/seeded row could carry); the rest cover
    #: near-misses and junk. Each must DENY.
    UNRECOGNISED = ['posted_only', 'draft_and_posted', 'approved', 'draft_and_approve',
                    'DRAFT_AND_APPROVED', '', 'zzz']

    @pytest.mark.parametrize('stored', UNRECOGNISED)
    def test_an_unrecognised_stored_value_refuses_a_draft_at_the_route(
            self, client, db_session, admin_user, branch_manila, draft_po, stored):
        AppSettings.set_setting('po_print_access', stored)
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert TestPrintAccessGate.REFUSAL in resp.data

    @pytest.mark.parametrize('stored', UNRECOGNISED)
    def test_an_unrecognised_stored_value_hides_the_button(
            self, client, db_session, admin_user, branch_manila, draft_po, stored):
        """detail.html must invert identically, or the page offers a button the route
        refuses."""
        AppSettings.set_setting('po_print_access', stored)
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{draft_po.id}').data.decode()
        assert draft_po.po_number in body
        assert f'/purchase-orders/{draft_po.id}/print' not in body

    @pytest.mark.parametrize('stored', UNRECOGNISED)
    def test_an_unrecognised_stored_value_still_allows_an_approved_po(
            self, client, db_session, admin_user, branch_manila, approved_po, stored):
        """The control. Without it a gate that refused EVERYTHING -- for any stored
        value at all -- would satisfy both tests above."""
        AppSettings.set_setting('po_print_access', stored)
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 200


class TestPrintAccessDefaultWhenUnset:
    """The fail-closed DEFAULT -- the only configuration that exists in production.

    Nothing writes po_print_access today (no entry in seed_data.py:725-730 or
    demo_seed.py:156-161), and every other gate test in this file calls set_setting()
    first, so the unset path -- the one every real install runs on -- was unexercised:
    flipping either default site left 23 passed, 0 failures.

    These tests deliberately never touch the key.
    """

    def test_a_draft_is_refused_when_the_key_is_unset(
            self, client, db_session, admin_user, branch_manila, draft_po):
        """Pins the ROUTE's default (purchase_orders/views.py::print_po)."""
        assert AppSettings.get_setting('po_print_access') is None, \
            'something wrote the key -- this test no longer exercises the default'
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert TestPrintAccessGate.REFUSAL in resp.data

    def test_a_draft_is_refused_when_the_key_is_unset_and_the_form_is_preprinted(
            self, client, db_session, admin_user, branch_manila, draft_po):
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        assert AppSettings.get_setting('po_print_access') is None
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert TestPrintAccessGate.REFUSAL in resp.data

    def test_the_print_button_is_hidden_on_a_draft_when_the_key_is_unset(
            self, client, db_session, admin_user, branch_manila, draft_po):
        """Pins the SECOND default site (purchase_orders/views.py::view, which reads
        both settings for the template) -- a separate literal from the route's."""
        assert AppSettings.get_setting('po_print_access') is None
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{draft_po.id}').data.decode()
        assert draft_po.po_number in body
        assert f'/purchase-orders/{draft_po.id}/print' not in body

    def test_an_approved_po_still_prints_when_the_key_is_unset(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The control: the default is fail-CLOSED for drafts, not off for everyone."""
        assert AppSettings.get_setting('po_print_access') is None
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 200

    def test_the_print_button_is_shown_on_an_approved_po_when_the_key_is_unset(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The control for the second default site."""
        assert AppSettings.get_setting('po_print_access') is None
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}').data.decode()
        assert f'/purchase-orders/{approved_po.id}/print' in body


class TestLayoutSave:

    def test_full_access_can_save(self, client, db_session, admin_user, branch_manila):
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-orders/print-layout', json={'paper': 'letter'})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['paper'] == 'letter'

    def test_a_saved_field_width_round_trips(self, client, db_session, admin_user,
                                             branch_manila):
        """`w` must survive the save, or the width the user dragged is discarded
        server-side even once the template emits it."""
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-orders/print-layout', json={
            'fields': {'po_no': {'x': 100, 'y': 60, 'w': 250,
                                 'fontSize': 12, 'bold': True}}})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['fields']['po_no']['w'] == 250

    def test_a_staff_user_is_refused(self, client, db_session, staff_user, branch_manila):
        """Layout edits change what prints on a client's real stationery.

        The staff user is given the purchase_orders module permission and the PO's
        branch FIRST: without either, enforce_module_access / validate_branch_session
        redirect before purchase_orders.save_print_layout ever runs, and the test
        would 'pass' on a 302 that says nothing about the view's own role guard
        (memory feedback-outer-gate-masks-inner-guard)."""
        perms = staff_user.get_book_permissions()
        perms.update({'purchase_orders': True, 'products': True})
        staff_user.set_book_permissions(perms)
        if branch_manila not in staff_user.branches:
            staff_user.branches.append(branch_manila)
        db_session.commit()
        _login(client, staff_user, branch_manila)
        assert client.post('/purchase-orders/print-layout', json={}).status_code == 403


class TestBothRoutesFollowTheOptionalModuleGate:
    """purchase_orders is optional (default_enabled=False). enforce_module_access
    matches by ENDPOINT PREFIX -- the module declares `('purchase_orders.',)` --
    so both new endpoints are covered only because their names happen to start with
    it. `purchase_orders.save_print_layout` is a brand-new endpoint riding that
    coincidence, and nothing pinned it: rename the blueprint or register the layout
    route on another blueprint and both routes silently open up for a company that
    never enabled the module."""

    def test_the_print_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila, approved_po):
        _set_modules(db_session, purchase_orders=False)
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 404

    def test_the_layout_save_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila):
        """Admin -- has_full_access, so a 404 here can only be the module gate, not
        save_print_layout's own 403."""
        _set_modules(db_session, purchase_orders=False)
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-orders/print-layout', json={'paper': 'letter'})
        assert resp.status_code == 404

    def test_both_routes_are_reachable_when_the_module_is_on(
            self, client, db_session, admin_user, branch_manila, approved_po):
        """The control: the 404s above are the module gate, not two dead URLs."""
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 200
        assert client.post('/purchase-orders/print-layout',
                           json={'paper': 'letter'}).status_code == 200


class TestPoPrintFormSettingRegistration:
    """A print form nobody can select is unreachable. All three registration parts
    (SelectField, SETTINGS_KEYS, template) are proven: a `render_field` with no
    views.py entry renders fine and silently discards every save."""

    VALID_FORM_DATA = {
        'company_name': 'Acme Trading Corp.',
        'trade_name': 'Acme',
        'company_tin': '123-456-789-000',
        'tin_branch_code': '000',
        'rdo_code': '050',
        'vat_registration_type': 'VAT',
        'company_address': '123 Rizal Ave, Manila',
        'postal_code': '1000',
        'phone': '02-8123-4567',
        'email': 'info@acme.ph',
        'fiscal_year_start': '01',
        'officer_president': 'Juan Dela Cruz',
        'officer_treasurer': 'Maria Santos',
        'officer_secretary': 'Pedro Reyes',
    }

    def test_the_settings_page_renders_the_control(self, client, db_session,
                                                   admin_user, main_branch):
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="po_print_form"' in body

    def test_the_settings_post_persists_the_chosen_value(self, client, db_session,
                                                         admin_user, main_branch):
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['po_print_form'] = 'preprinted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('po_print_form') == 'preprinted'

    def test_the_saved_value_repopulates_the_control(self, client, db_session,
                                                     admin_user, main_branch):
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data.decode()
        select = re.search(r'<select[^>]*name="po_print_form".*?</select>', body, re.S)
        assert select, 'the po_print_form control is not rendered'
        # `selected` and `value=` must sit on the SAME <option>. WTForms emits them
        # in the order `selected value="..."`; asserting a hand-guessed order is how
        # a render assertion silently checks nothing (memory
        # render-assertions-miss-order-and-attributes).
        chosen = re.findall(r'<option[^>]*\bselected\b[^>]*>', select.group(0))
        assert chosen == ['<option selected value="preprinted">'], chosen

    def test_the_control_is_hidden_when_the_module_is_disabled(
            self, client, db_session, admin_user, main_branch):
        """Tied to an optional module, like so_print_form / dr_print_form
        (BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS)."""
        _set_modules(db_session, purchase_orders=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="po_print_form"' not in body
        # Positive control: the page rendered and its siblings are still there.
        assert b'name="sv_print_form"' in body


class TestPoPrintAccessSettingRegistration:
    """po_print_access shipped with NO UI control at all -- the gate existed, but the
    only way to relax it was to hand-write an app_settings row. It gets its own
    PO_PRINT_ACCESS_CHOICES rather than the shared PRINT_ACCESS_CHOICES, whose
    posted_only/draft_and_posted values carry POSTING semantics: a PO posts nothing,
    so wiring it to the shared constant would let the UI store a value the route can
    never act on.

    All three registration parts are proven separately -- a `render_field` with no
    views.py SETTINGS_KEYS entry renders fine and silently discards every save."""

    VALID_FORM_DATA = TestPoPrintFormSettingRegistration.VALID_FORM_DATA

    def test_the_settings_page_renders_the_control(self, client, db_session,
                                                   admin_user, main_branch):
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="po_print_access"' in body

    def test_the_control_offers_exactly_the_po_specific_choices(
            self, client, db_session, admin_user, main_branch):
        """Not the shared PRINT_ACCESS_CHOICES. `posted_only` in this control would be
        a fail-open-looking value the route cannot honour, and 'Posted only' is wrong
        wording for a document that never posts."""
        from app.company_settings.forms import PO_PRINT_ACCESS_CHOICES
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data.decode()
        select = re.search(r'<select[^>]*name="po_print_access".*?</select>', body, re.S)
        assert select, 'the po_print_access control is not rendered'
        options = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>',
                             select.group(0))
        assert options == PO_PRINT_ACCESS_CHOICES, options

    def test_the_shared_print_access_constant_is_untouched(self):
        """Six existing controls (APV/SI/CDV/check/CRV/payslip) render from it; the PO
        gate must not have been bought by widening what they offer."""
        from app.company_settings.forms import PRINT_ACCESS_CHOICES
        assert PRINT_ACCESS_CHOICES == [
            ('posted_only', 'Posted only'),
            ('draft_and_posted', 'Draft and posted'),
        ]

    def test_the_settings_post_persists_the_chosen_value(self, client, db_session,
                                                         admin_user, main_branch):
        """Separate from the render test on purpose: the field renders whether or not
        views.py lists it, and without the SETTINGS_KEYS entry the POST is discarded
        in silence."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['po_print_access'] = 'draft_and_approved'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSettings.get_setting('po_print_access') == 'draft_and_approved'

    def test_a_saved_value_actually_relaxes_the_route(
            self, client, db_session, admin_user, branch_manila, main_branch, draft_po):
        """End to end: the control is not decorative -- what the settings page stores
        is the exact token purchase_orders.print_po() tests for. A saved value that
        the gate cannot match is the fail-open control this decision replaced."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['po_print_access'] = 'draft_and_approved'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{draft_po.id}/print').status_code == 200

    def test_the_default_saved_value_keeps_the_route_closed(
            self, client, db_session, admin_user, branch_manila, main_branch, draft_po):
        """The control for the test above -- and the realistic case: an admin who saves
        the settings page without touching this control writes the field's default,
        which must still refuse a draft."""
        _login(client, admin_user, main_branch)
        assert client.post('/settings', data=dict(self.VALID_FORM_DATA),
                           follow_redirects=True).status_code == 200
        assert AppSettings.get_setting('po_print_access') == 'approved_only'
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert TestPrintAccessGate.REFUSAL in resp.data

    def test_the_saved_value_repopulates_the_control(self, client, db_session,
                                                     admin_user, main_branch):
        AppSettings.set_setting('po_print_access', 'draft_and_approved')
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data.decode()
        select = re.search(r'<select[^>]*name="po_print_access".*?</select>', body, re.S)
        assert select, 'the po_print_access control is not rendered'
        chosen = re.findall(r'<option[^>]*\bselected\b[^>]*>', select.group(0))
        assert chosen == ['<option selected value="draft_and_approved">'], chosen

    def test_the_control_is_hidden_when_the_module_is_disabled(
            self, client, db_session, admin_user, main_branch):
        """Gated like its po_print_form sibling
        (BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS)."""
        _set_modules(db_session, purchase_orders=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="po_print_access"' not in body
        # Positive control: the page rendered and the ungated siblings in the SAME
        # print-access grid are still there.
        assert b'name="cr_print_access"' in body
        assert b'name="sv_print_access"' in body


# -- Purchase Requisition fixtures --------------------------------------------
# Built on `branch_manila` like the PO fixtures above, so one _login() serves the
# whole file and an RR can reference a PO in the same branch.

@pytest.fixture
def uom_box(db_with_data):
    """`code` and `name` are deliberately DIFFERENT WORDS, not 'BOX'/'Box'.

    Every overlay's uom column must print `.code`; the previous name ('Box') differed
    from the code only in CASE, so `== [uom_box.code]` distinguished `.code` from
    `.name` by nothing but capitalisation -- one `|upper` or a case-insensitive
    comparison anywhere and all three assertions would go vacuous at once. 'Carton'
    shares no characters with 'BOX', so the mutation .code -> .name is unmissable."""
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure(code='BOX', name='Carton', is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def product_bolt(db_with_data, uom_box):
    from app.products.models import Product
    p = Product(code='P900', name='Hex Bolt', is_active=True,
                default_unit_of_measure_id=uom_box.id)
    db.session.add(p)
    db.session.commit()
    return p


def _make_pr(branch, product, uom, number, *, date_needed=date(2026, 8, 20),
             asap=False, status='approved'):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 5),
                         date_needed=date_needed, date_needed_asap=asap,
                         reason='Stock replenishment', status=status,
                         branch_id=branch.id)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='hex bolt 12mm', quantity=Decimal('25'),
        product_id=product.id, unit_of_measure_id=uom.id))
    db.session.add(pr)
    db.session.commit()
    return pr


@pytest.fixture
def approved_pr(db_with_data, branch_manila, product_bolt, uom_box):
    return _make_pr(branch_manila, product_bolt, uom_box, '00885')


@pytest.fixture
def asap_pr(db_with_data, branch_manila, product_bolt, uom_box):
    """`date_needed_asap` and `date_needed` are MUTUALLY EXCLUSIVE on the model --
    setting the flag clears the date (purchase_requests/models.py:80-87)."""
    return _make_pr(branch_manila, product_bolt, uom_box, '00884',
                    date_needed=None, asap=True)


@pytest.fixture
def asap_pr_with_a_stale_date(db_with_data, branch_manila, product_bolt, uom_box):
    """A requisition carrying BOTH the flag and a date.

    The model's own docstring says the exclusion is "enforced in the views, not by
    a DB constraint, because SQLite CHECK constraints here would need a table
    rebuild" -- so this row is representable, and a legacy import or a future code
    path can produce it. It is also the ONLY input that can tell the two ASAP
    branches apart: with `date_needed` already NULL, a template that dropped the
    ASAP test entirely still renders an empty box and no data-date, so every
    assertion about them would pass vacuously."""
    return _make_pr(branch_manila, product_bolt, uom_box, '00882',
                    date_needed=date(2026, 9, 30), asap=True)


def _grant_module_access(user, branch, db_session, *modules):
    """Give a non-full-access user the module permissions and the document's branch.

    Without BOTH, enforce_module_access / validate_branch_session redirect before the
    view under test ever runs, and the assertion would 'pass' on a 302 that says
    nothing about what it claims to check (memory feedback-outer-gate-masks-inner-guard)."""
    perms = user.get_book_permissions()
    perms.update({m: True for m in modules})
    user.set_book_permissions(perms)
    if branch not in user.branches:
        user.branches.append(branch)
    db_session.commit()


def _column_cells(body):
    """{column key: [cell text, ...]} for every line-item column on the overlay.

    A `data-col="x"` presence assertion is satisfied by an element that renders
    EMPTY -- which is exactly the failure these columns are prone to, since several
    of them are derived rather than stored. This pulls out the actual cell text so a
    column can be asserted on its VALUE."""
    band = body.split('class="pp-lineitems"', 1)
    assert len(band) == 2, 'the line-item band is not rendered on the overlay'
    chunks = re.split(r'data-col="([^"]+)"', band[1])
    out = {}
    for key, chunk in zip(chunks[1::2], chunks[2::2]):
        out[key] = [c.strip() for c in
                    re.findall(r'<div class="pp-cell"[^>]*>(.*?)</div>', chunk, re.S)]
    return out


def _plain_rows(body):
    """[[cell text, ...], ...] -- one list per <tbody> <tr>, for print.html's
    (the PLAIN/`current` form's) line-item table. Mirrors `_column_cells` above:
    read the RENDERED cell text, not merely whether a <td> is present, so a column
    that renders empty is caught rather than satisfying a presence check."""
    tbody = re.search(r'<tbody>(.*?)</tbody>', body, re.S)
    assert tbody, 'the line-item table body is not rendered'
    rows = re.findall(r'<tr>(.*?)</tr>', tbody.group(1), re.S)
    return [[c.strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            for row in rows]


class TestPurchaseRequisitionPrintForm:
    """`pr_print_form` routes the requisition's print surface. There is deliberately
    NO pr_print_access sibling: a requisition is an INTERNAL document -- it never
    reaches a supplier, so the commercial risk that justifies the PO's draft gate does
    not exist here. `hidden` is its off switch."""

    def test_current_renders_the_standard_form(self, client, db_session, admin_user,
                                               branch_manila, approved_pr):
        AppSettings.set_setting('pr_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-requests/{approved_pr.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data, 'rendered the pre-printed overlay instead'
        # Positive control: the standard form really rendered.
        assert approved_pr.pr_number.encode() in resp.data

    def test_the_default_is_the_standard_form(self, client, db_session, admin_user,
                                              branch_manila, approved_pr):
        """The unset key is the only configuration that exists in production today --
        nothing seeds pr_print_form, and every other test here sets it first."""
        assert AppSettings.get_setting('pr_print_form') is None, \
            'something wrote the key -- this test no longer exercises the default'
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-requests/{approved_pr.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data

    def test_preprinted_renders_the_overlay_with_every_declared_field(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        from app.purchase_requests.preprinted_layout import FIELD_KEYS
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-requests/{approved_pr.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert CANVAS in body
        for key in FIELD_KEYS:
            assert f'data-el="{key}"' in body, f'{key} is not rendered on the overlay'

    def test_the_overlay_emits_each_field_s_declared_width(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """`w` is MANDATORY on every field of a preprinted_base document and the PR
        declaration sets 500/200. The SO macro this template family was adapted from
        emits only left/top/font-size/font-weight, so a straight copy drops `w`: it
        never reaches the page, and the designer's serializer (boxWidth() reads
        el.style.width) then posts `w: undefined`, collapsing every declared width."""
        from app.purchase_requests.preprinted_layout import (
            DEFAULT_PR_PREPRINTED_LAYOUT, FIELD_KEYS)
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            expected = DEFAULT_PR_PREPRINTED_LAYOUT['fields'][key]['w']
            assert f'width:{expected}px' in tag, \
                f'{key} rendered without its declared width: {tag}'

    def test_the_overlay_loads_the_shared_designer_assets(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """The shared core, not a per-document copy -- and cache-busted, since a static
        asset linked with no ?v= caches indefinitely."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        assert 'css/preprinted_designer.css?v=1' in body
        assert 'js/preprinted_designer.js?v=1' in body
        assert 'pr_preprinted_designer' not in body, 'made a per-document copy'
        assert "initPreprintedDesigner({ saveUrl: '/purchase-requests/print-layout' })" in body

    def test_the_overlay_renders_the_designer_s_dom_contract(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """preprinted_designer.js names these ids as its contract with the template
        ('Do not rename any of them') and returns false without #ppCanvas /
        #editLayoutBtn -- i.e. an Edit button that silently does nothing."""
        from app.common.preprinted_base import TEXT_KEYS
        from app.purchase_requests.preprinted_layout import COLUMN_KEYS
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        for element_id in ('ppCanvas', 'editLayoutBtn', 'ppPaper', 'ppFontFamily',
                           'ppDateFormat', 'ppFieldControls', 'ppColControls',
                           'ppPageStyle'):
            assert f'id="{element_id}"' in body, f'#{element_id} is missing'
        for key in COLUMN_KEYS:
            assert f'data-col="{key}"' in body, f'column {key} is missing'
        for key in TEXT_KEYS:
            assert f'data-text="{key}"' in body, f'signatory text {key} is missing'
        # Emitted as markup, not as an autoescaped string (which would render
        # `data-signatory=&#34;1&#34;`).
        assert body.count('data-signatory="1"') == len(TEXT_KEYS)
        assert 'data-signatory=&#34;' not in body

    def test_every_field_carries_its_designer_label(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """preprinted_designer.js:248 builds each element's checkbox caption from
        `el.dataset.label || key` -- drop data-label and edit mode degrades to raw
        storage keys in the control panel the user is meant to read. The PR labels are
        not cosmetic: 'reason' is captioned **Note**, the module's own word since
        commit 7d1e3d9b."""
        from app.purchase_requests.preprinted_layout import FIELD_KEYS, FIELD_LABELS
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            assert f'data-label="{FIELD_LABELS[key]}"' in tag, \
                f'{key} rendered without its declared designer label: {tag}'

    def test_a_non_full_access_user_is_offered_no_edit_layout_button(
            self, client, db_session, staff_user, branch_manila, approved_pr):
        """`can_edit_layout` is has_full_access -- the same rule save_print_layout
        enforces with a 403. A staff user shown an 'Edit Layout' button would drag a
        layout around and discover only at Save that the server refuses it."""
        _grant_module_access(staff_user, branch_manila, db_session,
                             'purchase_requests', 'purchase_orders', 'products')
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, staff_user, branch_manila)
        resp = client.get(f'/purchase-requests/{approved_pr.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the overlay itself rendered -- staff may PRINT.
        assert CANVAS in body
        assert 'id="editLayoutBtn"' not in body
        assert 'data-can-edit="false"' in body

    def test_a_full_access_user_is_offered_the_edit_layout_button(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """The control for the assertion above."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        assert 'id="editLayoutBtn"' in body
        assert 'data-can-edit="true"' in body

    def test_hidden_refuses_and_redirects(self, client, db_session, admin_user,
                                          branch_manila, approved_pr):
        AppSettings.set_setting('pr_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-requests/{approved_pr.id}/print',
                          follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert b'Purchase Requisition printing is not enabled.' in resp.data

    def test_the_print_button_is_hidden_when_the_form_is_hidden(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """The page must not offer a control the route refuses -- mirrors
        purchase_orders/detail.html and sales_invoices/detail.html:109."""
        AppSettings.set_setting('pr_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}').data.decode()
        # Positive control: the page really rendered, so the absence below is not a
        # 302/404/empty body passing for a hidden button.
        assert approved_pr.pr_number in body
        assert f'/purchase-requests/{approved_pr.id}/print' not in body

    def test_the_print_button_is_shown_when_printing_is_enabled(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """The control: the absence above is the setting, not a removed button."""
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}').data.decode()
        assert f'/purchase-requests/{approved_pr.id}/print' in body


class TestPurchaseRequisitionOverlayValues:
    """The overlay is data-only -- the pre-printed stock supplies every label -- so a
    field that renders EMPTY is invisible to a presence assertion and prints as blank
    paper. Each declared field is asserted on its VALUE."""

    def _cell(self, body, key):
        m = re.search(r'data-el="%s"[^>]*>([^<]*)<' % re.escape(key), body)
        assert m, f'the {key} box is not rendered on the overlay'
        return m.group(1).strip()

    def test_each_field_prints_its_record_value(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        assert self._cell(body, 'pr_number') == '00885'
        assert self._cell(body, 'reason') == 'Stock replenishment'
        assert self._cell(body, 'branch') == branch_manila.name
        # 'long' (%d %B %Y) is the PR declaration's default dateFormat.
        assert self._cell(body, 'request_date') == '05 August 2026'
        assert self._cell(body, 'date_needed') == '20 August 2026'

    @pytest.mark.parametrize('fmt,request_date,date_needed', [
        ('long',   '05 August 2026', '20 August 2026'),
        ('medium', 'Aug 05, 2026',   'Aug 20, 2026'),
        ('us',     '08/05/2026',     '08/20/2026'),
        ('eu',     '05/08/2026',     '20/08/2026'),
        ('iso',    '2026-08-05',     '2026-08-20'),
    ])
    def test_both_dates_honour_the_designer_s_chosen_format(
            self, client, db_session, admin_user, branch_manila, approved_pr,
            fmt, request_date, date_needed):
        """The date format is a LAYOUT choice made in the designer's own dropdown
        (`layout.dateFormat` -> DATE_FORMATS), exactly as the PO overlay resolves it
        (print_preprinted.html:112). Hardcoding '%Y-%m-%d' would leave that control
        silently doing nothing on the requisition while working on the purchase order.
        Every format is exercised: one case alone also passes against a template that
        hardcoded that one."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.post('/purchase-requests/print-layout',
                           json={'dateFormat': fmt}).status_code == 200
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        assert self._cell(body, 'request_date') == request_date
        assert self._cell(body, 'date_needed') == date_needed

    def test_asap_prints_asap_instead_of_a_date(
            self, client, db_session, admin_user, branch_manila, asap_pr):
        """date_needed_asap and date_needed are mutually exclusive -- print one, never
        both, and never an empty box on a requisition that says ASAP."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{asap_pr.id}/print').data.decode()
        assert self._cell(body, 'date_needed') == 'ASAP'

    def test_asap_wins_over_a_stale_date_and_the_two_are_never_printed_together(
            self, client, db_session, admin_user, branch_manila,
            asap_pr_with_a_stale_date):
        """The flag is the answer; the leftover date must not print beside it or
        instead of it. Run against a row carrying BOTH, the only input that can tell
        the ASAP branch from an empty box."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(
            f'/purchase-requests/{asap_pr_with_a_stale_date.id}/print').data.decode()
        assert self._cell(body, 'date_needed') == 'ASAP'
        # Both renderings of the stale date: the long form is what layout.dateFormat
        # ('long', the default) would print into a visible box, the ISO form is what a
        # `data-date` attribute carries -- and the ISO form is also what every OTHER
        # dateFormat leaks through, so the long-form literal alone would miss a leak
        # on any client whose designer picked a different format.
        assert '30 September 2026' not in body
        assert '2026-09-30' not in body

    def test_an_asap_requisition_carries_no_reformattable_date(
            self, client, db_session, admin_user, branch_manila,
            asap_pr_with_a_stale_date):
        """preprinted_designer.js:511 rewrites the text of EVERY `.pp-el[data-date]`
        when the format dropdown changes. An ASAP box carrying a data-date would have
        'ASAP' silently replaced by a date -- here, the stale one the flag overrides."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(
            f'/purchase-requests/{asap_pr_with_a_stale_date.id}/print').data.decode()
        tag = _element(body, 'date_needed')
        assert tag and 'data-date' not in tag, tag
        # Control: request_date on the SAME page DOES carry one, so the absence above
        # is the ASAP branch and not a macro that never emits data-date at all.
        dated = _element(body, 'request_date')
        assert dated and 'data-date="2026-08-05"' in dated, dated

    def test_each_line_column_prints_its_record_value(
            self, client, db_session, admin_user, branch_manila, approved_pr,
            product_bolt, uom_box):
        """A line-item column that renders empty satisfies a `data-col=` presence
        assertion while printing blank paper -- assert the VALUES."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{approved_pr.id}/print').data.decode()
        cells = _column_cells(body)
        assert cells['line_number'] == ['1']
        assert cells['product'] == [f'{product_bolt.code} — {product_bolt.name}']
        assert cells['description'] == ['hex bolt 12mm']
        assert cells['quantity'] == ['25']
        assert cells['uom'] == [uom_box.code]


class TestPurchaseRequisitionLayoutSave:

    def test_full_access_can_save(self, client, db_session, admin_user, branch_manila):
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-requests/print-layout', json={'paper': 'letter'})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['paper'] == 'letter'

    def test_a_saved_field_width_round_trips(self, client, db_session, admin_user,
                                             branch_manila):
        """`w` must survive the save, or the width the user dragged is discarded
        server-side even once the template emits it."""
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-requests/print-layout', json={
            'fields': {'pr_number': {'x': 100, 'y': 60, 'w': 250,
                                     'fontSize': 12, 'bold': True}}})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['fields']['pr_number']['w'] == 250

    def test_the_saved_layout_reaches_the_overlay(self, client, db_session, admin_user,
                                                  branch_manila, approved_pr):
        """The round trip is not enough on its own: get_layout() is per-BRANCH, so a
        save keyed on one branch and a print reading another would both pass their own
        assertions and never meet."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.post('/purchase-requests/print-layout', json={
            'fields': {'pr_number': {'x': 100, 'y': 60, 'w': 250,
                                     'fontSize': 12, 'bold': True}}}).status_code == 200
        tag = _element(client.get(f'/purchase-requests/{approved_pr.id}/print')
                       .data.decode(), 'pr_number')
        assert tag and 'width:250px' in tag, tag

    def test_a_staff_user_is_refused(self, client, db_session, staff_user, branch_manila):
        """Layout edits change what prints on a client's real stationery.

        The staff user is given the module permissions and the branch FIRST: without
        either, enforce_module_access / validate_branch_session redirect before
        purchase_requests.save_print_layout ever runs, and the test would 'pass' on a
        302 that says nothing about the view's own role guard."""
        _grant_module_access(staff_user, branch_manila, db_session,
                             'purchase_requests', 'purchase_orders', 'products')
        _login(client, staff_user, branch_manila)
        assert client.post('/purchase-requests/print-layout', json={}).status_code == 403


class TestPrRoutesFollowTheOptionalModuleGate:
    """purchase_requests is optional (default_enabled=False). enforce_module_access
    matches by ENDPOINT PREFIX -- the module declares `('purchase_requests.',)` -- so
    `purchase_requests.save_print_layout` is a brand-new endpoint covered only because
    its name happens to start with it."""

    def test_the_print_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        _set_modules(db_session, purchase_requests=False)
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-requests/{approved_pr.id}/print').status_code == 404

    def test_the_layout_save_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila):
        """Admin -- has_full_access, so a 404 here can only be the module gate, not
        save_print_layout's own 403."""
        _set_modules(db_session, purchase_requests=False)
        _login(client, admin_user, branch_manila)
        assert client.post('/purchase-requests/print-layout',
                           json={'paper': 'letter'}).status_code == 404

    def test_both_routes_are_reachable_when_the_module_is_on(
            self, client, db_session, admin_user, branch_manila, approved_pr):
        """The control: the 404s above are the module gate, not two dead URLs."""
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-requests/{approved_pr.id}/print').status_code == 200
        assert client.post('/purchase-requests/print-layout',
                           json={'paper': 'letter'}).status_code == 200


class TestPrPrintFormSettingRegistration:
    """A print form nobody can select is unreachable -- the feature would be settable
    only by hand-writing an app_settings row, so no client could ever switch the
    requisition to pre-printed. All three registration parts (SelectField,
    SETTINGS_KEYS, template) are proven SEPARATELY: a `render_field` with no views.py
    entry renders fine and silently discards every save."""

    VALID_FORM_DATA = TestPoPrintFormSettingRegistration.VALID_FORM_DATA

    def test_the_settings_page_renders_the_control(self, client, db_session,
                                                   admin_user, main_branch):
        _login(client, admin_user, main_branch)
        assert b'name="pr_print_form"' in client.get('/settings').data

    def test_the_settings_post_persists_the_chosen_value(self, client, db_session,
                                                         admin_user, main_branch):
        """Separate from the render test on purpose: the field renders whether or not
        views.py lists it, and without the SETTINGS_KEYS entry the POST is discarded
        in silence."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['pr_print_form'] = 'preprinted'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        assert AppSettings.get_setting('pr_print_form') == 'preprinted'

    def test_a_saved_value_actually_routes_the_print_page(
            self, client, db_session, admin_user, branch_manila, main_branch,
            approved_pr):
        """End to end: the control is not decorative -- what the settings page stores
        is the exact token purchase_requests.print_pr() tests for."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['pr_print_form'] = 'preprinted'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        _login(client, admin_user, branch_manila)
        assert b'pp-canvas' in client.get(
            f'/purchase-requests/{approved_pr.id}/print').data

    def test_the_saved_value_repopulates_the_control(self, client, db_session,
                                                     admin_user, main_branch):
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data.decode()
        select = re.search(r'<select[^>]*name="pr_print_form".*?</select>', body, re.S)
        assert select, 'the pr_print_form control is not rendered'
        # `selected` and `value=` must sit on the SAME <option>; asserting a
        # hand-guessed attribute order is how a render assertion checks nothing
        # (memory render-assertions-miss-order-and-attributes).
        chosen = re.findall(r'<option[^>]*\bselected\b[^>]*>', select.group(0))
        assert chosen == ['<option selected value="preprinted">'], chosen

    def test_the_control_is_hidden_when_the_module_is_disabled(
            self, client, db_session, admin_user, main_branch):
        """Tied to an optional module, like so_print_form / dr_print_form /
        po_print_form (BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS)."""
        _set_modules(db_session, purchase_requests=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="pr_print_form"' not in body
        # Positive control: the page rendered and its ungated sibling is still there.
        assert b'name="sv_print_form"' in body


# -- Receiving Report fixtures ------------------------------------------------
# There is no shared `approved_rr` fixture anywhere in the suite -- the RR suites
# use module-local helpers (`_make_draft_rr` at
# tests/integration/test_receiving_reports_lifecycle.py:39 and `_draft_rr` at
# test_receiving_report_stock_posting.py:48). This is that helper, on
# `branch_manila` to match the PO fixtures above: an RR references a PO, so both
# must live in the same branch or _rr_or_404 / _get_po_or_404 abort 404.

@pytest.fixture
def rr_source_po(db_with_data, branch_manila, vendor_acme, product_bolt, uom_box):
    """The PO an RR receives against. Its line carries a product, a UoM and an
    ordered quantity, because those three are exactly what the RR overlay has to
    DERIVE -- an RR line stores none of them."""
    po = PurchaseOrder(po_number='00990', order_date=date(2026, 8, 5), status='approved',
                       vendor_id=vendor_acme.id, vendor_name=vendor_acme.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch_manila.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='hex bolt 12mm', quantity=Decimal('40'),
        unit_price=Decimal('5.00'), amount=Decimal('200.00'),
        line_total=Decimal('200.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0'),
        product_id=product_bolt.id, unit_of_measure_id=uom_box.id))
    po.calculate_totals()
    db.session.add(po)
    db.session.commit()
    return po


@pytest.fixture
def approved_rr(client, db_session, admin_user, branch_manila, rr_source_po):
    """Approved through its OWN route, not by assigning `status` -- approving an RR
    runs the open-quantity guard and post_rr_receipt(), so a hand-set status would
    print a document the application would never have produced."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    po_line = rr_source_po.line_items[0]
    rr = ReceivingReport(branch_id=branch_manila.id, rr_number='00778',
                         receipt_date=date(2026, 8, 6),
                         vendor_id=rr_source_po.vendor_id,
                         vendor_name=rr_source_po.vendor_name,
                         remarks='Received in good order', status='draft')
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=po_line.id,
        product_id=po_line.product_id, received_quantity=Decimal('15')))
    db.session.add(rr)
    db.session.commit()
    _login(client, admin_user, branch_manila)
    assert client.post(f'/receiving-reports/{rr.id}/approve',
                       follow_redirects=True).status_code == 200
    db_session.refresh(rr)
    assert rr.status == 'approved', 'the fixture RR did not approve'
    return rr


class TestReceivingReportPrintForm:
    """`rr_print_form` routes the receiving report's print surface. Like the
    requisition, and unlike the purchase order, it has NO *_print_access sibling: an
    RR is receipt evidence held internally, so `hidden` is its off switch."""

    def test_current_renders_the_standard_form(self, client, db_session, admin_user,
                                               branch_manila, approved_rr):
        AppSettings.set_setting('rr_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data, 'rendered the pre-printed overlay instead'
        # Positive control: the standard form really rendered.
        assert approved_rr.rr_number.encode() in resp.data

    def test_the_default_is_the_standard_form(self, client, db_session, admin_user,
                                              branch_manila, approved_rr):
        """The unset key is the only configuration that exists in production today --
        nothing seeds rr_print_form, and every other test here sets it first."""
        assert AppSettings.get_setting('rr_print_form') is None, \
            'something wrote the key -- this test no longer exercises the default'
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data

    def test_preprinted_renders_the_overlay_with_every_declared_field(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        from app.receiving_reports.preprinted_layout import FIELD_KEYS
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert CANVAS in body
        for key in FIELD_KEYS:
            assert f'data-el="{key}"' in body, f'{key} is not rendered on the overlay'

    def test_the_overlay_emits_each_field_s_declared_width(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """`w` is MANDATORY on every field of a preprinted_base document and the RR
        declaration sets 500/200. Without it the width reaches neither the page nor
        the designer's save payload (boxWidth() reads el.style.width)."""
        from app.receiving_reports.preprinted_layout import (
            DEFAULT_RR_PREPRINTED_LAYOUT, FIELD_KEYS)
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            expected = DEFAULT_RR_PREPRINTED_LAYOUT['fields'][key]['w']
            assert f'width:{expected}px' in tag, \
                f'{key} rendered without its declared width: {tag}'

    def test_the_overlay_loads_the_shared_designer_assets(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """The shared core, not a per-document copy -- and cache-busted, since a static
        asset linked with no ?v= caches indefinitely."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        assert 'css/preprinted_designer.css?v=1' in body
        assert 'js/preprinted_designer.js?v=1' in body
        assert 'rr_preprinted_designer' not in body, 'made a per-document copy'
        assert "initPreprintedDesigner({ saveUrl: '/receiving-reports/print-layout' })" in body

    def test_the_overlay_renders_the_designer_s_dom_contract(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """preprinted_designer.js names these ids as its contract with the template
        ('Do not rename any of them') and returns false without #ppCanvas /
        #editLayoutBtn -- i.e. an Edit button that silently does nothing."""
        from app.common.preprinted_base import TEXT_KEYS
        from app.receiving_reports.preprinted_layout import COLUMN_KEYS
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        for element_id in ('ppCanvas', 'editLayoutBtn', 'ppPaper', 'ppFontFamily',
                           'ppDateFormat', 'ppFieldControls', 'ppColControls',
                           'ppPageStyle'):
            assert f'id="{element_id}"' in body, f'#{element_id} is missing'
        for key in COLUMN_KEYS:
            assert f'data-col="{key}"' in body, f'column {key} is missing'
        for key in TEXT_KEYS:
            assert f'data-text="{key}"' in body, f'signatory text {key} is missing'
        # Emitted as markup, not as an autoescaped string (which would render
        # `data-signatory=&#34;1&#34;`).
        assert body.count('data-signatory="1"') == len(TEXT_KEYS)
        assert 'data-signatory=&#34;' not in body

    def test_every_field_carries_its_designer_label(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """preprinted_designer.js:248 builds each element's checkbox caption from
        `el.dataset.label || key` -- drop data-label and edit mode degrades to raw
        storage keys in the control panel the user is meant to read."""
        from app.receiving_reports.preprinted_layout import FIELD_KEYS, FIELD_LABELS
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        for key in FIELD_KEYS:
            tag = _element(body, key)
            assert tag, f'{key} is not rendered on the overlay'
            assert f'data-label="{FIELD_LABELS[key]}"' in tag, \
                f'{key} rendered without its declared designer label: {tag}'

    def test_a_non_full_access_user_is_offered_no_edit_layout_button(
            self, client, db_session, staff_user, branch_manila, approved_rr):
        """`can_edit_layout` is has_full_access -- the same rule save_print_layout
        enforces with a 403."""
        _grant_module_access(staff_user, branch_manila, db_session,
                             'receiving_reports', 'purchase_orders', 'products')
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, staff_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Positive control: the overlay itself rendered -- staff may PRINT.
        assert CANVAS in body
        assert 'id="editLayoutBtn"' not in body
        assert 'data-can-edit="false"' in body

    def test_a_full_access_user_is_offered_the_edit_layout_button(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """The control for the assertion above."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        assert 'id="editLayoutBtn"' in body
        assert 'data-can-edit="true"' in body

    def test_hidden_refuses_and_redirects(self, client, db_session, admin_user,
                                          branch_manila, approved_rr):
        AppSettings.set_setting('rr_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print',
                          follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert b'Receiving Report printing is not enabled.' in resp.data

    def test_the_print_button_is_hidden_when_the_form_is_hidden(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """The page must not offer a control the route refuses."""
        AppSettings.set_setting('rr_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}').data.decode()
        # Positive control: the page really rendered, so the absence below is not a
        # 302/404/empty body passing for a hidden button.
        assert approved_rr.rr_number in body
        assert f'/receiving-reports/{approved_rr.id}/print' not in body

    def test_the_print_button_is_shown_when_printing_is_enabled(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """The control: the absence above is the setting, not a removed button."""
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}').data.decode()
        assert f'/receiving-reports/{approved_rr.id}/print' in body


class TestReceivingReportOverlayValues:
    """The overlay is data-only, so an element that renders EMPTY satisfies every
    `data-el=` / `data-col=` presence assertion while printing blank paper. Half of
    the RR's line columns are DERIVED through the purchase_order_item FK, and their
    declared keys do not match the model's attribute names -- COLUMN_KEYS says
    `ordered_qty` and `uom` where the model exposes `ordered_quantity` (to_dict) and
    `uom_text` / `unit_of_measure` (receiving_reports/models.py:104-106,113-114).
    Nothing that exists today catches a typo in that mapping, so every column is
    asserted on its VALUE, taken from the referenced PO line."""

    def _cell(self, body, key):
        m = re.search(r'data-el="%s"[^>]*>([^<]*)<' % re.escape(key), body)
        assert m, f'the {key} box is not rendered on the overlay'
        return m.group(1).strip()

    def test_the_rr_line_itself_stores_none_of_the_derived_columns(self, approved_rr):
        """Why the assertions below matter: `ReceivingReportItem` stores only
        line_number, a product_id snapshot and received_quantity. A template that
        read description / ordered_qty / uom off the RR line would render three
        empty columns and still satisfy a presence assertion."""
        from app.receiving_reports.models import ReceivingReportItem
        line = approved_rr.line_items[0]
        assert not hasattr(line, 'description')
        assert not hasattr(line, 'ordered_qty')
        assert not hasattr(ReceivingReportItem, 'uom')
        # The FK the derived values must come through. nullable=False, so it is
        # always present.
        assert line.purchase_order_item is not None

    def test_each_field_prints_its_record_value(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            rr_source_po):
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        assert self._cell(body, 'rr_number') == '00778'
        assert self._cell(body, 'vendor_name') == 'ACME'
        assert self._cell(body, 'remarks') == 'Received in good order'
        # po_number is NOT a header field -- one receipt may settle several of a
        # vendor's orders, so there is no single `po_number` box any more; it
        # moved to a per-line COLUMN (see test_each_line_column_prints_its_record_value
        # and TestReceivingReportOverlayPoNumberColumn below).
        assert 'data-el="po_number"' not in body
        # 'long' (%d %B %Y) is the RR declaration's default dateFormat.
        assert self._cell(body, 'receipt_date') == '06 August 2026'

    @pytest.mark.parametrize('fmt,printed', [
        ('long',   '06 August 2026'),
        ('medium', 'Aug 06, 2026'),
        ('us',     '08/06/2026'),
        ('eu',     '06/08/2026'),
        ('iso',    '2026-08-06'),
    ])
    def test_the_receipt_date_honours_the_designer_s_chosen_format(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            fmt, printed):
        """The date format is a LAYOUT choice made in the designer's own dropdown
        (`layout.dateFormat` -> DATE_FORMATS), exactly as the PO overlay resolves it.
        Every format is exercised: one case alone also passes against a template that
        hardcoded that one."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.post('/receiving-reports/print-layout',
                           json={'dateFormat': fmt}).status_code == 200
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        assert self._cell(body, 'receipt_date') == printed

    def test_each_line_column_prints_its_record_value(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            rr_source_po, product_bolt, uom_box):
        """description, ordered_qty and uom come from the PO line; line_number and
        received_quantity from the RR line. The two ordered/received figures are
        deliberately DIFFERENT (40 vs 15) so a template that wired one column to the
        other's value fails instead of matching by coincidence."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        cells = _column_cells(body)
        assert cells['line_number'] == ['1']
        assert cells['product'] == [f'{product_bolt.code} — {product_bolt.name}']
        assert cells['description'] == ['hex bolt 12mm']
        assert cells['po_number'] == [rr_source_po.po_number]
        assert cells['ordered_qty'] == ['40']
        assert cells['received_quantity'] == ['15']
        assert cells['uom'] == [uom_box.code]

    def test_the_uom_column_falls_back_to_the_po_line_s_free_text(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            rr_source_po):
        """A PO line may carry a free-text `uom_text` instead of a UnitOfMeasure FK
        (both columns are nullable). The second branch of the mapping, unreachable
        from the test above."""
        po_line = rr_source_po.line_items[0]
        po_line.unit_of_measure_id = None
        po_line.uom_text = 'PAIL'
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
        assert _column_cells(body)['uom'] == ['PAIL']


@pytest.fixture
def rr_source_po_2(db_with_data, branch_manila, vendor_acme, product_bolt, uom_box):
    """A SECOND approved PO from the same vendor -- the multi-PO receiving case
    (Task 4): one receipt may settle several of a vendor's orders in a single
    delivery, so `po_number` has to be a per-LINE value, not a header field."""
    po = PurchaseOrder(po_number='00991', order_date=date(2026, 8, 5), status='approved',
                       vendor_id=vendor_acme.id, vendor_name=vendor_acme.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch_manila.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='hex nut 12mm', quantity=Decimal('20'),
        unit_price=Decimal('2.00'), amount=Decimal('40.00'),
        line_total=Decimal('40.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0'),
        product_id=product_bolt.id, unit_of_measure_id=uom_box.id))
    po.calculate_totals()
    db.session.add(po)
    db.session.commit()
    return po


@pytest.fixture
def multi_po_rr(db_session, branch_manila, rr_source_po, rr_source_po_2):
    """One receipt, two lines, each drawn from a DIFFERENT PO of the same vendor.

    Built directly via the ORM rather than through create()/approve() (the pattern
    `approved_rr` uses): the print route gates only on `rr_print_form` (there is no
    rr_print_access sibling), so a draft prints identically to an approved one, and
    this fixture exists to answer a rendering question, not to re-prove the
    approval workflow `approved_rr` already covers."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    poi_1 = rr_source_po.line_items[0]
    poi_2 = rr_source_po_2.line_items[0]
    rr = ReceivingReport(branch_id=branch_manila.id, rr_number='00779',
                         receipt_date=date(2026, 8, 6),
                         vendor_id=rr_source_po.vendor_id,
                         vendor_name=rr_source_po.vendor_name,
                         remarks='Two POs, one delivery', status='draft')
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=poi_1.id,
        product_id=poi_1.product_id, received_quantity=Decimal('10')))
    rr.line_items.append(ReceivingReportItem(
        line_number=2, purchase_order_item_id=poi_2.id,
        product_id=poi_2.product_id, received_quantity=Decimal('5')))
    db.session.add(rr)
    db.session.commit()
    return rr


@pytest.fixture
def rr_with_an_orphaned_line(db_session, branch_manila, rr_source_po):
    """A line whose `purchase_order_item_id` points at NO ROW at all.

    `purchase_order_item_id` is `nullable=False`, so this is the only way to make
    `ReceivingReportItem.purchase_order_item` resolve to None on a row that is
    actually PERSISTED and printed -- it is representable because SQLite FK
    enforcement is OFF app-wide (memory `sqlite-fk-off-delete-guard`), not a purely
    hypothetical state: a purged PO line, a bad legacy import, or any future
    deletion path that forgets to guard this FK would leave exactly this."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    poi = rr_source_po.line_items[0]
    rr = ReceivingReport(branch_id=branch_manila.id, rr_number='00780',
                         receipt_date=date(2026, 8, 6),
                         vendor_id=rr_source_po.vendor_id,
                         vendor_name=rr_source_po.vendor_name,
                         remarks='One good line, one orphaned', status='draft')
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=poi.id,
        product_id=poi.product_id, received_quantity=Decimal('10')))
    rr.line_items.append(ReceivingReportItem(
        line_number=2, purchase_order_item_id=999999, received_quantity=Decimal('3')))
    db.session.add(rr)
    db.session.commit()
    return rr


class TestReceivingReportOverlayPoNumberColumn:
    """`po_number` moved from a header FIELD to a per-line COLUMN (Task 5) because
    one receipt may settle several of a vendor's orders (Task 4) -- no single header
    box can print "the" PO number any more. Rendered from
    `ReceivingReportItem.po_number` (app/receiving_reports/models.py), never
    inlined in the template."""

    def test_a_multi_po_receipt_prints_each_lines_own_po_number(
            self, client, db_session, admin_user, branch_manila, multi_po_rr,
            rr_source_po, rr_source_po_2):
        """The failure this column exists to catch: a template wired to ONE PO
        (the old header FK, or a naive `rr.purchase_orders[0]`) would repeat the
        same number on every line instead of each line printing its own."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/receiving-reports/{multi_po_rr.id}/print').data.decode()
        cells = _column_cells(body)
        assert cells['po_number'] == [rr_source_po.po_number, rr_source_po_2.po_number]
        # The two POs are genuinely different numbers -- otherwise a
        # repeat-the-first-number bug would coincidentally satisfy the assertion.
        assert rr_source_po.po_number != rr_source_po_2.po_number

    def test_a_line_with_no_purchase_order_item_prints_an_empty_po_number_without_raising(
            self, client, db_session, admin_user, branch_manila,
            rr_with_an_orphaned_line, rr_source_po):
        """The control the brief calls for. The plan's own rejected snippet
        (`purchase_order_item.purchase_order.po_number`) would have raised
        `AttributeError` in real Python code -- `purchase_order` is not a real
        relationship, its backref is `order` -- and even the Jinja-inlined form of
        that mistake would only have masked the symptom (an always-empty column,
        never caught by a presence assertion), not fixed it. Here the model
        property must degrade line-by-line: line 1 (a real PO line) still prints
        its number; line 2 (orphaned) is empty -- proving the empty cell is that
        ONE line's own state, not the whole column going blank."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{rr_with_an_orphaned_line.id}/print')
        assert resp.status_code == 200
        cells = _column_cells(resp.data.decode())
        assert cells['po_number'] == [rr_source_po.po_number, '']


class TestReceivingReportPlainPrintPoNumberColumn:
    """print.html (`rr_print_form == 'current'`) gained the same PO No. column --
    Task 1 removed this template's header `PO #:` line, so without a per-line
    column the plain printout would carry no PO reference at all."""

    def test_the_plain_print_carries_a_po_number_column(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            rr_source_po):
        AppSettings.set_setting('rr_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{approved_rr.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data, 'rendered the pre-printed overlay instead'
        body = resp.data.decode()
        assert '<th>PO No.</th>' in body
        rows = _plain_rows(body)
        assert len(rows) == 1
        # Columns are #, Item, PO No., Ordered, Received (print.html's <thead> order).
        assert rows[0][2] == rr_source_po.po_number

    def test_a_multi_po_receipt_prints_each_lines_own_po_number(
            self, client, db_session, admin_user, branch_manila, multi_po_rr,
            rr_source_po, rr_source_po_2):
        AppSettings.set_setting('rr_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(
            f'/receiving-reports/{multi_po_rr.id}/print').data.decode()
        rows = _plain_rows(body)
        assert [r[2] for r in rows] == [rr_source_po.po_number, rr_source_po_2.po_number]
        assert rr_source_po.po_number != rr_source_po_2.po_number

    def test_a_line_with_no_purchase_order_item_prints_an_empty_po_number_without_raising(
            self, client, db_session, admin_user, branch_manila,
            rr_with_an_orphaned_line, rr_source_po):
        AppSettings.set_setting('rr_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/receiving-reports/{rr_with_an_orphaned_line.id}/print')
        assert resp.status_code == 200
        rows = _plain_rows(resp.data.decode())
        assert [r[2] for r in rows] == [rr_source_po.po_number, '']


class TestReceivingReportLayoutSave:

    def test_full_access_can_save(self, client, db_session, admin_user, branch_manila):
        _login(client, admin_user, branch_manila)
        resp = client.post('/receiving-reports/print-layout', json={'paper': 'letter'})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['paper'] == 'letter'

    def test_a_saved_field_width_round_trips(self, client, db_session, admin_user,
                                             branch_manila):
        """`w` must survive the save, or the width the user dragged is discarded
        server-side even once the template emits it."""
        _login(client, admin_user, branch_manila)
        resp = client.post('/receiving-reports/print-layout', json={
            'fields': {'rr_number': {'x': 100, 'y': 60, 'w': 250,
                                     'fontSize': 12, 'bold': True}}})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['fields']['rr_number']['w'] == 250

    def test_the_saved_layout_reaches_the_overlay(self, client, db_session, admin_user,
                                                  branch_manila, approved_rr):
        """The round trip is not enough on its own: get_layout() is per-BRANCH, so a
        save keyed on one branch and a print reading another would both pass their own
        assertions and never meet."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.post('/receiving-reports/print-layout', json={
            'fields': {'rr_number': {'x': 100, 'y': 60, 'w': 250,
                                     'fontSize': 12, 'bold': True}}}).status_code == 200
        tag = _element(client.get(f'/receiving-reports/{approved_rr.id}/print')
                       .data.decode(), 'rr_number')
        assert tag and 'width:250px' in tag, tag

    def _both_papers(self, client, db_session, admin_user, branch_manila,
                     approved_rr, approved_pr, save_url):
        """POST `paper: letter` to *save_url*, then read layout.paper back off BOTH
        print pages as (rr, pr).

        Read back through the PRINT PAGES, not by POSTing the sibling's save route
        and inspecting the echo: `save_layout` sanitises the SUBMITTED payload over
        the declaration's defaults and never consults what is stored, so an empty
        POST echoes the defaults whatever the mutation did. That version of this
        test passed against the cross-wired route."""
        AppSettings.set_setting('rr_print_form', 'preprinted')
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.post(save_url, json={'paper': 'letter'}).status_code == 200
        return (_body_paper(client.get(
                    f'/receiving-reports/{approved_rr.id}/print').data.decode()),
                _body_paper(client.get(
                    f'/purchase-requests/{approved_pr.id}/print').data.decode()))

    def test_an_rr_layout_save_does_not_reach_the_requisition(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            approved_pr):
        """Each declaration owns its own setting key (pr_preprinted_layout /
        rr_preprinted_layout). Wiring the RR route to purchase_requests.save_layout
        would pass every assertion above while silently overwriting the requisition's
        stationery.

        Asserted through `_body_paper` (the <body> TAG), never as a substring: both
        overlays hardcode `data-paper="continuous"` inside their own inline CSS, so
        the substring form is true on every render and pins nothing."""
        rr, pr = self._both_papers(client, db_session, admin_user, branch_manila,
                                   approved_rr, approved_pr,
                                   '/receiving-reports/print-layout')
        # Positive control: the save DID land on the receiving report.
        assert rr == 'letter', rr
        assert pr == 'continuous', 'the RR save reached the requisition layout'

    def test_a_pr_layout_save_does_not_reach_the_receiving_report(
            self, client, db_session, admin_user, branch_manila, approved_rr,
            approved_pr):
        """The mirror direction. A cross-wire is directional -- pinning only
        RR -> PR leaves purchase_requests.save_print_layout free to write
        rr_preprinted_layout, the same defect with the documents swapped."""
        rr, pr = self._both_papers(client, db_session, admin_user, branch_manila,
                                   approved_rr, approved_pr,
                                   '/purchase-requests/print-layout')
        # Positive control: the save DID land on the requisition.
        assert pr == 'letter', pr
        assert rr == 'continuous', 'the PR save reached the receiving-report layout'

    def test_a_staff_user_is_refused(self, client, db_session, staff_user, branch_manila):
        """Layout edits change what prints on a client's real stationery.

        The staff user is given the module permissions and the branch FIRST: without
        either, enforce_module_access / validate_branch_session redirect before
        receiving_reports.save_print_layout ever runs, and the test would 'pass' on a
        302 that says nothing about the view's own role guard."""
        _grant_module_access(staff_user, branch_manila, db_session,
                             'receiving_reports', 'purchase_orders', 'products')
        _login(client, staff_user, branch_manila)
        assert client.post('/receiving-reports/print-layout', json={}).status_code == 403


class TestRrRoutesFollowTheOptionalModuleGate:
    """receiving_reports is optional (default_enabled=False). enforce_module_access
    matches by ENDPOINT PREFIX -- the module declares `('receiving_reports.',)` -- so
    `receiving_reports.save_print_layout` is a brand-new endpoint covered only because
    its name happens to start with it."""

    def test_the_print_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        _set_modules(db_session, receiving_reports=False)
        _login(client, admin_user, branch_manila)
        assert client.get(f'/receiving-reports/{approved_rr.id}/print').status_code == 404

    def test_the_layout_save_route_404s_when_the_module_is_off(
            self, client, db_session, admin_user, branch_manila):
        """Admin -- has_full_access, so a 404 here can only be the module gate, not
        save_print_layout's own 403."""
        _set_modules(db_session, receiving_reports=False)
        _login(client, admin_user, branch_manila)
        assert client.post('/receiving-reports/print-layout',
                           json={'paper': 'letter'}).status_code == 404

    def test_both_routes_are_reachable_when_the_module_is_on(
            self, client, db_session, admin_user, branch_manila, approved_rr):
        """The control: the 404s above are the module gate, not two dead URLs."""
        _login(client, admin_user, branch_manila)
        assert client.get(f'/receiving-reports/{approved_rr.id}/print').status_code == 200
        assert client.post('/receiving-reports/print-layout',
                           json={'paper': 'letter'}).status_code == 200


class TestRrPrintFormSettingRegistration:
    """A print form nobody can select is unreachable -- the feature would be settable
    only by hand-writing an app_settings row, so no client could ever switch the
    receiving report to pre-printed. All three registration parts (SelectField,
    SETTINGS_KEYS, template) are proven SEPARATELY: a `render_field` with no views.py
    entry renders fine and silently discards every save."""

    VALID_FORM_DATA = TestPoPrintFormSettingRegistration.VALID_FORM_DATA

    def test_the_settings_page_renders_the_control(self, client, db_session,
                                                   admin_user, main_branch):
        _login(client, admin_user, main_branch)
        assert b'name="rr_print_form"' in client.get('/settings').data

    def test_the_settings_post_persists_the_chosen_value(self, client, db_session,
                                                         admin_user, main_branch):
        """Separate from the render test on purpose: the field renders whether or not
        views.py lists it, and without the SETTINGS_KEYS entry the POST is discarded
        in silence."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['rr_print_form'] = 'preprinted'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        assert AppSettings.get_setting('rr_print_form') == 'preprinted'

    def test_a_saved_value_actually_routes_the_print_page(
            self, client, db_session, admin_user, branch_manila, main_branch,
            approved_rr):
        """End to end: the control is not decorative -- what the settings page stores
        is the exact token receiving_reports.print_rr() tests for."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['rr_print_form'] = 'preprinted'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        _login(client, admin_user, branch_manila)
        assert b'pp-canvas' in client.get(
            f'/receiving-reports/{approved_rr.id}/print').data

    def test_the_two_controls_persist_independently(self, client, db_session,
                                                    admin_user, main_branch):
        """Both were registered in one pass; a copy-paste slip that pointed the RR
        control at the PR key would pass every single-key test above."""
        _login(client, admin_user, main_branch)
        data = dict(self.VALID_FORM_DATA)
        data['rr_print_form'] = 'preprinted'
        data['pr_print_form'] = 'hidden'
        assert client.post('/settings', data=data,
                           follow_redirects=True).status_code == 200
        assert AppSettings.get_setting('rr_print_form') == 'preprinted'
        assert AppSettings.get_setting('pr_print_form') == 'hidden'

    def test_the_saved_value_repopulates_the_control(self, client, db_session,
                                                     admin_user, main_branch):
        AppSettings.set_setting('rr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data.decode()
        select = re.search(r'<select[^>]*name="rr_print_form".*?</select>', body, re.S)
        assert select, 'the rr_print_form control is not rendered'
        # `selected` and `value=` must sit on the SAME <option>; asserting a
        # hand-guessed attribute order is how a render assertion checks nothing
        # (memory render-assertions-miss-order-and-attributes).
        chosen = re.findall(r'<option[^>]*\bselected\b[^>]*>', select.group(0))
        assert chosen == ['<option selected value="preprinted">'], chosen

    def test_the_control_is_hidden_when_the_module_is_disabled(
            self, client, db_session, admin_user, main_branch):
        """Tied to an optional module, like its po_/pr_ siblings
        (BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS)."""
        _set_modules(db_session, receiving_reports=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="rr_print_form"' not in body
        # Positive control: the page rendered, and disabling THIS module left the
        # sibling P2P control alone.
        assert b'name="pr_print_form"' in body
