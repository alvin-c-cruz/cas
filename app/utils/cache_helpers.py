"""
Cache helper functions for frequently accessed static data.

Provides cached access to:
- Chart of Accounts
- VAT Categories
- Withholding Tax codes
- Branch list
- User permissions

Cache TTL: 1 hour (static data changes infrequently)
"""
from sqlalchemy.orm import joinedload
from app import cache
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
from app.branches.models import Branch
from app.sales_vat_categories.models import SalesVATCategory


@cache.memoize(timeout=3600)
def get_active_accounts():
    """Get all active accounts (cached for 1 hour)"""
    return Account.query.filter_by(is_active=True).order_by(Account.code).all()


@cache.memoize(timeout=3600)
def get_accounts_by_type(account_type):
    """Get accounts filtered by type (cached for 1 hour)"""
    return Account.query.filter_by(
        account_type=account_type,
        is_active=True
    ).order_by(Account.code).all()


@cache.memoize(timeout=3600)
def get_account_by_code(code):
    """Get account by code (cached for 1 hour)"""
    return Account.query.filter_by(code=code, is_active=True).first()


@cache.memoize(timeout=3600)
def get_vat_categories():
    """Get all active VAT categories (cached for 1 hour)"""
    return VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()


@cache.memoize(timeout=3600)
def get_sales_vat_categories():
    """Get all active Sales VAT categories (cached for 1 hour).

    joinedload(output_vat_account) is REQUIRED: these ORM objects are memoized and
    outlive their request/session, and to_dict() reads output_vat_account.code/name.
    Without eager-load, the detached read raises DetachedInstanceError -> HTTP 500 on
    /sales-orders/create once the cache warms. See test_sales_vat_cache.py.
    """
    return (SalesVATCategory.query
            .options(joinedload(SalesVATCategory.output_vat_account))
            .filter_by(is_active=True).order_by(SalesVATCategory.code).all())


@cache.memoize(timeout=3600)
def get_withholding_tax_codes():
    """Get all active withholding tax codes (cached for 1 hour)"""
    return WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()


@cache.memoize(timeout=3600)
def get_active_branches():
    """Get all active branches (cached for 1 hour)"""
    return Branch.query.filter_by(is_active=True).order_by(Branch.code).all()


@cache.memoize(timeout=3600)
def get_main_branch():
    """Get the main branch (cached for 1 hour)"""
    return Branch.query.filter_by(code='MAIN', is_active=True).first()


def clear_account_cache():
    """Clear account-related caches after updates"""
    cache.delete_memoized(get_active_accounts)
    cache.delete_memoized(get_accounts_by_type)
    cache.delete_memoized(get_account_by_code)


def clear_vat_cache():
    """Clear VAT category cache after updates"""
    cache.delete_memoized(get_vat_categories)


def clear_sales_vat_cache():
    """Clear Sales VAT category cache after updates."""
    cache.delete_memoized(get_sales_vat_categories)


def clear_withholding_tax_cache():
    """Clear withholding tax cache after updates"""
    cache.delete_memoized(get_withholding_tax_codes)


def clear_branch_cache():
    """Clear branch cache after updates"""
    cache.delete_memoized(get_active_branches)
    cache.delete_memoized(get_main_branch)


def clear_all_caches():
    """Clear all cached data"""
    cache.clear()


@cache.memoize(timeout=3600)
def get_module_override(key):
    """Stored `module_enabled:<key>` value ('1'/'0') or None if unset (cached 1h)."""
    from app.settings import AppSettings
    return AppSettings.get_setting(f'module_enabled:{key}')


def clear_module_config_cache():
    """Invalidate cached module-enablement after a toggle."""
    cache.delete_memoized(get_module_override)


@cache.memoize(timeout=3600)
def get_active_units():
    """Get all active units of measure (cached 1 hour)."""
    from app.units_of_measure.models import UnitOfMeasure
    return UnitOfMeasure.query.filter_by(is_active=True).order_by(UnitOfMeasure.code).all()


def clear_uom_cache():
    """Clear units-of-measure cache after updates."""
    cache.delete_memoized(get_active_units)


@cache.memoize(timeout=3600)
def get_active_product_categories():
    """Get all active product categories (cached 1 hour)."""
    from app.product_categories.models import ProductCategory
    return ProductCategory.query.filter_by(is_active=True).order_by(ProductCategory.code).all()


def clear_product_category_cache():
    """Clear product-category cache after updates."""
    cache.delete_memoized(get_active_product_categories)


@cache.memoize(timeout=3600)
def get_active_products():
    """Get all active products (cached 1 hour).

    Eager-load default_unit_of_measure: Product.to_dict() reads
    default_unit_of_measure.code, a relationship. Cached ORM objects outlive the
    request/session that created them, so a lazy load on a later (detached) access
    raises DetachedInstanceError (HTTP 500). joinedload populates the attribute at
    query time, so reading it detached is safe — matching the column-only helpers
    above that are already detach-safe.
    """
    from sqlalchemy.orm import joinedload
    from app.products.models import Product
    return (Product.query
            .options(joinedload(Product.default_unit_of_measure))
            .filter_by(is_active=True)
            .order_by(Product.code)
            .all())


def clear_product_cache():
    """Clear products cache after updates."""
    cache.delete_memoized(get_active_products)
