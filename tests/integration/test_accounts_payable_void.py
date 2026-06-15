"""Voiding a draft APV (B-015 regression).

The void route crashed with UnboundLocalError ("cannot access local variable
'current_app'") because a local `from flask import current_app` in the except
block shadowed the module-level import used in the try block.
"""
from decimal import Decimal

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.audit.models import AuditLog
import pytest
from app.utils import ph_now
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_draft_bill(db_session, branch):
    v = Vendor(code='VV001', name='Void Vendor', check_payee_name='Void Vendor',
               is_active=True)
    db_session.add(v)
    db_session.commit()
    today = ph_now().date()
    bill = AccountsPayable(
        ap_number='AP-VOID-0001', vendor_id=v.id, vendor_name=v.name,
        branch_id=branch.id, ap_date=today, due_date=today,
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

        resp = client.post(f'/accounts-payable/{bill.id}/void', data={
            'void_reason': 'Regression test for the current_app shadowing bug',
            'reversal_date': '2026-06-12',
        }, follow_redirects=True)
        html = resp.data.decode('utf-8')
        assert 'Error voiding' not in html
        assert 'voided' in html

        refreshed = db_session.get(AccountsPayable, bill.id)
        assert refreshed.status == 'voided'

        audit = AuditLog.query.filter_by(module='accounts_payable', action='void',
                                         record_id=bill.id).first()
        assert audit is not None
        assert audit.user_id == admin_user.id


class TestBillNumberAfterVoid:
    def test_voided_number_not_reissued(self, client, db_session,
                                        admin_user, main_branch):
        """B-016: ap_number is unique, so the generator must not offer a
        voided bill's number again (it would collide on save)."""
        from app.accounts_payable.views import generate_ap_number
        from app.utils import ph_now

        login(client)
        bill = make_draft_bill(db_session, main_branch)
        now = ph_now()
        bill.ap_number = f'AP-{now.year}-{now.month:02d}-0001'
        bill.status = 'voided'
        db_session.commit()

        next_number = generate_ap_number()
        assert next_number == f'AP-{now.year}-{now.month:02d}-0002'
