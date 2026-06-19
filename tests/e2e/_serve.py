"""
Launch a seeded CAS dev server for Playwright e2e smoke tests.

NOT a pytest module — run as a subprocess by tests/e2e/conftest.py::live_server.
Reads SQLALCHEMY_DATABASE_URI (a temp file DB), SECRET_KEY, and E2E_PORT from the
environment, builds the app in development config (CSRF on — the browser submits real
csrf_token() inputs), creates tables, seeds the minimal dataset + a few vendors, then
serves on 127.0.0.1:$E2E_PORT.
"""
import os

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
                           ('V003', 'Gamma Traders')]:
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

if __name__ == '__main__':
    port = int(os.environ.get('E2E_PORT', '5099'))
    # threaded=True so Playwright's sequential actions never block; reloader off for a clean child.
    app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False, debug=False)
