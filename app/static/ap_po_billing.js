/* AP <- PO/RR billing picker (Phase 3). Buy-side mirror of si_dr_billing.js.
   Loaded only when the purchase_orders/receiving_reports modules are enabled (the template
   gates the <script>). Defensive: no-ops when its anchor markup is absent, so a gated-out
   form (e.g. Zhiyuan) is unaffected even if this file is somehow loaded. Injects normal AP
   line rows via the global addLineItem() and records source_po_ids / source_rr_ids. */
(function () {
  'use strict';
  const section = document.getElementById('poBillingSection');
  const payee = document.getElementById('payee');
  if (!section || !payee || typeof window.addLineItem !== 'function') return; // no-op

  const listEl = document.getElementById('poBillingList');
  const emptyEl = document.getElementById('poBillingEmpty');
  const lockedEl = document.getElementById('poBillingLocked');
  const srcPo = document.getElementById('sourcePoIds');
  const srcRr = document.getElementById('sourceRrIds');

  let consolidate = false;
  let pulledAny = false;

  function vendorId() {
    const v = (payee.value || '');
    return v.startsWith('vendor:') ? parseInt(v.slice('vendor:'.length), 10) : null;
  }

  function pushId(hidden, id) {
    let arr = [];
    try { arr = JSON.parse(hidden.value || '[]'); } catch (e) { arr = []; }
    if (!arr.includes(id)) arr.push(id);
    hidden.value = JSON.stringify(arr);
  }

  function injectLines(lines) {
    if (typeof window.removeBlankStarterLine === 'function') { window.removeBlankStarterLine(); }
    (lines || []).forEach(function (ln) {
      window.addLineItem({
        description: ln.description || '',
        amount: ln.amount || 0,
        product_id: ln.product_id || null,
        quantity: ln.quantity != null ? ln.quantity : null,
        unit_price: ln.unit_price != null ? ln.unit_price : null,
        uom_id: ln.uom_id || null,
        uom_text: ln.uom_display || '',
        vat_category: ln.vat_category || '',
        account_id: ln.account_id || null,
        wt_id: null, wt_rate: null,
        // R-02 Phase 6: which PO/RR line this was billed from, and its expected
        // price/qty at injection time -- the live variance check compares against
        // these; the server re-derives matched_* itself at submit, never trusting them.
        source_po_item_id: ln.po_item_id || null,
        source_rr_item_id: ln.rr_item_id || null,
        matched_unit_price: ln.unit_price != null ? ln.unit_price : null,
        matched_quantity: ln.quantity != null ? ln.quantity : null,
      });
    });
  }

  function lockIfNeeded() {
    if (!consolidate && pulledAny) {
      section.querySelectorAll('.po-pull-btn').forEach(function (b) { b.disabled = true; });
      if (lockedEl) lockedEl.style.display = '';
    }
  }

  function rowButton(label, sub, onPull) {
    const wrap = document.createElement('div');
    wrap.className = 'po-billing-row';
    wrap.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:4px 0;';
    wrap.innerHTML = '<span>' + label + (sub ? ' <span class="form-hint">' + sub + '</span>' : '') + '</span>';
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'btn btn-secondary btn-sm po-pull-btn'; btn.textContent = 'Pull';
    btn.addEventListener('click', function () {
      onPull();
      pulledAny = true;
      btn.disabled = true;
      lockIfNeeded();
    });
    wrap.appendChild(btn);
    return wrap;
  }

  function render(pos, rrs) {
    listEl.innerHTML = '';
    if (!pos.length && !rrs.length) {
      emptyEl.style.display = ''; section.style.display = '';
      return;
    }
    emptyEl.style.display = 'none';
    pos.forEach(function (po) {
      listEl.appendChild(rowButton('PO ' + po.po_number, '(services / direct)',
        function () { injectLines(po.lines); pushId(srcPo, po.id); }));
    });
    rrs.forEach(function (rr) {
      listEl.appendChild(rowButton('RR ' + rr.rr_number,
        rr.purchase_order_number ? '(from ' + rr.purchase_order_number + ')' : '',
        function () { injectLines(rr.lines); pushId(srcRr, rr.id); }));
    });
    lockIfNeeded();
    section.style.display = '';
  }

  function reset() {
    if (srcPo) srcPo.value = '[]';
    if (srcRr) srcRr.value = '[]';
    pulledAny = false;
    if (lockedEl) lockedEl.style.display = 'none';
  }

  function load() {
    reset();
    const vid = vendorId();
    if (!vid) { section.style.display = 'none'; return; }
    Promise.all([
      fetch('/purchase-orders/billable?vendor_id=' + vid).then(function (r) { return r.ok ? r.json() : { pos: [] }; }).catch(function () { return { pos: [] }; }),
      fetch('/receiving-reports/billable?vendor_id=' + vid).then(function (r) { return r.ok ? r.json() : { rrs: [] }; }).catch(function () { return { rrs: [] }; }),
    ]).then(function (res) {
      consolidate = !!(res[0].consolidate || res[1].consolidate);
      render(res[0].pos || [], res[1].rrs || []);
    });
  }

  payee.addEventListener('change', load);
  if (vendorId()) load();
})();
