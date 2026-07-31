"""The combined AR aging report presents every branch at once.

Pins the multi-branch contract of `_build_ar_aging_data`: a customer trading
in two branches collapses to ONE summary row, invoices carry their branch, and
`viewable` reflects branch access rather than the selected branch.
"""
import pytest
from decimal import Decimal
from datetime import date

from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.reports.views import _build_ar_aging_data

pytestmark = [pytest.mark.integration]

AS_OF = date(2025, 12, 31)


def _customer(db_session, code, name=None):
    c = Customer(code=code, name=name or f'Cust {code}', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, branch_id, number, total,
             invoice_date=None, customer_name=None):
    d = invoice_date or date(2025, 11, 1)
    inv = SalesInvoice(
        branch_id=branch_id, invoice_number=number,
        invoice_date=d, due_date=d,
        customer_id=customer.id,
        customer_name=customer_name or customer.name,
        notes='', status='posted',
        amount_paid=Decimal('0.00'), balance=Decimal(str(total)),
        total_amount=Decimal(str(total)), subtotal=Decimal(str(total)),
        vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestCombinedBuilder:

    def test_same_customer_in_two_branches_is_one_row(self, db_session,
                                                      main_branch, branch_manila):
        c = _customer(db_session, 'CC1')
        _invoice(db_session, c, main_branch.id, 'SI-A', Decimal('1000.00'))
        _invoice(db_session, c, branch_manila.id, 'SI-B', Decimal('250.00'))
        rows, totals = _build_ar_aging_data(
            AS_OF, [main_branch.id, branch_manila.id])
        assert len(rows) == 1
        assert rows[0]['total'] == Decimal('1250.00')
        assert totals['total'] == Decimal('1250.00')

    def test_distinct_customers_sharing_a_name_stay_separate(self, db_session,
                                                            main_branch):
        a = _customer(db_session, 'CC2', name='Acme Corp')
        b = _customer(db_session, 'CC3', name='Acme Corp')
        _invoice(db_session, a, main_branch.id, 'SI-C', Decimal('100.00'))
        _invoice(db_session, b, main_branch.id, 'SI-D', Decimal('200.00'))
        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert len(rows) == 2

    def test_drifted_snapshot_names_collapse_to_one_row(self, db_session,
                                                       main_branch):
        c = _customer(db_session, 'CC4', name='SYCWIN COATING & WIRES INC.')
        _invoice(db_session, c, main_branch.id, 'SI-E', Decimal('300.00'),
                 customer_name='SYCWIN')
        _invoice(db_session, c, main_branch.id, 'SI-F', Decimal('400.00'),
                 customer_name='SYCWIN COATING AND WIRES')
        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert len(rows) == 1
        assert rows[0]['name'] == 'SYCWIN COATING & WIRES INC.'
        assert rows[0]['total'] == Decimal('700.00')

    def test_include_branch_annotates_each_invoice(self, db_session,
                                                  main_branch, branch_manila):
        c = _customer(db_session, 'CC5')
        _invoice(db_session, c, main_branch.id, 'SI-G', Decimal('10.00'))
        _invoice(db_session, c, branch_manila.id, 'SI-H', Decimal('20.00'))
        rows, _ = _build_ar_aging_data(
            AS_OF, [main_branch.id, branch_manila.id], include_branch=True)
        by_num = {i['invoice_number']: i for i in rows[0]['invoices']}
        assert by_num['SI-G']['branch_id'] == main_branch.id
        assert by_num['SI-G']['branch_code'] == main_branch.code
        assert by_num['SI-H']['branch_code'] == branch_manila.code

    def test_viewable_reflects_viewable_branch_ids(self, db_session,
                                                  main_branch, branch_manila):
        c = _customer(db_session, 'CC6')
        _invoice(db_session, c, main_branch.id, 'SI-I', Decimal('10.00'))
        _invoice(db_session, c, branch_manila.id, 'SI-J', Decimal('20.00'))
        rows, _ = _build_ar_aging_data(
            AS_OF, [main_branch.id, branch_manila.id], include_branch=True,
            viewable_branch_ids={main_branch.id})
        by_num = {i['invoice_number']: i for i in rows[0]['invoices']}
        assert by_num['SI-I']['viewable'] is True
        assert by_num['SI-J']['viewable'] is False

    def test_viewable_defaults_true_when_not_supplied(self, db_session,
                                                     main_branch):
        c = _customer(db_session, 'CC7')
        _invoice(db_session, c, main_branch.id, 'SI-K', Decimal('10.00'))
        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id],
                                       include_branch=True)
        assert rows[0]['invoices'][0]['viewable'] is True

    def test_inactive_branch_is_still_counted(self, db_session, main_branch,
                                             branch_manila):
        branch_manila.is_active = False
        db_session.commit()
        c = _customer(db_session, 'CC8')
        _invoice(db_session, c, branch_manila.id, 'SI-L', Decimal('500.00'))
        rows, totals = _build_ar_aging_data(
            AS_OF, [main_branch.id, branch_manila.id], include_branch=True,
            viewable_branch_ids={main_branch.id})
        assert totals['total'] == Decimal('500.00')
        assert rows[0]['invoices'][0]['viewable'] is False


class TestCombinedModuleGating:

    def test_key_is_in_the_registry(self):
        from app.users.module_access import MODULE_REGISTRY
        entry = next(m for m in MODULE_REGISTRY if m['key'] == 'ar_aging_combined')
        assert entry['endpoints'] == (
            'reports.ar_aging_combined',
            'reports.ar_aging_combined_export_excel',
            'reports.ar_aging_combined_export_csv',
        )

    def test_full_access_user_is_granted(self, db_session, admin_user):
        from app.users.module_access import can_access_module
        assert can_access_module(admin_user, 'ar_aging_combined') is True

    def test_absent_permission_denies_non_full_access_user(self, db_session,
                                                          staff_user):
        """No migration/backfill: the key is simply absent from stored
        book_permissions, and can_access_module's .get(key, False) denies."""
        from app.users.module_access import can_access_module
        perms = staff_user.get_book_permissions()
        perms.pop('ar_aging_combined', None)
        staff_user.set_book_permissions(perms)
        db_session.commit()
        assert can_access_module(staff_user, 'ar_aging_combined') is False

    def test_granted_permission_allows_non_full_access_user(self, db_session,
                                                           staff_user):
        from app.users.module_access import can_access_module
        perms = staff_user.get_book_permissions()
        perms['ar_aging_combined'] = True
        staff_user.set_book_permissions(perms)
        db_session.commit()
        assert can_access_module(staff_user, 'ar_aging_combined') is True


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def _set_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


class TestCombinedRoute:

    def test_page_loads(self, client, db_session, admin_user, main_branch):
        _login(client)
        _set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging-combined?as_of=2025-12-31')
        assert r.status_code == 200

    def test_shows_invoices_from_a_non_selected_branch(self, client, db_session,
                                                      admin_user, main_branch,
                                                      branch_manila):
        c = _customer(db_session, 'CR1')
        _invoice(db_session, c, branch_manila.id, 'SI-OTHER', Decimal('900.00'))
        _login(client)
        _set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging-combined?as_of=2025-12-31')
        assert b'SI-OTHER' in r.data
        assert branch_manila.code.encode() in r.data

    def test_viewable_row_links_and_non_viewable_row_does_not(
            self, client, db_session, staff_user, main_branch, branch_manila):
        """Paired presence/absence assertion -- an absence check alone would
        pass even if the link were merely renamed."""
        c = _customer(db_session, 'CR2')
        mine = _invoice(db_session, c, main_branch.id, 'SI-MINE', Decimal('10.00'))
        theirs = _invoice(db_session, c, branch_manila.id, 'SI-THEIRS', Decimal('20.00'))
        staff_user.set_branches([main_branch])
        perms = staff_user.get_book_permissions()
        perms['ar_aging_combined'] = True
        staff_user.set_book_permissions(perms)
        db_session.commit()

        _login(client, username=staff_user.username, password='staff123')
        _set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging-combined?as_of=2025-12-31')
        body = r.data.decode()

        assert f'/sales-invoices/{mine.id}' in body        # viewable -> linked
        assert f'/sales-invoices/{theirs.id}' not in body  # not viewable -> no link
        assert 'SI-THEIRS' in body                         # but still shown
