"""Rehearse cdvpay_0001 on a COPY of a real database. Usage:
    python tools/verify_cdvpay_migration.py instance/philgen.db
Never run against the live file: this copies it to a temp path first."""
import os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

src = Path(sys.argv[1]).resolve()
work = Path(tempfile.mkdtemp()) / src.name
shutil.copy(src, work)
env = dict(os.environ, SECRET_KEY='verify', FLASK_APP='flask_app.py',
           SQLALCHEMY_DATABASE_URI=f'sqlite:///{work}')
env.pop('CAS_EXPECT_COMPANY', None)
root = Path(__file__).resolve().parents[1]

def flask(*args):
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=root, env=env,
                          capture_output=True, text=True)

con = sqlite3.connect(work)
before = con.execute("SELECT COUNT(*), SUM(total_amount) FROM cash_disbursement_vouchers").fetchone()
con.close()
r = flask('upgrade', 'cdvpay_0001'); print(r.stdout[-400:], r.stderr[-400:])
con = sqlite3.connect(work)
after = con.execute("SELECT COUNT(*), SUM(total_amount) FROM cash_disbursement_vouchers").fetchone()
bad = con.execute("SELECT COUNT(*) FROM cash_disbursement_vouchers "
                  "WHERE payee_type!='vendor' OR payee_id!=vendor_id").fetchone()[0]
print('rows/total before', before, 'after', after, 'rows not backfilled as vendor:', bad,
      'integrity:', con.execute('PRAGMA integrity_check').fetchone())
con.close()
r = flask('downgrade', 'vbank_0001'); print('downgrade:', r.returncode, r.stderr[-200:])
r = flask('upgrade', 'cdvpay_0001'); print('re-upgrade:', r.returncode)
print('copy at', work)
