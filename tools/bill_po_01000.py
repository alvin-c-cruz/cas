"""Link JOHNSON's PO 01000 to APV 00013, the bill that is already its bill in substance.

WHY THIS EXISTS
---------------
This is the second half of the PO 01134 incident (see tools/reopen_po_01134.py for
the first, and the full sequence). On 2026-09-11 APV 00013 was created for ROTOPACK,
billed ROTOPACK's PO 01134, and was then edited to JOHNSON HARDWARE. The edit path
neither unbilled the old source nor billed a new one, so two orders ended up wrong:

  * PO 01134 stayed closed against a voucher that was no longer its own. Released on
    2026-09-21 by the sibling script -- that half is DONE on live philgen.
  * PO 01000, JOHNSON's actual order, was never billed at all. It is still
    'approved' with no AP link, even though APV 00013 is JOHNSON's posted bill for
    the goods. That is what THIS script fixes (owner decision 2026-09-22).

End state written here is exactly what `_bill_purchase_sources` writes on a normal
AP create (app/purchase_billing.py:68) -- status 'closed', accounts_payable_id set
-- plus an audit row saying why, which that function does not write. The absence of
such a row is precisely what made the original incident hard to diagnose: PO 01134's
trail ended at "Approved" while its status had moved twice.

WHAT IT DOES NOT DO
-------------------
It does not touch APV 00013, a posted BIR-registered document, and it does not
change any amount. The bill (PHP 36,788.58 for invoice 67481) is LESS than the order
(PHP 37,120.00); that gap is real and is reported, not corrected. A bill differing
from its order is ordinary, and reconciling the two is a bookkeeping decision, not
something a linking script should invent.

SAFETY
------
It refuses unless every expected value matches, including that PO 01134 has ALREADY
been released -- if that link is still in place, the first repair has not run here
and billing a second order to the same voucher would produce a state the app itself
would not create. Re-running is a no-op that says so. Back the database up first.

USAGE (on the PythonAnywhere server, from ~/cas, venv activated)
----------------------------------------------------------------
    cp instance/philgen.db "instance/philgen.$(date +%Y%m%d-%H%M%S).pre-po-bill.db"
    python tools/bill_po_01000.py --dry-run     # prints what it would do
    python tools/bill_po_01000.py --commit      # writes

Locally, rehearse against a copy first:
    SQLALCHEMY_DATABASE_URI=sqlite:///sandbox.db python tools/bill_po_01000.py --dry-run
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The one order this script may touch, and the exact state it must be in.
PO_ID = 7
EXPECT_PO_NUMBER = '01000'
EXPECT_PO_VENDOR_FRAGMENT = 'JOHNSON'
EXPECT_PO_STATUS = 'approved'

#: The bill it is being linked to.
AP_ID = 18
EXPECT_AP_NUMBER = '00013'

#: The sibling order whose release is a precondition, not a target.
RELEASED_PO_ID = 6
RELEASED_PO_NUMBER = '01134'

#: Where PO 01000 ends up -- the same end state app/purchase_billing.py
#: ::_bill_purchase_sources writes when a bill legitimately pulls an order.
BILLED_STATUS = 'closed'

NOTE = ('Billed by tools/bill_po_01000.py: APV 00013 is this order\'s bill in '
        'substance. The voucher was created for another vendor on 2026-09-11, '
        'billed that vendor\'s PO 01134, and was then edited to JOHNSON HARDWARE; '
        'the edit path billed nothing, so this order was never linked. Linked and '
        'closed to match what a normal bill would have done. The voucher itself was '
        'not touched, and the amounts were deliberately left as they are.')


def main():
    ap_args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap_args.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    g.add_argument('--commit', action='store_true', help='apply the change')
    args = ap_args.parse_args()

    # The `flask` CLI auto-loads .env; a plain script does not, and config.py raises
    # without SECRET_KEY. Already-exported values win, so the launcher's URI holds.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from app import create_app, db
    from app.purchase_orders.models import PurchaseOrder
    from app.accounts_payable.models import AccountsPayable
    from app.audit.utils import log_audit

    app = create_app()
    with app.app_context():
        print('database: %s' % app.config.get('SQLALCHEMY_DATABASE_URI'))

        po = db.session.get(PurchaseOrder, PO_ID)
        if po is None:
            sys.exit('REFUSED: there is no purchase order with id %d here. Wrong '
                     'database?' % PO_ID)
        bill = db.session.get(AccountsPayable, AP_ID)
        if bill is None:
            sys.exit('REFUSED: there is no accounts_payable row with id %d here. '
                     'Wrong database?' % AP_ID)

        print('order:    id=%d po_number=%r vendor=%r status=%r accounts_payable_id=%r '
              'total=%s' % (po.id, po.po_number, po.vendor_name, po.status,
                            po.accounts_payable_id, po.total_amount))
        print('bill:     id=%d ap_number=%r vendor=%r status=%r invoice=%r total=%s'
              % (bill.id, bill.ap_number, bill.vendor_name, bill.status,
                 bill.vendor_invoice_number, bill.total_amount))

        # Idempotence: already linked is a success, but only when it looks exactly
        # like this script's own end state.
        if po.accounts_payable_id == AP_ID and po.status == BILLED_STATUS:
            print('nothing to do: already linked to this bill and %s.' % BILLED_STATUS)
            return

        problems = []
        if po.po_number != EXPECT_PO_NUMBER:
            problems.append('po_number is %r, expected %r' % (po.po_number, EXPECT_PO_NUMBER))
        if EXPECT_PO_VENDOR_FRAGMENT not in (po.vendor_name or '').upper():
            problems.append('order vendor_name %r does not contain %r'
                            % (po.vendor_name, EXPECT_PO_VENDOR_FRAGMENT))
        if po.status != EXPECT_PO_STATUS:
            problems.append('order status is %r, expected %r' % (po.status, EXPECT_PO_STATUS))
        if po.accounts_payable_id is not None:
            problems.append('order is already linked to accounts_payable_id %r'
                            % po.accounts_payable_id)
        if bill.ap_number != EXPECT_AP_NUMBER:
            problems.append('ap_number is %r, expected %r' % (bill.ap_number, EXPECT_AP_NUMBER))
        if bill.vendor_id != po.vendor_id:
            problems.append('bill vendor_id %r does not match the order\'s %r -- this '
                            'is the very mismatch the incident was about'
                            % (bill.vendor_id, po.vendor_id))
        if bill.branch_id != po.branch_id:
            problems.append('bill branch_id %r does not match the order\'s %r'
                            % (bill.branch_id, po.branch_id))
        if problems:
            sys.exit('REFUSED: this is not the state this script was written for:\n  - '
                     + '\n  - '.join(problems))

        # Precondition, not a target: PO 01134 must already have been released, or
        # the first repair has not run against this database.
        stale = db.session.get(PurchaseOrder, RELEASED_PO_ID)
        if stale is not None and stale.accounts_payable_id == AP_ID:
            sys.exit('REFUSED: PO %s (id %d) is STILL linked to this bill. Run '
                     'tools/reopen_po_01134.py first -- billing a second order to a '
                     'voucher that has not released the first produces a state the '
                     'app would never create.' % (RELEASED_PO_NUMBER, RELEASED_PO_ID))
        print('checked:  PO %s is no longer linked to this bill' % RELEASED_PO_NUMBER)

        others = (PurchaseOrder.query
                  .filter(PurchaseOrder.accounts_payable_id == AP_ID,
                          PurchaseOrder.id != po.id).all())
        if others:
            sys.exit('REFUSED: %d other order(s) already bill this voucher (%s). One '
                     'bill per order is this installation\'s setting; re-check by hand.'
                     % (len(others), ', '.join(o.po_number for o in others)))

        if po.total_amount != bill.total_amount:
            print('NOTE:     order total %s != bill total %s. Left as-is on purpose '
                  '-- see the docstring.' % (po.total_amount, bill.total_amount))

        old = {'status': po.status, 'accounts_payable_id': po.accounts_payable_id}
        new = {'status': BILLED_STATUS, 'accounts_payable_id': AP_ID}
        print('change:   %s -> %s' % (old, new))

        if args.dry_run:
            print('DRY RUN: nothing written.')
            return

        po.status = BILLED_STATUS
        po.accounts_payable_id = AP_ID
        db.session.commit()

        # log_audit commits on its own and swallows every exception, so this cannot
        # fail the repair above -- but it can be lost silently. Verify the row.
        log_audit(action='UPDATE', module='purchase_orders', record_id=po.id,
                  record_identifier='%s - %s' % (po.po_number, po.vendor_name),
                  old_values=old, new_values=new, notes=NOTE)

        db.session.refresh(po)
        print('written:  id=%d po_number=%r status=%r accounts_payable_id=%r'
              % (po.id, po.po_number, po.status, po.accounts_payable_id))
        if po.status != BILLED_STATUS or po.accounts_payable_id != AP_ID:
            sys.exit('FAILED: the row did not end up in the expected state.')
        print('done.     %s' % NOTE)


if __name__ == '__main__':
    main()
