"""
Building an AP voucher's Notes (Particulars) from the PO/RR pulled into it.

The AP form refuses to save with Notes empty, so today every voucher's
particulars are retyped by hand even though the pulled documents already carry
every fact the text states. This builds the sentence PhilGen actually writes.

The convention is MEASURED, not invented. Across the 1353 particulars in
PhilGen's legacy disbursement register: 44% open "PAYMENT FOR THE ...", 30%
cite a PO, 18% an SI, 12% an RR, and the shape is consistently

    PAYMENT FOR THE PURCHASE OF <what>
    FOR <purpose> USE
    -PO NO.00742, SI NO.403159, RR - OCTOBER 2025

with the reference line repeated per source document on multi-PO vouchers.

Two rules the tests below pin hard, both of them "never invent":
  * nothing pulled -> empty string, NOT a bare "PAYMENT FOR THE PURCHASE OF"
  * no purpose / no invoice number -> that part is omitted, not filled with a
    placeholder. Every PO that exists today has no purpose (popurp_0001 shipped
    with no backfill), so the no-purpose path is the COMMON case.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts_payable.particulars import build_particulars
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem

pytestmark = [pytest.mark.unit, pytest.mark.accounts_payable]


def _po(branch, number, purpose=None, items=('CHLORINE',), status='approved'):
    po = PurchaseOrder(branch_id=branch.id, po_number=number, vendor_name='Acme',
                       status=status, purpose=purpose, order_date=date(2026, 8, 1))
    for n, what in enumerate(items, start=1):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description=what, quantity=Decimal('1'),
            unit_price=Decimal('10'), amount=Decimal('10')))
    db.session.add(po)
    db.session.commit()
    return po


def _rr(branch, number, po, vendor, receipt_date=date(2026, 8, 19)):
    # vendor_id is NOT NULL since the RR went vendor-first (rrmulti_0001) -- a
    # receipt without one cannot be inserted at all.
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, vendor_id=vendor.id,
                         vendor_name=vendor.name, status='approved',
                         receipt_date=receipt_date)
    for n, poi in enumerate(po.line_items, start=1):
        rr.line_items.append(ReceivingReportItem(
            line_number=n, purchase_order_item_id=poi.id,
            received_quantity=Decimal('1')))
    db.session.add(rr)
    db.session.commit()
    return rr


def _enable_billing_modules(db_session):
    """The PO/RR pull section -- and so the Regenerate button -- is gated on the
    optional modules being on."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{key}', '1')
    db_session.commit()
    clear_module_config_cache()


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


# --- nothing to say --------------------------------------------------------

def test_nothing_pulled_produces_nothing(db_session, main_branch):
    """A dangling "PAYMENT FOR THE PURCHASE OF" with no items is worse than a
    blank box: the form's own guard would accept it as filled in."""
    assert build_particulars([], []) == ''


# --- the PO path -----------------------------------------------------------

def test_a_single_po_names_its_items_and_its_number(db_session, main_branch):
    po = _po(main_branch, '01080', items=('CHLORINE',))

    text = build_particulars([po.id], [])

    assert text == 'PAYMENT FOR THE PURCHASE OF CHLORINE\n-PO NO.01080'


def test_several_items_are_listed_in_line_order(db_session, main_branch):
    po = _po(main_branch, '01081', items=('CHLORINE', 'FOAMKLIN'))

    assert build_particulars([po.id], []).startswith(
        'PAYMENT FOR THE PURCHASE OF CHLORINE, FOAMKLIN')


def test_a_repeated_item_is_named_once(db_session, main_branch):
    """Two lines of the same material is a quantity split, not two things."""
    po = _po(main_branch, '01082', items=('CHLORINE', 'CHLORINE'))

    assert build_particulars([po.id], []).startswith(
        'PAYMENT FOR THE PURCHASE OF CHLORINE\n')


def test_the_purpose_becomes_its_own_line_between_items_and_references(db_session,
                                                                       main_branch):
    po = _po(main_branch, '01083', purpose='FOR PRODUCTION USE')

    assert build_particulars([po.id], []) == (
        'PAYMENT FOR THE PURCHASE OF CHLORINE\n'
        'FOR PRODUCTION USE\n'
        '-PO NO.01083'
    )


def test_a_po_without_a_purpose_gets_no_purpose_line(db_session, main_branch):
    """CONTROL, and the common case -- popurp_0001 backfilled nothing."""
    po = _po(main_branch, '01084', purpose=None)

    text = build_particulars([po.id], [])

    assert text == 'PAYMENT FOR THE PURCHASE OF CHLORINE\n-PO NO.01084'
    assert '\n\n' not in text, 'the omitted purpose left a blank line behind'
    assert 'None' not in text


# --- the RR path -----------------------------------------------------------

def test_an_rr_cites_its_po_and_the_month_it_was_received(db_session, main_branch,
                                                          vl_vendor):
    po = _po(main_branch, '00872', purpose='FOR PRODUCTION USE')
    rr = _rr(main_branch, '00638', po, vl_vendor, receipt_date=date(2026, 1, 15))

    assert build_particulars([], [rr.id]) == (
        'PAYMENT FOR THE PURCHASE OF CHLORINE\n'
        'FOR PRODUCTION USE\n'
        '-PO NO.00872, RR - JANUARY 2026'
    )


def test_the_invoice_number_lands_between_the_po_and_the_rr(db_session, main_branch,
                                                            vl_vendor):
    """Legacy order is PO NO., SI NO., RR -- not appended at the end."""
    po = _po(main_branch, '00872')
    rr = _rr(main_branch, '00638', po, vl_vendor, receipt_date=date(2026, 1, 15))

    assert build_particulars([], [rr.id], invoice_number='32664').endswith(
        '-PO NO.00872, SI NO.32664, RR - JANUARY 2026')


def test_a_blank_invoice_number_is_omitted_not_printed_empty(db_session, main_branch,
                                                             vl_vendor):
    """CONTROL: the number is typed later, so absent is the normal state."""
    po = _po(main_branch, '00873')
    rr = _rr(main_branch, '00639', po, vl_vendor)

    for blank in (None, '', '   '):
        text = build_particulars([], [rr.id], invoice_number=blank)
        assert 'SI NO.' not in text, f'{blank!r} produced an empty SI NO. segment'


# --- several documents on one voucher --------------------------------------

def test_each_document_gets_its_own_reference_line(db_session, main_branch):
    """PhilGen bills several POs on one voucher and lists each one."""
    a = _po(main_branch, '00742', items=('WEIGHING SCALE',))
    b = _po(main_branch, '00743', items=('MOTOR',))

    text = build_particulars([a.id, b.id], [])

    assert text.splitlines()[-2:] == ['-PO NO.00742', '-PO NO.00743']


def test_items_across_documents_are_merged_without_repeats(db_session, main_branch):
    a = _po(main_branch, '00744', items=('CHLORINE', 'FOAMKLIN'))
    b = _po(main_branch, '00745', items=('FOAMKLIN', 'COAL'))

    assert build_particulars([a.id, b.id], []).startswith(
        'PAYMENT FOR THE PURCHASE OF CHLORINE, FOAMKLIN, COAL')


def test_one_shared_purpose_is_stated_once(db_session, main_branch):
    a = _po(main_branch, '00746', purpose='FOR PRODUCTION USE')
    b = _po(main_branch, '00747', purpose='FOR PRODUCTION USE')

    assert build_particulars([a.id, b.id], []).count('FOR PRODUCTION USE') == 1


def test_two_different_purposes_are_both_kept(db_session, main_branch):
    """Not observed in 168 legacy POs, but dropping one would silently lose a
    fact the user typed -- so keep both rather than picking a winner."""
    a = _po(main_branch, '00748', purpose='FOR PRODUCTION USE')
    b = _po(main_branch, '00749', purpose='FOR BOILER USE')

    text = build_particulars([a.id, b.id], [])

    assert 'FOR PRODUCTION USE' in text and 'FOR BOILER USE' in text


def test_an_unknown_id_is_ignored_rather_than_crashing(db_session, main_branch):
    """The ids come from a hidden form field the browser owns."""
    po = _po(main_branch, '00750')

    assert build_particulars([po.id, 999999], [888888]) == (
        'PAYMENT FOR THE PURCHASE OF CHLORINE\n-PO NO.00750'
    )


def test_the_invoice_number_is_dropped_when_several_documents_are_cited(db_session,
                                                                       main_branch):
    """The voucher carries ONE vendor invoice number, but legacy vouchers citing
    several orders give each its own ("-PO NO.00742, SI NO.403159" then
    "-PO NO.00743, SI NO.403160"). Repeating the single number we have onto
    every line would state something false about all but one of them, so it is
    omitted rather than guessed at.
    """
    a = _po(main_branch, '00760')
    b = _po(main_branch, '00761')

    text = build_particulars([a.id, b.id], [], invoice_number='403159')

    assert 'SI NO.' not in text, (
        'the one invoice number was attributed to several orders: ' + text
    )


def test_the_invoice_number_still_appears_for_a_single_document(db_session, main_branch):
    """CONTROL for the rule above -- it must not suppress the ordinary case."""
    po = _po(main_branch, '00762')

    assert build_particulars([po.id], [], invoice_number='403159').endswith(
        '-PO NO.00762, SI NO.403159')


# --- the endpoint the browser calls ----------------------------------------

class TestParticularsEndpoint:
    """The route is a thin wrapper, so these cover the wrapper's own risks --
    auth, junk input, and that it actually returns the builder's text."""

    URL = '/accounts-payable/particulars'

    def test_it_returns_the_built_sentence(self, client, db_session, main_branch,
                                           accountant_user):
        po = _po(main_branch, '00800', purpose='FOR PRODUCTION USE')
        _login(client, accountant_user, main_branch)

        resp = client.post(self.URL, json={'po_ids': [po.id], 'rr_ids': []})

        assert resp.status_code == 200
        assert resp.get_json()['notes'] == (
            'PAYMENT FOR THE PURCHASE OF CHLORINE\nFOR PRODUCTION USE\n-PO NO.00800')

    def test_it_refuses_an_anonymous_caller(self, client, db_session, main_branch):
        """It reads document contents, so it is behind the same gate as the form."""
        resp = client.post(self.URL, json={'po_ids': [], 'rr_ids': []})

        assert resp.status_code in (302, 401, 403), \
            f'the particulars endpoint answered an anonymous caller ({resp.status_code})'

    def test_junk_ids_do_not_500(self, client, db_session, main_branch, accountant_user):
        """The ids come from a hidden field the browser owns; a stale or hand-edited
        value must produce empty text, not a server error."""
        _login(client, accountant_user, main_branch)

        resp = client.post(self.URL, json={'po_ids': ['nope', None, {}],
                                           'rr_ids': 'not-a-list',
                                           'invoice_number': 12345})

        assert resp.status_code == 200
        assert resp.get_json()['notes'] == ''

    def test_a_missing_body_is_not_an_error(self, client, db_session, main_branch,
                                            accountant_user):
        _login(client, accountant_user, main_branch)

        resp = client.post(self.URL)

        assert resp.status_code == 200
        assert resp.get_json()['notes'] == ''


class TestTheFormReachesIt:
    """Render assertions only.

    These prove the CONTROL EXISTS and is wired to a loaded script -- the class
    of bug where a backend is complete but has no reachable UI path. They do NOT
    prove the button works; that is browser behaviour and belongs to the
    pre-merge /ui-test pass.
    """

    def test_the_form_offers_a_regenerate_control(self, client, db_session, main_branch,
                                                  accountant_user):
        _enable_billing_modules(db_session)
        _login(client, accountant_user, main_branch)

        body = client.get('/accounts-payable/create').data.decode()

        assert 'id="regenerateParticulars"' in body
        assert 'refreshApParticulars' in body, \
            'the button is rendered but calls nothing'

    def test_the_button_cannot_submit_the_form(self, client, db_session, main_branch,
                                               accountant_user):
        """A bare <button> inside a <form> submits it -- here that would save a
        half-filled voucher instead of rewriting the notes."""
        _enable_billing_modules(db_session)
        _login(client, accountant_user, main_branch)

        body = client.get('/accounts-payable/create').data.decode()
        button = body[body.index('id="regenerateParticulars"') - 200:
                      body.index('id="regenerateParticulars"') + 50]

        assert 'type="button"' in button, 'the Regenerate button would submit the form'

    def test_the_script_that_defines_it_is_loaded(self, client, db_session, main_branch,
                                                  accountant_user):
        _enable_billing_modules(db_session)
        _login(client, accountant_user, main_branch)

        body = client.get('/accounts-payable/create').data.decode()

        assert 'ap_po_billing.js' in body
        # A cache-buster is mandatory on this file: it is edited often and a
        # link without one caches indefinitely, so the fix silently never ships.
        assert 'ap_po_billing.js?v=' in body,             'ap_po_billing.js is linked with no ?v= cache-buster'
