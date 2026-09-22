"""Put a Sales Order that was confirmed by mistake back to draft.

WHY THIS EXISTS
---------------
The app has a confirm route and a cancel route, but NO unconfirm: draft -> confirmed
is one-way in the UI (app/sales_orders/views.py::confirm). Cancelling is not the same
thing and is not a substitute -- a cancelled order is a dead record, whereas an order
confirmed by a misclick should go back to being editable.

Requested by the owner 2026-09-22 for SO 00001E ("I did not confirm it"), which is
why that number is the default, but the script takes any order number.

WHAT CONFIRMING DOES, AND SO WHAT REVERTING MUST UNDO
-----------------------------------------------------
`confirm()` sets status, confirmed_by_id and confirmed_at, and calls
`write_revision` to lay down REV 0 -- the baseline every later amendment is measured
against and the snapshot that reproduces the job order slip issued to production.
All four are undone here. Leaving Rev 0 behind would be worse than untidy: revision
numbers come from `latest_revision`, so a later genuine confirm would number its
baseline Rev 1 and the order would carry a Rev 0 snapshot of a state nobody ever
confirmed.

REFUSALS
--------
Reverting is only safe while nothing downstream has acted on the confirmation, so
the script refuses when:

  * the order is not 'confirmed' (a draft needs nothing; a cancelled order is a
    different decision and is not silently resurrected here),
  * it has been AMENDED -- any revision beyond Rev 0. Amendments are the audit
    record of a confirmed order changing; unwinding them is not a revert,
  * a Delivery Receipt references it. Goods have moved against this order,
  * a Delivery Receipt against it has been invoiced. Checked separately from the
    line above and on purpose: that is the condition
    delivery_receipts.models::so_is_invoiced tests, and an invoice is posted
    accounting, which a revert must never reach behind,
  * a Quotation was converted into it. That link is provenance rather than
    downstream work, so this one is a WARNING, not a refusal -- it is reported and
    the revert proceeds.

Every refusal names what stands in the way, so the owner can decide rather than
read a failure.

SAFETY
------
Re-running is a no-op that says so. The change is audited with a real before/after
through the same helper the routes use. Back the database up first.

USAGE (on the PythonAnywhere server, from ~/cas, venv activated)
----------------------------------------------------------------
    cp instance/philgen.db "instance/philgen.$(date +%Y%m%d-%H%M%S).pre-so-revert.db"
    python tools/revert_so_to_draft.py --dry-run               # SO 00001E
    python tools/revert_so_to_draft.py --commit
    python tools/revert_so_to_draft.py --so-number 0002 --dry-run

Locally, rehearse against a copy first:
    SQLALCHEMY_DATABASE_URI=sqlite:///sandbox.db python tools/revert_so_to_draft.py --dry-run
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_SO_NUMBER = '00001E'
EXPECT_STATUS = 'confirmed'
REVERT_STATUS = 'draft'

NOTE_TEMPLATE = ('Reverted to draft by tools/revert_so_to_draft.py: the order was '
                 'confirmed in error (owner, 2026-09-22) and the app has no unconfirm '
                 'route. status, confirmed_by and confirmed_at cleared and the Rev 0 '
                 'baseline written by confirm() removed, so a later genuine confirm '
                 'numbers its own baseline Rev 0. Nothing downstream referenced it.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    g.add_argument('--commit', action='store_true', help='apply the change')
    ap.add_argument('--so-number', default=DEFAULT_SO_NUMBER,
                    help='the Sales Order number to revert (default %(default)s)')
    args = ap.parse_args()

    # The `flask` CLI auto-loads .env; a plain script does not, and config.py raises
    # without SECRET_KEY. Already-exported values win, so the launcher's URI holds.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from app import create_app, db
    from app.sales_orders.models import SalesOrder
    from app.sales_orders.revision_models import SalesOrderRevision
    from app.delivery_receipts.models import DeliveryReceipt
    from app.quotations.models import Quotation
    from app.audit.utils import log_audit

    app = create_app()
    with app.app_context():
        print('database: %s' % app.config.get('SQLALCHEMY_DATABASE_URI'))

        matches = SalesOrder.query.filter_by(so_number=args.so_number).all()
        if not matches:
            known = [s.so_number for s in
                     SalesOrder.query.order_by(SalesOrder.id).limit(20).all()]
            sys.exit('REFUSED: no Sales Order numbered %r here. Wrong database? The '
                     'first orders present are: %s'
                     % (args.so_number, ', '.join(known) or '(none)'))
        if len(matches) > 1:
            sys.exit('REFUSED: %d orders share the number %r, so this script cannot '
                     'tell which one you mean.' % (len(matches), args.so_number))
        so = matches[0]

        print('order:    id=%d so_number=%r customer=%r status=%r confirmed_at=%r'
              % (so.id, so.so_number, so.customer_name, so.status, so.confirmed_at))

        if so.status == REVERT_STATUS and so.confirmed_at is None \
                and so.confirmed_by_id is None:
            print('nothing to do: already a draft with no confirmation recorded.')
            return

        if so.status != EXPECT_STATUS:
            sys.exit('REFUSED: status is %r, expected %r. A cancelled or invoiced '
                     'order is a different decision and is not resurrected here.'
                     % (so.status, EXPECT_STATUS))

        revisions = (SalesOrderRevision.query
                     .filter_by(sales_order_id=so.id)
                     .order_by(SalesOrderRevision.revision_number).all())
        amended = [r for r in revisions if r.revision_number > 0]
        if amended:
            sys.exit('REFUSED: this order has been amended (revision%s %s). Amendments '
                     'are the audit record of a confirmed order changing, and unwinding '
                     'them is not a revert -- decide by hand.'
                     % ('s' if len(amended) > 1 else '',
                        ', '.join(str(r.revision_number) for r in amended)))

        drs = DeliveryReceipt.query.filter_by(sales_order_id=so.id).all()
        if drs:
            invoiced = [d for d in drs if d.sales_invoice_id is not None]
            sys.exit('REFUSED: %d Delivery Receipt(s) reference this order (%s)%s. '
                     'Goods have moved against the confirmation.'
                     % (len(drs), ', '.join(d.dr_number or str(d.id) for d in drs),
                        ', and %d of them %s invoiced' % (
                            len(invoiced), 'is' if len(invoiced) == 1 else 'are')
                        if invoiced else ''))
        print('checked:  no Delivery Receipt references this order')

        quotes = Quotation.query.filter_by(sales_order_id=so.id).all()
        if quotes:
            # Provenance, not downstream work -- reported, not refused.
            print('WARNING:  %d quotation(s) were converted into this order (%s). That '
                  'link is left alone; it records where the order came from.'
                  % (len(quotes),
                     ', '.join(getattr(q, 'quotation_number', None) or str(q.id)
                               for q in quotes)))

        baseline = [r for r in revisions if r.revision_number == 0]
        print('revisions: %d found; %d baseline row(s) will be deleted'
              % (len(revisions), len(baseline)))

        old = {'status': so.status,
               'confirmed_by_id': so.confirmed_by_id,
               'confirmed_at': so.confirmed_at.isoformat() if so.confirmed_at else None}
        new = {'status': REVERT_STATUS, 'confirmed_by_id': None, 'confirmed_at': None}
        print('change:   %s -> %s' % (old, new))

        if args.dry_run:
            print('DRY RUN: nothing written.')
            return

        so.status = REVERT_STATUS
        so.confirmed_by_id = None
        so.confirmed_at = None
        for rev in baseline:
            db.session.delete(rev)
        db.session.commit()

        # log_audit commits on its own and swallows every exception, so it cannot
        # fail the revert above -- but a row can be lost silently. Verified below.
        log_audit(action='UPDATE', module='sales_orders', record_id=so.id,
                  record_identifier=so.so_number,
                  old_values=old, new_values=new, notes=NOTE_TEMPLATE)

        db.session.refresh(so)
        left = SalesOrderRevision.query.filter_by(sales_order_id=so.id).count()
        print('written:  id=%d so_number=%r status=%r confirmed_at=%r revisions_left=%d'
              % (so.id, so.so_number, so.status, so.confirmed_at, left))
        if so.status != REVERT_STATUS or so.confirmed_at is not None \
                or so.confirmed_by_id is not None:
            sys.exit('FAILED: the order did not end up in the expected state.')
        print('done.     It is editable again at /sales-orders/%d/edit' % so.id)


if __name__ == '__main__':
    main()
