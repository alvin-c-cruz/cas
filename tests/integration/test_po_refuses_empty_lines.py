"""A Purchase Order may not be saved with no lines, nor submitted unpriced.

FOUND 2026-10-17 by the ripple check of BUG-PR-DRAFT-EDIT-SAVES-WITH-NO-LINES
(Philgen PR 01021, whose draft Update deleted both lines and flashed "updated").
The PO module had the same holes, wider:

  * edit() hard-deletes every line of the draft and rebuilds from the posted
    payload; create() builds from it. _parse_and_attach_po_lines skips blank rows
    and refused nothing when it kept none, so either save could leave an order
    with no lines and still report success.
  * The form's hidden line field started as value="[]". Its submit serialiser
    runs only once the script at the bottom of the page has -- after the whole
    product list -- so a save clicked while the page is still loading posted
    "[]", which reads exactly like "the user deleted every row". In a browser on
    a copy of Philgen's books that emptied a two-line requisition.
  * submit() checked only the vendor. A submitted order can be RECEIVED against
    (receiving_reports.RECEIVABLE_PO_STATUSES) but has no Return to Draft, so an
    order approve() would refuse ended up received and stuck.

Owner's rule (2026-10-17): a save needs at least one line with a product or a
description -- a draft may still be unpriced while quotes come in -- and submit
needs a priced line, the same predicate approve() uses (has_approvable_line).
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

STORED = 'PORTLAND CEMENT 40KG'


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def vendor(db_session):
    v = Vendor(code='V-EMPTY', name='CITI HARDWARE', is_active=True)
    db.session.add(v)
    db.session.commit()
    return v


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


PRICED = ((STORED, '10', '280'),)


def _po(db_session, branch, vendor, number, status='draft', lines=PRICED):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 10, 17), status=status,
                       branch_id=branch.id, vendor_id=vendor.id, vendor_name=vendor.name,
                       notes='Deliver to the plant', payment_terms='Net 30',
                       vat_treatment='inclusive')
    for n, (desc, qty, price) in enumerate(lines, start=1):
        item = PurchaseOrderItem(line_number=n, description=desc, quantity=Decimal(qty),
                                 unit_price=Decimal(price) if price else None)
        item.calculate_amounts()
        po.line_items.append(item)
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _header(vendor, number, **extra):
    data = {'po_number': number, 'order_date': '2026-10-17', 'vendor_id': str(vendor.id),
            'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'notes': 'Re-specified'}
    data.update(extra)
    return data


def _line(description=STORED, price='280'):
    amount = str(Decimal('10') * Decimal(price)) if price else '0'
    return {'description': description, 'quantity': '10', 'unit_price': price,
            'amount': amount}


def _edit(client, po, line_items=None, omit_line_items=False):
    data = _header(po.vendor, po.po_number, row_version=str(po.row_version))
    if not omit_line_items:
        data['line_items'] = line_items
    return client.post(f'/purchase-orders/{po.id}/edit', data=data, follow_redirects=True)


def _create(client, vendor, number, line_items=None, omit_line_items=False):
    data = _header(vendor, number)
    if not omit_line_items:
        data['line_items'] = line_items
    return client.post('/purchase-orders/create', data=data, follow_redirects=True)


def _descriptions(db_session, po):
    db_session.refresh(po)
    return [li.description for li in po.line_items]


def _actions_for(po):
    return [a.action for a in AuditLog.query.filter_by(
        module='purchase_orders', record_id=po.id).all()]


def _hidden_line_field(html):
    tag = re.search(r'<input[^>]*id="lineItemsJson"[^>]*>', html)
    assert tag, 'the form must carry the hidden line field'
    return tag.group(0)


class TestAnUpdateMustLeaveALine:

    def test_an_update_with_no_lines_is_refused(self, client, accountant_user,
                                                main_branch, vendor, db_session):
        """THE regression -- PR 01021's Update, replayed on a Purchase Order."""
        po = _po(db_session, main_branch, vendor, 'EMPTY-EDIT-1')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, '[]')
        assert resp.status_code == 200
        assert b'needs at least one line' in resp.data
        assert _descriptions(db_session, po) == [STORED]
        assert 'update' not in _actions_for(po)

    def test_an_update_with_only_blank_rows_is_refused(self, client, accountant_user,
                                                       main_branch, vendor, db_session):
        """Blank rows are skipped as trailing lines, so they keep nothing either."""
        po = _po(db_session, main_branch, vendor, 'EMPTY-EDIT-2')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, json.dumps([
            {}, {'product_id': None, 'description': None, 'quantity': None,
                 'unit_price': None, 'amount': '0'}]))
        assert b'needs at least one line' in resp.data
        assert _descriptions(db_session, po) == [STORED]

    def test_a_refused_update_writes_nothing_else(self, client, accountant_user,
                                                  main_branch, vendor, db_session):
        """The header change rides in the same request. The rollback must take it,
        the bulk line DELETE, AND claim_version's row_version bump -- or the
        user's next save false-conflicts against their own stale token."""
        po = _po(db_session, main_branch, vendor, 'EMPTY-EDIT-3')
        version = po.row_version
        _login(client, accountant_user, main_branch)
        _edit(client, po, '[]')
        db_session.refresh(po)
        assert po.notes == 'Deliver to the plant'
        assert po.row_version == version

    def test_an_unpriced_line_is_still_a_line(self, client, accountant_user,
                                              main_branch, vendor, db_session):
        """CONTROL, and the owner's rule: a draft may be saved before the prices
        are known. Pricing is judged at submit and approve, not here."""
        po = _po(db_session, main_branch, vendor, 'EMPTY-EDIT-4')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, json.dumps([_line('CEMENT, PRICE TO FOLLOW', price=None)]))
        assert b'updated successfully' in resp.data
        assert _descriptions(db_session, po) == ['CEMENT, PRICE TO FOLLOW']


class TestLinesThatNeverReachedTheServer:

    def test_a_blank_line_field_is_refused_and_says_so(self, client, accountant_user,
                                                       main_branch, vendor, db_session):
        """What the form now posts when Update is clicked before its script ran.
        Pin the MESSAGE: the minimum-line rule would refuse it too, and blame the
        user for deleting rows they never touched."""
        po = _po(db_session, main_branch, vendor, 'NOARRIVE-1')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, '')
        assert b'did not reach the server' in resp.data
        assert b'needs at least one line' not in resp.data
        assert _descriptions(db_session, po) == [STORED]
        assert 'update' not in _actions_for(po)

    def test_an_absent_line_field_is_refused_and_says_so(self, client, accountant_user,
                                                         main_branch, vendor, db_session):
        po = _po(db_session, main_branch, vendor, 'NOARRIVE-2')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, omit_line_items=True)
        assert b'did not reach the server' in resp.data
        assert _descriptions(db_session, po) == [STORED]

    @pytest.mark.parametrize('raw', ['{not json', '[1,2', '123', '"a string"', 'null'])
    def test_an_unreadable_line_field_is_refused_without_a_500(
            self, client, accountant_user, main_branch, vendor, db_session, raw):
        po = _po(db_session, main_branch, vendor, 'NOARRIVE-3')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, raw)
        assert resp.status_code == 200
        assert b'could not be read' in resp.data
        assert _descriptions(db_session, po) == [STORED]

    def test_the_refusal_puts_the_stored_lines_back_on_screen(
            self, client, accountant_user, main_branch, vendor, db_session):
        """Re-rendering the posted payload would show an empty grid -- the very
        picture that invites the next empty Update."""
        po = _po(db_session, main_branch, vendor, 'NOARRIVE-4')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, po, '')
        assert STORED.encode() in resp.data


class TestACreateMustHaveALine:

    def test_a_create_with_no_lines_is_refused(self, client, accountant_user,
                                               main_branch, vendor, db_session):
        _login(client, accountant_user, main_branch)
        resp = _create(client, vendor, 'EMPTY-NEW-1', '[]')
        assert b'needs at least one line' in resp.data
        assert PurchaseOrder.query.filter_by(po_number='EMPTY-NEW-1').count() == 0

    @pytest.mark.parametrize('omit', [False, True], ids=['blank', 'absent'])
    def test_a_create_whose_lines_never_arrived_says_so(
            self, client, accountant_user, main_branch, vendor, db_session, omit):
        _login(client, accountant_user, main_branch)
        resp = _create(client, vendor, 'EMPTY-NEW-2', '', omit_line_items=omit)
        assert b'did not reach the server' in resp.data
        assert PurchaseOrder.query.filter_by(po_number='EMPTY-NEW-2').count() == 0

    def test_an_unreadable_create_is_refused_without_a_500(
            self, client, accountant_user, main_branch, vendor, db_session):
        _login(client, accountant_user, main_branch)
        resp = _create(client, vendor, 'EMPTY-NEW-3', '{not json')
        assert resp.status_code == 200
        assert b'could not be read' in resp.data
        assert PurchaseOrder.query.filter_by(po_number='EMPTY-NEW-3').count() == 0

    def test_an_unpriced_draft_can_still_be_created(self, client, accountant_user,
                                                    main_branch, vendor, db_session):
        """CONTROL -- the owner's rule allows a draft before prices are known."""
        _login(client, accountant_user, main_branch)
        resp = _create(client, vendor, 'EMPTY-NEW-4',
                       json.dumps([_line('CEMENT, PRICE TO FOLLOW', price=None)]))
        assert b'created successfully' in resp.data
        po = PurchaseOrder.query.filter_by(po_number='EMPTY-NEW-4').one()
        assert [li.description for li in po.line_items] == ['CEMENT, PRICE TO FOLLOW']


class TestTheFormStartsWithoutAPayload:
    """The serialiser's starting value must not be a valid "no lines" payload."""

    def test_on_the_edit_page(self, client, accountant_user, main_branch, vendor,
                              db_session):
        po = _po(db_session, main_branch, vendor, 'HIDDEN-1')
        _login(client, accountant_user, main_branch)
        tag = _hidden_line_field(
            client.get(f'/purchase-orders/{po.id}/edit').get_data(as_text=True))
        assert 'value=""' in tag and '[]' not in tag

    def test_on_the_create_page(self, client, accountant_user, main_branch):
        _login(client, accountant_user, main_branch)
        tag = _hidden_line_field(
            client.get('/purchase-orders/create').get_data(as_text=True))
        assert 'value=""' in tag and '[]' not in tag


class TestSubmitNeedsAPricedLine:
    """approve() refuses an order without a priced line, and a submitted order
    can already be received against with no way back to draft -- so submit must
    not hand over an order the approver cannot approve."""

    def test_submitting_with_no_lines_is_refused(self, client, accountant_user,
                                                 main_branch, vendor, db_session):
        po = _po(db_session, main_branch, vendor, 'EMPTY-SUBMIT-1', lines=())
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        assert b'with a unit price before submitting' in resp.data
        db_session.refresh(po)
        assert po.status == 'draft'
        assert 'submit' not in _actions_for(po)

    def test_submitting_with_only_unpriced_lines_is_refused(
            self, client, accountant_user, main_branch, vendor, db_session):
        po = _po(db_session, main_branch, vendor, 'EMPTY-SUBMIT-2',
                 lines=((STORED, '10', None),))
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        assert b'with a unit price before submitting' in resp.data
        db_session.refresh(po)
        assert po.status == 'draft'

    def test_submitting_with_a_priced_line_still_works(self, client, accountant_user,
                                                       main_branch, vendor, db_session):
        """CONTROL -- the guard must refuse only the order approve() would."""
        po = _po(db_session, main_branch, vendor, 'EMPTY-SUBMIT-3')
        _login(client, accountant_user, main_branch)
        client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        db_session.refresh(po)
        assert po.status == 'submitted'


class TestTheAmendScreenReadsABlankFieldTheSameWay:
    """It shares the template, so it now receives "" where it used to receive
    "[]". It must say the lines did not arrive, not judge "" as a proposal to
    remove every line."""

    def test_amend(self, client, accountant_user, main_branch, vendor, db_session):
        po = _po(db_session, main_branch, vendor, 'BLANK-AMEND-1', status='approved')
        _login(client, accountant_user, main_branch)
        data = _header(vendor, po.po_number, row_version=str(po.row_version),
                       amend_reason='vendor corrected the quantity', line_items='')
        resp = client.post(f'/purchase-orders/{po.id}/amend', data=data,
                           follow_redirects=True)
        assert b'did not reach the server' in resp.data
        assert _descriptions(db_session, po) == [STORED]
