"""
Launch a seeded CAS dev server for Playwright e2e smoke tests.

NOT a pytest module — run as a subprocess by tests/e2e/conftest.py::live_server.
Reads SQLALCHEMY_DATABASE_URI (a temp file DB), SECRET_KEY, and E2E_PORT from the
environment, builds the app in development config (CSRF on — the browser submits real
csrf_token() inputs), creates tables, seeds the minimal dataset + a few vendors, then
serves on 127.0.0.1:$E2E_PORT.
"""
import os
from datetime import date, timedelta
from decimal import Decimal

from app import create_app, db

app = create_app('development')

with app.app_context():
    db.create_all()
    from app.users.models import User
    # Seed only once (the temp DB is fresh, but guard for safety / restarts).
    if not User.query.filter_by(username='admin').first():
        from app.seeds.seed_data import seed_minimal
        seed_minimal()  # admin/admin123, MAIN branch, COA, VAT cats, WHT codes, settings
        from app.vendors.models import Vendor
        from app.withholding_tax.models import WithholdingTax
        existing = {v.code for v in Vendor.query.all()}
        for code, name in [('V001', 'Alpha Trading Inc'),
                           ('V002', 'Beta Supplies Co'),
                           ('V003', 'Gamma Traders'),
                           # Entity-decoding regression fixture (search-select.js): name
                           # carries every char Jinja autoescapes (& < > " '). Choices.js
                           # must render this DECODED, not as literal HTML entities.
                           ('V004', 'O\'Brien & <Sons> "Co."')]:
            if code not in existing:
                db.session.add(Vendor(code=code, name=name, is_active=True))
        db.session.commit()
        # Assign WC100 to V001 so WT-scoping e2e tests can verify enabled vs disabled states.
        # V002/V003 intentionally have no WHT codes (cover the disabled "no WHT" path).
        v001 = Vendor.query.filter_by(code='V001').first()
        wc100 = WithholdingTax.query.filter_by(code='WC100').first()
        if v001 and wc100:
            v001.withholding_taxes = [wc100]
            db.session.commit()
        # A customer for the Sales Invoice create-form e2e smoke (customer picker).
        from app.customers.models import Customer
        if not Customer.query.filter_by(code='C001').first():
            db.session.add(Customer(code='C001', name='Acme Customer Inc', is_active=True))
            db.session.commit()

        # Open AP bills for V001 / open SI invoices for C001 — fixtures for the CDV/CRV
        # Notes-autofill e2e tests (they exercise Section A settlement-doc apply/remove,
        # which needs real "open" (posted, balance > 0) documents to pick from). Header
        # rows are inserted directly (no line items / JE) since these tests never submit
        # the CDV/CRV form — they only observe the client-side JS reacting to the fetched
        # open-bills / open-invoices JSON.
        from app.branches.models import Branch
        from app.accounts_payable.models import AccountsPayable
        from app.sales_invoices.models import SalesInvoice
        branch = Branch.query.first()
        v001 = Vendor.query.filter_by(code='V001').first()
        c001 = Customer.query.filter_by(code='C001').first()
        today = date.today()
        due = today + timedelta(days=30)
        if branch and v001 and not AccountsPayable.query.filter_by(ap_number='APV-2026-07-0001').first():
            for num, amt in [('APV-2026-07-0001', '1000.00'), ('APV-2026-07-0002', '1500.00')]:
                db.session.add(AccountsPayable(
                    branch_id=branch.id, ap_number=num, ap_date=today, due_date=due,
                    vendor_id=v001.id, vendor_name=v001.name, notes='',
                    total_amount=Decimal(amt), balance=Decimal(amt), status='posted',
                ))
            db.session.commit()
        if branch and c001 and not SalesInvoice.query.filter_by(invoice_number='SI-2026-07-0001').first():
            for num, amt in [('SI-2026-07-0001', '2000.00'), ('SI-2026-07-0002', '2500.00')]:
                db.session.add(SalesInvoice(
                    branch_id=branch.id, invoice_number=num, invoice_date=today, due_date=due,
                    customer_id=c001.id, customer_name=c001.name, notes='',
                    total_amount=Decimal(amt), balance=Decimal(amt), status='posted',
                ))
            db.session.commit()

        # ── Sales-cycle profile ────────────────────────────────────────────────
        # Only when explicitly requested (E2E_SEED_PROFILE=sales), enable the optional
        # Sales-cycle modules and seed products + a confirmed Sales Order so the
        # Quotation and Delivery-Receipt create-form smokes have real data to drive.
        # Kept OUT of the default seed because turning `products` ON changes the
        # AP/SI/CDV/CRV line grids and would break their (lean-seed) smokes.
        if os.environ.get('E2E_SEED_PROFILE') == 'sales':
            from app.settings import AppSettings
            from app.units_of_measure.models import UnitOfMeasure
            from app.products.models import Product
            from app.sales_orders.models import SalesOrder, SalesOrderItem
            for key in ('units_of_measure', 'products', 'sales_orders',
                        'quotations', 'delivery_receipts', 'credit_memos', 'debit_memos'):
                AppSettings.set_setting(f'module_enabled:{key}', '1')
            db.session.commit()

            pc = UnitOfMeasure.query.filter_by(code='PC').first()
            if not pc:
                pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
                db.session.add(pc); db.session.commit()
            if not Product.query.filter_by(code='P001').first():
                for code, name, price in [('P001', 'Widget Standard', '100.00'),
                                          ('P002', 'Gadget Deluxe', '250.00')]:
                    db.session.add(Product(code=code, name=name, is_active=True,
                                           default_unit_of_measure_id=pc.id,
                                           default_unit_price=Decimal(price)))
                db.session.commit()

            # A CONFIRMED Sales Order with one product line (open qty = ordered, since
            # no Delivery Receipt exists yet) — the fixture the DR create grid reads.
            branch = Branch.query.first()
            c001 = Customer.query.filter_by(code='C001').first()
            p001 = Product.query.filter_by(code='P001').first()
            if branch and c001 and p001 and not SalesOrder.query.filter_by(so_number='SO-E2E-0001').first():
                so = SalesOrder(
                    so_number='SO-E2E-0001', branch_id=branch.id, order_date=today,
                    customer_id=c001.id, customer_name=c001.name, notes='',
                    status='confirmed')
                item = SalesOrderItem(
                    line_number=1, product_id=p001.id, quantity=Decimal('10'),
                    unit_price=Decimal('100.00'), unit_of_measure_id=pc.id,
                    vat_category='V0', vat_rate=Decimal('0'))
                item.calculate_amounts()
                so.line_items.append(item)
                so.calculate_totals()
                db.session.add(so); db.session.commit()

            # A POSTED Sales Invoice with one line -- the fixture the Credit Memo create
            # grid references (pick SI -> load lines -> enter a credit amount). Line is
            # VAT-free so the create smoke needs no assigned memo accounts (JE is at post,
            # which is covered by integration tests).
            from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
            if branch and c001 and not SalesInvoice.query.filter_by(invoice_number='SI-E2E-0001').first():
                si = SalesInvoice(
                    branch_id=branch.id, invoice_number='SI-E2E-0001', invoice_date=today,
                    due_date=today + timedelta(days=30), customer_id=c001.id,
                    customer_name=c001.name, notes='', status='posted',
                    total_amount=Decimal('1000.00'), balance=Decimal('1000.00'))
                si_item = SalesInvoiceItem(
                    line_number=1, description='Consulting service', amount=Decimal('1000.00'),
                    vat_category=None, vat_rate=Decimal('0'), account_id=None)
                si_item.calculate_amounts()
                si.line_items.append(si_item)
                db.session.add(si); db.session.commit()

            # A POSTED DEBIT NOTE (Phase 2b) with an open balance -- the fixture the CRV
            # open-items picker unions in, so the collect-a-debit-note smoke has a debit
            # note to pick. Header-only (the CRV reads the memo's balance, not its lines).
            from app.sales_memos.models import SalesMemo
            si_e2e = SalesInvoice.query.filter_by(invoice_number='SI-E2E-0001').first()
            if (branch and c001 and si_e2e
                    and not SalesMemo.query.filter_by(memo_number='DM-E2E-0001').first()):
                db.session.add(SalesMemo(
                    memo_type='debit', memo_number='DM-E2E-0001', memo_date=today,
                    sales_invoice_id=si_e2e.id, original_invoice_number=si_e2e.invoice_number,
                    branch_id=branch.id, customer_id=c001.id, customer_name=c001.name,
                    reason='Undercharge correction (e2e)', notes='',
                    subtotal=Decimal('560.00'), total_amount=Decimal('560.00'),
                    balance=Decimal('560.00'), amount_paid=Decimal('0.00'),
                    destination='ar', status='posted'))
                db.session.commit()

            # DR->SI billing fixture: give P001 a revenue account (so a pulled SI line has one)
            # and seed a DELIVERED, unbilled DR for the SI form's picker. Use a SEPARATE SO
            # (SO-E2E-0002) so SO-E2E-0001 stays fully-open for the DR *create* smoke (a
            # delivered DR against SO-E2E-0001 would consume its open qty and hide it there).
            from app.accounts.models import Account
            from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
            rev = Account.query.filter(Account.account_type.in_(['Income', 'Revenue'])).first()
            if rev and p001 and p001.default_account_id is None:
                p001.default_account_id = rev.id
                db.session.commit()
            if (branch and c001 and p001
                    and not SalesOrder.query.filter_by(so_number='SO-E2E-0002').first()):
                so2 = SalesOrder(
                    so_number='SO-E2E-0002', branch_id=branch.id, order_date=today,
                    customer_id=c001.id, customer_name=c001.name, notes='', status='confirmed')
                bi = SalesOrderItem(
                    line_number=1, product_id=p001.id, quantity=Decimal('10'),
                    unit_price=Decimal('100.00'), unit_of_measure_id=pc.id,
                    vat_category='V0', vat_rate=Decimal('0'))
                bi.calculate_amounts()
                so2.line_items.append(bi); so2.calculate_totals()
                db.session.add(so2); db.session.commit()
                dr = DeliveryReceipt(
                    dr_number='DR-E2E-0001', branch_id=branch.id, delivery_date=today,
                    sales_order_id=so2.id, customer_id=c001.id, customer_name=c001.name,
                    status='delivered')
                dr.line_items.append(DeliveryReceiptItem(
                    line_number=1, sales_order_item_id=so2.line_items[0].id,
                    product_id=p001.id, delivered_quantity=Decimal('10')))
                db.session.add(dr); db.session.commit()

if __name__ == '__main__':
    port = int(os.environ.get('E2E_PORT', '5099'))
    # threaded=True so Playwright's sequential actions never block; reloader off for a clean child.
    app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False, debug=False)
