"""Integration tests for the APV/CDV historical seed generator."""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.branches.models import Branch
from app.seeds.seed_data import (
    seed_chart_of_accounts, seed_vat_categories, seed_withholding_tax_codes,
)
from app.seeds import history_seed as hs

pytestmark = [pytest.mark.integration]


def _admin():
    from app.users.models import User
    u = User.query.filter_by(username='admin').first()
    if u is None:
        u = User(username='admin', email='admin@cas.local',
                 full_name='System Administrator', role='admin', is_active=True)
        u.set_password('admin123')
        db.session.add(u); db.session.commit()
    return u


@pytest.fixture
def base_db(db_session):
    """Populate the seed-db COA + VAT + WHT + a Main branch into the empty test DB."""
    seed_chart_of_accounts()
    seed_vat_categories()
    seed_withholding_tax_codes()
    branch = Branch(code='MAIN', name='Main Office', is_active=True)
    db.session.add(branch)
    db.session.commit()
    return branch


class TestRefsAndHelpers:
    def test_resolve_refs_finds_structural_accounts(self, base_db):
        refs = hs.resolve_refs()
        assert refs['ap'].code == '20101'
        assert refs['wt'].code == '20301'
        assert refs['input_vat'].code == '10501'
        assert refs['cash_on_hand'].code == '10101'
        assert refs['cash_in_bank'].code == '10110'
        # every expense code referenced by a vendor resolves to an Account
        for v in hs.VENDORS:
            assert v['expense_code'] in refs['expense']

    def test_next_doc_number_sequences_per_month(self):
        counters = {}
        assert hs.next_doc_number('AP', date(2021, 1, 5), counters) == 'AP-2021-01-0001'
        assert hs.next_doc_number('AP', date(2021, 1, 9), counters) == 'AP-2021-01-0002'
        assert hs.next_doc_number('AP', date(2021, 2, 1), counters) == 'AP-2021-02-0001'
        assert hs.next_doc_number('CD', date(2021, 1, 9), counters) == 'CD-2021-01-0001'

    def test_ensure_vendors_creates_twelve_with_defaults(self, base_db):
        vendors = hs.ensure_vendors()
        assert len(vendors) == 12
        from app.vendors.models import Vendor
        assert Vendor.query.count() == 12
        # idempotent within a run
        assert len(hs.ensure_vendors()) == 12
        assert Vendor.query.count() == 12

    def test_ensure_accountant_user(self, base_db):
        u = hs.ensure_accountant_user()
        assert u.username == 'accountant'
        assert u.role == 'accountant'
        assert u.check_password('cas-accountant')


class TestApvBuilder:
    def test_build_apv_posts_balanced_je(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user()
        hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-LAW')   # VATABLE + WC010 10%
        vobj = Vendor.query.filter_by(code='HV-LAW').first()
        counters = {}
        ap = hs.build_apv(date(2021, 3, 4), spec, vobj, refs,
                          creator_id=acct.id, poster_id=admin.id,
                          branch_id=base_db.id, counters=counters, amount=Decimal('56000.00'))
        assert ap.ap_number == 'AP-2021-03-0001'
        assert ap.status == 'posted'
        # VAT extracted from 56,000 inclusive @12%
        assert ap.vat_amount == Decimal('6000.00')
        # WHT 10% of net (50,000)
        assert ap.withholding_tax_amount == Decimal('5000.00')
        # Net payable = subtotal - WHT
        assert ap.total_amount == Decimal('51000.00')
        # JE exists and balances
        je = ap.journal_entry
        assert je is not None and je.status == 'posted'
        debit = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        credit = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        assert debit == credit

    def test_build_apv_exempt_no_vat(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user()
        hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-WATR')  # VAT-EXEMPT, no WHT
        vobj = Vendor.query.filter_by(code='HV-WATR').first()
        ap = hs.build_apv(date(2021, 3, 6), spec, vobj, refs, acct.id, admin.id,
                          base_db.id, {}, amount=Decimal('2000.00'))
        assert ap.vat_amount == Decimal('0.00')
        assert ap.withholding_tax_amount == Decimal('0.00')
        assert ap.total_amount == Decimal('2000.00')
        je = ap.journal_entry
        debit = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        credit = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        assert debit == credit
