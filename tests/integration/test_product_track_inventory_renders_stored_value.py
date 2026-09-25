"""The product edit form ticks Track Inventory exactly when the stored value is true.

docs/bug-reports/2026-09-23-product-master-duplicate-and-track-inventory-default.md, section 2,
reported that the edit form "shows track_inventory as 'y'" for products whose stored value is 0,
and concluded the form misstated the record. It does not: WTForms renders EVERY checkbox with
the fixed submit value `value="y"`; whether it is ticked is the separate `checked` attribute,
which follows the stored value. The report read `input.value`. Pinned here (2026-09-25) so the
non-bug is not "fixed" into a real one.
"""
import re

import pytest

from app import db
from app.products.models import Product
from tests.integration.test_products_crud import _login, products_module_enabled  # noqa: F401

pytestmark = [pytest.mark.integration]


@pytest.fixture
def inventory_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:inventory', '1'); db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.mark.parametrize('stored', [False, True])
def test_checked_follows_the_stored_value(client, db_session, admin_user, main_branch,
                                          products_module_enabled, inventory_on, stored):
    p = Product(name=f'TRACK {stored}', is_active=True, track_inventory=stored)
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)

    html = client.get(f'/products/{p.id}/edit').get_data(as_text=True)

    tag = re.search(r'<input[^>]*id="track_inventory"[^>]*>', html)
    assert tag, 'the Track Inventory checkbox is not rendered'
    assert (' checked' in tag.group(0)) is stored
    assert 'value="y"' in tag.group(0), 'the submit value is constant; it is not the state'
