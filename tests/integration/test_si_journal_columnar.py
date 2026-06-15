# tests/integration/test_si_journal_columnar.py

import pytest
from datetime import date
from decimal import Decimal

# These tests exercise the pure data layer — no Flask app context needed
# They build JournalEntry and JournalEntryLine objects in-memory and call build_columnar_si directly.


class TestBuildColumnarSI:

    def test_build_columnar_si_posted_pivot_and_balance(self, app, db_session):
        """One posted SI JE with AR (dr) and Revenue (cr) — should balance to 0."""
        from app.journals.si_journal_data import build_columnar_si
        from app.journal_entries.models import JournalEntry, JournalEntryLine
        from app.accounts.models import Account
        from app.branches.models import Branch

        # Set up accounts
        branch = Branch(code='T', name='Test', is_active=True)
        db_session.add(branch)
        db_session.flush()

        ar = Account(code='AR01', name='AR Test', account_type='Asset', normal_balance='debit', is_active=True)
        rev = Account(code='REV1', name='Revenue Test', account_type='Revenue', normal_balance='credit', is_active=True)
        db_session.add_all([ar, rev])
        db_session.flush()

        je = JournalEntry(
            entry_number='SI-0001', entry_type='sale', entry_date=date(2026, 6, 1),
            description='Test SI', status='posted', branch_id=branch.id,
            total_debit=Decimal('1000'), total_credit=Decimal('1000')
        )
        db_session.add(je)
        db_session.flush()

        line1 = JournalEntryLine(
            entry_id=je.id, account_id=ar.id, line_number=1,
            debit_amount=Decimal('1000'), credit_amount=Decimal('0'), description='AR'
        )
        line2 = JournalEntryLine(
            entry_id=je.id, account_id=rev.id, line_number=2,
            debit_amount=Decimal('0'), credit_amount=Decimal('1000'), description='Revenue'
        )
        db_session.add_all([line1, line2])
        db_session.commit()

        matrix = build_columnar_si([je], [], ar.id, None, set(), voided_invoices=[])

        assert matrix['balanced'] is True
        assert matrix['totals'].get(ar.id) == Decimal('1000')    # debit posted as positive
        assert matrix['totals'].get(rev.id) == Decimal('-1000')  # credit posted as negative
        col_groups = {c['account_id']: c['group'] for c in matrix['columns']}
        assert col_groups[ar.id] == 'ar'
        assert col_groups[rev.id] == 'revenue'
        # AR should sort before Revenue
        col_order = [c['account_id'] for c in matrix['columns']]
        assert col_order.index(ar.id) < col_order.index(rev.id)

    def test_build_columnar_si_draft_excluded_from_totals(self, app, db_session):
        """Draft entries appear in rows but do not contribute to totals."""
        from app.journals.si_journal_data import build_columnar_si
        from app.journal_entries.models import JournalEntry, JournalEntryLine
        from app.accounts.models import Account
        from app.branches.models import Branch

        branch = Branch(code='T2', name='Test2', is_active=True)
        db_session.add(branch)
        db_session.flush()

        ar = Account(code='AR02', name='AR Test2', account_type='Asset', normal_balance='debit', is_active=True)
        rev = Account(code='REV2', name='Revenue Test2', account_type='Revenue', normal_balance='credit', is_active=True)
        db_session.add_all([ar, rev])
        db_session.flush()

        posted = JournalEntry(
            entry_number='SI-0002', entry_type='sale', entry_date=date(2026, 6, 1),
            description='Posted SI', status='posted', branch_id=branch.id,
            total_debit=Decimal('500'), total_credit=Decimal('500')
        )
        draft = JournalEntry(
            entry_number='SI-0003', entry_type='sale', entry_date=date(2026, 6, 2),
            description='Draft SI', status='draft', branch_id=branch.id,
            total_debit=Decimal('200'), total_credit=Decimal('200')
        )
        db_session.add_all([posted, draft])
        db_session.flush()

        for i, (je, amt) in enumerate([(posted, 500), (draft, 200)]):
            db_session.add(JournalEntryLine(
                entry_id=je.id, account_id=ar.id, line_number=1,
                debit_amount=Decimal(str(amt)), credit_amount=Decimal('0'), description='AR'
            ))
            db_session.add(JournalEntryLine(
                entry_id=je.id, account_id=rev.id, line_number=2,
                debit_amount=Decimal('0'), credit_amount=Decimal(str(amt)), description='Rev'
            ))
        db_session.commit()

        matrix = build_columnar_si([posted], [draft], ar.id, None, set())

        # Draft row present but cells empty
        draft_rows = [r for r in matrix['rows'] if r.get('is_draft')]
        assert len(draft_rows) == 1
        assert draft_rows[0]['cells'] == {}
        # Totals only include posted
        assert matrix['totals'].get(ar.id) == Decimal('500')

    def test_build_columnar_si_voided_invoice_row(self, app, db_session):
        """Voided SalesInvoice appears as a row with is_voided=True; no amounts in totals."""
        from app.journals.si_journal_data import build_columnar_si
        from app.sales_invoices.models import SalesInvoice
        from app.branches.models import Branch
        from app.customers.models import Customer

        branch = Branch(code='T3', name='Test3', is_active=True)
        db_session.add(branch)
        db_session.flush()

        # SalesInvoice requires customer_id (NOT NULL) — create a minimal customer
        customer = Customer(
            code='CUST-V001',
            name='Voided Customer',
        )
        db_session.add(customer)
        db_session.flush()

        voided_inv = SalesInvoice(
            invoice_number='SI-V001',
            invoice_date=date(2026, 6, 1),
            due_date=date(2026, 6, 30),
            customer_id=customer.id,
            customer_name='Voided Customer',
            branch_id=branch.id,
            status='voided',
            subtotal=Decimal('0'),
            vat_amount=Decimal('0'),
            total_before_wt=Decimal('0'),
            withholding_tax_amount=Decimal('0'),
            total_amount=Decimal('0'),
            amount_paid=Decimal('0'),
            balance=Decimal('0'),
            notes='',
        )
        db_session.add(voided_inv)
        db_session.commit()

        matrix = build_columnar_si([], [], None, None, set(), voided_invoices=[voided_inv])

        voided_rows = [r for r in matrix['rows'] if r.get('is_voided')]
        assert len(voided_rows) == 1
        assert voided_rows[0]['invoice'].invoice_number == 'SI-V001'
        assert not matrix['totals']  # no amounts
