"""Voiding a draft APV (B-015 regression).

The void route crashed with UnboundLocalError ("cannot access local variable
'current_app'") because a local `from flask import current_app` in the except
block shadowed the module-level import used in the try block.
"""
from decimal import Decimal

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.audit.models import AuditLog
from app.utils import ph_now


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_draft_bill(db_session, branch):
    v = Vendor(code='VV001', name='Void Vendor', check_payee_name='Void Vendor',
               is_active=True)
    db_session.add(v)
    db_session.commit()
    today = ph_now().date()
    bill = PurchaseBill(
        bill_number='AP-VOID-0001', vendor_id=v.id, vendor_name=v.name,
        branch_id=branch.id, bill_date=today, due_date=today,
        payment_terms='Net 30', status='draft',
        subtotal=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        total_before_wt=Decimal('1120.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1120.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('1120.00'),
    )
    db_session.add(bill)
    db_session.commit()
    return bill


class TestVoidDraft:
    def test_void_draft_succeeds_and_audited(self, client, db_session,
                                             admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        bill = make_draft_bill(db_session, main_branch)

        resp = client.post(f'/purchase-bills/{bill.id}/void', data={
            'void_reason': 'Regression test for the current_app shadowing bug',
            'reversal_date': '2026-06-12',
        }, follow_redirects=True)
        html = resp.data.decode('utf-8')
        assert 'Error voiding' not in html
        assert 'voided' in html

        refreshed = db_session.get(PurchaseBill, bill.id)
        assert refreshed.status == 'voided'

        audit = AuditLog.query.filter_by(module='purchase_bill', action='void',
                                         record_id=bill.id).first()
        assert audit is not None
        assert audit.user_id == admin_user.id
