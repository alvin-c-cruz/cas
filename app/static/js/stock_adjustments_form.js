/* Stock Adjustment line editor (R-03 slice 2a-i, Task 8).
 *
 * Single source of truth is the #lines hidden field: it is seeded with the
 * current line JSON on load (server sets form.lines.data on edit) and the row
 * grid is serialized back into it on submit. Rows are built with textContent so
 * a product name can never inject markup.
 */
(function () {
  'use strict';

  var form = document.getElementById('sa-form');
  var linesField = document.getElementById('lines');
  var tbody = document.querySelector('#sa-lines tbody');
  var noLines = document.getElementById('sa-no-lines');
  var addBtn = document.getElementById('sa-add-line');
  if (!form || !linesField || !tbody || !addBtn) { return; }

  var products = [];
  try {
    products = JSON.parse(document.getElementById('sa-products-data').textContent || '[]');
  } catch (e) { products = []; }

  function buildProductSelect(selectedId) {
    var sel = document.createElement('select');
    sel.className = 'form-control sa-product';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '- select product -';
    sel.appendChild(placeholder);
    products.forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = String(p.id);
      opt.textContent = p.code + ' - ' + p.name;
      if (selectedId != null && String(p.id) === String(selectedId)) { opt.selected = true; }
      sel.appendChild(opt);
    });
    return sel;
  }

  function updateUnitCostState(row) {
    var qty = parseFloat(row.querySelector('.sa-qty').value);
    var costInput = row.querySelector('.sa-cost');
    if (!isNaN(qty) && qty > 0) {
      costInput.removeAttribute('disabled');
      costInput.setAttribute('required', 'required');
      costInput.placeholder = 'required';
    } else {
      costInput.removeAttribute('required');
      costInput.value = '';
      costInput.setAttribute('disabled', 'disabled');
      costInput.placeholder = 'n/a for stock-out';
    }
  }

  function addRow(data) {
    data = data || {};
    var tr = document.createElement('tr');

    var tdProduct = document.createElement('td');
    tdProduct.appendChild(buildProductSelect(data.product_id));
    tr.appendChild(tdProduct);

    var tdQty = document.createElement('td');
    tdQty.className = 'text-right';
    var qty = document.createElement('input');
    qty.type = 'number';
    qty.step = 'any';
    qty.className = 'form-control text-right sa-qty';
    if (data.quantity_delta != null) { qty.value = data.quantity_delta; }
    tdQty.appendChild(qty);
    tr.appendChild(tdQty);

    var tdCost = document.createElement('td');
    tdCost.className = 'text-right';
    var cost = document.createElement('input');
    cost.type = 'number';
    cost.step = '0.01';
    cost.min = '0';
    cost.className = 'form-control text-right sa-cost';
    if (data.unit_cost != null && data.unit_cost !== '') { cost.value = data.unit_cost; }
    tdCost.appendChild(cost);
    tr.appendChild(tdCost);

    var tdNote = document.createElement('td');
    var note = document.createElement('input');
    note.type = 'text';
    note.maxLength = 500;
    note.className = 'form-control sa-note';
    if (data.note != null) { note.value = data.note; }
    tdNote.appendChild(note);
    tr.appendChild(tdNote);

    var tdRemove = document.createElement('td');
    var rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-secondary btn-sm';
    rm.textContent = 'Remove';
    rm.addEventListener('click', function () {
      tr.parentNode.removeChild(tr);
      refreshEmptyState();
    });
    tdRemove.appendChild(rm);
    tr.appendChild(tdRemove);

    qty.addEventListener('input', function () { updateUnitCostState(tr); });
    tbody.appendChild(tr);
    updateUnitCostState(tr);
    refreshEmptyState();
  }

  function refreshEmptyState() {
    noLines.style.display = tbody.children.length ? 'none' : '';
  }

  function serialize() {
    var out = [];
    Array.prototype.forEach.call(tbody.children, function (tr) {
      var pid = tr.querySelector('.sa-product').value;
      var qty = tr.querySelector('.sa-qty').value;
      if (!pid || qty === '') { return; }
      var row = { product_id: pid, quantity_delta: qty };
      var cost = tr.querySelector('.sa-cost').value;
      if (cost !== '') { row.unit_cost = cost; }
      var note = tr.querySelector('.sa-note').value;
      if (note) { row.note = note; }
      out.push(row);
    });
    return out;
  }

  addBtn.addEventListener('click', function () { addRow(); });

  form.addEventListener('submit', function () {
    linesField.value = JSON.stringify(serialize());
  });

  // Seed from the hidden field (single source of truth).
  var seed = [];
  try { seed = JSON.parse(linesField.value || '[]'); } catch (e) { seed = []; }
  seed.forEach(addRow);
  refreshEmptyState();
})();
