/* SI pre-printed layout designer (SI-P-71) — the thin drag/serialize/save layer.
   Positioning is drag-only. Columns: drag a header left/right to reorder; a checkbox
   strip toggles show/hide. Serializes the DOM to the layout JSON and POSTs it. */
(function () {
  const canvas = document.getElementById('ppCanvas');
  const editBtn = document.getElementById('editLayoutBtn');
  if (!canvas || !editBtn) return;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const fontSel = document.getElementById('ppFontFamily');
  const paperSel = document.getElementById('ppPaper');
  const dateSel = document.getElementById('ppDateFormat');
  const fieldStrip = document.getElementById('ppFieldControls');
  const colStrip = document.getElementById('ppColControls');
  const printBtn = document.querySelector('.btn-print');
  let editing = false;

  // --- Save button injected next to Edit ---
  const saveBtn = document.createElement('button');
  saveBtn.id = 'saveLayoutBtn';
  saveBtn.type = 'button';
  saveBtn.className = 'btn btn-edit';
  saveBtn.textContent = 'Save Layout';
  saveBtn.style.display = 'none';
  editBtn.after(saveBtn);

  // --- Floating per-element toolbar: font size -/+ and bold ---
  const elBar = document.createElement('div');
  elBar.id = 'ppElemBar';
  elBar.className = 'pp-elem-bar screen-only';
  elBar.style.display = 'none';
  elBar.innerHTML =
    '<button type="button" id="ppFontDec" title="Smaller">A-</button>' +
    '<button type="button" id="ppFontInc" title="Larger">A+</button>' +
    '<button type="button" id="ppBoldBtn" title="Bold"><b>B</b></button>';
  document.body.appendChild(elBar);
  let selected = null;

  function positionBar() {
    if (!selected) return;
    const r = selected.getBoundingClientRect();
    elBar.style.left = (window.scrollX + r.left) + 'px';
    elBar.style.top = Math.max(0, window.scrollY + r.top - 32) + 'px';
  }
  function selectEl(el) {
    if (selected) selected.classList.remove('pp-selected');
    selected = el;
    if (!el) { elBar.style.display = 'none'; return; }
    el.classList.add('pp-selected');
    elBar.style.display = 'flex';
    positionBar();
  }
  function changeFont(delta) {
    if (!selected) return;
    const cur = parseInt(getComputedStyle(selected).fontSize) || 11;
    selected.style.fontSize = Math.max(6, Math.min(72, cur + delta)) + 'px';
    positionBar();
  }
  elBar.querySelector('#ppFontInc').addEventListener('click', () => changeFont(1));
  elBar.querySelector('#ppFontDec').addEventListener('click', () => changeFont(-1));
  elBar.querySelector('#ppBoldBtn').addEventListener('click', () => {
    if (!selected) return;
    const w = getComputedStyle(selected).fontWeight;
    selected.style.fontWeight = (w === '700' || w === 'bold') ? 'normal' : 'bold';
  });

  const li = () => canvas.querySelector('.pp-lineitems');
  const cols = () => [...canvas.querySelectorAll('.pp-col')];
  const fieldEls = () => [...canvas.querySelectorAll('.pp-el:not(.pp-lineitems)')];

  function stripHeading(text) {
    const h = document.createElement('span');
    h.textContent = text;
    h.style.fontWeight = '700';
    return h;
  }

  // --- Per-field show/hide control strip (built once) ---
  function setFieldVisible(key, visible) {
    const el = canvas.querySelector('.pp-el[data-el="' + key + '"]');
    if (el) el.classList.toggle('pp-field-hidden', !visible);
  }
  function buildFieldControls() {
    if (!fieldStrip || fieldStrip.dataset.built) return;
    fieldStrip.appendChild(stripHeading('Fields:'));
    fieldEls().forEach((el) => {
      const key = el.dataset.el;
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.fieldtoggle = key;
      cb.checked = !el.classList.contains('pp-field-hidden');
      cb.addEventListener('change', () => setFieldVisible(key, cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (el.dataset.label || key)));
      fieldStrip.appendChild(label);
    });
    fieldStrip.dataset.built = '1';
  }

  // --- Column show/hide control strip (built once) ---
  function setColVisible(key, visible) {
    canvas.querySelectorAll('.pp-col[data-col="' + key + '"]').forEach((c) =>
      c.classList.toggle('pp-col-hidden', !visible));
  }
  function buildColControls() {
    if (!colStrip || colStrip.dataset.built) return;
    colStrip.appendChild(stripHeading('Columns:'));
    cols().forEach((col) => {
      const key = col.dataset.col;
      if (key === 'product') return;   // Particulars is mandatory — no show/hide toggle
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.coltoggle = key;
      cb.checked = !col.classList.contains('pp-col-hidden');
      cb.addEventListener('change', () => setColVisible(key, cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (col.dataset.label || key)));
      colStrip.appendChild(label);
    });
    colStrip.dataset.built = '1';
  }

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    if (fontSel) fontSel.style.display = editing ? '' : 'none';
    if (paperSel) paperSel.style.display = editing ? '' : 'none';
    if (dateSel) dateSel.style.display = editing ? '' : 'none';
    if (printBtn) printBtn.style.display = editing ? 'none' : '';  // no printing while designing
    if (fieldStrip) { buildFieldControls(); fieldStrip.classList.toggle('pp-show', editing); }
    if (colStrip) { buildColControls(); colStrip.classList.toggle('pp-show', editing); }
    editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
    if (!editing) selectEl(null);
  }
  editBtn.addEventListener('click', () => setEditing(!editing));

  // --- Drag: fields (.pp-el) move freely; a line-item column (.pp-col) moves
  //     HORIZONTALLY on its own x, while a VERTICAL drag moves the whole band
  //     (all columns share the top), so rows always stay aligned. Cells/rows never
  //     move independently of their column. ---
  let drag = null;      // moving a .pp-el
  let colDrag = null;   // moving a .pp-col

  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    const c = canvas.getBoundingClientRect();
    const col = e.target.closest('.pp-col');
    if (col) {
      const r = col.getBoundingClientRect();
      colDrag = { col, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    const el = e.target.closest('.pp-el');
    if (!el) return;
    selectEl(el);
    const r = el.getBoundingClientRect();
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  canvas.addEventListener('pointermove', (e) => {
    if (colDrag) {
      const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - colDrag.c.left - colDrag.dx)));
      const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - colDrag.c.top - colDrag.dy)));
      colDrag.col.style.left = x + 'px';                     // this column's x
      cols().forEach((c) => { c.style.top = y + 'px'; });    // shared band top -> rows aligned
      return;
    }
    if (!drag) return;
    const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - drag.c.left - drag.dx)));
    const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - drag.c.top - drag.dy)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });

  function endDrag() { drag = null; colDrag = null; positionBar(); }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    canvas.querySelectorAll('.pp-el:not(.pp-lineitems)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        hidden: el.classList.contains('pp-field-hidden'),
      };
    });
    const colEls = cols();
    const first = colEls[0];
    const lics = first ? getComputedStyle(first) : null;
    const columns = colEls.map((c) => ({
      key: c.dataset.col,
      x: parseInt(c.style.left) || 0,
      visible: !c.classList.contains('pp-col-hidden'),
      width: parseInt(c.style.width) || 60,
    }));
    return {
      paper: (paperSel && paperSel.value) || document.body.dataset.paper || 'continuous',
      dateFormat: (dateSel && dateSel.value) || 'long',
      // read the select (exact ALLOWED_FONTS string) rather than the computed
      // stack, so the value round-trips through the server-side whitelist.
      page: { fontFamily: (fontSel && fontSel.value) || getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        y: first ? (parseInt(first.style.top) || 0) : 300,
        rowHeight: parseInt(li().dataset.rowheight) || 20,
        fontSize: lics ? (parseInt(lics.fontSize) || 10) : 10,
        bold: lics ? (lics.fontWeight === '700' || lics.fontWeight === 'bold') : false,
        columns,
      },
    };
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.textContent = 'Saving…';
    try {
      const resp = await fetch('/sales-invoices/print-layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(collect()),
      });
      if (resp.ok) {
        if (!document.getElementById('layoutSavedFlag')) {
          const flag = document.createElement('span');
          flag.id = 'layoutSavedFlag';
          flag.style.display = 'none';
          document.body.appendChild(flag);
        }
        saveBtn.textContent = 'Saved ✓';
        setTimeout(() => { saveBtn.textContent = 'Save Layout'; }, 1500);
      } else {
        saveBtn.textContent = 'Save failed';
      }
    } catch (err) {
      saveBtn.textContent = 'Save failed';
    }
  });

  // page-wide font family (options rendered server-side from ALLOWED_FONTS)
  if (fontSel) {
    fontSel.addEventListener('change', () => {
      document.body.style.fontFamily = fontSel.value;
    });
  }

  // date format: live-preview the invoice/due dates. Keys + strftime mirror
  // preprinted_layout.DATE_FORMATS (day/month zero-padded, matching strftime).
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtDate(iso, key) {
    const p = (iso || '').split('-');
    if (p.length !== 3) return iso || '';
    const y = p[0], m = p[1], d = p[2], mi = parseInt(m, 10) - 1;
    switch (key) {
      case 'long': return d + ' ' + MONTHS[mi] + ' ' + y;
      case 'medium': return MON[mi] + ' ' + d + ', ' + y;
      case 'us': return m + '/' + d + '/' + y;
      case 'eu': return d + '/' + m + '/' + y;
      default: return iso;   // iso
    }
  }
  if (dateSel) {
    dateSel.addEventListener('change', () => {
      canvas.querySelectorAll('.pp-el[data-date]').forEach((el) => {
        el.textContent = fmtDate(el.dataset.date, dateSel.value);
      });
    });
  }

  // paper size: resize the canvas + rewrite the @page rule live; guides hide for non-continuous.
  if (paperSel) {
    paperSel.addEventListener('change', () => {
      const opt = paperSel.selectedOptions[0];
      document.body.dataset.paper = paperSel.value;
      canvas.style.width = opt.dataset.w + 'px';
      canvas.style.height = opt.dataset.h + 'px';
      const ps = document.getElementById('ppPageStyle');
      if (ps) ps.textContent = '@media print { @page { size: ' + opt.dataset.css + '; margin: 0; } }';
    });
  }
})();
