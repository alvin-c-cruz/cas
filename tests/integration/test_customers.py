"""
Integration tests for the customer list view.
"""


def test_customer_list_renders_empty(client, db_session, accountant_user, main_branch):
    """Customer list returns 200 with empty state on a fresh DB."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Customer Maintenance' in response.data
    assert b'No customers found' in response.data


def test_customer_list_shows_customer(client, db_session, accountant_user, main_branch):
    """Customer list shows code, name, and BIR-incomplete badge when TIN is missing."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30',
                    is_active=True)
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Test Corp' in response.data
    assert b'C001' in response.data
    assert b'BIR incomplete' in response.data


def test_customer_list_delete_modal_present(client, db_session, accountant_user, main_branch):
    """Delete modal is in the HTML — no data-confirm HTML attribute on any form element."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert b'delete-modal-' in response.data
    # base.html JS contains 'data-confirm' as a string literal in script; the real
    # check is that no HTML element uses the attribute assignment form data-confirm="
    assert b'data-confirm="' not in response.data
