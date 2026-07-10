"""Generic legacy-accounting importer: replays a client's legacy Flask bookkeeping
database into CAS as posted journal vouchers (GL replay).

One legacy document becomes one CAS `JournalEntry` carrying that document's raw
debit/credit lines. Source documents (SI/AP/CRV/CDV) are NOT reconstructed -- the
legacy books are raw dr/cr, and CAS has no petty-cash module at all, so replaying
at the GL level is the only lossless mapping.

Safety model, in order:
  1. Fail closed on the target DB filename (never write to the wrong client).
  2. Fail closed on any legacy account that will not resolve.
  3. Fail closed on any entry-number collision, before a single row is written.
  4. Dry-run by default; `--commit` additionally requires a passing tie-out.
  5. `--purge` removes exactly what this importer wrote (entry_type='legacy_import').
"""
