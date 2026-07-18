"""Income Statement by Product Line (Phase 3a+3b) -- re-projects generate_income_statement()
onto product-line columns. See
docs/superpowers/specs/2026-07-12-income-statement-by-product-line-phase3-design.md
(2026-07-19 addendum) for the master invariant and traversal rule this implements.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.reports.financial import generate_income_statement
from app.reports.product_line import generate_sales_by_product_line
from app.reports.sections import IS_SECTIONS

UNALLOCATED = 'unallocated'
TOTAL = 'total'
_SI_ON_BOOKS = ('posted', 'partially_paid', 'paid')


def _resolve_leaves(section_lines):
    """Flatten a rollup() section's 'lines' into real leaf {account_id, amount} dicts.

    Per the traversal rule (spec addendum): a top-level entry WITH children distributes
    each CHILD (the real leaf account); a top-level entry with NO children IS the leaf
    itself (there is no finer account underneath it).
    """
    leaves = []
    for entry in section_lines:
        children = entry.get('children') or []
        if children:
            for c in children:
                leaves.append({'account_id': c['account_id'], 'amount': Decimal(str(c['amount']))})
        else:
            leaves.append({'account_id': entry['account_id'], 'amount': Decimal(str(entry['total']))})
    return leaves
