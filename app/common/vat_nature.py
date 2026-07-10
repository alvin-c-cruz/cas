"""Resolve a line's stored VAT-category code to its BIR classification.

Lines store the category CODE ('V12', 'V12SV'), not the name. SI/CRV lines
resolve against sales_vat_categories; AP/CDV lines against vat_categories.
Returns None for an empty, unmatched, or unclassified code -- never a guessed
default. The reports render None as 'Unclassified'.
"""
from app import db
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory


def _nature(model, code):
    if not code:
        return None
    row = db.session.query(model.transaction_nature).filter_by(code=code).first()
    return row[0] if row else None


def resolve_sales_nature(code):
    """BIR sales classification for a SalesVATCategory code, or None."""
    return _nature(SalesVATCategory, code)


def resolve_purchase_nature(code):
    """BIR purchase classification for a VATCategory code, or None."""
    return _nature(VATCategory, code)
