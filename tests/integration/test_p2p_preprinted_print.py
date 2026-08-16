"""Pre-printed print routing and gating for the P2P documents.

Asserted on the RENDERED GET, never by posting a payload the test built itself:
a POST-contract test structurally cannot see a template that failed to render a
field (this is how BUG-DR-EDIT-FALSE-CONFLICT shipped green in this codebase).
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


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


def _element(body, key):
    """The full opening tag of the overlay element for *key*, or None."""
    m = re.search(r'<div[^>]*data-el="%s"[^>]*>' % re.escape(key), body)
    return m.group(0) if m else None


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
        assert 'pp-canvas' in body
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
        assert 'pp-canvas' in body
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

    def test_an_approved_po_is_allowed(self, client, db_session, admin_user,
                                       branch_manila, approved_po):
        """The control. Without it the gate could refuse everything and the test
        above would still pass."""
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 200

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

    def test_the_print_button_is_shown_on_an_approved_detail_page(
            self, client, db_session, admin_user, branch_manila, approved_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}').data.decode()
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
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure(code='BOX', name='Box', is_active=True)
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
        assert 'pp-canvas' in body
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
        assert 'pp-canvas' in body
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

    def test_an_asap_requisition_carries_no_reformattable_date(
            self, client, db_session, admin_user, branch_manila, asap_pr):
        """preprinted_designer.js:511 rewrites the text of EVERY `.pp-el[data-date]`
        when the format dropdown changes. An ASAP box carrying a data-date would have
        'ASAP' silently replaced by a date the record does not have."""
        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-requests/{asap_pr.id}/print').data.decode()
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
