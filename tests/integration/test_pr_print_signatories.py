"""Editable signatories on the Purchase Request printout.

Company-level (AppSettings rows, no model change): on the paper form the same
three people sign every requisition.

Deliberately NOT derived from created_by/submitted_by/approved_by. Those are CAS
users; the designated signatories frequently are not, and deriving them printed
"System Administrator" three times on a requisition one admin had created,
submitted and approved.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='SIG-1', request_date=date(2026, 7, 30),
                        branch_id=main_branch.id, status='draft',
                        created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


class TestSignatoryDefaults:

    def test_default_roles_render_with_blank_names(self, client, db_session,
                                                   admin_user, main_branch, pr):
        _enable(db_session)
        _login(client, admin_user, main_branch)
        data = client.get(f'/purchase-requests/{pr.id}/print').data

        assert b'Prepared by' in data
        assert b'Noted by' in data
        assert b'Approved by' in data

    def test_creator_name_is_NOT_used_as_a_signatory(self, client, db_session,
                                                     admin_user, main_branch, pr):
        """The regression that motivated this. admin created the PR; with the old
        derived behaviour their name printed on the signature line."""
        _enable(db_session)
        _login(client, admin_user, main_branch)
        data = client.get(f'/purchase-requests/{pr.id}/print').data

        sig = data.split(b'sig-row')[-1]
        assert admin_user.full_name.encode() not in sig


class TestSignatoriesAreEditable:

    def test_saving_changes_what_prints(self, client, db_session, admin_user,
                                        main_branch, pr):
        _enable(db_session)
        _login(client, admin_user, main_branch)

        resp = client.post('/settings/print-signatories', data={
            'pr_id': pr.id,
            'pr_sig1_name': 'Ivan Morontos', 'pr_sig1_role': 'Prepared by',
            'pr_sig2_name': 'Leandro Lahindo', 'pr_sig2_role': 'Noted by',
            'pr_sig3_name': 'Alfredo Redulfin Jr.', 'pr_sig3_role': 'Approved by',
        }, follow_redirects=True)

        assert resp.status_code == 200
        assert b'Ivan Morontos' in resp.data
        assert b'Leandro Lahindo' in resp.data
        assert b'Alfredo Redulfin Jr.' in resp.data

    def test_a_custom_label_is_kept(self, client, db_session, admin_user,
                                    main_branch, pr):
        """Roles are editable too, not just names -- 'freely change'."""
        _enable(db_session)
        _login(client, admin_user, main_branch)

        client.post('/settings/print-signatories', data={
            'pr_id': pr.id, 'pr_sig1_name': 'R. Cruz',
            'pr_sig1_role': 'Requested by',
        })
        data = client.get(f'/purchase-requests/{pr.id}/print').data
        assert b'Requested by' in data

    def test_blank_label_falls_back_to_its_default(self, client, db_session,
                                                   admin_user, main_branch, pr):
        """A cleared label must not print an empty role caption."""
        _enable(db_session)
        _login(client, admin_user, main_branch)

        client.post('/settings/print-signatories', data={
            'pr_id': pr.id, 'pr_sig1_name': 'R. Cruz', 'pr_sig1_role': '',
        })
        data = client.get(f'/purchase-requests/{pr.id}/print').data
        assert b'Prepared by' in data


class TestSignatoryEditorIsGated:

    def test_staff_cannot_save(self, client, db_session, staff_user, main_branch, pr):
        _enable(db_session)
        staff_user.add_branch(main_branch)
        db_session.commit()
        AppSettings.set_setting('pr_sig1_name', 'Original Name')
        db_session.commit()
        _login(client, staff_user, main_branch)

        client.post('/settings/print-signatories', data={
            'pr_id': pr.id, 'pr_sig1_name': 'Injected Name',
        }, follow_redirects=True)

        # Assert the STORED value, not the response: a redirect to the dashboard
        # would look identical whether or not the write was blocked.
        assert AppSettings.get_setting('pr_sig1_name') == 'Original Name'

    def test_modify_button_hidden_from_staff(self, client, db_session, staff_user,
                                             main_branch, pr):
        _enable(db_session)
        staff_user.book_permissions = None
        staff_user.set_book_permissions({'purchase_requests': True})
        staff_user.add_branch(main_branch)
        db_session.commit()
        _login(client, staff_user, main_branch)

        data = client.get(f'/purchase-requests/{pr.id}/print').data
        assert b'sigModifyBtn' not in data

    def test_modify_button_shown_to_admin(self, client, db_session, admin_user,
                                          main_branch, pr):
        """Control: the gate must be conditional, not a permanent hide."""
        _enable(db_session)
        _login(client, admin_user, main_branch)

        data = client.get(f'/purchase-requests/{pr.id}/print').data
        assert b'sigModifyBtn' in data


class TestEditorNeverPrints:

    def test_button_and_modal_are_marked_no_print(self, client, db_session,
                                                  admin_user, main_branch, pr):
        """The editor is screen-only. `.no-print` on the modal and the toolbar is
        the only thing keeping it off the paper."""
        _enable(db_session)
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/print').data.decode()

        i = html.index('id="sigModal"')
        assert 'no-print' in html[max(0, i - 120):i]
        assert '.no-print { display: none; }' in html
