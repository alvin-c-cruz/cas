"""Task 5: the amend UI -- the PO form in amend mode, and the detail page's Amend button.

Every assertion here is made on a **GET render** (or on the re-render a refused POST
produces), never on a POST contract. That is the whole point of the file:

* A hidden field dropped from a template is structurally INVISIBLE to a POST-based
  test, because the test client supplies the field itself. That is exactly how
  BUG-DR-EDIT-FALSE-CONFLICT shipped green (memory
  `csrf-only-render-drops-hidden-fields`). `row_version`, `line_items` and
  `amend_reason` are therefore pinned on the rendered GET.
* A template guard that disagrees with its route's guard has also already shipped
  here (`delete_approved_email`: backend loosened, template `{% if %}` left in
  place -- a reachable route with no UI path, invisible to every POST-based test).
  The Amend button is gated on `_has_approve_level_role()`, the SAME predicate
  `purchase_orders.amend()` uses, and BOTH directions are asserted.
* The line-identity mapping lives in template JS that pytest cannot execute. It is
  pinned in two complementary halves: the DATA each render hands the JS (assertable
  server-side) and the SOURCE of the branch that consumes it. See
  TestPoAmendLineIdentity for why both halves of the fallback are load-bearing.
"""
import json
import re
import shutil
import subprocess
from datetime import date
from decimal import Decimal

import pytest

from tests.integration import _line_identity_js as _js

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


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
    """Direct-session login. conftest's login_user posts through the real /login
    view, which does not select a branch -- with two accessible branches the branch
    picker would swallow every request."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture(autouse=True)
def logged_in(client, admin_user, branch_manila):
    """Default session: admin, scoped to the PO's branch. Role tests re-login as
    the role under test BEFORE issuing their first request -- flask_login caches
    the user on `g`, so the first request of a test wins for that test."""
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
def approved_po(db_with_data, branch_manila, vendor_acme):
    """Flipped to `approved` in the DB rather than through the approve route.

    Nothing here reads revisions, and issuing the approve POST would cache `admin`
    on `g` for the rest of the test -- which the role tests below cannot afford.
    """
    po = _make_draft_po(branch_manila, vendor_acme, '00997')
    po.status = 'approved'
    db.session.commit()
    return po


#: The amend-mode banner. Asserted verbatim in both directions (present in amend
#: mode, absent on the draft-edit form), so a reworded banner is a deliberate
#: two-line change rather than something that can silently disappear.
_AMEND_BANNER = 'This Purchase Order is approved. Saving creates a new revision.'


#: `const EXISTING = [...];` -- the line array the form hands its JS. Non-greedy to
#: the first `];`, which is safe because the array holds only flat objects.
_EXISTING_RE = re.compile(r'const EXISTING\s*=\s*(\[.*?\]);', re.DOTALL)


def _existing(html):
    m = _EXISTING_RE.search(html)
    assert m is not None, 'the form no longer emits the EXISTING line array to its JS'
    return json.loads(m.group(1))


def _amend_get(client, po):
    resp = client.get(f'/purchase-orders/{po.id}/amend')
    assert resp.status_code == 200
    return resp.data.decode()


def _post_amend(client, po, **overrides):
    data = {
        'po_number': po.po_number,
        'order_date': '2026-08-05',
        'vendor_id': po.vendor_id,
        'vat_treatment': 'inclusive',
        'payment_terms': 'Net 30',
        'notes': '',
        'amend_reason': 'vendor corrected the quantity',
        'line_items': '[]',
        'row_version': po.row_version,
    }
    data.update(overrides)
    return client.post(f'/purchase-orders/{po.id}/amend', data=data)


# -- executing the form's own JS ------------------------------------------
#
# Everything above is a SOURCE-SHAPE assertion: it proves a string is present in
# the response, not that a browser round-trips the line identity. That gap is not
# theoretical -- an adversarial review mutated the dataset guard to
# `if (poItemId != null && d.id != null)`, which leaves EVERY source token this
# file asserts intact, and all the text-level tests stayed green while every
# existing line began posting as a NEW line on the second submit (a
# delete-and-recreate that strands ReceivingReportItem.purchase_order_item_id).
#
# So the chain below is EXECUTED. The form's real <script> block is lifted out of
# the real rendered response and run in node against a minimal DOM shim; the test
# then reads what the submit handler actually serialised into the hidden input.
#
# What this buys and what it does not:
#   * BUYS: poItemIdOf -> the addRow guard -> tr.dataset -> the submit serialiser
#     -> the hidden input, executed as written, against the two payload shapes the
#     app really renders. Any rewrite of the guard, the fallback, the dataset key,
#     the serialised key or the target element id changes the OUTPUT.
#   * DOES NOT BUY: real DOM semantics. The shim's cells return empty values, so
#     only the line IDENTITY is observed here -- not quantities, VAT lookup,
#     Choices.js, event wiring or native form validation. Those still need the
#     pre-merge /ui-test browser pass (see the review's browser list).
#
# node is REQUIRED, never skipped: a test that quietly skips when its runtime is
# missing observes nothing and turns the suite green for the wrong reason. Same
# rule tests/integration/test_po_rev0_backfill.py states for its subprocesses.

#: Executed via the shared harness -- see tests/integration/_line_identity_js.py
#: for the DOM shim, what it buys, and why node is required rather than skipped.
#: It was extracted there when the Purchase Request form became its second
#: consumer; duplicating the shim per document is the same bet that left the PO
#: and SO validators drifting apart until a separate change reconciled them.
_MARKER = 'poItemIdOf'
_FORM_ID = 'poForm'


def _line_items_input(html):
    return _js.line_items_input(html)


def _line_items_input_id(html):
    return _js.line_items_input_id(html)


def _serialise_lines(tmp_path, html, hand_added=0):
    return _js.serialise_lines(tmp_path, html, marker=_MARKER, form_id=_FORM_ID,
                               hand_added=hand_added)


# -- the three fields a POST-based test structurally cannot see ------------

class TestAmendFormRendersItsFields:
    def test_amend_form_renders_the_row_version_token(self, client, approved_po):
        # submitted_version() reads the token from the RAW POST body, so a template
        # that stops rendering it posts no token and false-conflicts every
        # amendment. A POST-contract test supplies the token itself and cannot see
        # that -- BUG-DR-EDIT-FALSE-CONFLICT exactly.
        assert 'name="row_version"' in _amend_get(client, approved_po)

    def test_amend_form_renders_the_line_items_input(self, client, approved_po):
        # amend() refuses a POST whose `line_items` key is ABSENT ("did not reach
        # the server"). Drop this input from the render and every amendment made in
        # a real browser is refused -- with the whole pytest suite still green.
        html = _amend_get(client, approved_po)
        assert 'name="line_items"' in html
        # The NAME is what the server reads; the ID is what the JS writes to
        # (getElementById('lineItemsJson')). Pinning only the name leaves the
        # form posting its static value="[]" after an id rename -- which empties
        # an APPROVED PO. Both halves, plus the coupling between them:
        # TestPoAmendLineIdentityExecuted
        # ::test_the_serialiser_writes_into_the_rendered_line_items_input executes
        # the JS and fails if the two sides stop naming the same element.
        assert 'id="lineItemsJson"' in html
        assert _line_items_input_id(html) == 'lineItemsJson'
        assert "getElementById('lineItemsJson')" in html, (
            'the submit handler no longer targets the rendered line_items input')

    def test_amend_form_renders_the_amend_reason_field(self, client, approved_po):
        # amend_reason is DataRequired + Length(min=10). Without the field there is
        # no reachable way to satisfy it: every browser amendment is refused.
        assert 'name="amend_reason"' in _amend_get(client, approved_po)


# -- amend mode vs. draft edit mode ----------------------------------------

class TestAmendModeShape:
    def test_the_amend_form_posts_to_the_amend_route(self, client, approved_po):
        # form.html's action is hard-coded to edit/create. Left unbranched, the
        # amend GET renders a form that posts to edit() -- which refuses anything
        # that is not a draft, so the button would simply never work.
        html = _amend_get(client, approved_po)
        tag = re.search(r'<form[^>]*id="poForm"[^>]*>', html)
        assert tag is not None, 'the PO form tag was not found'
        assert f'action="/purchase-orders/{approved_po.id}/amend"' in tag.group(0)

    def test_the_amend_form_po_number_is_readonly(self, client, approved_po):
        # An amendment revises an order; it does not renumber it. amend() already
        # declines to reassign po_number, so an editable box is a control that
        # silently discards what the user typed.
        html = _amend_get(client, approved_po)
        field = re.search(r'<input[^>]*name="po_number"[^>]*>', html)
        assert field is not None, 'po_number input not found in the amend form'
        assert 'readonly' in field.group(0)

    def test_the_amend_form_submit_button_says_update(self, client, approved_po):
        assert '>Update<' in _amend_get(client, approved_po)

    def test_the_amend_form_warns_that_saving_creates_a_revision(
            self, client, approved_po):
        """The banner is the ONLY prose on this page that says the user is
        amending -- the title, page_title and <h1> all still read "Edit Purchase
        Order" (deliberate: sales_orders/form.html does the same). Delete it and
        the amend screen is distinguishable from the ordinary draft-edit screen
        only by a greyed-out PO number and a reason box, with the whole suite
        green. It is load-bearing UI, so it is pinned."""
        assert _AMEND_BANNER in _amend_get(client, approved_po)

    def test_the_draft_edit_form_is_untouched_by_amend_mode(self, client, draft_po):
        """The negative control: none of the amend-mode branches may leak into the
        ordinary draft edit form, which still renumbers, still posts to edit(), and
        must not ask for a reason."""
        resp = client.get(f'/purchase-orders/{draft_po.id}/edit')
        assert resp.status_code == 200
        html = resp.data.decode()

        field = re.search(r'<input[^>]*name="po_number"[^>]*>', html)
        assert field is not None, 'po_number input not found in the edit form'
        assert 'readonly' not in field.group(0)
        assert 'name="amend_reason"' not in html
        assert _AMEND_BANNER not in html
        tag = re.search(r'<form[^>]*id="poForm"[^>]*>', html)
        assert f'action="/purchase-orders/{draft_po.id}/edit"' in tag.group(0)


class TestTheServerSideRefusalIsReachableInABrowser:
    """`amend_reason` renders `required minlength="10"` (WTForms emits both from
    DataRequired + Length). Without `novalidate` on the form, a browser blocks the
    submit with a native constraint bubble and the `submit` event never fires --
    so amend()'s own refusal flash, its re-render, AND the post-refusal line-identity
    replay (the single most important behaviour on this form) are unreachable by a
    real user and by the pre-merge browser pass. pytest's test client never sees
    this: it posts straight past client-side validation.

    `novalidate` is the app-wide convention (40+ forms, including
    sales_orders/form.html:19, the precedent this task mirrors); purchase_orders is
    the outlier.
    """

    def test_the_amend_form_is_novalidate_so_a_refusal_can_reach_the_server(
            self, client, approved_po):
        html = _amend_get(client, approved_po)
        tag = re.search(r'<form[^>]*id="poForm"[^>]*>', html)
        assert tag is not None, 'the PO form tag was not found'
        assert 'novalidate' in tag.group(0), (
            'the amend form re-enabled native constraint validation -- '
            'amend_reason is required+minlength=10, so the browser now blocks the '
            'submit and no server-side refusal (and therefore no line-identity '
            'replay) is reachable outside pytest')

    def test_the_create_and_draft_edit_forms_keep_their_native_validation(
            self, client, draft_po):
        """The control. `novalidate` is scoped to amend mode ON PURPOSE: create and
        draft-edit are two already-shipped browser paths on this same template, and
        turning their client-side validation off is a behaviour change this task
        neither needs nor is scoped to make. If someone later hoists `novalidate`
        onto the bare <form> tag, this dies."""
        for url in (f'/purchase-orders/{draft_po.id}/edit', '/purchase-orders/create'):
            resp = client.get(url)
            assert resp.status_code == 200, url
            tag = re.search(r'<form[^>]*id="poForm"[^>]*>', resp.data.decode())
            assert tag is not None, f'the PO form tag was not found on {url}'
            assert 'novalidate' not in tag.group(0), (
                f'{url} lost its native client-side validation -- amend mode\'s '
                'novalidate leaked onto a path that never asked for it')


# -- the line-identity mapping (the silent, expensive one) -----------------

class TestPoAmendLineIdentity:
    """`PurchaseOrderItem.to_dict()` emits `id`; the SUBMITTED payload carries
    `po_item_id` and no `id`. Both the validator and the applier key on
    `po_item_id`. So the form's JS must map the identity across from BOTH shapes:

      * the `id` half covers the FIRST render (lines loaded from the DB);
      * the `po_item_id` half covers the re-render after a refusal (lines coming
        back from the submitted payload).

    With only the `id` half, the SECOND submit after any refusal loses every line
    identity -- and a correction silently becomes "all lines removed, all lines
    added", refused outright the moment any receipt exists against the PO. A
    refusal followed by a resubmit is the most likely real-world sequence there is.

    pytest cannot execute the JS, so each half is pinned twice: the DATA the render
    hands it, and the SOURCE of the branch that consumes that data.
    """

    def test_the_first_render_hands_the_stored_id_and_the_mapping_reads_it(
            self, client, approved_po):
        line_id = approved_po.line_items[0].id
        html = _amend_get(client, approved_po)

        lines = _existing(html)
        assert lines[0]['id'] == line_id
        assert 'po_item_id' not in lines[0], (
            'to_dict() does not emit po_item_id -- if it ever does, the fallback '
            'below is no longer what carries the first render')
        assert re.search(r'd\.id\s*!=\s*null\s*\?\s*d\.id', html) is not None, (
            'the line-identity mapping no longer reads `id` -- the FIRST render '
            'loses every line identity, so any amendment reads as '
            '"all lines removed, all lines added"')

    def test_the_re_render_after_a_refusal_hands_po_item_id_and_the_mapping_falls_back(
            self, client, approved_po):
        line_id = approved_po.line_items[0].id
        submitted = [{'po_item_id': line_id, 'product_id': None,
                      'description': 'widget', 'quantity': '10',
                      'unit_price': '5.00', 'amount': '50.00',
                      'vat_category': None, 'vat_rate': '0'}]
        resp = _post_amend(client, approved_po, amend_reason='typo',
                           line_items=json.dumps(submitted))
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'at least 10 characters' in html, (
            'precondition: this POST must be REFUSED and re-rendered, which is the '
            'only path that feeds the submitted payload back into the form')

        lines = _existing(html)
        assert lines[0]['po_item_id'] == line_id
        assert 'id' not in lines[0], (
            'the re-render replays the RAW submission, which carries no `id` -- '
            'that is precisely why the fallback half exists')
        assert re.search(r'd\.po_item_id\s*!=\s*null\s*\?\s*d\.po_item_id',
                         html) is not None, (
            'the line-identity mapping no longer falls back to `po_item_id` -- the '
            'SECOND submit after any refusal loses every line identity and turns a '
            'correction into a delete-everything-and-re-add')

    def test_the_mapped_identity_reaches_the_row_and_is_serialised_back(
            self, client, approved_po):
        """The rest of the wire, pinned link by link.

        A correct `poItemIdOf` is worth nothing if its result is never written
        onto the row, and a row that carries the identity is worth nothing if the
        submit handler does not put it back on the payload under the key the
        validator and the applier both parse. Each link deleted on its own leaves
        every POST-based test in test_po_amend.py green -- they post the line JSON
        directly instead of exercising this JS. (Verified: dropping the dataset
        write alone survived this file's first mutation run.)
        """
        html = _amend_get(client, approved_po)
        assert re.search(r'const poItemId\s*=\s*poItemIdOf\(d\)', html) is not None, (
            'the row no longer resolves its line identity through the mapping')
        assert re.search(r'tr\.dataset\.poItemId\s*=\s*poItemId\b', html) is not None, (
            'the resolved line identity is no longer written onto the row -- the '
            'submit serialiser below reads an empty dataset and every line posts '
            'as new')
        assert re.search(r'po_item_id:\s*tr\.dataset\.poItemId', html) is not None, (
            'the submit-time line serialiser no longer emits po_item_id -- an '
            'amendment can no longer update existing lines in place')

    def test_the_dataset_write_guard_is_exactly_the_null_check(
            self, client, approved_po):
        """The cheap layer, and a SOURCE-SHAPE PROXY -- it proves the guard reads
        as written, not that a browser behaves.

        The three assertions above pin that three TOKENS appear; they are blind to
        what the guard around them TESTS. `if (poItemId != null && d.id != null)`
        keeps every one of those tokens and still drops the identity of every line
        on the second submit after any refusal. Pinning the exact expression closes
        that specific rewrite cheaply and with no runtime dependency.

        The test that actually observes the behaviour is
        TestPoAmendLineIdentityExecuted below, which runs this JS. If this
        assertion ever fails on a harmless reformat (`!==`, added spaces), check
        THAT class is still green and then update the pattern here -- do not delete
        it.
        """
        html = _amend_get(client, approved_po)
        assert re.search(
            r'if \(poItemId != null\) tr\.dataset\.poItemId = poItemId;',
            html) is not None, (
            'the dataset-write guard is no longer `if (poItemId != null)`. Any '
            'extra condition here (e.g. `&& d.id != null`) silently restricts the '
            'identity write to the FIRST render, so every line posts as new after '
            'a refusal -- refused outright once a receipt exists, and a '
            'delete-and-recreate when none does')


class TestPoAmendLineIdentityExecuted:
    """The behavioural layer: the form's real JS, executed (see the module comment
    above `_JS_DRIVER` for exactly what this does and does not prove).

    Everything else in this file asserts on text. These four assert on the array a
    browser would actually POST.
    """

    def test_the_first_render_posts_the_stored_line_identity(
            self, client, approved_po, tmp_path):
        line_id = approved_po.line_items[0].id
        posted = _serialise_lines(tmp_path, _amend_get(client, approved_po))

        assert len(posted) == 1
        assert posted[0]['po_item_id'] == str(line_id), (
            'the form loaded an existing line from the DB and then posted it '
            'without its identity -- validate_amendment reads that as "line '
            'removed, line added"')

    def test_the_re_render_after_a_refusal_still_posts_the_line_identity(
            self, client, approved_po, tmp_path):
        """THE regression this whole task exists to prevent, executed.

        Refuse -> fix -> resubmit is the most ordinary sequence a user can produce.
        The re-render replays the SUBMITTED payload, which carries `po_item_id` and
        no `id`, so this is the round trip that dies the moment the identity
        mapping is narrowed to the `id` half.
        """
        line_id = approved_po.line_items[0].id
        submitted = [{'po_item_id': line_id, 'product_id': None,
                      'description': 'widget', 'quantity': '10',
                      'unit_price': '5.00', 'amount': '50.00',
                      'vat_category': None, 'vat_rate': '0'}]
        resp = _post_amend(client, approved_po, amend_reason='typo',
                           line_items=json.dumps(submitted))
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'at least 10 characters' in html, (
            'precondition: this POST must be REFUSED and re-rendered')

        posted = _serialise_lines(tmp_path, html)
        assert len(posted) == 1
        assert posted[0]['po_item_id'] == str(line_id), (
            'the SECOND submit after a refusal lost the line identity: every '
            'existing line would post as new, turning a correction into a '
            'delete-everything-and-re-add that strands any '
            'ReceivingReportItem.purchase_order_item_id pointing at it')

    def test_a_hand_added_line_posts_no_identity_while_the_existing_one_keeps_its_own(
            self, client, approved_po, tmp_path):
        """The other direction. A row added during the amendment must post
        po_item_id null (parse_submission then treats it as a new line); an
        unconditional dataset write would post the string "null" instead, and a
        guard that leaks the previous row's id would merge two lines into one."""
        line_id = approved_po.line_items[0].id
        posted = _serialise_lines(tmp_path, _amend_get(client, approved_po),
                                  hand_added=1)

        assert len(posted) == 2
        assert posted[0]['po_item_id'] == str(line_id)
        assert posted[1]['po_item_id'] is None, (
            'a hand-added line posted an identity it does not have: '
            f'{posted[1]["po_item_id"]!r}')

    def test_the_serialiser_writes_into_the_rendered_line_items_input(
            self, client, approved_po, tmp_path):
        """The JS handle and the rendered input must name the SAME element.

        `_serialise_lines` reads the input's id out of the rendered HTML and fails
        if nothing was written to it, so renaming one side only dies here. That
        rename is otherwise silent AND destructive: the submit handler throws a
        TypeError which does NOT cancel the submit, the form posts its static
        value="[]", amend()'s absent-key guard does not fire (the key IS present),
        and an approved PO is emptied to zero lines and a 0.00 total -- flashed as
        a successful amendment with a revision recorded.
        """
        posted = _serialise_lines(tmp_path, _amend_get(client, approved_po))
        assert posted != [], (
            'the serialiser produced an empty array for a PO that has a line')


# -- the detail page's Amend button ----------------------------------------

def _amend_href(po):
    return f'/purchase-orders/{po.id}/amend'


class TestAmendButtonOnDetail:
    def _approve_in_db(self, po, user, branch, status='approved'):
        """Flip *po*'s status without issuing a request, and give *user* access to
        *branch*. A non-admin with NO assigned branch is force-logged-out by the
        branch-session guard before any view runs -- which would "pass" an absence
        test for entirely the wrong reason."""
        po.status = status
        if user is not None and branch not in user.branches:
            user.branches.append(branch)
        db.session.commit()

    def test_an_accountant_sees_the_amend_button(
            self, client, accountant_user, branch_manila, draft_po):
        # The route admits `accountant` (_has_approve_level_role). A template gate
        # of "admin only" would pass every other test in this file -- they all run
        # as admin -- while leaving accountants with no UI path to a route they are
        # entitled to use.
        self._approve_in_db(draft_po, accountant_user, branch_manila)
        _login(client, accountant_user, branch_manila)

        resp = client.get(f'/purchase-orders/{draft_po.id}')
        assert resp.status_code == 200
        assert _amend_href(draft_po) in resp.data.decode()

    def test_a_staff_user_does_not_see_the_amend_button(
            self, client, staff_user, branch_manila, draft_po):
        # THE gate case. `staff` may edit a DRAFT PO but may NOT approve one, and
        # amend() refuses them. A button gated on edit() rule instead would render
        # a control that refuses on click. `viewer` does not cover this: viewer is
        # refused by both the loose and the tight rule.
        perms = staff_user.get_book_permissions()
        perms.update({'purchase_orders': True, 'products': True})
        staff_user.set_book_permissions(perms)
        self._approve_in_db(draft_po, staff_user, branch_manila)
        _login(client, staff_user, branch_manila)

        resp = client.get(f'/purchase-orders/{draft_po.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Positive control: the page really rendered, so the absence below is not
        # a 302/404/empty body passing for a hidden button.
        assert draft_po.po_number in html
        assert _amend_href(draft_po) not in html

    def test_a_draft_po_shows_no_amend_button(self, client, draft_po):
        # A draft is EDITED, not amended -- amend() bounces a draft straight back
        # to edit(). Runs as admin, so only the status guard can hide the button.
        resp = client.get(f'/purchase-orders/{draft_po.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert draft_po.po_number in html
        assert _amend_href(draft_po) not in html

    @pytest.mark.parametrize('status', ['closed', 'cancelled'])
    def test_a_terminal_po_shows_no_amend_button(self, client, approved_po, status):
        approved_po.status = status
        db.session.commit()
        resp = client.get(f'/purchase-orders/{approved_po.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert approved_po.po_number in html
        assert _amend_href(approved_po) not in html

    def test_an_approved_po_shows_the_amend_button(self, client, approved_po):
        resp = client.get(f'/purchase-orders/{approved_po.id}')
        assert resp.status_code == 200
        assert _amend_href(approved_po) in resp.data.decode()

    def test_a_partially_received_po_shows_the_amend_button(self, client, approved_po):
        # PurchaseOrder.AMEND_STATUSES has TWO members. A template guard written as
        # `status == 'approved'` passes the test above and silently drops the
        # second one the moment that transition ships.
        approved_po.status = 'partially_received'
        db.session.commit()
        resp = client.get(f'/purchase-orders/{approved_po.id}')
        assert resp.status_code == 200
        assert _amend_href(approved_po) in resp.data.decode()
