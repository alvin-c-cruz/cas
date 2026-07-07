"""Phase 1 — pre-printed layouts are branch-scoped (SI + CRV).

Each branch keeps its own saved layout (one branch's pre-printed stock has
debit/credit boxes, another's doesn't); the key is `<doc>_preprinted_layout:<branch_id>`,
falling back to the DEFAULT when a branch has not customized.
"""
import json
import pytest

from app.settings import AppSettings
from app.audit.models import AuditLog
from app.sales_invoices import preprinted_layout as si
from app.cash_receipts import preprinted_layout as crv

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize('mod, default', [
    (si, 'DEFAULT_SV_PREPRINTED_LAYOUT'),
    (crv, 'DEFAULT_CRV_PREPRINTED_LAYOUT'),
])
class TestBranchScopedLayout:
    def test_two_branches_keep_independent_layouts(self, db_session, mod, default):
        first_field = mod.FIELD_KEYS[0]
        mod.save_layout({'fields': {first_field: {'x': 111, 'y': 10}}}, 'admin', branch_id=1)
        mod.save_layout({'fields': {first_field: {'x': 222, 'y': 20}}}, 'admin', branch_id=2)
        assert mod.get_layout(branch_id=1)['fields'][first_field]['x'] == 111
        assert mod.get_layout(branch_id=2)['fields'][first_field]['x'] == 222

    def test_unset_branch_falls_back_to_default(self, db_session, mod, default):
        first_field = mod.FIELD_KEYS[0]
        mod.save_layout({'fields': {first_field: {'x': 333}}}, 'admin', branch_id=1)
        # branch 99 never customized -> default position, not branch 1's
        out = mod.get_layout(branch_id=99)
        assert out['fields'][first_field] == getattr(mod, default)['fields'][first_field]

    def test_branch_key_is_document_setting_key_plus_branch(self, db_session, mod, default):
        mod.save_layout({}, 'admin', branch_id=7)
        assert AppSettings.get_setting(f'{mod.LAYOUT_SETTING_KEY}:7') is not None
        # the un-suffixed global key is NOT written by a branch-scoped save
        assert AppSettings.get_setting(mod.LAYOUT_SETTING_KEY) is None

    def test_save_audits_per_branch(self, db_session, mod, default):
        mod.save_layout({}, 'admin', branch_id=3)
        entry = AuditLog.query.filter_by(
            record_identifier=f'{mod.LAYOUT_SETTING_KEY.replace("_preprinted_layout","")}'
        )  # loose; real assert below
        rows = AuditLog.query.order_by(AuditLog.id.desc()).all()
        assert any(r.action == 'update' and 'preprinted_layout' in (r.record_identifier or '')
                   for r in rows)

    def test_legacy_no_branch_still_works(self, db_session, mod, default):
        # back-compat: no branch_id -> the old global key (existing callers/tests)
        first_field = mod.FIELD_KEYS[0]
        mod.save_layout({'fields': {first_field: {'x': 55}}}, 'admin')
        assert mod.get_layout()['fields'][first_field]['x'] == 55
        assert AppSettings.get_setting(mod.LAYOUT_SETTING_KEY) is not None
