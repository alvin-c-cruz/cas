"""A REFUSED Purchase Order save must hand the buyer her line items back.

BUG-PO-CREATE-DROPS-LINES-ON-VALIDATION-REJECT. Reported from the field by the
PhilGen purchaser on 2026-08-29: "sir sa PO bakit po pag nag sesave ako nawawala
po yung items na ginagawa ko po??" ... "nung inulit ko lagay pag save ko nawala
ulit sya sir" -- the lines vanish on save, and vanish again on every retry.

`create()` re-rendered each rejection with a hardcoded `line_items=[]`, so the
POST's own lines were thrown away. `edit()` a hundred lines below already
restores them from `request.form['line_items']`; create simply never did.

The retry is the tell, and it is `next_po_number_for()`: the suggestion comes off
each purchaser's OWN pad, so hers is the same colliding number every time. She
could not get a PO in at all without knowing to retype the number by hand.

RENDER assertions, deliberately: the defect is what the redisplayed FORM carries.
A route-level test that only checked "no order was created" passes just as
happily while every line is still being dropped.
"""
import json

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

LINE_DESC = 'PORTLAND CEMENT 40KG'
SECOND_DESC = 'REBAR 6M X 8MM'


@pytest.fixture(autouse=True)
def _po_enabled(db_session):
    for key in ('products', 'purchase_orders'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def vendor(db_session):
    v = Vendor(code='V-REJ', name='CITI HARDWARE', is_active=True)
    db.session.add(v)
    db.session.commit()
    return v


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _lines(*descriptions):
    return json.dumps([
        {'description': d, 'quantity': '50', 'unit_price': '280', 'amount': '14000'}
        for d in descriptions])


def _form(vendor_id, po_number, lines, **extra):
    data = {'po_number': po_number, 'order_date': '2026-08-30',
            'vendor_id': str(vendor_id), 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'notes': '', 'line_items': lines}
    data.update(extra)
    return data


class TestTheRejectedSaveGivesTheLinesBack:

    def test_a_duplicate_number_does_not_cost_the_buyer_her_lines(
            self, client, db_session, admin_user, main_branch, vendor):
        """THE REPRODUCTION -- exactly what the purchaser hit."""
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00004', _lines(LINE_DESC)))

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'Purchase Order number already exists.' in body, \
            'the duplicate was not refused -- this test is no longer exercising the reject path'
        assert LINE_DESC in body, \
            'the refused save discarded the line items the buyer had entered'

    def test_every_line_comes_back_not_merely_the_first(
            self, client, db_session, admin_user, main_branch, vendor):
        """A real order is multi-line; restoring one line would still lose work."""
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00004',
                                      _lines(LINE_DESC, SECOND_DESC)))

        body = resp.data.decode()
        assert LINE_DESC in body and SECOND_DESC in body, \
            'not every line survived the refused save'

    def test_an_unknown_vendor_also_gives_the_lines_back(
            self, client, db_session, admin_user, main_branch, vendor):
        """The second rejection path in create() carried the identical defect."""
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-orders/create',
                           data=_form(999999, '00042', _lines(LINE_DESC)))

        body = resp.data.decode()
        assert resp.status_code == 200
        assert LINE_DESC in body, \
            'the vendor-not-found refusal discarded the line items'

    def test_a_wtforms_validation_failure_also_gives_the_lines_back(
            self, client, db_session, admin_user, main_branch, vendor):
        """The MOST ordinary failure of all -- a required header field left blank
        -- never even reaches the two explicit rejections: it falls through to the
        function's final render, which served the fresh GET and the failed POST
        from the same hardcoded empty list."""
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '', _lines(LINE_DESC)))

        body = resp.data.decode()
        assert resp.status_code == 200
        assert LINE_DESC in body, \
            'a plain validation failure discarded the line items'


class TestTheRestoredLineKeepsItsUnit:
    """Handing the row back WITHOUT its unit is still lost work.

    Caught in the browser, not by the first round of tests: the refused save
    returned the product, description, quantity and price -- and an empty UOM
    cell. The two ends of the round trip spell the field differently. The form
    posts `uom_id` (form.html:505) while the row renderer reads
    `d.unit_of_measure_id` (form.html:336), which is what `to_dict()` emits, so
    the restored dict simply had no key the renderer recognised.

    Normalised in PYTHON rather than by teaching the JS a second spelling: the
    server is the layer pytest can actually hold, and edit()'s POST-failure
    restore feeds the identical renderer from the identical payload, so one fix
    covers both.
    """

    def _restored(self, body):
        """The line array the page hands its row renderer (`const EXISTING`)."""
        import re
        m = re.search(r'const EXISTING = (\[.*?\]);', body, re.S)
        assert m, 'the form no longer embeds its line items as EXISTING'
        return json.loads(m.group(1))

    def test_the_unit_survives_a_refused_save(
            self, client, db_session, admin_user, main_branch, vendor):
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'description': LINE_DESC, 'quantity': '50',
                             'unit_price': '280', 'amount': '14000',
                             'uom_id': 7}])

        body = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00004', lines)).data.decode()

        restored = self._restored(body)
        assert len(restored) == 1, 'the line did not come back at all'
        assert restored[0].get('unit_of_measure_id') == 7, (
            'the restored line lost its unit -- the renderer reads '
            'unit_of_measure_id and the POST spells it uom_id')

    def test_a_line_that_already_uses_the_renderer_spelling_is_untouched(
            self, client, db_session, admin_user, main_branch, vendor):
        """CONTROL. The normalisation must not overwrite a value that is already
        in the renderer's own spelling -- which is the shape edit()'s GET path
        supplies straight off to_dict()."""
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'description': LINE_DESC, 'quantity': '50',
                             'unit_price': '280', 'amount': '14000',
                             'unit_of_measure_id': 3, 'uom_id': 9}])

        body = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00004', lines)).data.decode()

        assert self._restored(body)[0]['unit_of_measure_id'] == 3, \
            'normalisation clobbered a unit the renderer could already read'

    def test_a_free_text_unit_is_not_given_a_bogus_id(
            self, client, db_session, admin_user, main_branch, vendor):
        """CONTROL. A services line carries uom_text and NO master FK. Inventing
        an id for it would bind the line to whatever unit happened to hold that
        row id."""
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'description': LINE_DESC, 'quantity': '1',
                             'unit_price': '100', 'amount': '100',
                             'uom_id': None, 'uom_text': 'LOT'}])

        body = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00004', lines)).data.decode()

        restored = self._restored(body)[0]
        assert restored.get('unit_of_measure_id') is None, \
            'a free-text unit was handed a fabricated master id'
        assert restored.get('uom_text') == 'LOT', 'the free-text unit was dropped'


class TestTheControls:

    def test_a_fresh_create_form_is_still_empty(
            self, client, db_session, admin_user, main_branch, vendor):
        """CONTROL, and the reason the final render could not simply be swapped:
        that one call serves BOTH the failed POST and the fresh GET. Restoring
        unconditionally would pre-fill a brand-new order with the previous
        request's lines."""
        _login(client, admin_user, main_branch)

        body = client.get('/purchase-orders/create').data.decode()

        assert LINE_DESC not in body and SECOND_DESC not in body, \
            'a brand-new PO form arrived with line items already on it'

    def test_a_refused_save_still_creates_no_order(
            self, client, db_session, admin_user, main_branch, vendor):
        """CONTROL. Handing the lines back must not quietly let the order
        through: the refusal is correct and must stay a refusal."""
        db.session.add(PurchaseOrder(branch_id=main_branch.id, po_number='00004',
                                     vendor_name='SOMEONE ELSE'))
        db.session.commit()
        _login(client, admin_user, main_branch)

        client.post('/purchase-orders/create',
                    data=_form(vendor.id, '00004', _lines(LINE_DESC)))

        assert PurchaseOrder.query.filter_by(po_number='00004').count() == 1, \
            'the refused save created a SECOND order on the duplicate number'

    def test_a_good_save_still_works(
            self, client, db_session, admin_user, main_branch, vendor):
        """CONTROL. The happy path is untouched."""
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-orders/create',
                           data=_form(vendor.id, '00077', _lines(LINE_DESC)),
                           follow_redirects=True)

        assert resp.status_code == 200
        po = PurchaseOrder.query.filter_by(po_number='00077').first()
        assert po is not None, 'a valid Purchase Order no longer saves'
        assert [li.description for li in po.line_items] == [LINE_DESC]
