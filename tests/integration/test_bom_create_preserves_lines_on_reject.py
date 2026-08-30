"""A REFUSED Bill of Materials save must hand back BOTH of its lists.

BUG-BOM-CREATE-DROPS-LINES-ON-REJECT. The fourth instance of the same defect --
a create view re-rendering a rejection with a hardcoded empty list -- and the one
the 2026-08-05 family-scoped sweep was furthest from finding, since Bills of
Materials are not a document family at all.

Two things make it differ from the Purchase Order and Purchase Requisition ports,
and both are places a mechanical copy would go wrong:

  * it loses TWO lists, not one. `line_items` AND `operations` (discrete mode).
    Restoring only the components would still cost the user every routing step.
  * the POST key is `lines`, while the template variable is `line_items`. A port
    that reused the PO spelling would read an absent key, restore nothing, and
    look exactly like a working fix.

It needs NO unit normalisation, unlike PO and PR: this form both writes and reads
`uom_id`, so applying the translation would invent a key its renderer never looks
at. That is why `restore_posted_lines` takes the flag rather than always doing it.
"""
import json

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial
from app.products.models import Product
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache, clear_product_cache

pytestmark = [pytest.mark.integration, pytest.mark.bill_of_materials]

COMPONENT_QTY = '12.5'


@pytest.fixture(autouse=True)
def _manufacturing_on(db_session):
    AppSettings.set_setting('manufacturing_discrete_enabled', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def products(db_session):
    made = []
    for code, name in (('FG-BOM', 'FINISHED WIDGET'), ('RM-BOM', 'RAW BAR STOCK')):
        p = Product(code=code, name=name, is_active=True)
        db.session.add(p)
        made.append(p)
    db.session.commit()
    clear_product_cache()
    yield made
    clear_product_cache()


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _post(client, product_id, lines, operations='[]', **over):
    data = {'product_id': str(product_id) if product_id else '',
            'manufacturing_mode': 'discrete',
            'lines': lines, 'operations': operations}
    data.update(over)
    return client.post('/bill-of-materials/new', data=data)


def _embedded(body, const_name):
    import re
    m = re.search(r'const %s = (\[.*?\]);' % const_name, body, re.S)
    return json.loads(m.group(1)) if m else None


class TestARefusedSaveGivesBothListsBack:

    def test_the_components_come_back(self, client, db_session, admin_user,
                                      main_branch, products):
        """A validation failure -- no product selected -- must not cost the user
        the component rows she has already built."""
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'component_product_id': products[1].id,
                             'quantity_per': COMPONENT_QTY, 'uom_id': None}])

        body = _post(client, None, lines).data.decode()

        assert BillOfMaterial.query.count() == 0, 'the invalid BOM was saved'
        restored = _embedded(body, 'existingItems')
        assert restored, 'the refused save discarded the component lines'
        assert str(restored[0].get('quantity_per')) == COMPONENT_QTY, \
            'the component came back without its quantity'

    def test_the_operations_come_back_too(self, client, db_session, admin_user,
                                          main_branch, products):
        """The second list. Restoring components alone would still throw away
        every routing step the user entered."""
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'component_product_id': products[1].id,
                             'quantity_per': COMPONENT_QTY, 'uom_id': None}])
        ops = json.dumps([{'sequence': 1, 'name': 'DEBURR', 'work_center_id': None}])

        body = _post(client, None, lines, operations=ops).data.decode()

        restored = _embedded(body, 'existingOperations')
        assert restored, 'the refused save discarded the operations'
        assert restored[0].get('name') == 'DEBURR', \
            'the operation came back without its name'

    def test_the_component_keeps_its_uom_key_unchanged(
            self, client, db_session, admin_user, main_branch, products):
        """CONTROL, and the reason the shared helper takes a flag. This form reads
        `uom_id`; translating it to `unit_of_measure_id` here would add a key the
        renderer never consults and silently blank the picker."""
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'component_product_id': products[1].id,
                             'quantity_per': COMPONENT_QTY, 'uom_id': 7}])

        body = _post(client, None, lines).data.decode()

        restored = _embedded(body, 'existingItems')[0]
        assert restored.get('uom_id') == 7, 'the component lost its unit'
        # The half that makes `normalise_uom=False` mean anything. Translating
        # here does not BREAK the unit -- `uom_id` survives either way -- it
        # quietly adds a key this renderer never consults, so an assertion on
        # uom_id alone cannot tell the flag from its absence. Asserting the
        # ABSENCE is what pins it.
        assert 'unit_of_measure_id' not in restored, (
            'the shared helper translated a unit key this form does not read -- '
            'normalise_uom=False was ignored')


class TestTheControls:

    def test_a_fresh_form_is_still_empty(self, client, db_session, admin_user,
                                         main_branch, products):
        """CONTROL. The one render serves the fresh GET as well as the failed
        POST, so restoring unconditionally would pre-fill a brand-new BOM."""
        _login(client, admin_user, main_branch)

        body = client.get('/bill-of-materials/new').data.decode()

        assert not _embedded(body, 'existingItems'), \
            'a brand-new BOM form arrived with component lines already on it'

    def test_a_good_save_still_works(self, client, db_session, admin_user,
                                     main_branch, products):
        """CONTROL. The happy path is untouched -- the assertion that caught the
        shadowed-builtin break when this fix was ported to Sales Orders."""
        _login(client, admin_user, main_branch)
        lines = json.dumps([{'component_product_id': products[1].id,
                             'quantity_per': COMPONENT_QTY, 'uom_id': None}])

        _post(client, products[0].id, lines)

        bom = BillOfMaterial.query.first()
        assert bom is not None, 'a valid Bill of Materials no longer saves'
        assert len(bom.lines) == 1, 'the saved BOM lost its component'
