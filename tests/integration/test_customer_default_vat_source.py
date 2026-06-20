from app.sales_vat_categories.models import SalesVATCategory
from app.vat_categories.models import VATCategory


def test_customer_form_lists_sales_vat_names(client, db_session, admin_user, main_branch):
    db_session.add(SalesVATCategory(code='SVAT-G', name='Sale of Goods (12%)', rate=12.00,
                                    transaction_nature='regular', is_active=True))
    db_session.add(VATCategory(code='VAT-12', name='Purchase Goods (12%)', rate=12.00, is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)
    resp = client.get('/customers/create')
    assert b'Sale of Goods (12%)' in resp.data
    assert b'Purchase Goods (12%)' not in resp.data
