"""Regression test: SI/CR journal pages must not 500 when VATCategory rows exist.

Pre-fix, _si_gl_account_ids() and _cr_gl_account_ids() iterated VATCategory and
accessed .output_vat_account, which no longer exists on that model (it was dropped
when output VAT moved to SalesVATCategory). Any seeded VATCategory row would
trigger an AttributeError → 500 on /journals/si and /journals/cr.

These tests seed BOTH a VATCategory row (to simulate the old trigger) and a
SalesVATCategory row with an output_vat_account_id (to exercise the correct path),
then assert both pages return 200.
"""
import pytest
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.users.models import User
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory

pytestmark = [pytest.mark.integration, pytest.mark.journals]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _branch(db_session):
    b = Branch(name='OVR Branch', code='OVR')
    db.session.add(b)
    db.session.commit()
    return b


@pytest.fixture()
def _accountant(db_session, _branch):
    from app.users.module_access import default_all_permissions
    u = User(username='ovr_acct', email='ovr_acct@test.com', full_name='OVR Acct',
             role='accountant', is_active=True)
    u.set_password('pass')
    # Accountants are now gated by book_permissions (Task 3); grant all so this
    # fixture user can reach /journals/si (accounts_receivable) and /journals/cr
    # (collections).
    u.set_book_permissions(default_all_permissions())
    u.branches.append(_branch)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def _output_vat_account(db_session):
    a = Account(code='OVR-VAT-OUT', name='Output VAT OVR', account_type='Liability',
                normal_balance='credit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture()
def _input_vat_account(db_session):
    a = Account(code='OVR-VAT-IN', name='Input VAT OVR', account_type='Asset',
                normal_balance='debit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture()
def _seeded_vat_rows(db_session, _output_vat_account, _input_vat_account):
    """Seed one VATCategory (purchase-side) and one SalesVATCategory (sales-side)."""
    # This VATCategory row is what previously caused AttributeError: no output_vat_account.
    vat = VATCategory(
        code='OVR-STD', name='OVR Standard', rate=Decimal('12.00'),
        is_active=True, input_vat_account_id=_input_vat_account.id,
    )
    db.session.add(vat)

    # SalesVATCategory — the correct source for output VAT accounts.
    svat = SalesVATCategory(
        code='OVR-OUT-STD', name='OVR Output Standard', rate=Decimal('12.00'),
        transaction_nature='regular', is_active=True,
        output_vat_account_id=_output_vat_account.id,
    )
    db.session.add(svat)
    db.session.commit()
    return vat, svat


def _login(client, username, branch_id, password='pass'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------

class TestOutputVATJournalRegression:
    """SI and CR journal views must return 200 when VATCategory rows are present."""

    def test_si_journal_ok_with_vat_category_row(
            self, client, _branch, _accountant, _seeded_vat_rows):
        _login(client, 'ovr_acct', _branch.id)
        resp = client.get('/journals/si')
        assert resp.status_code == 200, (
            f"Expected 200 on /journals/si but got {resp.status_code}. "
            "Pre-fix: VATCategory.output_vat_account AttributeError → 500."
        )

    def test_cr_journal_ok_with_vat_category_row(
            self, client, _branch, _accountant, _seeded_vat_rows):
        _login(client, 'ovr_acct', _branch.id)
        resp = client.get('/journals/cr')
        assert resp.status_code == 200, (
            f"Expected 200 on /journals/cr but got {resp.status_code}. "
            "Pre-fix: VATCategory.output_vat_account AttributeError → 500."
        )
