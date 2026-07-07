from app.seeds.seed_data import seed_minimal
from app.accounts.models import Account
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax


def test_seed_minimal_output_unchanged(db_session):
    seed_minimal()
    assert Account.query.count() == 25
    assert AppSettings.get_setting('company_name') == 'Company Name'
    assert VATCategory.query.count() == 7
    assert SalesVATCategory.query.count() == 3
    assert WithholdingTax.query.count() == 8
    # magic codes still present
    for code in ['10201', '10212', '20101', '20301', '30201', '30301']:
        assert Account.query.filter_by(code=code).first() is not None
