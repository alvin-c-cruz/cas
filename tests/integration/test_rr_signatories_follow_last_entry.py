"""A new receiving report seeds its signatories from the encoder's LAST one.

Owner, 2026-09-10: "signatories should autofill based on what the user encoded
last time." Before this, a new receipt always started from the company default,
so anyone whose crew differs from the configured names retyped all three lines
on every receipt.

Per USER, not per company: two receivers hand different people the goods, and
seeding from whoever saved most recently would hand each of them the other's
crew. This mirrors next_po_number_for(), which scopes a purchaser's pad to the
purchaser rather than to the branch, for the same reason.

The company default remains the fallback -- for the user's first ever receipt,
and per slot for any signatory their last receipt left blank.
"""
from datetime import date

import pytest

from app import db
from app.receiving_reports.models import ReceivingReport

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _vendor():
    """vendor_id is NOT NULL on receiving_reports."""
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='SIG-V').first()
    if not v:
        v = Vendor(code='SIG-V', name='Signatory Vendor')
        db.session.add(v); db.session.commit()
    return v


def _rr(main_branch, number, user_id, prepared=None, checked=None, received=None):
    v = _vendor()
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 9, 10),
                         branch_id=main_branch.id, status='draft',
                         vendor_id=v.id, vendor_name=v.name, created_by_id=user_id,
                         prepared_by=prepared, checked_by=checked,
                         received_by=received)
    db.session.add(rr); db.session.commit()
    return rr


def _create_page(client, main_branch, admin_user, login_user):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_orders', 'receiving_reports'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    db.session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/receiving-reports/create')
    assert resp.status_code == 200, 'the create page did not render (%s)' % resp.status_code
    return resp.get_data(as_text=True)


def _value_of(html, field):
    """The rendered value of one signatory input, not a bare substring: the same
    name legitimately appears elsewhere on the page."""
    import re
    m = re.search(r'<input[^>]*name="%s"[^>]*>' % field, html)
    assert m, 'the %s input is not rendered at all' % field
    v = re.search(r'value="([^"]*)"', m.group(0))
    return v.group(1) if v else ''


class TestItFollowsTheEncodersLastReceipt:

    def test_the_three_names_come_from_the_users_own_last_receipt(
            self, client, db_session, main_branch, admin_user, login_user):
        _rr(main_branch, 'SIG-1', admin_user.id,
            prepared='Rowena Diaz', checked='Ben Cruz', received='Mila Reyes')
        html = _create_page(client, main_branch, admin_user, login_user)
        assert _value_of(html, 'prepared_by') == 'Rowena Diaz'
        assert _value_of(html, 'checked_by') == 'Ben Cruz'
        assert _value_of(html, 'received_by') == 'Mila Reyes'

    def test_it_reads_the_latest_receipt_not_the_first(
            self, client, db_session, main_branch, admin_user, login_user):
        _rr(main_branch, 'SIG-2', admin_user.id, prepared='Old Name')
        _rr(main_branch, 'SIG-3', admin_user.id, prepared='New Name')
        html = _create_page(client, main_branch, admin_user, login_user)
        assert _value_of(html, 'prepared_by') == 'New Name'

    def test_another_users_receipt_is_not_borrowed(
            self, client, db_session, main_branch, admin_user, login_user):
        """The reason this is per-user: two receivers hand the goods to
        different people, and the newest receipt overall may not be theirs."""
        from app.users.models import User
        other = User(username='other_receiver', email='other@test.local',
                     full_name='Other Receiver', role='staff', is_active=True,
                     branch_id=main_branch.id)
        other.set_password('x-temp-123')
        db.session.add(other); db.session.commit()
        _rr(main_branch, 'SIG-4', admin_user.id, prepared='Mine')
        _rr(main_branch, 'SIG-5', other.id, prepared='Theirs')   # newest overall
        html = _create_page(client, main_branch, admin_user, login_user)
        assert _value_of(html, 'prepared_by') == 'Mine'

    def test_with_no_prior_receipt_the_company_default_is_used(
            self, client, db_session, main_branch, admin_user, login_user):
        """CONTROL: the existing behaviour must survive for a first-time user."""
        from app.settings import AppSettings
        AppSettings.set_setting('rr_sig1_name', 'Configured Preparer')
        db.session.commit()
        html = _create_page(client, main_branch, admin_user, login_user)
        assert _value_of(html, 'prepared_by') == 'Configured Preparer'

    def test_a_slot_left_blank_last_time_falls_back_to_the_default(
            self, client, db_session, main_branch, admin_user, login_user):
        """Per SLOT, not all-or-nothing: the last receipt names a preparer but
        no checker, so the checker comes from the company setting."""
        from app.settings import AppSettings
        AppSettings.set_setting('rr_sig2_name', 'Configured Checker')
        db.session.commit()
        _rr(main_branch, 'SIG-6', admin_user.id, prepared='Rowena Diaz')
        html = _create_page(client, main_branch, admin_user, login_user)
        assert _value_of(html, 'prepared_by') == 'Rowena Diaz'
        assert _value_of(html, 'checked_by') == 'Configured Checker'
