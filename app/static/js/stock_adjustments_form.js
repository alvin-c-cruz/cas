/* Stock Adjustment line editor (R-03 slice 2a-i, Task 8; extended R-03 2d
 * with a Lot column for specific-identification products).
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
  var productsById = {};
  products.forEach(function (p) { productsById[String(p.id)] = p; });

  var lotsByProduct = {};
  try {
    lotsByProduct = JSON.parse(document.getElementById('sa-lots-data').textContent || '{}');
  } catch (e) { lotsByProduct = {}; }

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

  function buildLotPicker(productId, selectedLotId) {
    var sel = document.createElement('select');
    sel.className = 'form-control sa-lot-picker';
    sel.setAttribute('required', 'required');
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '- select lot -';
    sel.appendChild(placeholder);
    var lots = lotsByProduct[String(productId)] || [];
    lots.forEach(function (l) {
      var opt = document.createElement('option');
      opt.value = String(l.id);
      opt.textContent = l.label + ' (' + l.remaining_qty + ' left @ ₱' + l.unit_cost + ')';
      if (selectedLotId != null && String(l.id) === String(selectedLotId)) { opt.selected = true; }
      sel.appendChild(opt);
    });
    return sel;
  }

  function buildLotRefInput(value) {
    var input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 200;
    input.className = 'form-control sa-lot-ref';
    input.placeholder = 'optional reference';
    if (value != null) { input.value = value; }
    return input;
  }

  function updateLotState(row, data) {
    data = data || {};
    var lotCell = row.querySelector('.sa-lot-cell');
    var productSel = row.querySelector('.sa-product');
    var qty = parseFloat(row.querySelector('.sa-qty').value);
    var product = productsById[productSel.value];
    lotCell.innerHTML = '';
    if (!product || product.costing_method !== 'specific_identification') {
      var placeholder = document.createElement('span');
      placeholder.className = 'text-muted';
      placeholder.textContent = 'n/a';
      lotCell.appendChild(placeholder);
      return;
    }
    if (!isNaN(qty) && qty < 0) {
      lotCell.appendChild(buildLotPicker(product.id, data.lot_id));
    } else {
      lotCell.appendChild(buildLotRefInput(data.lot_reference));
    }
  }

  function addRow(data) {
    data = data || {};
    var tr = document.createElement('tr');

    var tdProduct = document.createElement('td');
    var productSel = buildProductSelect(data.product_id);
    tdProduct.appendChild(productSel);
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

    var tdLot = document.createElement('td');
    tdLot.className = 'sa-lot-cell';
    tr.appendChild(tdLot);

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

    qty.addEventListener('input', function () {
      updateUnitCostState(tr);
      var existingRef = tr.querySelector('.sa-lot-ref');
      var preserved = existingRef ? { lot_reference: existingRef.value } : {};
      updateLotState(tr, preserved);
    });
    productSel.addEventListener('change', function () { updateLotState(tr); });
    tbody.appendChild(tr);
    updateUnitCostState(tr);
    updateLotState(tr, data);
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
      var lotPicker = tr.querySelector('.sa-lot-picker');
      if (lotPicker && lotPicker.value) { row.lot_id = lotPicker.value; }
      var lotRef = tr.querySelector('.sa-lot-ref');
      if (lotRef && lotRef.value) { row.lot_reference = lotRef.value; }
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
