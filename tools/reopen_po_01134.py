"""Release PO 01134, closed by a bill that was later re-pointed at another vendor.

WHY THIS EXISTS
---------------
APV 00013 (accounts_payable id 18) was created on 2026-09-11 10:56 for ROTOPACK and
legitimately billed PO 01134 (purchase_orders id 6), which set that PO to 'closed'
and linked it to the voucher. At 11:40 the SAME voucher was edited and its vendor
changed to JOHNSON HARDWARE. `_bill_purchase_sources` runs only on AP create and
`_unbill_purchase_sources` only on cancel/void (app/accounts_payable/views.py:945,
1483, 1795), so the edit released nothing: ROTOPACK's PO stayed closed, pointing at
what is now JOHNSON's posted bill. A 'closed' PO is outside RECEIVABLE_PO_STATUSES
and outside billable_pos_for, so nobody can receive or bill against it.

This script puts PO 01134 back exactly where `_unbill_purchase_sources` would have
put it -- status 'approved', accounts_payable_id NULL -- and, unlike that function,
writes an audit row saying why, because a status moving on its own with nothing in
the trail is what made this hard to diagnose in the first place.

It does NOT touch APV 00013 (a posted, BIR-registered document) and does NOT bill
JOHNSON's PO 01000. Both are separate decisions.

SAFETY
------
Every expected value is asserted before anything is written, so running this against
the wrong database, or twice, or after someone has already fixed it by hand, changes
nothing and says so. Back the database up first anyway -- see USAGE.

USAGE (on the PythonAnywhere server, from ~/cas, venv activated)
----------------------------------------------------------------
    cp instance/philgen.db "instance/philgen.$(date +%Y%m%d-%H%M%S).pre-po-reopen.db"
    python tools/reopen_po_01134.py --dry-run     # prints what it would do
    python tools/reopen_po_01134.py --commit      # writes

Locally, point it at a copy first by exporting the launcher's variable:
    SQLALCHEMY_DATABASE_URI=sqlite:///sandbox.db python tools/reopen_po_01134.py --commit
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The one row this script is allowed to touch, and the exact state it must be in.
PO_ID = 6
EXPECT_PO_NUMBER = '01134'
EXPECT_VENDOR_FRAGMENT = 'ROTOPACK'
EXPECT_STATUS = 'closed'
EXPECT_AP_ID = 18

#: Where it goes back to -- the same end state app/purchase_billing.py
#: ::_unbill_purchase_sources writes when a bill is cancelled or voided.
RESTORE_STATUS = 'approved'

NOTE = ('Released by tools/reopen_po_01134.py: APV 00013 billed this order on '
        '2026-09-11 and was then edited to a different vendor (ROTOPACK -> JOHNSON '
        'HARDWARE), which left the order closed and linked to a bill that is no '
        'longer its own. Restored to approved and unlinked, as cancelling that bill '
        'would have done. The bill itself was not touched.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    g.add_argument('--commit', action='store_true', help='apply the change')
    args = ap.parse_args()

    # The `flask` CLI auto-loads .env; a plain script does not, and config.py raises
    # without SECRET_KEY. Load it the same way so this runs from ~/cas unchanged.
    # Values already exported (the cas.ps1 launcher's SQLALCHEMY_DATABASE_URI, say)
    # win, because python-dotenv never overrides the real environment.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from app import create_app, db
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.receiving_reports.models import ReceivingReportItem
    from app.audit.utils import log_audit

    app = create_app()
    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        print('database: %s' % uri)

        po = db.session.get(PurchaseOrder, PO_ID)
        if po is None:
            sys.exit('REFUSED: there is no purchase order with id %d here. Wrong database?'
                     % PO_ID)

        print('found:    id=%d po_number=%r vendor=%r status=%r accounts_payable_id=%r'
              % (po.id, po.po_number, po.vendor_name, po.status, po.accounts_payable_id))

        # Idempotence: already released (by an earlier run, or by hand) is a success,
        # not an error -- but only when it looks released, never when it looks like
        # some third state nobody predicted.
        if po.status == RESTORE_STATUS and po.accounts_payable_id is None:
            print('nothing to do: already %s and unlinked.' % RESTORE_STATUS)
            return

        problems = []
        if po.po_number != EXPECT_PO_NUMBER:
            problems.append('po_number is %r, expected %r' % (po.po_number, EXPECT_PO_NUMBER))
        if EXPECT_VENDOR_FRAGMENT not in (po.vendor_name or '').upper():
            problems.append('vendor_name %r does not contain %r'
                            % (po.vendor_name, EXPECT_VENDOR_FRAGMENT))
        if po.status != EXPECT_STATUS:
            problems.append('status is %r, expected %r' % (po.status, EXPECT_STATUS))
        if po.accounts_payable_id != EXPECT_AP_ID:
            problems.append('accounts_payable_id is %r, expected %r'
                            % (po.accounts_payable_id, EXPECT_AP_ID))
        if problems:
            sys.exit('REFUSED: this row is not the one this script was written for:\n  - '
                     + '\n  - '.join(problems))

        # 'approved' is only the right destination because nothing was ever received
        # against this order; a partially received order would belong in
        # 'partially_received' instead, and that is a different repair.
        line_ids = [li.id for li in
                    PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).all()]
        received = (ReceivingReportItem.query
                    .filter(ReceivingReportItem.purchase_order_item_id.in_(line_ids)).count()
                    if line_ids else 0)
        if received:
            sys.exit('REFUSED: %d receiving-report line(s) reference this order, so '
                     '%r is not the correct restore state. Re-check by hand.'
                     % (received, RESTORE_STATUS))
        print('checked:  no receiving-report lines reference this order')

        old = {'status': po.status, 'accounts_payable_id': po.accounts_payable_id}
        new = {'status': RESTORE_STATUS, 'accounts_payable_id': None}
        print('change:   %s -> %s' % (old, new))

        if args.dry_run:
            print('DRY RUN: nothing written.')
            return

        po.status = RESTORE_STATUS
        po.accounts_payable_id = None
        db.session.commit()

        # Deliberately AFTER the commit and with user_id=None: nobody is logged in
        # here, and log_audit swallows its own failures, so a lost audit row must not
        # be able to roll back the repair itself.
        log_audit(module='purchase_orders', action='update', record_id=po.id,
                  record_identifier=po.po_number, old_values=old, new_values=new,
                  notes=NOTE, user_id=None)

        fresh = db.session.get(PurchaseOrder, PO_ID)
        print('now:      id=%d po_number=%r status=%r accounts_payable_id=%r'
              % (fresh.id, fresh.po_number, fresh.status, fresh.accounts_payable_id))
        if fresh.status != RESTORE_STATUS or fresh.accounts_payable_id is not None:
            sys.exit('FAILED: the row did not end up in the expected state.')
        print('OK: PO %s is open again and can be received and billed against.'
              % fresh.po_number)


if __name__ == '__main__':
    main()
