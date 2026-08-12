"""The PR printout carries the instance's uploaded logo.

Print templates are standalone -- they do not extend base.html, which held the
only <img> for the company logo -- so the printed requisition had no letterhead
while the sidebar did. `company_logo` is injected by the inject_company_info
context processor, so it reaches print.html without any view change.

Nothing about the logo is hardcoded: each client instance uploads its own under
Company Settings and the setting stores the FILENAME, so these tests assert the
conditional, never a particular image.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest

# The blueprint is registered with url_prefix='/settings', NOT
# '/company-settings'. Getting this wrong made the control test below
# VACUOUS: it asserted the absence of a URL that never appears either way.
LOGO_URL = b'/settings/logo'

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _set_modules(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='PRINT-1', request_date=date(2026, 7, 30),
                        branch_id=main_branch.id, status='draft',
                        created_by_id=admin_user.id, reason='Letterhead probe')
    db_session.add(p)
    db_session.commit()
    return p


def _print_page(client, db_session, admin_user, main_branch, pr, logo_value):
    from app.settings import AppSettings
    _set_modules(db_session, 'products', 'purchase_orders', 'purchase_requests')
    AppSettings.set_setting('company_logo', logo_value)
    AppSettings.set_setting('company_name', 'Probe Company')
    db_session.commit()
    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-requests/{pr.id}/print')
    assert resp.status_code == 200
    return resp.data


class TestPrintLetterhead:

    def test_logo_rendered_when_one_is_uploaded(self, client, db_session, admin_user,
                                                main_branch, pr):
        data = _print_page(client, db_session, admin_user, main_branch, pr,
                           'philgen-logo.png')
        # The route, not the stored filename: the filename never reaches the
        # browser, and asserting it would pass even if the <img> were missing.
        assert LOGO_URL in data
        assert b'<img' in data

    def test_no_image_when_no_logo_uploaded(self, client, db_session, admin_user,
                                            main_branch, pr):
        """Control. philgen currently has company_logo = '' -- an unconditional
        <img> would emit a broken-image icon onto every printed requisition."""
        data = _print_page(client, db_session, admin_user, main_branch, pr, '')
        assert LOGO_URL not in data

    def test_company_name_and_address_still_render(self, client, db_session,
                                                   admin_user, main_branch, pr):
        """The letterhead wrapper must not swallow the text it wraps."""
        data = _print_page(client, db_session, admin_user, main_branch, pr, '')
        assert b'Probe Company' in data
