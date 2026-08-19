"""Per-order PO signatories, the submit step, and Action Items.

Three things that arrived together because they share one migration (posig_0001):

  * SIGNATORIES are per ORDER and carry forward from THIS PURCHASER's own last
    one -- deliberately unlike the requisition's and receiving report's, which
    are company-wide AppSettings rows. This client runs two purchasers, each
    with her own pre-printed pad, each routing orders past different people.
  * SUBMIT gives a staff purchaser a way forward. Before it, she could raise a
    draft and move it nowhere, because approve is accountant-or-above.
  * ACTION ITEMS could not see a PO at all -- neither the draft nor, once the
    submit step existed, the state that is actually waiting on somebody.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    # Assign first. staff_user has NO branch assignment out of the box (only
    # accountant_user does), and the before_request hook clears an inaccessible
    # selected_branch_id and redirects to the picker -- so without this the POST
    # never reaches the view and every assertion fails for the wrong reason.
    if branch not in user.branches.all():
        user.branches.append(branch)
    # purchase_orders is optional + per_user, so the instance flag alone is not
    # enough: can_access_module falls through to book_permissions for anyone who
    # is not full-access. Open BOTH gates or the module gate bounces every
    # request and the assertions below pass or fail for the wrong reason.
    if not user.has_full_access:
        perms = dict(user.get_book_permissions() or {})
        perms.update({'purchase_orders': True, 'products': True})
        user.set_book_permissions(perms)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po(db_session, branch, vendor, number, user_id, status='draft', **sigs):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 19),
                       branch_id=branch.id, vendor_id=vendor.id,
                       vendor_name=vendor.name, status=status,
                       created_by_id=user_id, **sigs)
    # approve() refuses an order with no approvable line (has_approvable_line),
    # so a lineless PO would make every approve assertion fail for a reason that
    # has nothing to do with what is under test.
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Salt', quantity=Decimal('1'),
        unit_price=Decimal('10'), amount=Decimal('10')))
    po.calculate_totals()
    db_session.add(po)
    db_session.commit()
    return po


def _create(client, vendor, po_number, **extra):
    data = {'po_number': po_number, 'order_date': '2026-08-19',
            'vendor_id': str(vendor.id), 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'notes': '',
            'line_items': json.dumps([{'description': 'Salt', 'quantity': '1',
                                       'unit_price': '10', 'amount': '10'}])}
    data.update(extra)
    return client.post('/purchase-orders/create', data=data, follow_redirects=True)


class TestSignatoriesAreSavedPerOrder:

    def test_typed_signatories_persist(self, client, accountant_user, main_branch,
                                       vl_vendor, db_session):
        _login(client, accountant_user, main_branch)
        _create(client, vl_vendor, 'SIG-1', prepared_by='Angilyn',
                checked_by='Fred', approved_by='Juan')
        po = PurchaseOrder.query.filter_by(po_number='SIG-1').first()
        assert (po.prepared_by, po.checked_by, po.approved_by) == ('Angilyn', 'Fred', 'Juan')

    def test_blank_signatories_store_null_not_empty_string(self, client, accountant_user,
                                                           main_branch, vl_vendor, db_session):
        """A blank must not become '', or 'has this been filled in?' stops being
        answerable and the carry-forward would propagate emptiness as a value."""
        _login(client, accountant_user, main_branch)
        _create(client, vl_vendor, 'SIG-2', prepared_by='   ')
        po = PurchaseOrder.query.filter_by(po_number='SIG-2').first()
        assert po.prepared_by is None


class TestCarryForwardIsPerPurchaser:

    def test_a_new_order_prefills_from_this_purchasers_last_one(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        _po(db_session, main_branch, vl_vendor, 'CF-1', accountant_user.id,
            prepared_by='Angilyn', checked_by='Fred', approved_by='Juan')
        _login(client, accountant_user, main_branch)
        body = client.get('/purchase-orders/create').data.decode()
        assert 'value="Angilyn"' in body
        assert 'value="Fred"' in body
        assert 'value="Juan"' in body

    def test_another_purchasers_order_does_NOT_leak(self, client, accountant_user,
                                                    admin_user, main_branch, vl_vendor,
                                                    db_session):
        """The load-bearing case: two purchasers, two pads, two sets of people."""
        _po(db_session, main_branch, vl_vendor, 'CF-2', admin_user.id,
            prepared_by='OtherPurchaser', checked_by='OtherChecker')
        _login(client, accountant_user, main_branch)
        body = client.get('/purchase-orders/create').data.decode()
        assert 'OtherPurchaser' not in body
        assert 'OtherChecker' not in body

    def test_a_purchaser_with_no_prior_order_gets_blanks(self, client, accountant_user,
                                                         main_branch, db_session):
        _login(client, accountant_user, main_branch)
        body = client.get('/purchase-orders/create').data.decode()
        assert 'name="prepared_by"' in body       # the field renders...
        assert 'value="None"' not in body         # ...and never as the string None

    def test_the_carry_forward_takes_the_LATEST_order(self, client, accountant_user,
                                                      main_branch, vl_vendor, db_session):
        _po(db_session, main_branch, vl_vendor, 'CF-3', accountant_user.id,
            prepared_by='Older')
        _po(db_session, main_branch, vl_vendor, 'CF-4', accountant_user.id,
            prepared_by='Newer')
        _login(client, accountant_user, main_branch)
        body = client.get('/purchase-orders/create').data.decode()
        assert 'value="Newer"' in body
        assert 'value="Older"' not in body

    def test_editing_one_order_does_not_touch_another(self, client, accountant_user,
                                                      main_branch, vl_vendor, db_session):
        """CONTROL: the carry-forward is a SUGGESTION. If it were shared state,
        editing the newer order would rewrite the older one."""
        old = _po(db_session, main_branch, vl_vendor, 'CF-5', accountant_user.id,
                  prepared_by='Original')
        _login(client, accountant_user, main_branch)
        _create(client, vl_vendor, 'CF-6', prepared_by='Changed')
        db_session.refresh(old)
        assert old.prepared_by == 'Original'


class TestSubmitStep:

    def test_staff_can_submit_a_draft(self, client, staff_user, main_branch,
                                      vl_vendor, db_session):
        """The whole point: approve is accountant-or-above, so without this a
        staff purchaser's draft had nowhere to go."""
        from app.audit.models import AuditLog
        po = _po(db_session, main_branch, vl_vendor, 'SUB-1', staff_user.id)
        _login(client, staff_user, main_branch)
        client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        db_session.refresh(po)
        assert po.status == 'submitted'
        assert po.submitted_by_id == staff_user.id
        assert po.submitted_at is not None
        assert AuditLog.query.filter_by(module='purchase_orders', action='submit').first()

    def test_a_submitted_order_cannot_be_submitted_again(self, client, staff_user,
                                                         main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor, 'SUB-2', staff_user.id,
                 status='submitted')
        _login(client, staff_user, main_branch)
        resp = client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        assert b'Only a draft Purchase Order can be submitted' in resp.data

    def test_an_approver_can_approve_a_submitted_order(self, client, accountant_user,
                                                       main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor, 'SUB-3', accountant_user.id,
                 status='submitted')
        _login(client, accountant_user, main_branch)
        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        db_session.refresh(po)
        assert po.status == 'approved'

    def test_an_approver_can_still_approve_straight_from_draft(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        """CONTROL: adding a submit step must not force an approver to submit an
        order to herself. The requisition behaves the same way."""
        po = _po(db_session, main_branch, vl_vendor, 'SUB-4', accountant_user.id)
        _login(client, accountant_user, main_branch)
        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        db_session.refresh(po)
        assert po.status == 'approved'

    def test_staff_still_cannot_approve(self, client, staff_user, main_branch,
                                        vl_vendor, db_session):
        """CONTROL on the authz boundary: submit opened up, approve did not."""
        po = _po(db_session, main_branch, vl_vendor, 'SUB-5', staff_user.id,
                 status='submitted')
        _login(client, staff_user, main_branch)
        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        db_session.refresh(po)
        assert po.status == 'submitted'

    def test_the_detail_page_offers_submit_to_staff_but_not_approve(
            self, client, staff_user, main_branch, vl_vendor, db_session):
        """Route-level and template-level gates must agree -- a backend-only
        change with no reachable button is invisible to a POST-driven test."""
        po = _po(db_session, main_branch, vl_vendor, 'SUB-6', staff_user.id)
        _login(client, staff_user, main_branch)
        body = client.get(f'/purchase-orders/{po.id}').data.decode()
        assert f'/purchase-orders/{po.id}/submit' in body
        assert f'/purchase-orders/{po.id}/approve' not in body


class TestActionItems:

    def test_a_draft_order_appears_in_the_draft_list(self, accountant_user, main_branch,
                                                     vl_vendor, db_session):
        from app.dashboard.action_items_service import gather_draft_items
        _po(db_session, main_branch, vl_vendor, 'AI-1', accountant_user.id)
        items = gather_draft_items(accountant_user, main_branch.id)
        assert any(i.get('ref') == 'AI-1' or 'AI-1' in str(i.values()) for i in items)

    def test_a_submitted_order_appears_in_the_approval_list(self, accountant_user,
                                                            main_branch, vl_vendor,
                                                            db_session):
        from app.dashboard.action_items_service import gather_document_approval_items
        _po(db_session, main_branch, vl_vendor, 'AI-2', accountant_user.id,
            status='submitted')
        items = gather_document_approval_items(accountant_user, main_branch.id)
        assert any('AI-2' in str(i.values()) for i in items)

    def test_orders_are_hidden_when_the_module_is_off(self, accountant_user, main_branch,
                                                      vl_vendor, db_session):
        """CONTROL: Action Items must never be a side channel around the module
        gate the rest of the app enforces."""
        from app.dashboard.action_items_service import gather_draft_items
        from app.utils.cache_helpers import clear_module_config_cache
        _po(db_session, main_branch, vl_vendor, 'AI-3', accountant_user.id)
        AppSettings.set_setting('module_enabled:purchase_orders', '0')
        db_session.commit()
        clear_module_config_cache()
        items = gather_draft_items(accountant_user, main_branch.id)
        assert not any('AI-3' in str(i.values()) for i in items)


class TestPrint:

    def test_the_standard_print_carries_the_signatories(self, client, accountant_user,
                                                        main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor, 'PRN-1', accountant_user.id,
                 status='approved', prepared_by='Angilyn', checked_by='Fred',
                 approved_by='Juan')
        AppSettings.set_setting('po_print_form', 'current')
        db_session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-orders/{po.id}/print').data.decode()
        for name in ('Angilyn', 'Fred', 'Juan'):
            assert name in body
        for label in ('Prepared by', 'Checked by', 'Approved by'):
            assert label in body

    def test_a_blank_signatory_prints_a_line_not_a_placeholder(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor, 'PRN-2', accountant_user.id,
                 status='approved')
        AppSettings.set_setting('po_print_form', 'current')
        db_session.commit()
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-orders/{po.id}/print').data.decode()
        assert 'Prepared by' in body          # the ruled line and label render...
        assert 'None' not in body.split('sig-row')[-1]   # ...with no stringified None
