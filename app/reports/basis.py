"""Which basis a report is rendered on: GAAP (the books) or the owners' VAT-inclusive view.

Spec: docs/design/2026-09-13-owners-vat-inclusive-basis-design.md, section 2.

resolve_basis() is the ONLY gate. Three things must all hold for OWNERS: the company
switch is on, the user has full access (admin / Chief Accountant), and the request asked
for it with ?basis=owners. Anything else is GAAP, with no error: a stakeholder-facing user
who pastes an owners' URL simply gets the books.
"""
from app.settings import AppSettings

GAAP = 'gaap'
OWNERS = 'owners'

ENABLED_KEY = 'owners_basis_enabled'
VAT_EXPENSE_KEY_PREFIX = 'owners_basis_vat_expense_account:'

OWNERS_NOTE = "Owners' basis: VAT included in income and expenses. Not for external reporting."
NOT_BOOK_OF_RECORD = 'Not a book of record.'


def owners_basis_enabled():
    return AppSettings.get_setting(ENABLED_KEY) == '1'


def vat_expense_setting_key(category_id):
    return f'{VAT_EXPENSE_KEY_PREFIX}{int(category_id)}'


def _active_categories():
    from app.product_categories.models import ProductCategory
    return ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.code).all()


def vat_expense_account_map():
    """{ProductCategory.id: Account or None} for every ACTIVE product category.

    A code that no longer resolves to an ACTIVE account is reported as None, so a
    retired account cannot silently swallow VAT expense."""
    from app.accounts.models import Account
    out = {}
    for cat in _active_categories():
        code = AppSettings.get_setting(vat_expense_setting_key(cat.id))
        acct = Account.query.filter_by(code=code, is_active=True).first() if code else None
        out[cat.id] = acct
    return out


def unmapped_categories():
    """Active categories with no usable VAT expense account, in code order."""
    m = vat_expense_account_map()
    return [c for c in _active_categories() if m.get(c.id) is None]


def can_switch_basis(user):
    """Full-access user on a company whose switch is on."""
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and user.has_full_access and owners_basis_enabled())


def resolve_basis(user, args):
    """GAAP unless the switch is on, the user may switch, AND args['basis'] == 'owners'."""
    if args.get('basis') == OWNERS and can_switch_basis(user):
        return OWNERS
    return GAAP
