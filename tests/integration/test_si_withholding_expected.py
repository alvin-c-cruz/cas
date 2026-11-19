"""A branch can say its sales invoices should carry withholding tax; then an invoice warns when its customer has no
withholding code (WTX A, owner 14 Nov 2026; WTX-1 A, 17 Nov 2026).

Work order 2026-08-01-missing-default-wt-code-drops-cwt: four RIC CORP customers had no withholding code, so 13 posted
invoices recorded zero creditable withholding with nothing on screen to say so. CAS has no "corporate customer" field,
and Philgen's customers and RIC's EXTRA branch never withhold, so the warning is switched on per BRANCH (setting
`si_wt_expected:<branch id>`, a checkbox on the branch's edit page); after the deploy the root ticks it for RIC CORP
only. Nothing is blocked.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.withholding_expected import set_wt_expected, wt_expected
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]

WARNING = 'should carry withholding tax'


def _login(client, user, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True; s['selected_branch_id'] = branch.id


def _customer(code='C-WT', with_code=False):
    from app.customers.models import Customer
    c = Customer(code=code, name=f'{code} Corporation', is_active=True)
    if with_code:
        from app.withholding_tax.models import WithholdingTax
        wt = WithholdingTax.query.filter_by(code='WC158').first() or WithholdingTax(
            code='WC158', name='EWT 1% goods', sales_name='CWT 1% goods', rate=Decimal('1.00'), is_active=True)
        db.session.add(wt)
        c.withholding_taxes.append(wt)
    db.session.add(c); db.session.commit()
    return c


def _invoice(branch, customer, number='SI-WT-1'):
    si = SalesInvoice(invoice_number=number, invoice_date=date(2026, 11, 17), due_date=date(2026, 12, 17),
                      customer_id=customer.id, customer_name=customer.name, branch_id=branch.id, status='draft')
    db.session.add(si); db.session.commit()
    return si


class TestTheSwitch:

    def test_off_by_default(self, db_session, main_branch):
        assert wt_expected(main_branch.id) is False

    def test_the_branch_edit_page_offers_it_and_saves_it(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        html = client.get(f'/branches/{main_branch.id}/edit').data.decode('utf-8')
        assert 'name="si_wt_expected"' in html and 'Sales invoices in this branch should carry withholding tax' in html
        client.post(f'/branches/{main_branch.id}/edit', data={
            'code': main_branch.code, 'name': main_branch.name, 'is_active': 'y', 'si_wt_expected': 'y'},
            follow_redirects=True)
        assert wt_expected(main_branch.id) is True
        assert AppSettings.get_setting(f'si_wt_expected:{main_branch.id}') == '1'
        row = AuditLog.query.filter_by(module='branch', action='si_wt_expected').order_by(AuditLog.id.desc()).first()
        assert row is not None and 'on' in (row.notes or '')
        client.post(f'/branches/{main_branch.id}/edit', data={
            'code': main_branch.code, 'name': main_branch.name, 'is_active': 'y'}, follow_redirects=True)
        assert wt_expected(main_branch.id) is False

    def test_the_edit_page_shows_it_ticked_when_on(self, client, db_session, admin_user, main_branch):
        set_wt_expected(main_branch.id, True)
        _login(client, admin_user, main_branch)
        html = client.get(f'/branches/{main_branch.id}/edit').data.decode('utf-8')
        tag = next(t for t in html.split('<input') if 'name="si_wt_expected"' in t)
        assert 'checked' in tag


class TestTheWarning:

    def test_the_form_carries_the_branch_flag(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        off = client.get('/sales-invoices/create').data.decode('utf-8')
        assert 'id="siWtExpectedWarning"' in off and 'data-wt-expected="0"' in off
        set_wt_expected(main_branch.id, True)
        on = client.get('/sales-invoices/create').data.decode('utf-8')
        assert 'data-wt-expected="1"' in on and 'updateWtExpectedWarning' in on

    def test_the_invoice_page_warns_for_a_customer_without_a_code(self, client, db_session, admin_user, main_branch):
        set_wt_expected(main_branch.id, True)
        si = _invoice(main_branch, _customer())
        _login(client, admin_user, main_branch)
        assert WARNING in client.get(f'/sales-invoices/{si.id}').data.decode('utf-8')

    def test_no_warning_when_the_customer_has_a_code(self, client, db_session, admin_user, main_branch):
        set_wt_expected(main_branch.id, True)
        si = _invoice(main_branch, _customer(with_code=True))
        _login(client, admin_user, main_branch)
        assert WARNING not in client.get(f'/sales-invoices/{si.id}').data.decode('utf-8')

    def test_no_warning_on_a_branch_that_is_off(self, client, db_session, admin_user, main_branch):
        si = _invoice(main_branch, _customer())
        _login(client, admin_user, main_branch)
        assert WARNING not in client.get(f'/sales-invoices/{si.id}').data.decode('utf-8')
