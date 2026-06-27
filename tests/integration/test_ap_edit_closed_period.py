"""M3 regression: AP edit() early-return render paths must use the complete template context.

Before the fix, the closed-period rejection branch inside edit() called
render_template() without vat_categories / all_accounts / gl_accounts /
line_items — variables the template unconditionally accesses — causing a
TemplateUndefined error (500).  After the fix those branches use
_render_edit_form() which mirrors the full GET-path context.

This test reproduces the exact failure path: POST to edit with an ap_date
that falls in a closed accounting period so that validate_transaction_date_with_flash
returns False, triggering the early return.  The response must be 200 (the
form re-renders) and must carry the period-blocked flash message.
"""
import json
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.periods.models import AccountingPeriod

pytestmark = [pytest.mark.integration]

CLOSED_YEAR = 2024
CLOSED_MONTH = 1
CLOSED_DATE = date(CLOSED_YEAR, CLOSED_MONTH, 15)


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _set_branch(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


def _close_period(db_session, year=CLOSED_YEAR, month=CLOSED_MONTH):
    p = AccountingPeriod(year=year, month=month, status='closed')
    db_session.add(p)
    db_session.commit()
    return p


def _setup_gl_accounts(db_session):
    """Minimal GL accounts required by _get_gl_accounts() in the AP view."""
    ap_acct = Account(code='20101', name='AP Trade', account_type='Liability',
                      normal_balance='credit', is_active=True)
    wt_acct = Account(code='20301', name='WHT Payable', account_type='Liability',
                      normal_balance='credit', is_active=True)
    db_session.add_all([ap_acct, wt_acct])
    db_session.commit()
    return ap_acct, wt_acct


def _make_vendor(db_session):
    v = Vendor(code='V001', name='Test Vendor', check_payee_name='Test Vendor',
               is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def _make_draft_ap(db_session, vendor, branch, user):
    """Insert a minimal draft APV so the edit() view can load it."""
    ap = AccountsPayable(
        branch_id=branch.id,
        ap_number='AP-2024-01-0001',
        ap_date=CLOSED_DATE,
        due_date=CLOSED_DATE,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='',
        vendor_address='',
        payment_terms='Net 30',
        notes='Draft for closed-period test',
        status='draft',
        subtotal=Decimal('1000.00'),
        vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('1000.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1000.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('1000.00'),
        created_by_id=user.id,
    )
    db_session.add(ap)
    db_session.commit()
    return ap


class TestAPEditClosedPeriodRender:
    """Edit() closed-period rejection path must re-render 200, not 500."""

    def test_edit_closed_period_returns_200_not_500(
            self, client, db_session, accountant_user, main_branch):
        """Posting an APV edit with a date in a closed period must return 200
        (the form re-renders with a flash error), not 500 from a missing
        template variable (the M3 bug)."""
        _login(client, 'accountant', 'accountant123')
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        _setup_gl_accounts(db_session)
        vendor = _make_vendor(db_session)
        ap = _make_draft_ap(db_session, vendor, main_branch, accountant_user)

        resp = client.post(f'/accounts-payable/{ap.id}/edit', data={
            'ap_number': ap.ap_number,
            'ap_date': CLOSED_DATE.isoformat(),      # date in the closed period
            'due_date': CLOSED_DATE.isoformat(),
            'vendor_id': vendor.id,
            'notes': 'Updated notes',
            'line_items': json.dumps([]),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        })

        # Must NOT be a 500 (TemplateUndefined) — the form must re-render.
        assert resp.status_code == 200, (
            f'Expected 200 (form re-render) but got {resp.status_code}; '
            'likely the M3 early-return path is missing template context variables.'
        )
        html = resp.data.decode('utf-8', 'replace')
        # The period guard flash must be visible in the re-rendered form.
        assert 'closed' in html.lower() or 'period' in html.lower(), (
            'Expected a closed-period flash message in the re-rendered form.'
        )
