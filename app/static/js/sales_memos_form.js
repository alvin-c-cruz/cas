/* Sales Memo (Credit/Debit) line grid: on Sales-Invoice select, fetch that invoice's
   lines, render them read-only with one editable "Credit amount" per row, and serialize
   {sales_invoice_item_id, amount} into the hidden `lines` field. */
(function () {
  'use strict';

  var select = document.getElementById('si-select');
  var tbody = document.querySelector('#memo-lines tbody');
  var emptyMsg = document.getElementById('memo-no-lines');
  var hidden = document.getElementById('lines-json');
  var form = document.getElementById('memo-form');
  var totalEl = document.getElementById('memo-total');
  var custEl = document.getElementById('memo-customer');
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
      cell(tr, fmt(num(r.creditable)), 'text-right');

      var td = document.createElement('td');
      td.className = 'text-right';
      var input = document.createElement('input');
      input.type = 'number';
      input.step = '0.01';
      input.min = '0';
      input.max = String(r.creditable);
      input.className = 'form-control credit-input';
      input.dataset.siItemId = r.sales_invoice_item_id;
      td.appendChild(input);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
    serialize();
  }

  function serialize() {
    var out = [], total = 0;
    tbody.querySelectorAll('.credit-input').forEach(function (i) {
      var a = num(i.value);
      if (a > 0) {
        out.push({ sales_invoice_item_id: parseInt(i.dataset.siItemId, 10), amount: String(a) });
        total += a;
      }
    });
    hidden.value = JSON.stringify(out);
    if (totalEl) { totalEl.textContent = fmt(total); }
  }

  var siLinesBase = (form && form.dataset.siLinesBase) || '/credit-memos/si-lines/';

  function loadSI(id) {
    if (!id) { tbody.innerHTML = ''; emptyMsg.hidden = false; serialize(); return; }
    fetch(siLinesBase + id)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (data) {
        if (custEl) { custEl.textContent = data.customer_name ? ('Customer: ' + data.customer_name) : ''; }
        render(data.lines || []);
      })
      .catch(function () {
        tbody.innerHTML = '';
        emptyMsg.hidden = false;
        emptyMsg.textContent = 'Could not load invoice lines.';
      });
  }

  function toggleCash() {
    if (cashGroup) {
      cashGroup.style.display = (destSel && destSel.value === 'cash_refund') ? '' : 'none';
    }
  }

  if (select) {
    select.addEventListener('change', function () { loadSI(this.value); });
    if (select.value) { loadSI(select.value); }
  }
  if (destSel) { destSel.addEventListener('change', toggleCash); toggleCash(); }
  tbody.addEventListener('input', serialize);
  if (form) { form.addEventListener('submit', serialize); }
})();
