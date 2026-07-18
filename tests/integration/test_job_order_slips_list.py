"""Job Order Slips list -- operations-facing view of Sales Orders, no pricing.
Own grantable module (job_order_slips), independent of full sales_orders access."""
import datetime
import pytest
from app import db
from app.sales_orders.models import SalesOrder
from app.customers.models import Customer
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:job_order_slips', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_user(db_session, branch, username, permissions):
    user = User(username=username, email=f'{username}@test.com',
               full_name=username.title(), role='staff', is_active=True)
    user.set_password('testpass123')
    user.set_book_permissions(permissions)
    db.session.add(user)
    db.session.flush()
    user.set_branches([branch])
    db.session.commit()
    return user


def _customer(db_session):
    c = Customer.query.filter_by(code='ACME01').first()
    if c is None:
        c = Customer(code='ACME01', name='Acme', is_active=True)
        db.session.add(c); db.session.commit()
    return c


def _so(db_session, branch, number, status, order_date=datetime.date(2026, 6, 20)):
    c = _customer(db_session)
    so = SalesOrder(so_number=number, order_date=order_date, customer_id=c.id,
                    customer_name='Acme', branch_id=branch.id, status=status)
    db.session.add(so); db.session.commit()
    return so


def test_admin_with_sales_orders_only_sees_job_order_list(client, db_session, admin_user,
                                                           main_branch):
    """Admin always passes can_access_module -- confirms the route itself works end to end."""
    _so(db_session, main_branch, 'SO-JOL-1', 'confirmed')
    _login(client, admin_user, main_branch)
    resp = client.get('/sales-orders/job-order-slips')
    assert resp.status_code == 200
    assert b'SO-JOL-1' in resp.data


def test_staff_with_job_order_slips_only_can_reach_list(client, db_session, main_branch):
    """A user with ONLY job_order_slips granted -- no sales_orders -- must still reach it."""
    _so(db_session, main_branch, 'SO-JOL-2', 'confirmed')
    staff = _make_user(db_session, main_branch, 'ops_staff', {'job_order_slips': True})
    _login(client, staff, main_branch)
    resp = client.get('/sales-orders/job-order-slips')
    assert resp.status_code == 200
    assert b'SO-JOL-2' in resp.data


def test_staff_with_job_order_slips_only_cannot_reach_full_so_list(client, db_session,
                                                                    main_branch):
    """job_order_slips is its own permission -- it must NOT also grant sales_orders access."""
    staff = _make_user(db_session, main_branch, 'ops_staff2', {'job_order_slips': True})
    _login(client, staff, main_branch)
    resp = client.get('/sales-orders', follow_redirects=True)
    assert resp.status_code == 200
    assert b'You do not have access to this module.' in resp.data


def test_staff_with_sales_orders_only_denied_job_order_list(client, db_session, main_branch):
    """The reverse: full sales_orders access does NOT imply job_order_slips access."""
    staff = _make_user(db_session, main_branch, 'accounting_staff', {'sales_orders': True})
    _login(client, staff, main_branch)
    resp = client.get('/sales-orders/job-order-slips', follow_redirects=True)
    assert resp.status_code == 200
    assert b'You do not have access to this module.' in resp.data


def test_drafts_hidden_by_default(client, db_session, admin_user, main_branch):
    _so(db_session, main_branch, 'SO-JOL-DRAFT', 'draft')
    _so(db_session, main_branch, 'SO-JOL-CONFIRMED', 'confirmed')
    _login(client, admin_user, main_branch)
    resp = client.get('/sales-orders/job-order-slips')
    assert resp.status_code == 200
    assert b'SO-JOL-DRAFT' not in resp.data
    assert b'SO-JOL-CONFIRMED' in resp.data


def test_drafts_shown_when_setting_on(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    AppSettings.set_setting('job_order_slips_show_drafts', '1')
    db.session.commit()
    _so(db_session, main_branch, 'SO-JOL-DRAFT2', 'draft')
    _login(client, admin_user, main_branch)
    resp = client.get('/sales-orders/job-order-slips')
    assert resp.status_code == 200
    assert b'SO-JOL-DRAFT2' in resp.data


def test_no_price_columns_on_list(client, db_session, admin_user, main_branch):
    _so(db_session, main_branch, 'SO-JOL-NOPRICE', 'confirmed')
    _login(client, admin_user, main_branch)
    resp = client.get('/sales-orders/job-order-slips')
    html = resp.get_data(as_text=True)
    assert 'Total (PHP)' not in html
    assert 'Unit Price' not in html
