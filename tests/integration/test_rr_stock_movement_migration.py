"""Real-DB-copy verification (migration-verify-on-real-db-copy) -- proves the
migration runs against an actual accumulated schema, not just today's models."""
import os, shutil, subprocess, sqlite3, tempfile, pytest

REAL_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'cas.db')

@pytest.mark.skipif(not os.path.exists(REAL_DB), reason='no real cas.db to copy')
def test_migration_adds_column_on_real_db_copy():
    tmp = tempfile.mkdtemp()
    dbcopy = os.path.join(tmp, 'copy.db')
    shutil.copy(REAL_DB, dbcopy)
    env = dict(os.environ, SQLALCHEMY_DATABASE_URI=f'sqlite:///{dbcopy}', FLASK_ENV='development')
    r = subprocess.run(['flask', 'db', 'upgrade'], cwd=os.path.join(os.path.dirname(__file__), '..', '..'),
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(dbcopy)
    cols = {row[1] for row in con.execute("PRAGMA table_info(receiving_report_items)")}
    assert 'stock_movement_id' in cols
    con.close()
