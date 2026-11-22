/* Delivery Receipt form. BUG-10 A (owner, 22 Nov 2026): it follows the Sales Invoice form.

   The customer comes first. Then one plain choice: "Deliver against a sales order" (one of that
   customer's confirmed orders with open lines) or "Deliver without a sales order". One lines table
   serves both:
     against an order -> the order's lines (ordered, already delivered, open), a "Deliver now"
                         quantity on each; sent as `lines` = [{sales_order_item_id, delivered_quantity}]
     without an order -> lines the user adds (product, unit, quantity);
                         sent as `direct_lines` = [{product_id, uom_id, delivered_quantity}]
   Only the chosen way's lines are sent, and `sales_order_id` carries the order, or 0 for none.
   What was typed for the other way stays on the page until the customer changes.

   A saved DR keeps its customer and its way: the page then opens "locked" and only the header and
   the lines change.

   Rows are built with textContent, so a product or customer name can never inject markup. */
(function () {
  'use strict';

  var form = document.getElementById('dr-form');
  if (!form) { return; }

  function read(id, fallback) {
    var el = document.getElementById(id);
    if (!el) { return fallback; }
    try { return JSON.parse(el.textContent || ''); } catch (e) { return fallback; }
  }

  var orders = read('dr-orders-data', []);
  var soLines = read('so-lines-data', {});
  var existing = read('dr-existing-data', {});
  var free = read('dr-noso-data', {});
  var chosen = read('dr-selected-data', {});
  var products = free.products || [];
  var units = free.units || [];
  var locked = !!chosen.locked;

  var customerSel = document.getElementById('dr-customer');
  var soSel = document.getElementById('so-select');
  var soHidden = document.getElementById('sales-order-id');
  var wayOrder = form.querySelector('input[name="dr_source"][value="so"]');
  var wayNone = form.querySelector('input[name="dr_source"][value="none"]');
  var card = document.getElementById('customerCard');
  var cardLabel = document.getElementById('customerCardLabel');
  var sourceSection = document.getElementById('drSourceSection');
  var lockedBox = document.getElementById('lineItemsLocked');
  var linesSection = document.getElementById('lineItemsSection');
  var table = document.getElementById('lineItemsTable');
  var soBody = document.getElementById('dr-so-body');
  var freeBody = document.getElementById('dr-free-body');
  var noLines = document.getElementById('dr-no-lines');
  var noOrders = document.getElementById('dr-no-orders');
  var sourceError = document.getElementById('dr-source-error');
  var linesError = document.getElementById('dr-lines-error');
  var addButton = document.getElementById('dr-add-line');
  var linesHidden = document.getElementById('lines-json');
  var directHidden = document.getElementById('direct-lines-json');

  var PICK_ORDER = 'Select the sales order to deliver against, or choose "Deliver without a sales order".';
  var ORDER_PLACEHOLDER = 'Select the sales order…';
  var way = '';               // 'so' = against a sales order, 'none' = without one, '' = no customer yet
  var shownOrder = '';        // the order whose lines are in the table
  var soPicker = null;        // the search-select on the order picker
  var customerPicker = null;

  function num(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; }
  function show(node, yes) { if (node) { node.style.display = yes ? '' : 'none'; } }
  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }
  function option(value, label, selected) {
    var o = make('option', '', label);
    o.value = value;
    if (selected) { o.selected = true; }
    return o;
  }
  function searchable(select) {
    return (typeof initSearchSelect === 'function')
      ? initSearchSelect(select, { choicesOptions: { searchResultLimit: 50 } }) : null;
  }
  function say(node, text) { if (node) { node.textContent = text || ''; show(node, !!text); } }

  // -- the order picker -----------------------------------------------------------------------------

  function ordersOf(customerId) {
    return orders.filter(function (o) { return String(o.customer_id) === String(customerId); });
  }

  function orderValue() {
    var v = soPicker ? soPicker.getValue(true) : soSel.value;
    return v ? String(v) : '';
  }

  /* Only the chosen customer's orders are offered. `selectedId` starts the picker on one of them. */
  function fillOrders(list, selectedId) {
    var want = selectedId ? String(selectedId) : '';
    var items = [{ value: '', label: ORDER_PLACEHOLDER, selected: !want, placeholder: true }];
    list.forEach(function (o) {
      items.push({ value: String(o.id), label: o.label, selected: String(o.id) === want });
    });
    if (soPicker) {
      soPicker.setChoices(items, 'value', 'label', true);
    } else {                    // no search-select script: a plain <select> does the same job
      soSel.textContent = '';
      items.forEach(function (it) { soSel.appendChild(option(it.value, it.label, it.selected)); });
    }
  }

  function enableOrderPicker(yes) {
    soSel.disabled = !yes;
    if (soPicker) { if (yes) { soPicker.enable(); } else { soPicker.disable(); } }
  }

  // -- lines of a sales order -----------------------------------------------------------------------

  function cell(row, text, cls) {
    var td = make('td', cls || '', text);
    row.appendChild(td);
    return td;
  }

  /* The order's lines. `fill` puts back the quantities the page was opened with (an edit, or a save
     that was refused); an order picked afterwards starts empty. */
  function renderOrder(orderId, fill) {
    shownOrder = orderId || '';
    soBody.textContent = '';
    (soLines[orderId] || []).forEach(function (r) {
      var tr = make('tr');
      cell(tr, r.line_number);
      cell(tr, r.product_name);           // the product code is retired from display (owner, 9 Sep 2026)
      cell(tr, r.uom || '');
      cell(tr, r.ordered, 'text-right dr-col-so');
      cell(tr, r.delivered, 'text-right dr-col-so');
      cell(tr, r.open, 'text-right dr-col-so');
      var td = make('td', 'text-right');
      var input = make('input', 'form-control qty-input');
      input.type = 'number';
      input.step = '0.0001';
      input.min = '0';
      input.max = String(r.open);
      input.dataset.soItemId = r.sales_order_item_id;
      var prior = fill ? existing[r.sales_order_item_id] : undefined;
      input.value = (prior === undefined || prior === null) ? '' : prior;
      td.appendChild(input);
      tr.appendChild(td);
      cell(tr, '', 'dr-col-free');
      soBody.appendChild(tr);
    });
  }

  // -- lines without a sales order ------------------------------------------------------------------

  function renumber() {
    Array.prototype.forEach.call(freeBody.children, function (tr, i) { tr.firstChild.textContent = i + 1; });
  }

  function addFreeRow(line) {
    line = line || {};
    var tr = make('tr');
    cell(tr, '');

    var product = make('select', 'form-control dr-free-product');
    product.appendChild(option('', '— product —', !line.product_id));
    products.forEach(function (p) {
      product.appendChild(option(String(p.id), p.name, String(p.id) === String(line.product_id || '')));
    });
    var unit = make('select', 'form-control dr-free-unit');
    unit.appendChild(option('', '— product\'s unit —', !line.uom_id));
    units.forEach(function (u) {
      unit.appendChild(option(String(u.id), u.code, String(u.id) === String(line.uom_id || '')));
    });
    var qty = make('input', 'form-control qty-input');
    qty.type = 'number';
    qty.step = '0.0001';
    qty.min = '0';
    qty.value = line.delivered_quantity || '';
    var remove = make('button', 'li-btn-action dr-remove-line', '🗑');
    remove.type = 'button';
    remove.title = 'Remove line';
    remove.setAttribute('aria-label', 'Remove line');

    [product, unit].forEach(function (control) { var td = make('td'); td.appendChild(control); tr.appendChild(td); });
    cell(tr, '', 'dr-col-so'); cell(tr, '', 'dr-col-so'); cell(tr, '', 'dr-col-so');
    var qtyCell = make('td', 'text-right'); qtyCell.appendChild(qty); tr.appendChild(qtyCell);
    var removeCell = make('td', 'dr-col-free'); removeCell.appendChild(remove); tr.appendChild(removeCell);
    freeBody.appendChild(tr);

    // The pickers are made searchable once the row is in the page.
    searchable(product);
    var unitPicker = searchable(unit);
    product.addEventListener('change', function () {
      var p = products.filter(function (x) { return String(x.id) === product.value; })[0];
      if (p && p.uom_id && !unit.value) {              // the product's own unit, unless one was chosen
        if (unitPicker) { unitPicker.setChoiceByValue(String(p.uom_id)); } else { unit.value = String(p.uom_id); }
      }
      serialize();
    });
    unit.addEventListener('change', serialize);
    remove.addEventListener('click', function () {
      tr.remove();
      if (!freeBody.children.length) { addFreeRow(); }
      renumber();
      serialize();
    });
    renumber();
    return tr;
  }

  function freeRows() {
    return Array.prototype.map.call(freeBody.children, function (tr, i) {
      return { n: i + 1, product: tr.querySelector('.dr-free-product').value,
               unit: tr.querySelector('.dr-free-unit').value, qty: tr.querySelector('.qty-input').value };
    });
  }

  // -- what is sent ---------------------------------------------------------------------------------

  function serialize() {
    var lines = [], direct = [];
    if (way === 'so') {
      soBody.querySelectorAll('.qty-input').forEach(function (i) {
        var q = num(i.value);
        if (q > 0) { lines.push({ sales_order_item_id: parseInt(i.dataset.soItemId, 10), delivered_quantity: String(q) }); }
      });
    } else if (way === 'none') {
      freeRows().forEach(function (r) {
        if (!r.product && !r.qty) { return; }           // an untouched line
        direct.push({ product_id: r.product || null, uom_id: r.unit || null, delivered_quantity: r.qty || 0 });
      });
    }
    linesHidden.value = JSON.stringify(lines);
    directHidden.value = JSON.stringify(direct);
    soHidden.value = way === 'so' ? orderValue() : (way === 'none' ? '0' : '');
  }

  // -- the way: against a sales order, or without one -----------------------------------------------

  function setWay(next, fill) {
    way = next;
    wayOrder.checked = way === 'so';
    wayNone.checked = way === 'none';
    table.classList.toggle('dr-mode-so', way !== 'none');
    table.classList.toggle('dr-mode-free', way === 'none');
    enableOrderPicker(way === 'so' && !locked);
    say(sourceError, '');
    say(linesError, '');
    if (way === 'so') {
      var order = orderValue();
      if (order !== shownOrder) { renderOrder(order, fill); }
      show(noLines, !soBody.children.length);
      noLines.textContent = order ? 'This sales order has no open lines.' : 'Select the sales order to load its open lines.';
    } else {
      if (way === 'none' && !freeBody.children.length) { addFreeRow(); }
      show(noLines, false);
    }
    show(addButton, way === 'none');
    serialize();
  }

  // -- the customer ---------------------------------------------------------------------------------

  function customerName() {
    var o = customerSel.options[customerSel.selectedIndex];
    return o && o.value ? o.textContent.trim() : '';
  }

  /* `start` is the page opening (on ?so=, on an edit, or after a refused save): then what the server
     says was chosen is put back. A customer picked by the user starts the order over. */
  function setCustomer(customerId, start) {
    var has = !!customerId;
    card.classList.toggle('vendor-step-card--done', has);
    cardLabel.textContent = has ? '✓ ' + customerName() : 'Select Customer';
    lockedBox.classList.toggle('line-items-locked--hidden', has);
    show(sourceSection, has);
    show(linesSection, has);
    Array.prototype.forEach.call(document.querySelectorAll('.header-fields'), function (node) {
      node.classList.toggle('header-fields--active', has);
    });
    if (!has) { way = ''; shownOrder = ''; soBody.textContent = ''; serialize(); return; }

    var mine = ordersOf(customerId);
    var order = start && chosen.sales_order_id ? String(chosen.sales_order_id) : (mine.length === 1 ? String(mine[0].id) : '');
    if (!start) { shownOrder = ''; soBody.textContent = ''; }      // another customer's order lines do not carry over
    fillOrders(mine, order);
    wayOrder.disabled = locked || !mine.length;
    wayNone.disabled = locked;
    show(noOrders, !mine.length && !locked);
    var next = start && chosen.source ? chosen.source : 'so';
    if (!mine.length) { next = 'none'; }
    setWay(next, !!start);
  }

  // -- wiring ---------------------------------------------------------------------------------------

  customerPicker = searchable(customerSel);
  soPicker = searchable(soSel);
  (free.existing || []).forEach(addFreeRow);

  customerSel.addEventListener('change', function () { setCustomer(customerSel.value, false); });
  soSel.addEventListener('change', function () {
    if (way !== 'so') { return; }
    renderOrder(orderValue(), false);
    setWay('so', false);
  });
  wayOrder.addEventListener('change', function () { if (wayOrder.checked) { setWay('so', false); } });
  wayNone.addEventListener('change', function () { if (wayNone.checked) { setWay('none', false); } });
  addButton.addEventListener('click', function () { addFreeRow(); serialize(); });
  table.addEventListener('input', serialize);

  form.addEventListener('submit', function (e) {
    serialize();
    say(sourceError, '');
    say(linesError, '');
    if (way === 'so' && !orderValue()) {
      e.preventDefault();
      say(sourceError, PICK_ORDER);
      return;
    }
    if (way === 'none') {
      var half = freeRows().filter(function (r) { return (r.product || r.qty) && !(r.product && num(r.qty) > 0); })[0];
      if (half) {
        e.preventDefault();
        say(linesError, 'Line ' + half.n + ': choose the product and enter a quantity above zero, or remove the line.');
      }
    }
  });

  setCustomer(chosen.customer_id ? String(chosen.customer_id) : customerSel.value, true);
})();
