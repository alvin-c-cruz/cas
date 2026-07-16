/* Vendor Debit Memo line grid: on Accounts-Payable-bill select, fetch that bill's
   lines, render them read-only with one editable "Debit amount" per row, and serialize
   {accounts_payable_item_id, amount} into the hidden `lines` field. Mirror of
   sales_memos_form.js, buy-side field names. */
(function () {
  'use strict';

  var select = document.getElementById('ap-select');
  var tbody = document.querySelector('#memo-lines tbody');
  var emptyMsg = document.getElementById('memo-no-lines');
  var hidden = document.getElementById('lines-json');
  var form = document.getElementById('memo-form');
  var totalEl = document.getElementById('memo-total');
  var vendorEl = document.getElementById('memo-vendor');
  var destSel = document.getElementById('destination-select');
  var cashGroup = document.getElementById('cash-account-group');

  function num(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; }
  function fmt(n) { return n.toFixed(2); }

  function cell(row, text, cls) {
    var td = document.createElement('td');
    td.textContent = text;
    if (cls) { td.className = cls; }
    row.appendChild(td);
    return td;
  }

  function render(lines) {
    tbody.innerHTML = '';
    emptyMsg.hidden = lines.length > 0;
    lines.forEach(function (r) {
      var tr = document.createElement('tr');
      var label = r.product_code ? r.product_code + ': ' + r.product_name
                                 : (r.product_name || '(no product)');
      cell(tr, label);
      cell(tr, r.uom_display || '');
      cell(tr, r.vat_category || '');
      cell(tr, r.wt_rate ? (r.wt_rate + '%') : '');
      cell(tr, fmt(num(r.debitable)), 'text-right');

      var td = document.createElement('td');
      td.className = 'text-right';
      var input = document.createElement('input');
      input.type = 'number';
      input.step = '0.01';
      input.min = '0';
      input.max = String(r.debitable);
      input.className = 'form-control debit-input';
      input.dataset.apItemId = r.accounts_payable_item_id;
      td.appendChild(input);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
    serialize();
  }

  function serialize() {
    var out = [], total = 0;
    tbody.querySelectorAll('.debit-input').forEach(function (i) {
      var a = num(i.value);
      if (a > 0) {
        out.push({ accounts_payable_item_id: parseInt(i.dataset.apItemId, 10), amount: String(a) });
        total += a;
      }
    });
    hidden.value = JSON.stringify(out);
    if (totalEl) { totalEl.textContent = fmt(total); }
  }

  var apLinesBase = (form && form.dataset.apLinesBase) || '/vendor-debit-memos/ap-lines/';

  function loadAP(id) {
    if (!id) { tbody.innerHTML = ''; emptyMsg.hidden = false; serialize(); return; }
    fetch(apLinesBase + id)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (data) {
        if (vendorEl) { vendorEl.textContent = data.vendor_name ? ('Vendor: ' + data.vendor_name) : ''; }
        render(data.lines || []);
      })
      .catch(function () {
        tbody.innerHTML = '';
        emptyMsg.hidden = false;
        emptyMsg.textContent = 'Could not load bill lines.';
      });
  }

  function toggleCash() {
    if (cashGroup) {
      cashGroup.style.display = (destSel && destSel.value === 'cash_refund') ? '' : 'none';
    }
  }

  if (select) {
    select.addEventListener('change', function () { loadAP(this.value); });
    if (select.value) { loadAP(select.value); }
  }
  if (destSel) { destSel.addEventListener('change', toggleCash); toggleCash(); }
  tbody.addEventListener('input', serialize);
  if (form) { form.addEventListener('submit', serialize); }
})();
