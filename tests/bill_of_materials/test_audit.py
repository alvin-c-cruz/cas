"""Audit-log coverage for BOM create/update/toggle (R-07 Wave 0)."""
import pytest
from app.settings import AppSettings
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_create_logs_audit_entry(client, accountant_user, db_session, main_branch):
    from app import db
    from app.products.models import Product
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    AppSettings.set_setting('manufacturing_discrete_enabled', '1')
    db_session.commit()
    out = Product(code='BOMA-OUT', name='Out', is_active=True)
    db.session.add(out); db.session.commit()
    _login(client, accountant_user, main_branch)
    client.post('/bill-of-materials/new', data={
        'product_id': out.id, 'manufacturing_mode': 'discrete', 'lines': '[]',
    }, follow_redirects=True)
    entry = AuditLog.query.filter_by(module='bill_of_materials', action='create').first()
    assert entry is not None
    assert entry.record_identifier == 'BOMA-OUT'
