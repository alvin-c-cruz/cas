"""Resolution order: device pref -> is_default -> first row -> legacy key -> hardcoded.
Never a hard failure at any step."""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts.service import resolve_payload
from app.purchase_orders.preprinted_layout import get_layout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

DOC, SCOPE = 'purchase_orders', 1


def _row(name, payload, is_default=False):
    r = PrintLayout(doc_type=DOC, scope_id=SCOPE, name=name,
                    payload=json.dumps(payload), is_default=is_default)
    db.session.add(r); db.session.commit()
    return r


def test_no_rows_and_no_legacy_key_returns_none(db_session):
    assert resolve_payload(DOC, SCOPE, 'dev1') is None


def test_the_default_row_wins_when_the_device_has_no_pref(db_session):
    _row('Default', {'marker': 'default'}, is_default=True)
    _row('Other', {'marker': 'other'})
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'default'


def test_the_device_pref_beats_the_default(db_session):
    _row('Default', {'marker': 'default'}, is_default=True)
    other = _row('Other', {'marker': 'other'})
    db_session.add(PrintLayoutDevicePref(device_id='dev1', doc_type=DOC,
                                         scope_id=SCOPE, layout_id=other.id))
    db_session.commit()
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'other'
    # a DIFFERENT workstation is unaffected
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev2'))['marker'] == 'default'


def test_a_pref_pointing_at_a_deleted_layout_falls_back(db_session):
    """AC 4. ON DELETE SET NULL leaves the pref row; resolution must not blow up."""
    _row('Default', {'marker': 'default'}, is_default=True)
    other = _row('Other', {'marker': 'other'})
    db_session.add(PrintLayoutDevicePref(device_id='dev1', doc_type=DOC,
                                         scope_id=SCOPE, layout_id=other.id))
    db_session.commit()
    db_session.delete(other); db_session.commit()
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'default'


def test_get_layout_reads_through_to_the_legacy_key(db_session):
    """With no rows at all, behaviour is exactly as before this feature."""
    legacy = get_layout(branch_id=SCOPE)
    legacy['page']['fontFamily'] = 'Arial, sans-serif'
    AppSettings.set_setting('po_preprinted_layout:1', json.dumps(legacy), 'system')
    assert get_layout(branch_id=SCOPE)['page']['fontFamily'] == 'Arial, sans-serif'


def test_a_row_beats_the_legacy_key(db_session):
    legacy = get_layout(branch_id=SCOPE)
    legacy['page']['fontFamily'] = 'Arial, sans-serif'
    AppSettings.set_setting('po_preprinted_layout:1', json.dumps(legacy), 'system')
    row = dict(legacy); row['page'] = {'fontFamily': 'Georgia, serif'}
    _row('Default', row, is_default=True)
    assert get_layout(branch_id=SCOPE)['page']['fontFamily'] == 'Georgia, serif'
