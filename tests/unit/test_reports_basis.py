"""resolve_basis() is the only gate to the owners' view: company switch ON, full-access
user, and ?basis=owners. Any one missing -> GAAP, silently (spec section 2)."""
import pytest

from app import db
from app.accounts.models import Account
from app.product_categories.models import ProductCategory
from app.settings import AppSettings
from app.reports import basis as B

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]


def _cat(code, name, active=True):
    c = ProductCategory(code=code, name=name, is_active=active)
    db.session.add(c); db.session.commit()
    return c


def _acct(code, name, atype='Other Expense', normal='Debit', active=True):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=active)
    db.session.add(a); db.session.commit()
    return a


def test_disabled_by_default(app, db_session):
    assert B.owners_basis_enabled() is False


def test_resolve_is_gaap_when_switch_off(app, db_session, admin_user):
    assert B.resolve_basis(admin_user, {'basis': 'owners'}) == B.GAAP


def test_resolve_is_owners_for_full_access_with_switch_and_param(app, db_session, admin_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(admin_user, {'basis': 'owners'}) == B.OWNERS


def test_resolve_is_gaap_without_param(app, db_session, admin_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(admin_user, {}) == B.GAAP


def test_resolve_is_gaap_for_staff_even_with_param(app, db_session, staff_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.resolve_basis(staff_user, {'basis': 'owners'}) == B.GAAP
    assert B.can_switch_basis(staff_user) is False


def test_chief_accountant_may_switch(app, db_session, chief_accountant_user):
    AppSettings.set_setting(B.ENABLED_KEY, '1')
    assert B.can_switch_basis(chief_accountant_user) is True


def test_vat_expense_map_and_unmapped(app, db_session):
    tin = _cat('TIN', 'Tincan'); pla = _cat('PLA', 'Plastic'); _cat('OLD', 'Old', active=False)
    vat_tin = _acct('811001', 'VAT EXPENSE - TINCAN')
    AppSettings.set_setting(B.vat_expense_setting_key(tin.id), vat_tin.code)
    m = B.vat_expense_account_map()
    assert set(m) == {tin.id, pla.id}          # inactive category excluded
    assert m[tin.id].id == vat_tin.id and m[pla.id] is None
    assert [c.id for c in B.unmapped_categories()] == [pla.id]


def test_mapping_to_inactive_account_counts_as_unmapped(app, db_session):
    tin = _cat('TIN', 'Tincan')
    dead = _acct('811009', 'Dead', active=False)
    AppSettings.set_setting(B.vat_expense_setting_key(tin.id), dead.code)
    assert B.vat_expense_account_map()[tin.id] is None
