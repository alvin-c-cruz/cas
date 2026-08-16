"""An approved Purchase Request can be amended until it is converted.

Every refusal path asserts BOTH that nothing was written AND that the requisition
is byte-identical afterwards. Asserting only "it survived" cannot tell one guard
from another -- slice 2's C1 shipped behind exactly that kind of control.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


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


def _revs(pr):
    return (DocumentRevision.query
            .filter_by(document_type='purchase_requests', document_id=pr.id)
            .order_by(DocumentRevision.revision_number).all())


def _payload(pr, overrides=None, drop_ids=()):
    """Overrides keyed by line id. NOT **kwargs -- int keys cannot be unpacked."""
    overrides = overrides or {}
    out = []
    for li in pr.line_items:
        if li.id in drop_ids:
            continue
        row = {'pr_item_id': li.id, 'product_id': li.product_id,
               'description': li.description,
               'quantity': str(li.quantity) if li.quantity is not None else None,
               'uom_text': li.uom_text}
        row.update(overrides.get(li.id, {}))
        out.append(row)
    return json.dumps(out)


def _amend(client, pr, line_items=None, omit_line_items=False, **over):
    data = {
        'pr_number': pr.pr_number,
        'request_date': '2026-08-11',
        'reason': 'Site needs cement',
        'amend_reason': 'quantity corrected after site re-measure',
        'row_version': str(pr.row_version),
    }
    if not omit_line_items:
        data['line_items'] = line_items if line_items is not None else _payload(pr)
    data.update(over)
    return client.post(f'/purchase-requests/{pr.id}/amend', data=data,
                       follow_redirects=True)


@pytest.fixture
def approved_pr(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    pr = _pr(db_session, main_branch, status='submitted')
    client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
    db_session.refresh(pr)
    assert pr.status == 'approved' and len(_revs(pr)) == 1
    return pr


class TestAmendSucceeds:

    def test_amending_appends_rev_1_with_the_reason(self, client, db_session, approved_pr):
        resp = _amend(client, approved_pr,
                      line_items=_payload(approved_pr,
                                          {approved_pr.line_items[0].id: {'quantity': '25'}}))
        assert resp.status_code == 200
        db_session.refresh(approved_pr)
        revs = _revs(approved_pr)
        assert [r.revision_number for r in revs] == [0, 1]
        assert revs[1].reason == 'quantity corrected after site re-measure'
        assert approved_pr.line_items[0].quantity == Decimal('25')

    def test_the_status_is_unchanged(self, client, db_session, approved_pr):
        _amend(client, approved_pr)
        db_session.refresh(approved_pr)
        assert approved_pr.status == 'approved'

    def test_the_pr_number_is_not_renumbered(self, client, db_session, approved_pr):
        before = approved_pr.pr_number
        _amend(client, approved_pr, pr_number='PR-HIJACK-9999')
        db_session.refresh(approved_pr)
        assert approved_pr.pr_number == before

    def test_an_ordinary_header_field_IS_applied(self, client, db_session, approved_pr):
        # Control for the rule above: pr_number is pinned, but request_date and
        # reason are ordinary editable fields and must not be silently discarded.
        _amend(client, approved_pr, reason='Revised scope after site meeting')
        db_session.refresh(approved_pr)
        assert approved_pr.reason == 'Revised scope after site meeting'
        assert approved_pr.request_date == date(2026, 8, 11)

    def test_line_ids_survive_the_amendment(self, client, db_session, approved_pr):
        before = [li.id for li in approved_pr.line_items]
        _amend(client, approved_pr,
               line_items=_payload(approved_pr,
                                   {approved_pr.line_items[0].id: {'quantity': '25'}}))
        db_session.refresh(approved_pr)
        assert [li.id for li in approved_pr.line_items] == before

    def test_the_amendment_is_audited_as_amend_not_update(self, client, db_session, approved_pr):
        from app.audit.models import AuditLog
        _amend(client, approved_pr)
        entry = (AuditLog.query
                 .filter_by(module='purchase_requests', record_id=approved_pr.id,
                            action='amend')
                 .first())
        assert entry is not None, (
            "the audit log is where an auditor separates a draft edit from a "
            "rewrite of an approved document -- action must be 'amend'")


class TestStatusGuards:

    def test_a_draft_is_redirected_to_edit(self, client, db_session, main_branch,
                                           accountant_user):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft', number='PR-DRAFT-1')
        resp = _amend(client, pr)
        assert _revs(pr) == []
        assert resp.request.path.endswith('/edit'), 'a draft is EDITED, not amended'

    def test_a_submitted_pr_is_refused(self, client, db_session, main_branch,
                                       accountant_user):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='submitted', number='PR-SUB-1')
        _amend(client, pr)
        assert _revs(pr) == []

    def test_a_converted_pr_is_refused_and_the_message_NAMES_its_po(
            self, client, db_session, approved_pr):
        from app.purchase_orders.models import PurchaseOrder
        po = PurchaseOrder(po_number='PO-00123', order_date=date(2026, 8, 11),
                           status='draft', vendor_name='ACME',
                           branch_id=approved_pr.branch_id, payment_terms='Net 30',
                           vat_treatment='inclusive')
        db.session.add(po); db.session.commit()
        approved_pr.status = 'converted'
        approved_pr.purchase_order_id = po.id
        db.session.commit()
        before = len(_revs(approved_pr))

        resp = _amend(client, approved_pr)
        # Assert the FLASH SENTENCE, not just the PO number: the detail page
        # renders its own link to the converted order, so `b'PO-00123' in
        # resp.data` matched that link and stayed green even with the message
        # replaced by a bare "cannot be amended" (mutation r4).
        assert b'was already converted to Purchase Order PO-00123' in resp.data, (
            'a bare "cannot be amended" leaves the user with nowhere to go; the '
            'actionable fact is WHICH purchase order this requisition became')
        assert len(_revs(approved_pr)) == before

    def test_an_approved_pr_whose_lines_are_all_ordered_is_also_refused(
            self, client, db_session, approved_pr):
        """The half of is_converted() that AMEND_STATUSES cannot cover.

        A PR whose status still reads 'approved' but whose every line is
        already on a purchase order passes the status guard, so only
        is_converted()'s line half refuses it. Without this case, deleting the
        whole converted guard left every test green (mutation r3) because the
        status guard caught the ordinary converted PR.

        The EVIDENCE changed with line-level allocation. This used to set only
        purchase_order_id, because conversion COPIED the lines and the header
        back-link was the sole trace. Now PO lines carry source_pr_item_id, and
        the back-link alone is deliberately NOT proof of consumption -- the
        whole-requisition shortcut sets it on a PARTIAL pull too, where the
        requisition must stay amendable. So the state that must still be
        refused is "every line ordered, status not yet caught up".
        """
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        po = PurchaseOrder(po_number='PO-00777', order_date=date(2026, 8, 11),
                           status='draft', vendor_name='ACME',
                           branch_id=approved_pr.branch_id, payment_terms='Net 30',
                           vat_treatment='inclusive')
        for n, li in enumerate(approved_pr.line_items, start=1):
            po.line_items.append(PurchaseOrderItem(
                line_number=n, description=li.description, quantity=li.quantity,
                unit_price=1, amount=Decimal(str(li.quantity)),
                source_pr_item_id=li.id))
        db.session.add(po); db.session.commit()
        approved_pr.purchase_order_id = po.id      # status stays 'approved'
        db.session.commit()
        before = len(_revs(approved_pr))

        resp = _amend(client, approved_pr)
        assert b'was already converted to Purchase Order PO-00777' in resp.data
        assert len(_revs(approved_pr)) == before

    def test_a_back_link_alone_does_not_freeze_a_partly_ordered_pr(
            self, client, db_session, approved_pr):
        """Control on the clause this task REMOVED from is_converted().

        Restoring `or purchase_order_id is not None` would fail here: the
        shortcut sets the back-link on a partial pull, and freezing the
        requisition then would strand the unordered remainder.
        """
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        line = approved_pr.line_items[0]
        po = PurchaseOrder(po_number='PO-00778', order_date=date(2026, 8, 11),
                           status='draft', vendor_name='ACME',
                           branch_id=approved_pr.branch_id, payment_terms='Net 30',
                           vat_treatment='inclusive')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description=line.description, quantity=Decimal('4'),
            unit_price=1, amount=Decimal('4'), source_pr_item_id=line.id))
        db.session.add(po); db.session.commit()
        approved_pr.purchase_order_id = po.id
        db.session.commit()

        assert approved_pr.is_converted() is False
        resp = _amend(client, approved_pr)
        assert b'was already converted to Purchase Order' not in resp.data


class TestRoleGate:
    """The approve-level rule, not the edit-level one. _pr_role_gate() admits
    staff; _approve_gate() does not. Gating amend on the edit rule is exactly the
    Critical slice 2 shipped on the Purchase Order side."""

    def test_a_staff_user_is_refused(self, client, db_session, main_branch,
                                     staff_user):
        """THREE preconditions, and all three are load-bearing.

        Deliberately does NOT use the `approved_pr` fixture. flask_login caches
        the user on `g`, and conftest's session-scoped `app` fixture keeps ONE app
        context pushed for the whole run, so `g` SURVIVES ACROSS REQUESTS: a test
        whose first request is made as somebody else keeps that identity no
        matter what the session cookie later says. The fixture approves through
        the route as an accountant, so building on it made this test drive the
        amendment AS THE ACCOUNTANT -- it passed the gate and amended
        successfully, with the assertion failing only by luck of the message.
        A role test's FIRST request must be made as the role under test.

        The other two: conftest's staff_user lists neither purchase_requests in
        book_permissions NOR any branch, and either gap stops the request before
        the role gate (module 404 / branch-picker bounce), so "nothing changed"
        would hold for a reason unrelated to authorization.

        The PR is therefore built directly at status='approved' rather than
        approved through the route. It carries no Rev 0, which is irrelevant
        here: the assertion is that the gate refuses BEFORE anything is written.
        """
        staff_user.set_book_permissions({'purchase_requests': True,
                                         'purchase_orders': True, 'products': True})
        staff_user.set_branches([main_branch])
        db_session.commit()
        pr = _pr(db_session, main_branch, status='approved', number='PR-STAFF-1')
        _login(client, staff_user, main_branch)
        resp = _amend(client, pr)   # the FIRST request of this test
        assert b'Only an approver' in resp.data, (
            "pin the ROLE GATE's own message -- 'nothing changed' cannot tell it "
            'from a module 404, a branch bounce, or the wrong user entirely')
        assert _revs(pr) == []
        db_session.refresh(pr)
        assert pr.line_items[0].quantity == Decimal('10')

    def test_an_accountant_IS_admitted(self, client, db_session, approved_pr):
        # Control: the gate must not be over-tightened to admin-only without a
        # test dying. approved_pr is already driven as accountant_user.
        _amend(client, approved_pr)
        assert [r.revision_number for r in _revs(approved_pr)] == [0, 1]


class TestMalformedPayload:

    @pytest.mark.parametrize('raw', ['123', 'true', '1.5', '"a string"', 'null'])
    def test_a_non_list_line_items_is_refused_without_a_500(
            self, client, db_session, approved_pr, raw):
        before = len(_revs(approved_pr))
        resp = _amend(client, approved_pr, line_items=raw)
        assert resp.status_code == 200, 'a crafted payload must not 500'
        # Pin the ROUTE's message. The shared validator carries its own
        # non-list guard and refuses too, so "no 500 and nothing written" stayed
        # green with the route's guard deleted (mutation r8). The route's guard
        # is not redundant: it also stops a non-list reaching `restore`, which is
        # what the refusal re-render feeds to the template.
        assert b'could not be read' in resp.data
        db_session.refresh(approved_pr)
        assert len(approved_pr.line_items) == 1
        assert len(_revs(approved_pr)) == before

    @pytest.mark.parametrize('raw', ['{not json', '[1,2', 'undefined'])
    def test_unparseable_json_is_refused_without_a_500(
            self, client, db_session, approved_pr, raw):
        before = len(_revs(approved_pr))
        resp = _amend(client, approved_pr, line_items=raw)
        assert resp.status_code == 200
        db_session.refresh(approved_pr)
        assert len(approved_pr.line_items) == 1
        assert len(_revs(approved_pr)) == before

    def test_an_absent_line_items_field_says_so_rather_than_blaming_the_user(
            self, client, db_session, approved_pr):
        # Pin the MESSAGE. "the requisition survived" is vacuous here: with the
        # absent-key branch removed, line_items falls back to [] and the
        # minimum-line postcondition refuses it anyway.
        before = len(_revs(approved_pr))
        resp = _amend(client, approved_pr, omit_line_items=True)
        assert b'did not reach the server' in resp.data
        assert b'at least one requested item' not in resp.data
        db_session.refresh(approved_pr)
        assert len(approved_pr.line_items) == 1
        assert len(_revs(approved_pr)) == before


class TestMinimumLine:

    def test_removing_every_line_is_refused(self, client, db_session, approved_pr):
        before = len(_revs(approved_pr))
        resp = _amend(client, approved_pr, line_items=json.dumps([]))
        assert resp.status_code == 200
        db_session.refresh(approved_pr)
        assert len(approved_pr.line_items) == 1, 'the requisition must keep a line'
        assert len(_revs(approved_pr)) == before

    def test_removing_some_but_not_all_lines_still_succeeds(
            self, client, db_session, main_branch, accountant_user):
        # Control: the guard must not over-tighten into "no removal at all".
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='submitted', number='PR-TWO-1',
                 lines=(('Cement', '10'), ('Sand', '4')))
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        dropped = pr.line_items[1].id
        _amend(client, pr, line_items=_payload(pr, drop_ids=(dropped,)))
        db_session.refresh(pr)
        assert len(pr.line_items) == 1
        assert [r.revision_number for r in _revs(pr)] == [0, 1]


class TestConcurrency:

    def test_a_validator_refusal_does_not_bump_the_row_version(
            self, client, db_session, approved_pr):
        """Ordering guard: validate BEFORE claim_version.

        claim_version's conditional UPDATE bumps row_version as a side effect, so
        claiming first leaves that bump behind on a request that only re-renders
        -- and the user's next submit then false-conflicts against their own
        stale token. The existing byte-identical test cannot see this: it refuses
        on the REASON, which fails at form validation before either step runs.
        This one is refused by the VALIDATOR, which sits between the two.
        """
        before_version = approved_pr.row_version
        before = len(_revs(approved_pr))
        # Two rows claiming the same original line -- the validator's duplicate
        # check refuses it, after form validation and before any write.
        line_id = approved_pr.line_items[0].id
        dupe = json.dumps([
            {'pr_item_id': line_id, 'description': 'Cement', 'quantity': '10'},
            {'pr_item_id': line_id, 'description': 'Cement again', 'quantity': '5'},
        ])
        resp = _amend(client, approved_pr, line_items=dupe)
        assert resp.status_code == 200
        db_session.refresh(approved_pr)
        assert len(_revs(approved_pr)) == before, 'a refused amendment writes nothing'
        assert approved_pr.row_version == before_version, (
            'the validator refused, so claim_version must not have run -- its '
            'UPDATE would leave a version bump behind on an unchanged document')

    def test_a_stale_row_version_is_refused(self, client, db_session, approved_pr):
        before = len(_revs(approved_pr))
        resp = _amend(client, approved_pr, row_version=str(approved_pr.row_version - 1))
        assert len(_revs(approved_pr)) == before
        assert b'changed' in resp.data.lower() or b'conflict' in resp.data.lower()


class TestReason:

    def test_a_reason_shorter_than_ten_characters_is_refused(
            self, client, db_session, approved_pr):
        before = len(_revs(approved_pr))
        _amend(client, approved_pr, amend_reason='typo')
        assert len(_revs(approved_pr)) == before

    def test_the_requisition_is_byte_identical_after_a_refusal(
            self, client, db_session, approved_pr):
        before_qty = approved_pr.line_items[0].quantity
        before_version = approved_pr.row_version
        _amend(client, approved_pr, amend_reason='typo',
               line_items=_payload(approved_pr,
                                   {approved_pr.line_items[0].id: {'quantity': '999'}}))
        db_session.refresh(approved_pr)
        assert approved_pr.line_items[0].quantity == before_qty
        assert approved_pr.row_version == before_version, (
            "claim_version's UPDATE bumps row_version as a side effect -- a "
            'refused amendment must not leave that bump behind')
