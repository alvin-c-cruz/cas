"""Quick audit-log inspector for the manual test run.

Usage:
    python scripts/audit_check.py [N]            # last N audit entries (default 10)
    python scripts/audit_check.py sql "SELECT ..."  # arbitrary read-only query
"""
import sqlite3
import sys

DB = "instance/cas.db"


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if len(sys.argv) >= 3 and sys.argv[1] == "sql":
        rows = con.execute(sys.argv[2]).fetchall()
    else:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
        rows = con.execute(
            "SELECT id, module, action, record_identifier, user_id, timestamp, notes "
            "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    for r in rows:
        print(dict(r))


if __name__ == "__main__":
    main()
