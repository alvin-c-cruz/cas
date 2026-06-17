"""Regression coverage for the APV (Accounts Payable) create FORM.

Focus: BUG #4 — a create that bounces server-side must NOT wipe the typed
line items. The form's notes field is DataRequired, so posting with empty
notes fails validation and re-renders; the submitted line_items JSON must be
carried back (restore_lines) so the page can re-hydrate the rows.

Accounting actions run as an ACCOUNTANT (not admin) per project testing rule.
"""
import json
import pytest

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def setup_accounts(db_session):
    ap  = Account(code='20101', name='AP Trade',        account_type='Liability', normal_balance='credit', is_active=True)
    wt  = Account(code='20301', name='WHT Payable',      account_type='Liability', normal_balance='credit', is_active=True)
    exp = Account(code='60101', name='Office Supplies',  account_type='Expense',   normal_balance='debit',  is_active=True)
    db_session.add_all([ap, wt, exp])
    db_session.commit()
    return ap, wt, exp


def make_vendor(db_session):
    v = Vendor(code='APV01', name='APV Vendor', check_payee_name='APV Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


class TestAPVFormRender:
    def test_failed_create_preserves_submitted_lines(self, client, db_session, accountant_user, main_branch):
        """BUG #4: a bounced create (empty notes) carries the typed line items
        back via restore_lines instead of wiping them. Pre-fix the re-render
        passed ap=None with no line data, so the lines vanished."""
        login(client, 'accountant', 'accountant123')
        ap, wt, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        line_items = [{'description': 'APV-Bounce-Item-XYZ', 'amount': 5600.0,
                       'vat_category': '', 'account_id': exp.id,
                       'wt_id': None, 'wt_rate': None}]

        today = ph_now().date().isoformat()
        resp = client.post('/accounts-payable/create', data={
            'ap_number': 'AP-BOUNCE-0001',
            'ap_date': today,
            'due_date': today,
            'vendor_id': vendor.id,
            'vendor_invoice_number': 'INV-BOUNCE',
            'payment_terms': 'Net 30',
            'notes': '',  # <-- triggers the server-side bounce (notes DataRequired)
            'line_items': json.dumps(line_items),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        })  # no follow_redirects: a bounce re-renders (200), it does not redirect

        # Re-render, not a redirect; nothing persisted.
        assert resp.status_code == 200
        assert AccountsPayable.query.filter_by(ap_number='AP-BOUNCE-0001').first() is None

        html = resp.data.decode('utf-8', 'replace')
        # The submitted line is carried back for re-hydration (restore_lines).
        assert 'APV-Bounce-Item-XYZ' in html
        assert str(exp.id) in html
        # Confirms it was a genuine validation bounce.
        assert 'Notes are required' in html
