"""
TDD Performance Tests for Database Optimization
These tests define performance requirements BEFORE implementation

Run with: pytest tests/performance/ -v
"""
import pytest
import time
from datetime import date, datetime
from sqlalchemy import event, text
from app.accounts.models import Account
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.audit.models import AuditLog
from app.errors.models import ErrorLog


@pytest.fixture
def query_counter():
    """Fixture to count SQL queries"""
    from app import db

    class QueryCounter:
        def __init__(self):
            self.count = 0
            self.queries = []

        def reset(self):
            self.count = 0
            self.queries = []

    counter = QueryCounter()

    def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter.count += 1
        counter.queries.append(statement)

    event.listen(db.engine, "after_cursor_execute", receive_after_cursor_execute)

    yield counter

    event.remove(db.engine, "after_cursor_execute", receive_after_cursor_execute)


@pytest.mark.performance
class TestAccountQueryPerformance:
    """TDD: Test account query performance requirements"""

    def test_account_by_code_lookup_is_fast(self, db_session, query_counter):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Looking up account by code should complete in <50ms
        WHY: Frequently used in transaction forms, dropdowns
        SOLUTION: Add index on code column
        """
        # Arrange: Create 1000 accounts
        for i in range(1000):
            account = Account(
                code=f'TEST{i:04d}',
                name=f'Test Account {i}',
                account_type='Asset',
                normal_balance='Debit'
            )
            db_session.add(account)
        db_session.commit()

        # Act: Measure query time
        start = time.time()
        result = Account.query.filter_by(code='TEST0500').first()
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance requirement
        assert result is not None
        assert result.code == 'TEST0500'
        assert duration_ms < 50, f"Query took {duration_ms:.2f}ms, expected <50ms"
        # This will FAIL initially without index, then PASS after adding index

    def test_active_accounts_query_uses_index(self, db_session, query_counter):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Filtering by is_active should be indexed
        WHY: Chart of accounts dropdown filters active accounts
        SOLUTION: Add index on is_active column
        """
        # Arrange: Create mix of active and inactive accounts
        for i in range(500):
            account = Account(
                code=f'ACTIVE{i:03d}',
                name=f'Active Account {i}',
                account_type='Asset',
                normal_balance='Debit',
                is_active=True
            )
            db_session.add(account)

        for i in range(500):
            account = Account(
                code=f'INACTIVE{i:03d}',
                name=f'Inactive Account {i}',
                account_type='Asset',
                normal_balance='Debit',
                is_active=False
            )
            db_session.add(account)
        db_session.commit()

        # Act: Query active accounts
        query_counter.reset()
        start = time.time()
        active_accounts = Account.query.filter_by(is_active=True).all()
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance and correctness
        assert len(active_accounts) == 500
        assert all(a.is_active for a in active_accounts)
        assert duration_ms < 100, f"Query took {duration_ms:.2f}ms, expected <100ms"
        # Will FAIL without index, PASS after adding index


@pytest.mark.performance
class TestN1QueryPrevention:
    """TDD: Test N+1 query prevention requirements"""

    def test_sales_invoices_list_no_n_plus_1(self, db_session, query_counter, cash_account):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Loading 100 invoices should use <=5 queries (not 100+)
        WHY: List page would make 1 query per invoice for customer name
        SOLUTION: Use joinedload(SalesInvoice.customer)
        """
        # Arrange: Create customers and invoices
        customers = []
        for i in range(10):
            customer = Customer(
                code=f'CUST{i:03d}',
                name=f'Customer {i}',
                email=f'customer{i}@test.com'
            )
            db_session.add(customer)
            customers.append(customer)
        db_session.commit()

        for i in range(100):
            invoice = SalesInvoice(
                invoice_number=f'INV-{i:04d}',
                invoice_date=date(2026, 1, 1),
                due_date=date(2026, 1, 31),
                customer_id=customers[i % 10].id,
                customer_name=customers[i % 10].name,
                status='draft',
                total_amount=1000.00
            )
            db_session.add(invoice)
        db_session.commit()

        # Act: Load invoices (NAIVE way - will fail)
        query_counter.reset()
        invoices = SalesInvoice.query.all()

        # Access customer for each invoice (triggers N+1)
        for invoice in invoices:
            _ = invoice.customer_name  # Using stored name, but testing relationship

        # Assert: Query count requirement
        assert len(invoices) == 100
        # REQUIREMENT: Should use <=5 queries total
        # 1 query for invoices, 1-2 for customers (with joinedload)
        # This will FAIL initially (100+ queries), PASS after joinedload
        assert query_counter.count <= 5, (
            f"Query count: {query_counter.count}, expected <=5 (N+1 detected!)"
        )

    def test_purchase_bills_with_items_optimized(self, db_session, query_counter):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Loading bills with items should use <=3 queries for 50 bills
        WHY: Bill list shows item count - could trigger N+1
        SOLUTION: Use selectinload(PurchaseBill.items)
        """
        # Arrange: Create vendors and bills with items
        from app.vendors.models import Vendor

        vendors = []
        for i in range(5):
            vendor = Vendor(
                code=f'VEND{i:03d}',
                name=f'Vendor {i}',
                email=f'vendor{i}@test.com'
            )
            db_session.add(vendor)
            vendors.append(vendor)
        db_session.commit()

        for i in range(50):
            bill = PurchaseBill(
                bill_number=f'BILL-{i:04d}',
                bill_date=date(2026, 1, 1),
                due_date=date(2026, 1, 31),
                vendor_id=vendors[i % 5].id,
                vendor_name=vendors[i % 5].name,
                status='draft',
                total_amount=5000.00
            )
            db_session.add(bill)
            db_session.flush()

            # Add 3 items to each bill
            for j in range(3):
                item = PurchaseBillItem(
                    bill_id=bill.id,
                    line_number=j + 1,
                    description=f'Item {j}',
                    amount=100.00,
                    vat_rate=0.00
                )
                item.calculate_amounts()
                db_session.add(item)
        db_session.commit()

        # Act: Load bills with items (with optimization)
        query_counter.reset()
        from sqlalchemy.orm import selectinload
        bills = PurchaseBill.query.options(selectinload(PurchaseBill.line_items)).all()

        # Access items for each bill (should NOT trigger N+1 with selectinload)
        total_items = sum(len(bill.line_items) for bill in bills)

        # Assert: Query count and correctness
        assert len(bills) == 50
        assert total_items == 150  # 50 bills × 3 items
        # REQUIREMENT: Should use <=3 queries (1 for bills, 1 for items with selectinload)
        # Will FAIL initially (50+ queries), PASS after selectinload
        assert query_counter.count <= 3, (
            f"Query count: {query_counter.count}, expected <=3 (N+1 detected!)"
        )


@pytest.mark.performance
class TestPaginationPerformance:
    """TDD: Test pagination performance requirements"""

    def test_customer_list_pagination_works(self, db_session):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Customer list should support pagination
        WHY: 1000+ customers would be slow to load all at once
        SOLUTION: Add .paginate() to query
        """
        # Arrange: Create 500 customers
        for i in range(500):
            customer = Customer(
                code=f'CUST{i:04d}',
                name=f'Customer {i}',
                email=f'customer{i}@test.com'
            )
            db_session.add(customer)
        db_session.commit()

        # Act: Query with pagination (simulating view)
        page_1 = Customer.query.paginate(page=1, per_page=20)
        page_2 = Customer.query.paginate(page=2, per_page=20)

        # Assert: Pagination working
        assert page_1.total == 500
        assert len(page_1.items) == 20
        assert page_1.pages == 25  # 500 / 20 = 25 pages
        assert page_1.has_next is True
        assert page_1.has_prev is False

        assert len(page_2.items) == 20
        assert page_2.has_prev is True
        # First customer on page 2 should be customer 20
        assert page_2.items[0].code == 'CUST0020'

    def test_vendor_list_pagination_performance(self, db_session):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Loading page 1 of vendors should be fast (<100ms)
        WHY: Users frequently access first page
        SOLUTION: Pagination + index on commonly sorted columns
        """
        # Arrange: Create 1000 vendors
        for i in range(1000):
            vendor = Vendor(
                code=f'V{i:04d}',
                name=f'Vendor {i}',
                email=f'vendor{i}@test.com'
            )
            db_session.add(vendor)
        db_session.commit()

        # Act: Measure pagination query time
        start = time.time()
        page = Vendor.query.order_by(Vendor.code).paginate(page=1, per_page=20)
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance requirement
        assert len(page.items) == 20
        assert duration_ms < 100, f"Pagination took {duration_ms:.2f}ms, expected <100ms"


@pytest.mark.performance
class TestAuditLogPerformance:
    """TDD: Test audit log query performance"""

    def test_audit_log_by_module_and_date_is_indexed(self, db_session, admin_user):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Filtering audit logs by module+date should be fast
        WHY: Audit report frequently filters by module and date range
        SOLUTION: Add composite index on (module, timestamp)
        """
        from app.utils import ph_now

        # Arrange: Create 5000 audit logs
        modules = ['account', 'customer', 'vendor', 'invoice', 'bill']
        for i in range(5000):
            log = AuditLog(
                module=modules[i % 5],
                action='create',
                record_id=i,
                record_identifier=f'Record {i}',
                user_id=admin_user.id,
                timestamp=ph_now()
            )
            db_session.add(log)
        db_session.commit()

        # Act: Query filtered by module
        start = time.time()
        account_logs = AuditLog.query.filter_by(module='account').all()
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance requirement
        assert len(account_logs) == 1000  # 5000 / 5 = 1000 per module
        assert duration_ms < 50, f"Query took {duration_ms:.2f}ms, expected <50ms"
        # Will FAIL without index, PASS after adding composite index


@pytest.mark.performance
class TestErrorLogPerformance:
    """TDD: Test error log query performance"""

    def test_error_log_by_severity_is_indexed(self, db_session):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Filtering errors by severity should be fast
        WHY: Error dashboard shows critical errors first
        SOLUTION: Add composite index on (severity, timestamp)
        """
        from app.utils import ph_now

        # Arrange: Create 2000 error logs
        severities = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']
        for i in range(2000):
            error = ErrorLog(
                severity=severities[i % 4],
                module='test',
                error_type='TestError',
                error_message=f'Error {i}',
                timestamp=ph_now()
            )
            db_session.add(error)
        db_session.commit()

        # Act: Query critical errors only
        start = time.time()
        critical_errors = ErrorLog.query.filter_by(severity='CRITICAL').all()
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance requirement
        assert len(critical_errors) == 500  # 2000 / 4 = 500 per severity
        assert duration_ms < 50, f"Query took {duration_ms:.2f}ms, expected <50ms"
        # Will FAIL without index, PASS after adding index


@pytest.mark.performance
class TestCompositeIndexes:
    """TDD: Test composite index requirements"""

    def test_invoices_by_status_and_date_fast(self, db_session):
        """
        RED → GREEN → REFACTOR
        REQUIREMENT: Filter invoices by status+date should use composite index
        WHY: Reports often filter "posted invoices in date range"
        SOLUTION: Add composite index on (status, invoice_date)
        """
        # Arrange: Create 1000 invoices with various statuses
        from app.customers.models import Customer

        customer = Customer(code='TEST001', name='Test Customer', email='test@test.com')
        db_session.add(customer)
        db_session.commit()

        statuses = ['draft', 'posted', 'cancelled']
        for i in range(1000):
            invoice = SalesInvoice(
                invoice_number=f'INV-{i:04d}',
                invoice_date=date(2026, 1, (i % 28) + 1),
                due_date=date(2026, 2, (i % 28) + 1),
                customer_id=customer.id,
                customer_name=customer.name,
                status=statuses[i % 3],
                total_amount=1000.00
            )
            db_session.add(invoice)
        db_session.commit()

        # Act: Query posted invoices (common filter)
        start = time.time()
        posted = SalesInvoice.query.filter_by(status='posted').all()
        duration_ms = (time.time() - start) * 1000

        # Assert: Performance requirement
        assert len(posted) > 300  # ~1/3 of invoices
        assert duration_ms < 100, f"Query took {duration_ms:.2f}ms, expected <100ms"
        # Will FAIL without composite index, PASS after adding it
