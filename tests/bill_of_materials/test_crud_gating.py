"""BOM CRUD + module gating + mode-availability tests (R-07 Wave 0)."""
import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache, clear_product_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable_bom(db_session):
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()


def _enable_discrete(db_session):
    AppSettings.set_setting('manufacturing_discrete_enabled', '1')
    db_session.commit()


def _product(db_session, code='BOMV-1'):
    from app import db
    from app.products.models import Product
    p = Product(code=code, name='Output Widget', is_active=True)
    db.session.add(p); db.session.commit()
    clear_product_cache()
    return p


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    # get_module_override() is memoized for 1h -- clear it so this test proves the
    # OFF state regardless of what an earlier test in this run already enabled
    # (mirrors bank_reconciliation/bank_transfers/petty_cash's identical guard).
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.get('/bill-of-materials/')
    assert resp.status_code == 404


def test_every_endpoint_404_when_module_off(client, accountant_user, db_session, main_branch):
    # Module is deliberately left OFF (not enabled) for this whole test.
    clear_module_config_cache()
    out = _product(db_session, 'BOMV-OFF')
    _login(client, accountant_user, main_branch)
    assert client.get('/bill-of-materials/').status_code == 404
    assert client.get('/bill-of-materials/new').status_code == 404
    assert client.post('/bill-of-materials/new', data={}).status_code == 404
    assert client.get(f'/bill-of-materials/{out.id}/edit').status_code == 404
    assert client.post(f'/bill-of-materials/{out.id}/edit', data={}).status_code == 404
    assert client.post(f'/bill-of-materials/{out.id}/toggle-active').status_code == 404


def test_create_blocked_when_no_mode_enabled(client, accountant_user, db_session, main_branch):
    _enable_bom(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/bill-of-materials/new', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Enable Discrete or Process Manufacturing' in resp.data


def test_create_bom(client, accountant_user, db_session, main_branch):
    _enable_bom(db_session)
    _enable_discrete(db_session)
    out = _product(db_session, 'BOMV-OUT')
    comp = _product(db_session, 'BOMV-COMP')
    _login(client, accountant_user, main_branch)
    resp = client.post('/bill-of-materials/new', data={
        'product_id': out.id, 'manufacturing_mode': 'discrete',
        'lines': f'[{{"component_product_id": {comp.id}, "quantity_per": "3.0000"}}]',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.bill_of_materials.models import BillOfMaterial
    bom = BillOfMaterial.query.filter_by(product_id=out.id).one()
    assert bom.manufacturing_mode == 'discrete'
    assert len(bom.lines) == 1


def test_product_picker_excludes_products_with_existing_bom(client, accountant_user, db_session, main_branch):
    _enable_bom(db_session)
    _enable_discrete(db_session)
    out = _product(db_session, 'BOMV-TAKEN')
    _product(db_session, 'BOMV-COMP2')
    _login(client, accountant_user, main_branch)
    client.post('/bill-of-materials/new', data={
        'product_id': out.id, 'manufacturing_mode': 'discrete', 'lines': '[]',
    }, follow_redirects=True)
    resp = client.get('/bill-of-materials/new')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert f'value="{out.id}"' not in body


def test_sidebar_shows_bom_when_enabled(client, admin_user, db_session, main_branch):
    _enable_bom(db_session)
    _login(client, admin_user, main_branch)
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'bill_of_materials.list_boms' in body or 'bill-of-materials' in body
