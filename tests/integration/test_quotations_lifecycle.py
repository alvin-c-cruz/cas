import json, pytest
from datetime import date, timedelta
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product

# Dates must be RELATIVE. These were hardcoded '2026-07-09' / '2026-08-09', so on
# 2026-08-10 every quote these helpers create silently became EXPIRED and the app
# correctly refused to accept it -- turning three accept->SO tests red with a
# `NoneType has no attribute line_items` that looked like a Sales Order bug.
_TODAY = date.today().isoformat()
_VALID_UNTIL = (date.today() + timedelta(days=31)).isoformat()

pytestmark = [pytest.mark.integration, pytest.mark.quotations]


@pytest.fixture(autouse=True)
def quotations_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('quotations', 'sales_orders', 'products', 'units_of_measure', 'employees'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _seed(db_session):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    return c, p


def _create_quote(client, c, p, treatment='exclusive', qty='2', price='100.00'):
    lines = json.dumps([{'product_id': str(p.id), 'quantity': qty, 'unit_price': price,
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': _TODAY, 'valid_until': _VALID_UNTIL,
        'vat_treatment': treatment, 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)


def test_send_locks_editing(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'sent'
    # locked: GET the edit form on a sent quote redirects away (302 without follow)
    resp = client.get(f'/quotations/{q.id}/edit', follow_redirects=False)
    assert resp.status_code == 302


def test_expired_sent_quote_cannot_be_accepted(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    # force the validity into the past
    q.valid_until = date.today() - timedelta(days=1)
    db_session.commit()
    assert q.is_expired is True
    resp = client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'sent' and q.sales_order_id is None
    assert b'expired' in resp.data.lower()


def test_reject_requires_reason(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    client.post(f'/quotations/{q.id}/reject', data={'reject_reason': 'too short'}, follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'sent'   # rejected refused (reason < 10 chars)
    client.post(f'/quotations/{q.id}/reject', data={'reject_reason': 'Price too high for the client budget'},
                follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'rejected' and q.reject_reason


def test_cancel_requires_reason(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/cancel', data={'cancel_reason': 'nope'}, follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'draft'
    client.post(f'/quotations/{q.id}/cancel', data={'cancel_reason': 'Customer withdrew the request'},
                follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'cancelled' and q.cancel_reason


def test_accept_creates_linked_inclusive_so_from_exclusive_quote(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    from app.sales_orders.models import SalesOrder
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'exclusive', qty='2', price='100.00')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'accepted' and q.sales_order_id is not None
    so = db_session.get(SalesOrder, q.sales_order_id)
    assert so.status == 'draft' and so.quotation_id == q.id
    # exclusive net 100 -> SO inclusive unit_price 112 (VAT folded in)
    assert so.line_items[0].unit_price == Decimal('112.00')
    assert so.line_items[0].vat_category == 'V12'
    assert so.salesperson_id == q.salesperson_id


def test_accept_zero_rated_quote_tags_so_lines(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    from app.sales_orders.models import SalesOrder
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'zero_rated', qty='2', price='100.00')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    so = db_session.get(SalesOrder, q.sales_order_id)
    assert so.line_items[0].vat_category == 'V0'
    assert so.line_items[0].vat_rate == Decimal('0')
    assert so.line_items[0].unit_price == Decimal('100.00')   # zero-rated: price unchanged


def test_accept_inclusive_quote_copies_lines_as_is(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    from app.sales_orders.models import SalesOrder
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive', qty='2', price='112.00')
    q = Quotation.query.first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    so = db_session.get(SalesOrder, q.sales_order_id)
    assert so.line_items[0].unit_price == Decimal('112.00')
    assert so.line_items[0].vat_category == 'V12'


def test_accept_only_when_sent(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    # still draft -> accept refused
    client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'draft' and q.sales_order_id is None


def test_the_create_helper_produces_a_quote_that_is_not_already_expired(
        client, db_session, admin_user, main_branch):
    """PRECONDITION GUARD. Every accept-> Sales Order test below depends on the
    quote created by `_create_quote` still being valid, because the accept route
    refuses an expired quotation -- correctly, and `test_expired_sent_quote_
    cannot_be_accepted` asserts that refusal.

    When `_create_quote` hardcoded `valid_until='2026-08-09'`, that precondition
    silently expired on 2026-08-10 and the three accept tests began failing with
    `AttributeError: 'NoneType' object has no attribute 'line_items'` -- a
    message that points at Sales Orders, not at the stale fixture. The bug was
    filed HIGH against quotation CREATE (which works fine) and cost a session.

    This test states the precondition directly, so the next time it breaks the
    failure names the real cause instead of sending someone into the SO code.
    """
    from app.quotations.models import Quotation
    c, p = _seed(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    _create_quote(client, c, p, 'inclusive')
    q = Quotation.query.first()
    assert q is not None, 'the create POST did not produce a quotation at all'
    assert q.valid_until >= date.today(), (
        'the fixture quote is already expired (valid_until=%s, today=%s) -- the '
        'accept tests below cannot pass. Use relative dates, never literals.'
        % (q.valid_until, date.today()))
    assert q.is_expired is False
