/* Delivery Receipt line grid: on SO select, render that SO's open lines and
   serialize {sales_order_item_id, delivered_quantity} into the hidden `lines` field. */
(function () {
  'use strict';

  var soLines = JSON.parse(document.getElementById('so-lines-data').textContent || '{}');
  var existing = JSON.parse(document.getElementById('dr-existing-data').textContent || '{}');
  var select = document.getElementById('so-select');
  var tbody = document.querySelector('#dr-lines tbody');
  var emptyMsg = document.getElementById('dr-no-lines');
  var hidden = document.getElementById('lines-json');
  var form = document.getElementById('dr-form');

  function num(v) {
    var n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }

  function cell(row, text, cls) {
    var td = document.createElement('td');
    td.textContent = text;
    if (cls) { td.className = cls; }
    row.appendChild(td);
    return td;
  }

  function render(soId) {
    tbody.innerHTML = '';
    var rows = soLines[soId] || [];
    emptyMsg.hidden = rows.length > 0;
    rows.forEach(function (r) {
      var tr = document.createElement('tr');
      var label = r.product_code ? r.product_code + ': ' + r.product_name : r.product_name;
      cell(tr, label);
      cell(tr, r.uom || '');
      cell(tr, r.ordered, 'text-right');
      cell(tr, r.delivered, 'text-right');
      cell(tr, r.open, 'text-right');

      var td = document.createElement('td');
      td.className = 'text-right';
      var input = document.createElement('input');
      input.type = 'number';
      input.step = '0.0001';
      input.min = '0';
      input.max = String(r.open);
      input.className = 'form-control qty-input';
      input.dataset.soItemId = r.sales_order_item_id;
      var prior = existing[r.sales_order_item_id];
      input.value = prior === undefined ? '' : prior;
      td.appendChild(input);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
    serialize();
  }

  function serialize() {
    var out = [];
    tbody.querySelectorAll('.qty-input').forEach(function (i) {
      var q = num(i.value);
      if (q > 0) {
        out.push({ sales_order_item_id: parseInt(i.dataset.soItemId, 10), delivered_quantity: String(q) });
      }
    });
    hidden.value = JSON.stringify(out);
  }

  if (select) {
    select.addEventListener('change', function () { render(this.value); });
    if (select.value) { render(select.value); }
  }
  tbody.addEventListener('input', serialize);
  if (form) { form.addEventListener('submit', serialize); }
})();
