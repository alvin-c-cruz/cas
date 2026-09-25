"""Salespeople from every branch the user can REACH are offered, not only the selected one.

Owner, 2026-09-25: "check the salesperson, it only show Company Account in Extra but should be
Lawrence Kiok". Kiok is a CORP employee; _salesperson_choices filtered on equality with the
selected branch, so an EXTRA sales order offered nobody. Same rule the CV payee picker got on
2026-09-24 (app/common/payee.py): set membership over the user's accessible branches. A user
who cannot reach CORP still does not see CORP's salespeople. One function feeds SO, DR,
quotation, SI and sales-memo forms, so all five follow.
"""
import re

import pytest

from app.employees.models import Employee

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture
def employees_on(db_session, request):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit(); clear_module_config_cache()
    request.addfinalizer(clear_module_config_cache)


@pytest.fixture
def kiok(db_session, main_branch):
    e = Employee(employee_no='EMP-0001', first_name='LAWRENCE', last_name='KIOK',
                 branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db_session.add(e); db_session.commit()
    return e


def _open(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _salesperson_values(html):
    m = re.search(r'<select[^>]*name="salesperson_id".*?</select>', html, re.S)
    assert m, 'salesperson select not rendered'
    return re.findall(r'value="(\d+)"', m.group(0))


def test_an_extra_order_offers_a_corp_salesperson(client, db_session, admin_user, main_branch,
                                                  branch_manila, employees_on, kiok):
    _open(client, admin_user, branch_manila)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    assert str(kiok.id) in _salesperson_values(html)


def test_a_user_who_cannot_reach_corp_does_not_see_him(client, db_session, staff_user, main_branch,
                                                       branch_manila, employees_on, kiok):
    staff_user.set_branches([branch_manila])
    staff_user.set_book_permissions({'sales_orders': True})   # staff need the book, else redirect
    db_session.commit()
    _open(client, staff_user, branch_manila)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    values = _salesperson_values(html)
    assert '0' in values, 'anti-vacuity: the select rendered with Company Account'
    assert str(kiok.id) not in values


def test_a_non_salesperson_is_still_left_out(client, db_session, admin_user, main_branch,
                                             branch_manila, employees_on, kiok):
    kiok.is_salesperson = False; db_session.commit()
    _open(client, admin_user, branch_manila)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    assert str(kiok.id) not in _salesperson_values(html)
