"""Restore the PO/RR line links the AP edit form erased from nine paid philgen vouchers.

WHY THIS EXISTS
---------------
Until fix/ap-edit-keeps-line-links, the AP edit page loaded each line through
AccountsPayableItem.to_dict(), which left out source_po_item_id / source_rr_item_id /
matched_unit_price / matched_quantity. The form posts back only what it loaded and
edit() rebuilds every line from that post, so every save of a PO/RR-billed DRAFT
voucher blanked every line's link (work order 2026-11-02-ap-edit-drops-po-rr-line-links).
The voucher HEADER links (PO/RR accounts_payable_id, status 'billed'/'closed') were never
touched -- only the per-line trail and the variance snapshot were lost.

Owner's word, 5 Nov 2026: "relink" (all nine; options were all nine / only the two proven
/ leave them).

EVIDENCE, per voucher
---------------------
proven    linked in the snapshot taken at creation, unlinked after its first edit
          (00039: philgen-20261007-1317.db; 00050: philgen-20261021-1555.db).
inferred  no snapshot exists between creation and first edit; every line matches its
          RR/PO line one-to-one on product, quantity, unit price and order.
00013 is a special case: its lines were created against ROTOPACK's PO 01134 and the
voucher was then re-pointed at JOHNSON; tools/bill_po_01000.py later linked JOHNSON's
PO 01000 to the header (Sep 2026). Its eight lines match PO 01000's eight exactly, so
this links them for the first time rather than restoring.

WHAT IT DOES NOT DO
-------------------
It changes only the four link/snapshot columns on the listed lines. No amount, account,
VAT, status or journal entry is touched; every voucher here is paid, and none of the RR
lines carries a stock movement (the script refuses one that does, because a tracked RR
line would also force the GRNI account -- out of scope). matched_* are derived exactly as
app/accounts_payable/views.py::_build_validated_ap_lines derives them on save.

SAFETY
------
Every line is checked before anything is written; one mismatch refuses the whole run.
A line already carrying exactly its target link counts as done, so re-running is a no-op.
One audit row per voucher records the before/after of each line.

USAGE (on the PythonAnywhere server; back the database up first)
---------------------------------------------------------------
    cd ~/cas && source venv/bin/activate
    cp instance/philgen.db "instance/philgen.$(date +%Y%m%d-%H%M%S).pre-relink.db"
    python ~/relink_ap_lines.py --app-dir ~/cas --dry-run
    python ~/relink_ap_lines.py --app-dir ~/cas --commit
"""
import argparse
import os
import sys
from decimal import Decimal

# (ap_id, ap_number, evidence, lines)
# line: (line_number, product_id, quantity, unit_price, rr_item_id, po_item_id)
# Read from philgen-20261104-1627.db, 5 Nov 2026.
PLAN = [
    (1, '0001', 'inferred', [
        (1, 22, '3', '6950', 1, 1)]),
    (2, '0002', 'inferred', [
        (1, 550, '3', '1300', 2, 2),
        (2, 551, '600', '75', 3, 3)]),
    (3, '0003', 'inferred', [
        (1, 514, '7', '500', 4, 5),
        (2, 561, '1', '420', 5, 6),
        (3, 562, '10', '150', 6, 7),
        (4, 563, '10', '130', 7, 8)]),
    (18, '00013', 'inferred (first link; header linked to PO 01000 by tools/bill_po_01000.py)', [
        (1, 568, '5', '120', None, 12),
        (2, 12, '1', '5000', None, 13),
        (3, 570, '6', '445', None, 14),
        (4, 335, '200', '40', None, 15),
        (5, 571, '18', '370', None, 16),
        (6, 572, '13', '980', None, 17),
        (7, 139, '1', '650', None, 18),
        (8, 383, '1', '800', None, 19)]),
    (26, '00019', 'inferred', [
        (1, 569, '40000', '5.3', 40, 11),
        (2, 569, '12100', '5.3', 41, None)]),   # overrun received without a PO line
    (57, '00037', 'inferred', [
        (1, 589, '15', '1140', 61, 75),
        (2, 590, '15', '1110.75', 62, 76),
        (3, 591, '15', '1110.75', 63, 77),
        (4, 592, '30', '1110.75', 64, 78),
        (5, 593, '15', '1110.75', 65, 79),
        (6, 594, '10', '1657.5', 66, 80)]),
    (59, '00039', 'proven', [
        (1, None, '2', '8750', 58, 85)]),
    (61, '00041', 'inferred', [
        (1, 654, '3', '630', 68, 72),
        (2, 655, '1', '11529', 69, 73)]),
    (75, '00050', 'proven', [
        (1, 56, '5', '5303.76', 86, 171),
        (2, 25, '5', '3025', 87, 172)]),
]

ALLOWED_STATUSES = ('posted', 'paid')
FIELDS = ('source_po_item_id', 'source_rr_item_id', 'matched_unit_price', 'matched_quantity')
NOTE = ('Line links restored by relink_ap_lines.py (owner: "relink", 5 Nov 2026). The AP edit '
        'form used to blank every line\'s PO/RR link on save (work order '
        '2026-11-02-ap-edit-drops-po-rr-line-links). Only the link and variance-snapshot '
        'columns changed; amounts, accounts and the journal entry were not touched. '
        'Evidence: %s.')


def _dec(v):
    return None if v is None else Decimal(str(v))


def _same(a, b):
    """Compare two numerics by value (Numeric columns come back as Decimal)."""
    return _dec(a) == _dec(b)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    g.add_argument('--commit', action='store_true', help='apply the change')
    p.add_argument('--app-dir', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   help='the CAS checkout (default: the parent of this script\'s folder)')
    args = p.parse_args()

    app_dir = os.path.abspath(os.path.expanduser(args.app_dir))
    os.chdir(app_dir)                      # relative sqlite paths resolve from the checkout
    sys.path.insert(0, app_dir)
    try:                                   # the flask CLI loads .env; a plain script must
        from dotenv import load_dotenv
        load_dotenv(os.path.join(app_dir, '.env'))
    except ImportError:
        pass

    from app import create_app, db
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import ReceivingReportItem
    from app.audit.utils import log_audit

    app = create_app()
    with app.app_context():
        print('database: %s' % app.config.get('SQLALCHEMY_DATABASE_URI'))
        problems, todo, done = [], [], 0

        for ap_id, ap_number, evidence, lines in PLAN:
            ap = db.session.get(AccountsPayable, ap_id)
            if ap is None or ap.ap_number != ap_number:
                problems.append('APV %s: id %d is %r here' % (
                    ap_number, ap_id, ap and ap.ap_number))
                continue
            if ap.status not in ALLOWED_STATUSES:
                problems.append('APV %s is %r, expected one of %s'
                                % (ap_number, ap.status, ALLOWED_STATUSES))
            by_no = {li.line_number: li for li in ap.line_items}
            changes = []
            for ln, prod, qty, price, rr_id, po_id in lines:
                tag = 'APV %s line %d' % (ap_number, ln)
                li = by_no.get(ln)
                if li is None:
                    problems.append('%s: no such line' % tag); continue
                if li.product_id != prod or not _same(li.quantity, qty) or not _same(li.unit_price, price):
                    problems.append('%s: line is product %r qty %s price %s, expected %r %s %s'
                                    % (tag, li.product_id, li.quantity, li.unit_price, prod, qty, price))
                    continue

                # Derive the target exactly as _build_validated_ap_lines does on save.
                if rr_id is not None:
                    rr_item = db.session.get(ReceivingReportItem, rr_id)
                    if rr_item is None:
                        problems.append('%s: RR item %d not found' % (tag, rr_id)); continue
                    if rr_item.receiving_report.accounts_payable_id != ap.id:
                        problems.append('%s: RR item %d belongs to RR %s, billed to ap id %r'
                                        % (tag, rr_id, rr_item.receiving_report.rr_number,
                                           rr_item.receiving_report.accounts_payable_id))
                    if rr_item.purchase_order_item_id != po_id:
                        problems.append('%s: RR item %d points at PO item %r, expected %r'
                                        % (tag, rr_id, rr_item.purchase_order_item_id, po_id))
                    if rr_item.product_id != prod or not _same(rr_item.received_quantity, qty):
                        problems.append('%s: RR item %d is product %r qty %s'
                                        % (tag, rr_id, rr_item.product_id, rr_item.received_quantity))
                    if rr_item.stock_movement_id is not None:
                        problems.append('%s: RR item %d is inventory-tracked (GRNI) -- out of scope'
                                        % (tag, rr_id))
                    po_item = rr_item.purchase_order_item
                    if po_item is not None and not _same(po_item.unit_price, price):
                        problems.append('%s: PO item %d price %s differs from the line\'s %s'
                                        % (tag, po_item.id, po_item.unit_price, price))
                    target = {'source_po_item_id': po_id, 'source_rr_item_id': rr_id,
                              'matched_unit_price': po_item.unit_price if po_item else None,
                              'matched_quantity': rr_item.received_quantity}
                else:
                    po_item = db.session.get(PurchaseOrderItem, po_id)
                    if po_item is None:
                        problems.append('%s: PO item %d not found' % (tag, po_id)); continue
                    if po_item.order.accounts_payable_id != ap.id:
                        problems.append('%s: PO item %d belongs to PO %s, billed to ap id %r'
                                        % (tag, po_id, po_item.order.po_number,
                                           po_item.order.accounts_payable_id))
                    if (po_item.product_id != prod or not _same(po_item.quantity, qty)
                            or not _same(po_item.unit_price, price)):
                        problems.append('%s: PO item %d is product %r qty %s price %s'
                                        % (tag, po_id, po_item.product_id, po_item.quantity,
                                           po_item.unit_price))
                    target = {'source_po_item_id': po_id, 'source_rr_item_id': None,
                              'matched_unit_price': po_item.unit_price,
                              'matched_quantity': po_item.quantity}

                current = {f: getattr(li, f) for f in FIELDS}
                if (current['source_po_item_id'], current['source_rr_item_id']) == \
                        (target['source_po_item_id'], target['source_rr_item_id']):
                    done += 1
                    continue
                if current['source_po_item_id'] is not None or current['source_rr_item_id'] is not None:
                    problems.append('%s: already linked to PO item %r / RR item %r -- not what this '
                                    'script expects' % (tag, current['source_po_item_id'],
                                                        current['source_rr_item_id']))
                    continue
                changes.append((li, current, target))
            if changes:
                todo.append((ap, evidence, changes))

        # No source line may end up claimed by two AP lines.
        claimed = {}
        for ap_id, ap_number, _e, lines in PLAN:
            for ln, _p, _q, _u, rr_id, po_id in lines:
                key = ('rr', rr_id) if rr_id is not None else ('po', po_id)
                if key in claimed:
                    problems.append('%s %d is claimed by %s and APV %s line %d'
                                    % (key[0].upper(), key[1], claimed[key], ap_number, ln))
                claimed[key] = 'APV %s line %d' % (ap_number, ln)
        for kind, model, col in (('rr', ReceivingReportItem, AccountsPayableItem.source_rr_item_id),
                                 ('po', PurchaseOrderItem, AccountsPayableItem.source_po_item_id)):
            ids = [k[1] for k in claimed if k[0] == kind]
            for other in AccountsPayableItem.query.filter(col.in_(ids)).all():
                mine = other.ap_id in {a for a, *_ in PLAN}
                if not mine:
                    problems.append('%s item %r is already linked from another voucher (ap id %d)'
                                    % (kind.upper(), getattr(other, col.key), other.ap_id))

        n_lines = sum(len(c) for _a, _e, c in todo)
        print('checked:  %d vouchers, %d lines; %d already linked, %d to relink'
              % (len(PLAN), sum(len(l) for *_x, l in PLAN), done, n_lines))
        if problems:
            sys.exit('REFUSED, nothing written:\n  - ' + '\n  - '.join(problems))
        for ap, evidence, changes in todo:
            print('APV %s (%s, %s) -- %s' % (ap.ap_number, ap.vendor_name, ap.status, evidence))
            for li, cur, tgt in changes:
                print('   line %d: RR item %r / PO item %r, matched price %s qty %s'
                      % (li.line_number, tgt['source_rr_item_id'], tgt['source_po_item_id'],
                         tgt['matched_unit_price'], tgt['matched_quantity']))
        if not todo:
            print('nothing to do: every line already carries its link.')
            return
        if args.dry_run:
            print('DRY RUN: nothing written.')
            return

        for _ap, _e, changes in todo:
            for li, _cur, tgt in changes:
                for f, v in tgt.items():
                    setattr(li, f, v)
        db.session.commit()

        def _j(v):
            return float(v) if isinstance(v, Decimal) else v

        # log_audit commits on its own and swallows every exception -- count the rows after.
        from app.audit.models import AuditLog
        before = AuditLog.query.count()
        for ap, evidence, changes in todo:
            log_audit(module='accounts_payable', action='update', record_id=ap.id,
                      record_identifier='%s - %s' % (ap.ap_number, ap.vendor_name),
                      old_values={'line %d' % li.line_number: {f: _j(v) for f, v in cur.items()}
                                  for li, cur, _t in changes},
                      new_values={'line %d' % li.line_number: {f: _j(v) for f, v in tgt.items()}
                                  for li, _c, tgt in changes},
                      notes=NOTE % evidence)
        audit_rows = AuditLog.query.count() - before

        db.session.expire_all()
        bad = []
        for ap, _e, changes in todo:
            for li, _cur, tgt in changes:
                row = db.session.get(AccountsPayableItem, li.id)
                for f, v in tgt.items():
                    if not _same(getattr(row, f), v) if f.startswith('matched') else getattr(row, f) != v:
                        bad.append('APV %s line %d %s' % (ap.ap_number, row.line_number, f))
        if bad:
            sys.exit('FAILED: rows did not end up as written: ' + ', '.join(bad))
        print('written:  %d lines on %d vouchers; %d audit rows (expected %d)'
              % (n_lines, len(todo), audit_rows, len(todo)))


if __name__ == '__main__':
    main()
