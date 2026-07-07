from app.seeds.seed_data import seed_firm
from app.seeds.firm_coa import FIRM_COA
from app.accounts.models import Account
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax


def test_seed_firm_creates_full_coa(db_session):
    seed_firm()
    assert Account.query.count() == len(FIRM_COA)
    for code in ['10201', '10212', '20101', '20301', '30201', '30301']:
        assert Account.query.filter_by(code=code).first() is not None


def test_seed_firm_sets_placeholder_company_name(db_session):
    seed_firm()
    assert AppSettings.get_setting('company_name') == 'Cruz Accounting & Software'


def test_seed_firm_tax_master_data(db_session):
    seed_firm()
    assert VATCategory.query.count() == 7
    assert SalesVATCategory.query.count() == 3
    assert WithholdingTax.query.count() == 8


def test_seed_firm_vat_pointers_resolve(db_session):
    seed_firm()
    v = VATCategory.query.filter_by(code='V12SV').first()
    assert v.input_vat_account is not None
    assert v.input_vat_account.code == '10503'
    sv = SalesVATCategory.query.filter_by(code='V12').first()
    assert sv.output_vat_account is not None
    assert sv.output_vat_account.code == '20201'


def test_seed_firm_wires_parents(db_session):
    seed_firm()
    ar = Account.query.filter_by(code='10201').first()
    assert ar.parent is not None
    assert ar.parent.code == '10200'


def test_seed_firm_admin_and_branch(db_session):
    seed_firm()
    from app.users.models import User
    from app.branches.models import Branch
    admin = User.query.filter_by(username='admin').first()
    assert admin is not None and admin.role == 'admin'
    assert Branch.query.filter_by(code='MAIN').first() is not None
