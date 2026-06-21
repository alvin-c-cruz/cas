"""Account edit form must preselect the account's current parent.

Regression for the bug where `views.py` set `form.parent_id.data = str(parent_id)`
while the field has `coerce=int`, so WTForms compared `int(option_value)` against
a string and never marked the option selected. The dropdown then showed
"None (Top Level)", and saving silently orphaned the child (parent_id -> None).
"""
import re
import pytest
from app.accounts.models import Account

pytestmark = [pytest.mark.accounts, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _parent_select(html):
    m = re.search(r'<select[^>]*id="parent-account-field".*?</select>', html, re.DOTALL)
    assert m, 'parent dropdown not found in edit form'
    return m.group(0)


class TestEditParentPreselect:
    def test_edit_child_preselects_its_parent(self, client, db_session,
                                              accountant_user, main_branch):
        login(client)
        g = Account(code='90000', name='Grp', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()
        c = Account(code='90001', name='Child', account_type='Asset',
                    normal_balance='debit', parent_id=g.id)
        db_session.add(c)
        db_session.commit()

        html = client.get(f'/accounts/{c.id}/edit').data.decode()
        sel = _parent_select(html)
        selected = re.findall(r'<option\b[^>]*\bselected\b[^>]*>', sel)
        assert len(selected) == 1, f'expected one selected parent option, got {selected}'
        assert f'value="{g.id}"' in selected[0], f'wrong parent preselected: {selected[0]}'

    def test_edit_top_level_selects_none(self, client, db_session,
                                         accountant_user, main_branch):
        login(client)
        g = Account(code='90000', name='Grp', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()

        html = client.get(f'/accounts/{g.id}/edit').data.decode()
        sel = _parent_select(html)
        selected = re.findall(r'<option\b[^>]*\bselected\b[^>]*>', sel)
        # a top-level account selects the "None (Top Level)" option (value="")
        assert len(selected) == 1 and 'value=""' in selected[0], selected
