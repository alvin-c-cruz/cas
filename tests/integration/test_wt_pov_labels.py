"""TDD test: POV-aware WT picker label helper + integration with sales surfaces."""
from app.utils.wt_labels import wt_label
from app.withholding_tax.models import WithholdingTax


def test_sales_pov_prefers_sales_name():
    wt = {'code': 'WC010', 'name': 'Professional Fees - Individuals',
          'sales_name': 'Professional Fees Income - Individual', 'rate': 10.0}
    assert wt_label(wt, 'sales') == 'WC010 — Professional Fees Income - Individual'


def test_sales_pov_falls_back_to_name_when_empty():
    wt = {'code': 'WC999', 'name': 'Buyer only', 'sales_name': None, 'rate': 1.0}
    assert wt_label(wt, 'sales') == 'WC999 — Buyer only'


def test_sales_pov_falls_back_to_name_when_blank_string():
    wt = {'code': 'WC888', 'name': 'Buyer name', 'sales_name': '', 'rate': 2.0}
    assert wt_label(wt, 'sales') == 'WC888 — Buyer name'


def test_buyer_pov_uses_name():
    wt = {'code': 'WC010', 'name': 'Professional Fees - Individuals',
          'sales_name': 'X', 'rate': 10.0}
    assert wt_label(wt, 'buyer') == 'WC010 — Professional Fees - Individuals'


def test_default_pov_is_buyer():
    wt = {'code': 'WC010', 'name': 'Professional Fees - Individuals',
          'sales_name': 'Seller POV', 'rate': 10.0}
    assert wt_label(wt) == 'WC010 — Professional Fees - Individuals'


# ── Integration: customer page shows seller-POV label ──────────────────────
def test_customer_create_page_shows_seller_pov_wt_label(client, db_session, admin_user, main_branch):
    """Customer create form must render sales_name (when set) in the WHT dropdown."""
    db_session.add(WithholdingTax(
        code='WCT01',
        name='Buyer Side Name',
        sales_name='Seller Side Name',
        description='Test',
        rate=10.0,
        is_active=True,
    ))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)

    resp = client.get('/customers/create')
    assert resp.status_code == 200
    assert b'Seller Side Name' in resp.data, "Sales POV label missing from customer WHT picker"
