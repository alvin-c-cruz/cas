"""Browser-tab titles must render the instance's company_name (multi-instance branding)."""


def test_login_title_uses_company_name(client, db_session):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'Acme Test Corp', 'test')
    resp = client.get('/login')
    body = resp.data.decode()
    assert '<title>Acme Test Corp' in body        # positive assertion (avoids CAS/CASH footgun)
    assert 'Login - CAS' not in body
