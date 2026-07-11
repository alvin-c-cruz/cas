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


def _seed_je_accounts(db_session):
    """Structural accounts + a VAT category required for a successful create POST."""
    _NORMAL = {'Asset': 'debit', 'Expense': 'debit', 'Liability': 'credit',
               'Equity': 'credit', 'Revenue': 'credit'}

    def goc(code, name, atype):
        a = Account.query.filter_by(code=code).first()
        if not a:
            a = Account(code=code, name=name, account_type=atype,
                        normal_balance=_NORMAL[atype], is_active=True)
            db_session.add(a)
            db_session.commit()
        return a

    goc('20101', 'Accounts Payable - Trade', 'Liability')
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    vat_acct = goc('10501', 'Input VAT - Current', 'Asset')
    exp = goc('61001', 'Rent Expense', 'Expense')
    vat_cat = VATCategory.query.filter_by(code='VAT12').first()
    if not vat_cat:
        vat_cat = VATCategory(code='VAT12', name='VAT 12%', rate=Decimal('12'),
                              is_active=True, input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)
        db_session.commit()
    return exp


def _line_items(account_id):
    return json.dumps([{
        'description': 'Test Service', 'amount': 11200.00,
        'vat_category': 'VAT12', 'account_id': account_id,
        'wt_id': None, 'wt_rate': None,
    }])


def _create_payload(vendor, account_id, files):
    data = {
        'ap_number': 'PRESAVE-1',
        'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id,
        'payment_terms': 'Net 30',
        'notes': 'Test particulars',
        'line_items': _line_items(account_id),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if files is not None:
        data['attachments'] = files
    return data


def test_create_with_one_file_attaches_it(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV001')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id,
                             [(io.BytesIO(b'%PDF-1.4 a'), 'receipt.pdf')]),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None
    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1
    assert atts[0].original_filename == 'receipt.pdf'

    audit = AuditLog.query.filter_by(module='accounts_payable_attachment', action='create').count()
    assert audit == 1


def test_create_mixed_valid_and_bad_type_saves_valid_and_skips_bad(
        client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV002')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id, [
            (io.BytesIO(b'%PDF-1.4 ok'), 'good.pdf'),
            (io.BytesIO(b'<svg></svg>'), 'bad.svg'),
        ]),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1                      # voucher saved, valid file kept
    assert atts[0].original_filename == 'good.pdf'
    assert b'skipped' in resp.data             # warning names the bad file
    assert b'bad.svg' in resp.data


def test_create_with_no_files_still_works(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV003')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id, None),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0


def test_create_invalid_lines_with_file_persists_nothing(
        client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV004')
    _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    before = AccountsPayable.query.count()
    exp = _seed_je_accounts(db_session)
    data = _create_payload(vendor, account_id=exp.id,
                           files=[(io.BytesIO(b'%PDF-1.4 x'), 'orphan.pdf')])
    # amount=0 triggers server-side "each line amount must be > 0" validation
    data['line_items'] = json.dumps([{
        'description': 'Bad line', 'amount': 0,
        'vat_category': 'VAT12', 'account_id': exp.id,
        'wt_id': None, 'wt_rate': None,
    }])
    resp = client.post('/accounts-payable/create', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert AccountsPayable.query.count() == before          # no AP created
    assert AccountsPayableAttachment.query.count() == 0     # no attachment row
