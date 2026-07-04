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

if __name__ == '__main__':
    port = int(os.environ.get('E2E_PORT', '5099'))
    # threaded=True so Playwright's sequential actions never block; reloader off for a clean child.
    app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False, debug=False)
