"""P6 Task 7 -- the expected-loss percentage on the BOM form.

Process mode only: a discrete Work Order has no loss concept at all (D4's
force-close writes its shortfall off to inventory_variance), so the field is
hidden for that mode and never stored against a discrete BOM.

**A blank field must store NULL, not 0.** This is the same distinction Task 1's
column carries and it is the whole backward-compatibility guarantee: NULL means
nobody set an expectation, so all loss stays absorbed exactly as it has been since
P3; 0.00 means the process is expected to lose nothing, so ALL loss is abnormal and
gets charged to the P&L. An empty form field coerced to 0 would silently start
expensing every existing BOM's ordinary shrinkage.
"""
import pytest
from decimal import Decimal

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache, clear_product_cache

pytestmark = [pytest.mark.integration, pytest.mark.bill_of_materials]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session, discrete=False):
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    AppSettings.set_setting('manufacturing_process_enabled', '1')
    if discrete:
        AppSettings.set_setting('manufacturing_discrete_enabled', '1')
    db_session.commit(); clear_module_config_cache()


def _product(db_session, code):
    from app import db
    from app.products.models import Product
    p = Product(code=code, name='Output Widget', is_active=True)
    db.session.add(p); db.session.commit()
    clear_product_cache()
    return p


def _bom_for(product):
    from app.bill_of_materials.models import BillOfMaterial
    return BillOfMaterial.query.filter_by(product_id=product.id).one()


class TestTheFieldIsRendered:
    def test_the_new_bom_form_offers_the_field(
            self, client, accountant_user, db_session, main_branch):
        """Rendered, not merely accepted by the POST handler. A field the view will
        store but the form never shows is unreachable for the accountant."""
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        r = client.get('/bill-of-materials/new')
        assert r.status_code == 200
        assert b'normal_loss_pct' in r.data
        assert b'Expected Normal Loss' in r.data, 'labelled in the accountant\'s words'

    def test_the_field_sits_in_a_process_only_section(
            self, client, accountant_user, db_session, main_branch):
        """Mirrors how Routing is scoped to discrete mode -- one marked section the
        mode toggle shows or hides, rather than a field that silently applies to a
        mode it means nothing for."""
        _enable(db_session, discrete=True)
        _login(client, accountant_user, main_branch)
        r = client.get('/bill-of-materials/new')
        # The full attribute, not the bare id. A bare `b'processSection' in r.data`
        # passes on ANY id containing that substring, and passes again on the
        # getElementById() call in the page's own script even if the div is gone --
        # so it asserts almost nothing. Caught by a mutation that renamed the id to
        # notProcessSection and stayed green.
        assert b'id="processSection"' in r.data
        assert b'id="routingSection"' in r.data, 'the discrete counterpart still there'


class TestBlankStoresNull:
    def test_leaving_it_blank_stores_NULL_not_zero(
            self, client, accountant_user, db_session, main_branch):
        """The guarantee. 0 would reclassify every unset BOM's ordinary shrinkage as
        an abnormal loss and start charging it to the P&L."""
        _enable(db_session)
        out = _product(db_session, 'NLF-OUT-A')
        comp = _product(db_session, 'NLF-COMP-A')
        _login(client, accountant_user, main_branch)
        r = client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '',
            'lines': f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]',
        }, follow_redirects=True)
        assert r.status_code == 200
        bom = _bom_for(out)
        assert bom.normal_loss_pct is None
        assert bom.normal_loss_pct != Decimal('0')

    def test_an_explicit_zero_IS_stored(
            self, client, accountant_user, db_session, main_branch):
        """The complement, so the test above cannot pass by the view discarding
        every value. 0.00 is a real expectation -- this process should lose nothing
        -- and it must survive the round trip distinct from blank."""
        _enable(db_session)
        out = _product(db_session, 'NLF-OUT-B')
        comp = _product(db_session, 'NLF-COMP-B')
        _login(client, accountant_user, main_branch)
        client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '0',
            'lines': f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]',
        }, follow_redirects=True)
        bom = _bom_for(out)
        assert bom.normal_loss_pct == Decimal('0.00')
        assert bom.normal_loss_pct is not None


class TestStoringAndEditing:
    def test_a_percentage_round_trips_through_create_and_edit(
            self, client, accountant_user, db_session, main_branch):
        _enable(db_session)
        out = _product(db_session, 'NLF-OUT-C')
        comp = _product(db_session, 'NLF-COMP-C')
        _login(client, accountant_user, main_branch)
        lines = f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]'
        client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '3.50', 'lines': lines,
        }, follow_redirects=True)
        bom = _bom_for(out)
        assert bom.normal_loss_pct == Decimal('3.50')

        r = client.get(f'/bill-of-materials/{bom.id}/edit')
        assert b'3.50' in r.data, 'the stored value must come back into the form'

        client.post(f'/bill-of-materials/{bom.id}/edit', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '7.25', 'lines': lines,
            'row_version': bom.row_version,
        }, follow_redirects=True)
        db_session.refresh(bom)
        assert bom.normal_loss_pct == Decimal('7.25')

    def test_clearing_it_on_edit_returns_to_NULL(
            self, client, accountant_user, db_session, main_branch):
        """Setting an expectation must be reversible. Without this, the only way back
        to "no expectation" would be 0.00 -- which means the opposite."""
        _enable(db_session)
        out = _product(db_session, 'NLF-OUT-D')
        comp = _product(db_session, 'NLF-COMP-D')
        _login(client, accountant_user, main_branch)
        lines = f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]'
        client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '3.00', 'lines': lines,
        }, follow_redirects=True)
        bom = _bom_for(out)
        client.post(f'/bill-of-materials/{bom.id}/edit', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': '', 'lines': lines,
            'row_version': bom.row_version,
        }, follow_redirects=True)
        db_session.refresh(bom)
        assert bom.normal_loss_pct is None


class TestDiscreteModeNeverStoresIt:
    def test_a_discrete_bom_stores_NULL_even_if_a_value_is_submitted(
            self, client, accountant_user, db_session, main_branch):
        """The mirror of how operations are parsed only for discrete mode. The field
        is hidden for discrete, so a submitted value means the mode was switched
        after typing (or the POST was hand-made) -- either way a discrete BOM has no
        equivalent-units denominator to charge an excess against, so storing the
        number would create an expectation nothing could ever act on."""
        _enable(db_session, discrete=True)
        out = _product(db_session, 'NLF-OUT-E')
        comp = _product(db_session, 'NLF-COMP-E')
        _login(client, accountant_user, main_branch)
        client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'discrete',
            'normal_loss_pct': '5.00',
            'lines': f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]',
        }, follow_redirects=True)
        bom = _bom_for(out)
        assert bom.manufacturing_mode == 'discrete'
        assert bom.normal_loss_pct is None


class TestValidation:
    @pytest.mark.parametrize('bad', ['-1', '101', 'abc'])
    def test_a_nonsense_percentage_is_refused(
            self, client, accountant_user, db_session, main_branch, bad):
        """A negative allowance would make ordinary output abnormal; over 100% would
        allow losing more than was ever started. Neither is a typo worth storing."""
        _enable(db_session)
        out = _product(db_session, f'NLF-OUT-{bad}')
        comp = _product(db_session, f'NLF-COMP-{bad}')
        _login(client, accountant_user, main_branch)
        client.post('/bill-of-materials/new', data={
            'product_id': out.id, 'manufacturing_mode': 'process',
            'normal_loss_pct': bad,
            'lines': f'[{{"component_product_id": {comp.id}, "quantity_per": "2.0000"}}]',
        }, follow_redirects=True)
        from app.bill_of_materials.models import BillOfMaterial
        assert BillOfMaterial.query.filter_by(product_id=out.id).first() is None, \
            'the BOM must not be created with an impossible expectation'
