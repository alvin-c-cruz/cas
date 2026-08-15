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
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s every route in this file for every role, admin
    included, and each gate test below would 'pass' for the wrong reason."""
    _set_modules(db_session, products=True, purchase_orders=True)
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
