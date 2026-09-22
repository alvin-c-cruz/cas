"""Apply the three registration corrections philgen's live PO overlay still needs.

WHY THIS EXISTS
---------------
The pre-printed Purchase Order overlay for philgen's branch 1 prints three elements
out of register against the client's own stationery. The owner measured the correct
values on 2026-09-18; they are constants below. Nothing about this is a code defect
-- it is one client's layout DATA, which is why it lives in a script and not in
`app/purchase_orders/preprinted_layout.py` (the declaration there is the default for
a NEW branch, and changing it would silently move every other instance's overlay).

The three, and the shape each one is:

  * `pr_number`   -- a lineItems COLUMN, so it carries x + width + visible.
  * `line_number` -- also a COLUMN. Hidden, because this client's legacy pad has no
                     line counter and the column's default slot sits inside
                     `product` on their saved layout. See the note in
                     preprinted_layout.py, which records exactly that overlap.
  * `currency`    -- a FIELD, so it carries x + y (+ w, fontSize, bold, hidden).

Getting those two shapes the wrong way round is the easy mistake here: FIELD_KEYS
has no `pr_number`, so writing an x/y pair into it raises KeyError, and a column has
no `y` at all (every column shares the band's y).

WHAT IT DOES NOT DO
-------------------
It writes only the three elements named above, leaving every other field, column,
extra and signatory text exactly as the branch has them -- it re-saves the layout it
read, with three edits applied. It does not touch any other branch or company.

Acceptance is a PHYSICAL before/after print onto the pre-printed stationery. A clean
run of this script proves only that the numbers are stored.

SAFETY
------
The layout is read through the app's own `get_layout`, so it resolves the same store
the print page resolves, and written through `save_layout`, so it is sanitized, the
legacy `app_settings` key and the named-layout row stay in lock-step, and the change
is audited. Every value is range-checked by that sanitizer; the script also asserts
the three keys exist before touching anything, and reports each one's before/after.

Re-running it is a no-op that says so.

USAGE (on the PythonAnywhere server, from ~/cas, venv activated)
----------------------------------------------------------------
    cp instance/philgen.db "instance/philgen.$(date +%Y%m%d-%H%M%S).pre-po-layout.db"
    python tools/fix_philgen_po_layout.py --dry-run     # prints what it would change
    python tools/fix_philgen_po_layout.py --commit      # writes

Locally, rehearse against a copy first:
    SQLALCHEMY_DATABASE_URI=sqlite:///sandbox.db python tools/fix_philgen_po_layout.py --dry-run
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Philgen's only branch. Asserted by name below so a wrong database refuses.
BRANCH_ID = 1
EXPECT_COMPANY_FRAGMENT = 'PHILGEN'

#: Owner's measured values, 2026-09-18. Columns carry x/width/visible; the field
#: carries x/y. Anything not named here is left exactly as stored.
COLUMN_TARGETS = {
    'pr_number': {'x': 48, 'width': 44, 'visible': True},
    'line_number': {'visible': False},
}
FIELD_TARGETS = {
    'currency': {'x': 545, 'y': 732},
}

AUDIT_NOTE = ('tools/fix_philgen_po_layout.py: pr_number, line_number and currency '
              'moved to the values measured against the pre-printed pad on '
              '2026-09-18. Layout data only; no other element was touched.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    g.add_argument('--commit', action='store_true', help='apply the change')
    ap.add_argument('--username', default='layout-fix-script',
                    help='name recorded in the audit trail for this save')
    args = ap.parse_args()

    # The `flask` CLI auto-loads .env; a plain script does not, and config.py raises
    # without SECRET_KEY. Already-exported values win -- python-dotenv never
    # overrides the real environment -- so the launcher's URI is respected.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from app import create_app, db
    from app.branches.models import Branch
    from app.purchase_orders.preprinted_layout import get_layout, save_layout

    app = create_app()
    with app.app_context():
        print('database: %s' % app.config.get('SQLALCHEMY_DATABASE_URI'))

        company = db.session.execute(
            db.text("select value from app_settings where key = 'company_name'")
        ).scalar()
        if not company or EXPECT_COMPANY_FRAGMENT not in company.upper():
            sys.exit('REFUSED: company_name is %r, which does not contain %r. This '
                     'script is written for one client\'s stationery only.'
                     % (company, EXPECT_COMPANY_FRAGMENT))
        print('company:  %s' % company)

        branch = db.session.get(Branch, BRANCH_ID)
        if branch is None:
            sys.exit('REFUSED: there is no branch with id %d here. Wrong database?'
                     % BRANCH_ID)
        print('branch:   id=%d name=%r' % (branch.id, branch.name))

        layout = get_layout(branch_id=BRANCH_ID)

        columns = {c['key']: c for c in layout['lineItems']['columns']}
        missing = [k for k in COLUMN_TARGETS if k not in columns]
        missing += [k for k in FIELD_TARGETS if k not in layout['fields']]
        if missing:
            sys.exit('REFUSED: this layout has no %s. The declaration has changed '
                     'since this script was written -- re-check the key shapes.'
                     % ', '.join(sorted(missing)))

        changes = []
        for key, target in COLUMN_TARGETS.items():
            col = columns[key]
            for prop, want in target.items():
                if col[prop] != want:
                    changes.append('column %s.%s: %r -> %r' % (key, prop, col[prop], want))
                col[prop] = want
        for key, target in FIELD_TARGETS.items():
            field = layout['fields'][key]
            for prop, want in target.items():
                if field[prop] != want:
                    changes.append('field %s.%s: %r -> %r' % (key, prop, field[prop], want))
                field[prop] = want

        if not changes:
            print('nothing to do: all three elements already carry these values.')
            return

        print('changes:')
        for line in changes:
            print('  - %s' % line)

        if args.dry_run:
            print('DRY RUN: nothing written.')
            return

        # save_layout re-sanitizes, dual-writes the legacy app_settings key when this
        # is the scope default, and writes its own audit row with a real before/after.
        save_layout(layout, args.username, branch_id=BRANCH_ID)
        db.session.commit()
        print('written.  %s' % AUDIT_NOTE)
        print('NEXT: print one PO onto the pre-printed pad and check registration. '
              'A clean run here only proves the numbers are stored.')


if __name__ == '__main__':
    main()
