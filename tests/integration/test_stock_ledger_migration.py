"""Prove the migration runs on a COPY of a real DB, not just create_all() from
today's models (migration-verify-on-real-db-copy). Skips cleanly if no real DB."""
import os, shutil, subprocess, sqlite3, tempfile, pytest

REAL_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'cas.db')

@pytest.mark.skipif(not os.path.exists(REAL_DB), reason='no real cas.db to copy')
def test_migration_upgrades_on_real_db_copy():
    tmp = tempfile.mkdtemp()
    dbcopy = os.path.join(tmp, 'copy.db')
    shutil.copy(REAL_DB, dbcopy)
    env = dict(os.environ, SQLALCHEMY_DATABASE_URI=f'sqlite:///{dbcopy}', FLASK_ENV='development')
    r = subprocess.run(['flask', 'db', 'upgrade'], cwd=os.path.join(os.path.dirname(__file__), '..', '..'),
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(dbcopy)
    cols = {row[1] for row in con.execute("PRAGMA table_info(stock_balances)")}
    assert 'row_version' in cols
    # server_default populates row_version=1 for any row inserted without it
    con.execute("INSERT INTO stock_balances (product_id, branch_id, updated_at) VALUES (1,1,'2026-07-21')")
    v = con.execute("SELECT row_version FROM stock_balances LIMIT 1").fetchone()[0]
    assert v == 1
    con.close()
