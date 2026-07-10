from app.seeds.seed_data import (
    seed_vat_categories, seed_withholding_tax_codes,
    _seed_vat_categories, _seed_withholding_taxes,
)
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax


class TestStandardSeedNatures:
    def test_seven_categories_all_classified(self, db_session):
        _seed_vat_categories()
        cats = VATCategory.query.all()
        assert len(cats) == 7
        assert all(c.transaction_nature for c in cats), \
            [c.code for c in cats if not c.transaction_nature]

    def test_standard_nature_assignment(self, db_session):
        _seed_vat_categories()
        by_code = {c.code: c.transaction_nature for c in VATCategory.query.all()}
        assert by_code == {
            'VEX': 'exempt', 'V0': 'zero_rated', 'INV': 'not_qualified',
            'V12CG': 'capital_goods', 'V12DG': 'domestic_goods',
            'V12SV': 'domestic_services', 'V12IM': 'importation',
        }


class TestLegacySeedNatures:
    def test_legacy_four_categories_all_classified(self, db_session):
        seed_vat_categories()
        by_code = {c.code: c.transaction_nature for c in VATCategory.query.all()}
        assert by_code == {
            'VATABLE': 'domestic_goods', 'VAT-EXEMPT': 'exempt',
            'ZERO-RATED': 'zero_rated', 'NON-VAT': 'not_qualified',
        }


class TestSeedTaxTypes:
    def test_standard_wht_seed_all_expanded(self, db_session):
        _seed_withholding_taxes()
        assert {w.tax_type for w in WithholdingTax.query.all()} == {'expanded'}

    def test_legacy_bank_interest_is_final_not_expanded(self, db_session):
        """WC100 'Interest from Bank Deposits' at 20% is a FINAL tax.
        Seeding it as expanded would let it onto a 2307 and a SAWT."""
        seed_withholding_tax_codes()
        wc100 = WithholdingTax.query.filter_by(code='WC100').first()
        assert wc100.name == 'Interest from Bank Deposits'
        assert wc100.tax_type == 'final'

    def test_legacy_other_codes_expanded(self, db_session):
        seed_withholding_tax_codes()
        wc010 = WithholdingTax.query.filter_by(code='WC010').first()
        assert wc010.tax_type == 'expanded'
