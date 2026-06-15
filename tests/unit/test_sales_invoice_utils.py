import pytest
from decimal import Decimal
from datetime import date


def test_compute_invoices_summary_empty(db_session, app):
    """compute_invoices_summary returns all zeros for a branch with no invoices."""
    with app.app_context():
        from app.branches.models import Branch
        branch = Branch.query.first()
        if not branch:
            branch = Branch(name='Main', code='MB', is_active=True)
            db_session.add(branch)
            db_session.commit()

        from app.sales_invoices.utils import compute_invoices_summary
        summary = compute_invoices_summary(branch.id)
        assert summary['outstanding_total'] == Decimal('0.00')
        assert summary['outstanding_count'] == 0
        assert summary['draft_count'] == 0
