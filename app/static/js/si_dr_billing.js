/* DR -> SI billing picker. On customer select, list that customer's delivered, unbilled
   Delivery Receipts; pulling one appends its lines to the SI via the form's global
   addLineItem() and records the DR id in the hidden `source_dr_ids` field. Honors the
   si_dr_billing_consolidate setting (echoed by the endpoint): when off, locks after one pull. */
(function () {
  'use strict';

  var customerSel = document.getElementById('customer_id');
  var section = document.getElementById('drBillingSection');
  var listEl = document.getElementById('drBillingList');
  var emptyEl = document.getElementById('drBillingEmpty');
  var lockedEl = document.getElementById('drBillingLocked');
  var hidden = document.getElementById('sourceDrIds');
  if (!customerSel || !section || !hidden) { return; }

  var sourceDrIds = [];
  var consolidate = false;
  var pulled = false;

  function num(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; }
  function round2(n) { return Math.round(n * 100) / 100; }
  function sync() { hidden.value = JSON.stringify(sourceDrIds); }

  function pull(dr, rowEl) {
    if (!consolidate && pulled) { return; }
    if (typeof window.addLineItem !== 'function') { return; }
    if (typeof window.removeBlankStarterLine === 'function') { window.removeBlankStarterLine(); }
    (dr.lines || []).forEach(function (ln) {
      var qty = ln.quantity, up = ln.unit_price;
      window.addLineItem({
        description: ln.product_name || 'Delivered item',
        product_id: ln.product_id,
        quantity: qty,
        uom_id: ln.uom_id,
        uom_text: ln.uom_display,
        unit_price: up,
        amount: (qty != null && up != null) ? round2(num(qty) * num(up)) : 0,
        vat_category: ln.vat_category || '',
        account_id: ln.account_id,
        wt_id: null, wt_rate: null
      });
    });
    sourceDrIds.push(dr.id);
    sync();
    pulled = true;
    if (rowEl) { rowEl.remove(); }
    if (!consolidate) {
      listEl.querySelectorAll('.dr-pull-btn').forEach(function (b) { b.disabled = true; });
      if (lockedEl) { lockedEl.style.display = ''; }
    }
    if (!listEl.querySelector('tbody tr')) { emptyEl.style.display = ''; }
  }

  function render(data) {
    consolidate = !!data.consolidate;
    listEl.innerHTML = '';
    section.style.display = '';
    var drs = data.drs || [];
    if (!drs.length) { emptyEl.style.display = ''; return; }
    emptyEl.style.display = 'none';
    var table = document.createElement('table');
    table.className = 'table';
    var tb = document.createElement('tbody');
    drs.forEach(function (dr) {
      var tr = document.createElement('tr');
      var td1 = document.createElement('td');
      td1.textContent = dr.dr_number + '  (' + (dr.delivery_date || '') + ', ' +
                        (dr.lines || []).length + ' line/s)';
      tr.appendChild(td1);
      var td2 = document.createElement('td');
      td2.style.textAlign = 'right';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-secondary btn-sm dr-pull-btn';
      btn.textContent = 'Pull';
      btn.addEventListener('click', function () { pull(dr, tr); });
      td2.appendChild(btn);
      tr.appendChild(td2);
      tb.appendChild(tr);
    });
    table.appendChild(tb);
    listEl.appendChild(table);
  }

  function load(cid) {
    // A customer change resets billing intent (server also guards customer mismatch).
    sourceDrIds = []; pulled = false; sync();
    if (lockedEl) { lockedEl.style.display = 'none'; }
    if (!cid || cid === '0' || cid === '__add_customer__') { section.style.display = 'none'; return; }
    fetch('/sales-invoices/billable-drs?customer_id=' + cid)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(render)
      .catch(function () { section.style.display = 'none'; });
  }

  customerSel.addEventListener('change', function () { load(this.value); });
  if (customerSel.value) { load(customerSel.value); }
})();
