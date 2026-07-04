"""seed_minimal() must produce the lean general-purpose CORE baseline (/reset-database)."""
import pytest

from app import db
from app.seeds.seed_data import seed_minimal, BASELINE_COA
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.users.models import User
from app.branches.models import Branch
from app.settings import AppSettings
from app.users.module_access import module_enabled
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]

# Posting anchors the views hardcode + the one expense leaf — all must be postable.
POSTABLE_ANCHORS = ['10101', '10110', '10201', '10212', '10501', '10502', '10503',
                    '10504', '20101', '20201', '20301', '30201', '40101', '40102', '50226']


def test_seed_minimal_produces_core_baseline(db_session):
    seed_minimal()

    # Admin + Main Branch, admin assigned
    admin = User.query.filter_by(username='admin').first()
    assert admin is not None and admin.role == 'admin'
    main = Branch.query.filter_by(code='MAIN').first()
    assert main is not None and main in admin.branches.all()

    # COA: exactly the 25-account baseline; anchors resolve as postable leaves
    assert Account.query.count() == len(BASELINE_COA) == 25
    all_accts = Account.query.all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}

    def postable(code):
        a = Account.query.filter_by(code=code).first()
        return a is not None and a.parent_id is not None and a.id not in parent_ids

    for code in POSTABLE_ANCHORS:
        assert postable(code), f"{code} must be a postable leaf"

    # VAT/WHT master data with correct account mappings
    assert VATCategory.query.count() == 7
    assert SalesVATCategory.query.count() == 3
    assert WithholdingTax.query.count() == 8
    assert VATCategory.query.filter_by(code='V12CG').first().input_vat_account_id == \
        Account.query.filter_by(code='10501').first().id
    assert SalesVATCategory.query.filter_by(code='V12').first().output_vat_account_id == \
        Account.query.filter_by(code='20201').first().id
    assert {w.code for w in WithholdingTax.query.all()} == {
        'WC158', 'WI158', 'WC160', 'WI160', 'WC100', 'WI100', 'WC010', 'WI010'}

    # 25 app settings; identity blank-ish, company_name default present
    assert AppSettings.query.count() == 25
    assert AppSettings.get_setting('company_name') == 'Company Name'
    assert AppSettings.get_setting('company_tin') == ''

    # CORE-only module gate: every optional module OFF, core stays ON
    clear_module_config_cache()
    assert module_enabled('bir_reports') is False
    assert module_enabled('units_of_measure') is False
    assert module_enabled('products') is False
    assert module_enabled('accounts_payable') is True
    assert module_enabled('journal_entries') is True


def test_seed_minimal_seeds_no_expense_except_office_supplies(db_session):
    """No-expenses rule, relaxed by exactly one (50226) so APV lines have a debit target."""
    seed_minimal()
    expense_codes = {a.code for a in Account.query.filter(
        Account.account_type.like('%Expense%')).all()}
    # Only the G&A header (50220, group) and the single Office Supplies leaf (50226).
    assert expense_codes == {'50220', '50226'}
