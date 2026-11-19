/* What the receiving report form's "no purchase order" warning offers (RR-1 A, owner 17 Nov 2026;
 * work order app-docs/bug-reports/2026-11-13-rr-received-without-po-link.md).
 *
 * Before: only open PO lines for the SAME product were offered, so a receiver who picked a new product
 * (RR 00780: product 767 while PO 02012 had the same dryer open as 555) saw no warning at all. Now every
 * open line of the vendor's orders in the branch is offered -- same product first -- each as a
 * "Receive against" button. Going on without a PO still needs a typed reason. Nothing is blocked.
 *
 * `rows` are /receiving-reports/open-lines rows: {purchase_order_item_id, po_number, product_id,
 * product_name, open, ...}, already scoped to the vendor and the session's branch.
 * Pure functions; tested by tests/e2e/test_rr_no_po_matches.py.
 */
(function (root) {
  'use strict';

  function rrNoPoMatches(rows, productId, maxOthers) {
    var cap = (maxOthers === undefined || maxOthers === null) ? 8 : maxOthers;
    var open = (rows || []).filter(function (r) { return r && r.open > 0; });
    var isSame = function (r) { return !!productId && r.product_id === productId; };
    var same = open.filter(isSame);
    var others = open.filter(function (r) { return !isSame(r); });
    return { same: same, others: others.slice(0, cap), moreOthers: Math.max(0, others.length - cap) };
  }

  function rrNoPoWarningText(m) {
    if (!m || (!m.same.length && !m.others.length)) return '';
    var parts = [];
    if (m.same.length) {
      parts.push('This vendor has ' + m.same.map(function (r) {
        return r.open + ' open on ' + r.po_number;
      }).join(', ') + '.');
    }
    if (m.others.length) {
      parts.push((m.same.length ? 'It also has other open purchase-order lines.'
                                : 'Not this product, but this vendor has open purchase-order lines.')
                 + ' If this delivery was one of them, receive it against that order.');
    }
    if (m.moreOthers) parts.push(m.moreOthers + ' more: use Pull from Purchase Orders.');
    return parts.join(' ');
  }

  function rrNoPoButtonLabel(r, isSame) {
    if (isSame) return 'Receive against ' + r.po_number;
    return 'Receive against ' + r.po_number + ': ' + (r.product_name || '') + ' (' + r.open + ' open)';
  }

  root.rrNoPoMatches = rrNoPoMatches;
  root.rrNoPoWarningText = rrNoPoWarningText;
  root.rrNoPoButtonLabel = rrNoPoButtonLabel;
})(window);
