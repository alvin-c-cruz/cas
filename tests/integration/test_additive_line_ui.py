"""Additive line UI — Description ALWAYS a column; Product/UoM optional secondary
columns; product-pick never autofills the Description (Product+UoM Activation / R-01).

Covers SI (Task 2), APV (Task 4), CDV (Task 5), CRV (Task 6). With products+uom
ON, the create form must still render the free-text Description column for each row
AND add a Product picker as an extra column — never substitute one for the other.
The onProductPick handler autofills account / unit_price / uom only, not the
description.

The Description / Product column headers are Jinja-gated server-side, so their
presence in the rendered HTML is a reliable behavioural signal (unlike the
client-side JS row template, whose ternaries are evaluated only in the browser).
"""
import pytest

from app import db
from app.customers.models import Customer
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration]


@pytest.fixture
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _customer(db_session):
    c = Customer.query.filter_by(code='AUIC').first()
    if not c:
        c = Customer(code='AUIC', name='UI Customer', is_active=True)
        db_session.add(c); db_session.commit()
    return c


def _vendor(db_session):
    v = Vendor.query.filter_by(code='AUIV').first()
    if not v:
        v = Vendor(code='AUIV', name='UI Vendor', check_payee_name='UI Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v); db_session.commit()
    return v


# ---------------------------------------------------------------------------
# Sales Invoice (Task 2)
# ---------------------------------------------------------------------------

def test_si_form_additive_description_and_product(client, db_session, accountant_user,
                                                  main_branch, modules_on):
    _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/sales-invoices/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    # Both columns present with products ON (additive, not substitution).
    assert '>Description</th>' in html
    assert '>Product</th>' in html
    # Product-pick must NOT autofill the description field.
    assert 'item.description = p.name' not in html


# ---------------------------------------------------------------------------
# Accounts Payable Voucher (Task 4)
# ---------------------------------------------------------------------------

def test_apv_form_additive_description_and_product(client, db_session, accountant_user,
                                                   main_branch, modules_on):
    _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>Product</th>' in html
    assert 'item.description = prod.name' not in html


# ---------------------------------------------------------------------------
# Cash Disbursement Voucher (Task 5)
# ---------------------------------------------------------------------------

def test_cdv_form_additive_description_and_product(client, db_session, accountant_user,
                                                   main_branch, modules_on):
    _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/cash-disbursements/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>Product</th>' in html
    assert 'item.description = p.name' not in html


# ---------------------------------------------------------------------------
# Cash Receipt Voucher (Task 6)
# ---------------------------------------------------------------------------

def test_crv_form_additive_description_and_product(client, db_session, accountant_user,
                                                   main_branch, modules_on):
    _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/cash-receipts/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>Product</th>' in html
    assert 'item.description = p.name' not in html


# ---------------------------------------------------------------------------
# UOM column hides when units_of_measure is disabled (FEAT-UOM-FALLBACK-HIDE-
# WHEN-DISABLED, owner directive: "product and uom should not be appearing in
# SI/CR/AP/CD if product and uom config is disabled"). Product already hides
# this way (proven by the tests above); UOM instead degraded to a free-text
# fallback column -- these tests pin the corrected, Product-mirroring behavior.
#
# No modules_on fixture here: units_of_measure/products default_enabled=False,
# so a fresh test DB is already in the "disabled" state under test.
# ---------------------------------------------------------------------------

def test_si_form_hides_uom_column_when_disabled(client, db_session, accountant_user, main_branch):
    _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/sales-invoices/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>UOM</th>' not in html
    assert '>Product</th>' not in html


def test_apv_form_hides_uom_column_when_disabled(client, db_session, accountant_user, main_branch):
    _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>UOM</th>' not in html
    assert '>Product</th>' not in html


def test_cdv_form_hides_uom_column_when_disabled(client, db_session, accountant_user, main_branch):
    _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/cash-disbursements/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>UOM</th>' not in html
    assert '>Product</th>' not in html


def test_crv_form_hides_uom_column_when_disabled(client, db_session, accountant_user, main_branch):
    _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.get('/cash-receipts/create')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert '>Description</th>' in html
    assert '>UOM</th>' not in html
    assert '>Product</th>' not in html
