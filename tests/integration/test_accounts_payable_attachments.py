"""Integration tests for APV file attachments (edit-mode upload + create-form upload)."""
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable, AccountsPayableAttachment
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.audit.models import AuditLog

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='ATV001', name='Attach Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_draft_ap(db_session, vendor, branch, ap_number='ATT-DRAFT-1'):
    ap = AccountsPayable(
        ap_number=ap_number, vendor_id=vendor.id, vendor_name=vendor.name,
        vendor_tin='', vendor_address='', branch_id=branch.id,
        ap_date=date.today(), due_date=date.today(), status='draft',
        subtotal=Decimal('100.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('100.00'), withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal('100.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('100.00'),
        payment_terms='Net 30',
    )
    db_session.add(ap)
    db_session.commit()
    return ap


def test_edit_mode_upload_creates_attachment_and_audit(client, db_session, admin_user, main_branch):
    login(client)
    vendor = make_vendor(db_session)
    ap = make_draft_ap(db_session, vendor, main_branch)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        f'/accounts-payable/{ap.id}/attachments/upload',
        data={'attachment': (io.BytesIO(b'%PDF-1.4 test'), 'invoice.pdf')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1
    assert atts[0].original_filename == 'invoice.pdf'
    assert atts[0].mime_type == 'application/pdf'

    audit = AuditLog.query.filter_by(module='accounts_payable_attachment', action='create').all()
    assert len(audit) == 1
