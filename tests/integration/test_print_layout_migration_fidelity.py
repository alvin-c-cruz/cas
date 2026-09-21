"""AC 6: printing a PO immediately before and after the migration must be IDENTICAL.

The payload is copied RAW, never re-sanitized. A stored layout is sanitized at READ
time against whatever the defaults currently are; sanitizing at WRITE time instead
would bake today's defaults into a value that was hand-aligned on paper months ago.
"""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout
from app.purchase_orders.preprinted_layout import get_layout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _seed_legacy(branch_id=1):
    """A layout with hand-aligned, non-default coordinates -- the realistic case.

    NOTE: the brief's worked example mutates `fields['pr_number']`, but on the
    real Purchase Order layout `pr_number` is a lineItems COLUMN key
    (DEFAULT_PO_PREPRINTED_LAYOUT['lineItems']['columns']), not a top-level
    field -- `get_layout()['fields']` has no such key (confirmed: FIELD_KEYS in
    app/purchase_orders/preprinted_layout.py lists po_no, order_date, ...,
    approved_by; pr_number is absent). Using it as written raises KeyError
    before the module under test is even reached. `po_no` is used instead,
    which IS a real field key, to keep the same intent -- a hand-aligned,
    non-default coordinate on a field that will actually be present.
    """
    lay = get_layout(branch_id=branch_id)
    lay['fields']['po_no']['x'] = 48
    lay['fields']['po_no']['w'] = 44
    raw = json.dumps(lay)
    AppSettings.set_setting(f'po_preprinted_layout:{branch_id}', raw, 'system')
    return raw


def test_the_migration_copies_the_payload_byte_for_byte(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    raw = _seed_legacy()
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    row = PrintLayout.query.filter_by(doc_type='purchase_orders', scope_id=1).one()
    assert row.payload == raw, 'payload was transformed on the way in'
    assert row.is_default is True


def test_get_layout_is_identical_before_and_after(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    _seed_legacy()
    before = get_layout(branch_id=1)
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    after = get_layout(branch_id=1)
    assert before == after


def test_the_unscoped_key_lands_on_scope_zero(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    lay = json.dumps(get_layout())
    AppSettings.set_setting('po_preprinted_layout', lay, 'system')
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    row = PrintLayout.query.filter_by(doc_type='purchase_orders', scope_id=0).one()
    assert row.name == 'Default'


def test_running_the_seed_twice_changes_nothing(db_session):
    """Migrations get re-run against restored databases. Idempotence is not optional."""
    from app.print_layouts.migrate import seed_from_app_settings
    _seed_legacy()
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    assert PrintLayout.query.count() == 1
