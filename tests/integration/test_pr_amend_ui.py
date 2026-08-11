"""Purchase Request amend UI: the form in amend mode, the Amend button, the panel.

Render assertions, not POST contracts. A hidden field dropped from a template is
structurally invisible to a POST-based test -- that is exactly how
BUG-DR-EDIT-FALSE-CONFLICT shipped green.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(db_session, branch, status='approved', number='PR-2026-08-0001',
        lines=(('Cement', '10'),)):
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 8, 10), status=status,
                         reason='Site needs cement')
    for n, (desc, qty) in enumerate(lines, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=desc, quantity=Decimal(qty), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


@pytest.fixture
def approved_pr(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    pr = _pr(db_session, main_branch, status='submitted')
    client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
    db_session.refresh(pr)
    return pr


def _amend_get(client, pr):
    resp = client.get(f'/purchase-requests/{pr.id}/amend')
    assert resp.status_code == 200
    return resp.data.decode()


def _detail(client, pr):
    resp = client.get(f'/purchase-requests/{pr.id}')
    assert resp.status_code == 200
    return resp.data.decode()


# -- the fields a POST-based test structurally cannot see ---------------------

class TestAmendFormRendersItsFields:

    def test_it_renders_the_row_version_token(self, client, approved_pr):
        # submitted_version() reads the token from the RAW POST body, so a
        # template that stops rendering it posts none and false-conflicts every
        # amendment -- BUG-DR-EDIT-FALSE-CONFLICT exactly.
        assert 'name="row_version"' in _amend_get(client, approved_pr)

    def test_it_renders_the_line_items_input_under_the_id_the_js_writes(
            self, client, approved_pr):
        html = _amend_get(client, approved_pr)
        # The NAME is what the server reads; the ID is what the submit handler
        # writes to. Pinning only the name leaves the form posting its static
        # value="[]" after an id rename -- which amend() then refuses as
        # "would leave none", so a real browser could never amend at all.
        assert 'name="line_items"' in html
        assert 'id="prLinesJson"' in html

    def test_it_renders_the_amend_reason_field(self, client, approved_pr):
        assert 'name="amend_reason"' in _amend_get(client, approved_pr)

    def test_no_hidden_field_is_rendered_twice_inside_the_form(
            self, client, approved_pr):
        """form.hidden_tag() emits CSRF plus every HiddenField. Rendering one of
        them explicitly as well posts the name twice and request.form.get() reads
        the FIRST (empty) copy -- invisible to the pytest client, which sends a
        single key by construction.

        Scoped to prForm's own markup: base.html carries its own forms (logout
        among them) with their own csrf_token, so a page-wide count measures the
        layout rather than this form.
        """
        html = _amend_get(client, approved_pr)
        m = re.search(r'<form[^>]*id="prForm".*?</form>', html, re.DOTALL)
        assert m, 'prForm is no longer rendered'
        form_html = m.group(0)
        # csrf_token is NOT in this list: the testing config disables CSRF, so
        # hidden_tag() emits none and a `== 1` assertion here would measure the
        # config rather than the template.
        for name in ('row_version', 'line_items', 'amend_reason'):
            assert form_html.count('name="%s"' % name) == 1, (
                '%s is rendered %d times inside prForm'
                % (name, form_html.count('name="%s"' % name)))


class TestAmendModeChangesTheForm:

    def test_it_posts_to_amend_not_edit(self, client, approved_pr):
        html = _amend_get(client, approved_pr)
        assert '/amend"' in html
        assert 'action="/purchase-requests/%d/edit"' % approved_pr.id not in html

    def test_the_pr_number_is_readonly(self, client, approved_pr):
        html = _amend_get(client, approved_pr)
        m = re.search(r'<input[^>]*name="pr_number"[^>]*>', html)
        assert m and 'readonly' in m.group(0), (
            'an amendment revises a requisition, it does not renumber it')

    def test_the_pr_number_is_NOT_readonly_on_a_draft_edit(
            self, client, accountant_user, main_branch, db_session):
        # Control: amend mode must not leak into the shared draft-edit render.
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft', number='PR-DRAFT-9')
        html = client.get(f'/purchase-requests/{pr.id}/edit').data.decode()
        m = re.search(r'<input[^>]*name="pr_number"[^>]*>', html)
        assert m and 'readonly' not in m.group(0)

    def test_amend_mode_carries_novalidate(self, client, approved_pr):
        """Without it the browser blocks a short reason client-side, so the
        server's refusal path -- and the post-refusal line-identity replay that
        depends on it -- is UNREACHABLE in a real browser, including by the
        pre-merge browser pass meant to cover exactly that."""
        html = _amend_get(client, approved_pr)
        m = re.search(r'<form[^>]*id="prForm"[^>]*>', html)
        assert m and 'novalidate' in m.group(0)

    def test_create_and_draft_edit_KEEP_native_validation(
            self, client, accountant_user, main_branch, db_session):
        # Control for the rule above: prForm is shared with two shipped browser
        # paths, so novalidate is scoped to amend mode and must not hoist.
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft', number='PR-DRAFT-8')
        for html in (client.get('/purchase-requests/create').data.decode(),
                     client.get(f'/purchase-requests/{pr.id}/edit').data.decode()):
            m = re.search(r'<form[^>]*id="prForm"[^>]*>', html)
            assert m and 'novalidate' not in m.group(0)


class TestAmendButton:

    def test_an_accountant_sees_it_on_an_approved_pr(self, client, approved_pr):
        assert 'Amend' in _detail(client, approved_pr)

    def test_a_staff_user_does_not(self, client, db_session, main_branch, staff_user):
        # FIRST request of this test is the staff one: flask_login caches the
        # user on `g` and conftest keeps one app context for the whole run, so a
        # test that first requests as somebody else keeps that identity.
        staff_user.set_book_permissions({'purchase_requests': True,
                                         'purchase_orders': True, 'products': True})
        staff_user.set_branches([main_branch])
        db_session.commit()
        pr = _pr(db_session, main_branch, status='approved', number='PR-STAFF-2')
        _login(client, staff_user, main_branch)
        html = _detail(client, pr)
        assert 'Amend' not in html, (
            'the button must follow the same APPROVE-level rule as the route, or '
            'staff sees a control that refuses on click -- the '
            'delete_approved_email shape')
        # Positive control: prove the page rendered for this user at all, rather
        # than the absence coming from a 404 or an empty body.
        assert pr.pr_number in html

    def test_no_amend_button_on_a_draft(self, client, accountant_user, main_branch,
                                        db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft', number='PR-DRAFT-7')
        html = _detail(client, pr)
        assert 'Amend' not in html
        assert pr.pr_number in html

    def test_no_amend_button_on_a_converted_pr(self, client, db_session, approved_pr):
        from app.purchase_orders.models import PurchaseOrder
        po = PurchaseOrder(po_number='PO-00999', order_date=date(2026, 8, 11),
                           status='draft', vendor_name='ACME',
                           branch_id=approved_pr.branch_id, payment_terms='Net 30',
                           vat_treatment='inclusive')
        db.session.add(po); db.session.commit()
        approved_pr.status = 'converted'
        approved_pr.purchase_order_id = po.id
        db.session.commit()
        html = _detail(client, approved_pr)
        assert 'Amend' not in html
        assert approved_pr.pr_number in html


    def test_no_amend_button_on_an_approved_pr_that_already_carries_a_po_id(
            self, client, db_session, approved_pr):
        # The half of is_converted() the STATUS guard cannot cover. Without this
        # case, deleting the button's converted guard changed nothing (mutation
        # u3) because the other converted test also flipped the status.
        from app.purchase_orders.models import PurchaseOrder
        po = PurchaseOrder(po_number='PO-00888', order_date=date(2026, 8, 11),
                           status='draft', vendor_name='ACME',
                           branch_id=approved_pr.branch_id, payment_terms='Net 30',
                           vat_treatment='inclusive')
        db.session.add(po); db.session.commit()
        approved_pr.purchase_order_id = po.id      # status stays 'approved'
        db.session.commit()
        html = _detail(client, approved_pr)
        assert 'Amend' not in html
        assert approved_pr.pr_number in html


# -- the revision history panel ----------------------------------------------

def _entries(html):
    """Each revision entry, bounded by its STABLE data-revision handle.

    Keyed off data-revision rather than the class attribute: on the PO panel the
    helper matched a trailing space that existed only because of a conditional
    class, and a behaviour-identical tidy silently made it return a subset while
    two tests failed blaming the panel.
    """
    return re.findall(r'<div data-revision="(\d+)"[^>]*>(.*?)</div>\s*</div>',
                      html, re.DOTALL)


class TestRevisionPanel:

    def test_the_baseline_is_captioned_as_the_original(self, client, approved_pr):
        html = _detail(client, approved_pr)
        entries = _entries(html)
        assert [n for n, _ in entries] == ['0']
        assert 'Original approved request' in entries[0][1]

    def test_an_amendment_appears_above_the_baseline_with_its_reason(
            self, client, db_session, approved_pr):
        client.post(f'/purchase-requests/{approved_pr.id}/amend', data={
            'pr_number': approved_pr.pr_number, 'request_date': '2026-08-11',
            'reason': 'Site needs cement',
            'amend_reason': 'quantity corrected after site re-measure',
            'row_version': str(approved_pr.row_version),
            'line_items': json.dumps([
                {'pr_item_id': approved_pr.line_items[0].id,
                 'description': 'Cement', 'quantity': '25'}]),
        }, follow_redirects=True)
        entries = _entries(_detail(client, approved_pr))
        assert [n for n, _ in entries] == ['1', '0'], 'newest first'
        assert 'quantity corrected after site re-measure' in entries[0][1]
        assert 'Original approved request' not in entries[0][1], (
            'an amendment must never be captioned as the baseline')

    def test_the_panel_names_who_and_when(self, client, approved_pr, accountant_user):
        entry = _entries(_detail(client, approved_pr))[0][1]
        assert accountant_user.username in entry
        # amended_at is naive PH-local (ph_now stored on a naive DateTime), so
        # the rendered hour must be the PH hour -- format_ph_datetime() would
        # treat it as UTC and shift it forward eight.
        rev = DocumentRevision.query.filter_by(
            document_type='purchase_requests', document_id=approved_pr.id).one()
        assert rev.amended_at.strftime('%b %d, %Y %H:%M') in entry

    def test_a_baseline_that_CARRIES_a_reason_renders_the_reason(
            self, client, db_session, accountant_user, main_branch):
        """The honesty branch, and why `reason` is tested FIRST.

        PR has no backfill migration today (every purchase_requests table in
        every client DB held zero rows -- measured in task 2), so a Rev 0 with a
        reason is only reachable through the shared service. It is still the case
        that decides the branch ORDER: if `rev.number == 0` were tested first,
        anything occupying slot 0 would be captioned "Original approved request"
        regardless of what it actually says -- an affirmative false claim about a
        document users make decisions on, and exactly what a future backfill's
        own disclosure would be swallowed by.

        Without this test, reordering the branches changed nothing (mutation u9).
        """
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='approved', number='PR-BASE-1')
        db.session.add(DocumentRevision(
            document_type='purchase_requests', document_id=pr.id,
            revision_number=0, snapshot_json='{}',
            reason='Rev 0 - reconstructed at upgrade, not an original capture',
            amended_by_id=accountant_user.id, branch_id=pr.branch_id))
        db.session.commit()
        entry = _entries(_detail(client, pr))[0][1]
        assert 'reconstructed at upgrade' in entry
        assert 'Original approved request' not in entry, (
            'a reconstruction must never be captioned as the original')

    def test_a_reason_less_amendment_is_NOT_captioned_as_the_baseline(
            self, client, db_session, accountant_user, main_branch):
        # write_revision(reason=None) is the shared service every later document
        # calls; nothing stops a caller writing revision 1 without a reason. If
        # the caption branch were `{% else %}` instead of `rev.number == 0`, that
        # revision would claim to be the approved original (mutation u10).
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='approved', number='PR-BASE-2')
        for n, reason in ((0, None), (1, None)):
            db.session.add(DocumentRevision(
                document_type='purchase_requests', document_id=pr.id,
                revision_number=n, snapshot_json='{}', reason=reason,
                amended_by_id=accountant_user.id, branch_id=pr.branch_id))
        db.session.commit()
        entries = dict(_entries(_detail(client, pr)))
        assert 'Original approved request' in entries['0']
        assert 'Original approved request' not in entries['1'], (
            'only revision 0 is the baseline; a reason-less amendment is still '
            'an amendment')

    def test_the_panel_shows_only_THIS_documents_revisions(
            self, client, db_session, accountant_user, main_branch):
        """document_type is part of the filter, not decoration.

        document_id is a plain Integer pointing at eight different tables, so a
        Purchase Request and a Purchase Order can share id 1 and only the type
        separates them. Dropping the filter changed nothing (mutation u13) until
        a same-id revision of another type existed.
        """
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='approved', number='PR-SCOPE-1')
        db.session.add(DocumentRevision(
            document_type='purchase_requests', document_id=pr.id,
            revision_number=0, snapshot_json='{}', reason=None,
            amended_by_id=accountant_user.id, branch_id=pr.branch_id))
        # A DIFFERENT document type carrying the SAME document_id.
        db.session.add(DocumentRevision(
            document_type='purchase_orders', document_id=pr.id,
            revision_number=7, snapshot_json='{}',
            reason='belongs to a purchase order, not this requisition',
            amended_by_id=accountant_user.id, branch_id=pr.branch_id))
        db.session.commit()
        html = _detail(client, pr)
        assert [n for n, _ in _entries(html)] == ['0']
        assert b'belongs to a purchase order' not in html.encode()

    def test_a_pr_with_no_revisions_renders_no_panel(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft', number='PR-DRAFT-6')
        html = _detail(client, pr)
        assert _entries(html) == []
        assert 'Revision history' not in html

    def test_the_panel_is_ONE_query_however_many_revisions(
            self, client, approved_pr, accountant_user, db_session):
        """Counts the SQL the request really executes.

        A lazy `amended_by` per row renders an identical page while paying a
        query per revision. Measured on a COLD session so the identity map
        cannot hide the lazy loads.
        """
        from sqlalchemy import event
        for n in range(1, 6):
            db.session.add(DocumentRevision(
                document_type='purchase_requests', document_id=approved_pr.id,
                revision_number=n, snapshot_json='{}', reason='r%d' % n,
                amended_by_id=accountant_user.id, branch_id=approved_pr.branch_id))
        db.session.commit()
        # Read the id BEFORE closing: the close detaches every instance, and
        # touching approved_pr.id afterwards raises DetachedInstanceError.
        pr_id = approved_pr.id

        statements = []

        def _before(conn, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _before)
        try:
            resp = client.get(f'/purchase-requests/{pr_id}')
            assert resp.status_code == 200
            html = resp.data.decode()
        finally:
            event.remove(db.engine, 'before_cursor_execute', _before)

        assert len(_entries(html)) == 6
        rev_queries = [s for s in statements if 'document_revisions' in s]
        assert len(rev_queries) == 1, (
            'the panel must be ONE query; got %d against document_revisions'
            % len(rev_queries))
        assert any('JOIN USERS' in s.upper() for s in rev_queries), (
            'the amender must come back on that same query (joinedload), not as '
            'a lazy load per row')
