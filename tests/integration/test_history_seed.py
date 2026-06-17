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
