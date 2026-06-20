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
    """Get all active Sales VAT categories (cached for 1 hour)."""
    return SalesVATCategory.query.filter_by(is_active=True).order_by(SalesVATCategory.code).all()


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
