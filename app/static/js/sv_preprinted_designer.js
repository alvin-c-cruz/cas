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

  // --- "+ Add text" button (arbitrary layout text) injected next to Save ---
  const addTextBtn = document.createElement('button');
  addTextBtn.id = 'addTextBtn';
  addTextBtn.type = 'button';
  addTextBtn.className = 'btn btn-edit';
  addTextBtn.textContent = '+ Add text';
  addTextBtn.style.display = 'none';
  saveBtn.after(addTextBtn);

  // --- Non-blocking notice banner (never confirm()/alert()) ---
  function showNotice(msg) {
    let n = document.getElementById('ppNotice');
    if (!n) {
      n = document.createElement('div');
      n.id = 'ppNotice';
      n.className = 'pp-notice screen-only';
      document.body.appendChild(n);
    }
    n.textContent = msg;
    n.style.display = 'block';
    clearTimeout(n._t);
    n._t = setTimeout(() => { n.style.display = 'none'; }, 4000);
  }

  // --- Floating per-element toolbar: font size -/+ and bold ---
  const elBar = document.createElement('div');
  elBar.id = 'ppElemBar';
  elBar.className = 'pp-elem-bar screen-only';
  elBar.style.display = 'none';
  elBar.innerHTML =
    '<button type="button" id="ppFontDec" title="Smaller">A-</button>' +
    '<button type="button" id="ppFontInc" title="Larger">A+</button>' +
    '<button type="button" id="ppBoldBtn" title="Bold"><b>B</b></button>' +
    '<button type="button" id="ppDupBtn" title="Duplicate">Dup</button>' +
    '<button type="button" id="ppDelBtn" title="Delete copy">Del</button>' +
    '<input type="text" id="ppTextInput" title="Edit text" style="display:none;width:170px;">' +
    // Field box: justification inside a fixed width (legacy invoices right-justify amounts).
    '<button type="button" id="ppAlignBtn" title="Justify text left or right inside the box" style="display:none;">Left</button>' +
    '<input type="number" id="ppWidthInput" title="Box width in px (0 = fit the text)" placeholder="width" min="0" max="912" style="display:none;width:64px;">' +
    // Column: vertical offset inside its row (e.g. a note on the line under its product).
    '<input type="number" id="ppDyInput" title="Row offset in px (moves this column up or down inside each row)" placeholder="offset" min="-80" max="80" style="display:none;width:64px;">';
  document.body.appendChild(elBar);
  const textInput = elBar.querySelector('#ppTextInput');
  const alignBtn = elBar.querySelector('#ppAlignBtn');
  const widthInput = elBar.querySelector('#ppWidthInput');
  const dyInput = elBar.querySelector('#ppDyInput');
  const isEndMark = (el) => !!(el && el.classList.contains('pp-endmark'));
  const isPlainField = (el) => !!(el && el.classList.contains('pp-el') && !el.classList.contains('pp-text')
    && !el.classList.contains('pp-col') && !isEndMark(el));
  // Editing a layout text (or the end marker) -> live-update its content.
  textInput.addEventListener('input', () => {
    if (selected && (selected.classList.contains('pp-text') || isEndMark(selected))) selected.textContent = textInput.value;
  });
  // Don't let a drag start from inside the text input.
  textInput.addEventListener('pointerdown', (e) => e.stopPropagation());
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
    // Only duplicated copies are deletable; primary fields use the Fields checklist.
    const delBtn = elBar.querySelector('#ppDelBtn');
    // Deletable: duplicated field copies AND any layout text (signatory or added).
    if (delBtn) delBtn.style.display = (el.dataset.extra || el.classList.contains('pp-text')) ? '' : 'none';
    // Layout texts and line-item columns are not duplicable.
    const isText = el.classList.contains('pp-text');
    const dupBtn = elBar.querySelector('#ppDupBtn');
    if (dupBtn) dupBtn.style.display = (isText || el.classList.contains('pp-col')) ? 'none' : '';
    const isEnd = isEndMark(el);
    if (dupBtn && isEnd) dupBtn.style.display = 'none';
    // Layout texts and the end marker get an editable text box in the toolbar.
    textInput.style.display = (isText || isEnd) ? '' : 'none';
    if (isText || isEnd) textInput.value = el.textContent.trim();
    // Data fields (and their copies) get justification + box width.
    const boxed = isPlainField(el);
    alignBtn.style.display = boxed ? '' : 'none';
    widthInput.style.display = boxed ? '' : 'none';
    if (boxed) {
      alignBtn.textContent = el.style.textAlign === 'right' ? 'Right' : 'Left';
      widthInput.value = parseInt(el.style.width) || 0;
    }
    // Columns get their row offset.
    const isCol = el.classList.contains('pp-col');
    dyInput.style.display = isCol ? '' : 'none';
    if (isCol) dyInput.value = parseInt(el.dataset.dy) || 0;
    positionBar();
  }
  function duplicateSelected() {
    if (!selected) return;
    const clone = selected.cloneNode(true);
    clone.classList.remove('pp-selected', 'pp-field-hidden');
    clone.dataset.extra = '1';
    clone.style.left = ((parseInt(selected.style.left) || 0) + 16) + 'px';
    clone.style.top = ((parseInt(selected.style.top) || 0) + 16) + 'px';
    canvas.appendChild(clone);
    selectEl(clone);
  }
  function deleteSelected() {
    if (!selected) return;
    const isText = selected.classList.contains('pp-text');
    if (!selected.dataset.extra && !isText) return;     // copies + layout texts only
    // Warn (don't block) when a pre-printed signatory line is removed.
    if (isText && selected.dataset.signatory) {
      showNotice('Removed signatory line "' + (selected.textContent || '').trim() +
        '". The blank-form default still ships it.');
    }
    const el = selected;
    selectEl(null);
    el.remove();
  }
  // A line-item column shares the band font, so font changes apply to every column
  // (and to the end marker, which prints in the band font).
  function fontTargets() {
    const band = selected && (selected.classList.contains('pp-col') || isEndMark(selected));
    return band ? cols().concat(endMark() ? [endMark()] : []) : [selected];
  }
  function changeFont(delta) {
    if (!selected) return;
    fontTargets().forEach((el) => {
      const cur = parseInt(getComputedStyle(el).fontSize) || 11;
      el.style.fontSize = Math.max(6, Math.min(72, cur + delta)) + 'px';
    });
    positionBar();
  }
  elBar.querySelector('#ppFontInc').addEventListener('click', () => changeFont(1));
  elBar.querySelector('#ppFontDec').addEventListener('click', () => changeFont(-1));
  elBar.querySelector('#ppBoldBtn').addEventListener('click', () => {
    if (!selected) return;
    const bold = ['700', 'bold'].includes(getComputedStyle(selected).fontWeight);
    fontTargets().forEach((el) => { el.style.fontWeight = bold ? 'normal' : 'bold'; });
  });
  elBar.querySelector('#ppDupBtn').addEventListener('click', duplicateSelected);
  elBar.querySelector('#ppDelBtn').addEventListener('click', deleteSelected);
  alignBtn.addEventListener('click', () => {
    if (!isPlainField(selected)) return;
    if (selected.style.textAlign === 'right') {
      selected.style.textAlign = 'left';
    } else {
      // Give the box the text's current width first, so the text does not jump.
      if (!(parseInt(selected.style.width) > 0)) {
        selected.style.width = Math.ceil(selected.getBoundingClientRect().width) + 'px';
      }
      selected.style.textAlign = 'right';
    }
    selectEl(selected);
  });
  widthInput.addEventListener('input', () => {
    if (!isPlainField(selected)) return;
    const w = Math.max(0, Math.min(912, parseInt(widthInput.value) || 0));
    selected.style.width = w ? w + 'px' : '';
    positionBar();
  });
  dyInput.addEventListener('input', () => {
    if (!selected || !selected.classList.contains('pp-col')) return;
    const dy = Math.max(-80, Math.min(80, parseInt(dyInput.value) || 0));
    const top = bandTop();
    selected.dataset.dy = dy;
    selected.style.top = (top + dy) + 'px';
    positionBar();
  });
  [widthInput, dyInput].forEach((inp) => inp.addEventListener('pointerdown', (e) => e.stopPropagation()));

  const li = () => canvas.querySelector('.pp-lineitems');
  const cols = () => [...canvas.querySelectorAll('.pp-col')];
  const endMark = () => canvas.querySelector('.pp-endmark');
  const fieldEls = () => [...canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra]):not(.pp-endmark)')];
  // The band's top: every column sits at bandTop + its own row offset.
  function bandTop() {
    const first = cols()[0];
    return first ? (parseInt(first.style.top) || 0) - (parseInt(first.dataset.dy) || 0) : 0;
  }
  // The end marker sits one row below the last line item, plus its own offset.
  function endBase(top) {
    const em = endMark();
    const rows = em ? (parseInt(em.dataset.rows) || 0) : 0;
    return top + rows * (parseInt(li().dataset.rowheight) || 20);
  }

  function stripHeading(text) {
    const h = document.createElement('span');
    h.textContent = text;
    h.style.fontWeight = '700';
    return h;
  }

  // --- Per-field show/hide control strip (built once) ---
  function setFieldVisible(key, visible) {
    const el = canvas.querySelector('[data-el="' + key + '"], [data-text="' + key + '"]');
    if (el) el.classList.toggle('pp-field-hidden', !visible);
  }
  function buildFieldControls() {
    if (!fieldStrip || fieldStrip.dataset.built) return;
    fieldStrip.appendChild(stripHeading('Fields:'));
    fieldEls().forEach((el) => {
      const key = el.dataset.el || el.dataset.text;
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
    const em = endMark();
    if (em) {
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.coltoggle = 'endMarker';
      cb.checked = !em.classList.contains('pp-field-hidden');
      cb.addEventListener('change', () => em.classList.toggle('pp-field-hidden', !cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' End marker'));
      colStrip.appendChild(label);
    }
    colStrip.dataset.built = '1';
  }

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    addTextBtn.style.display = editing ? '' : 'none';
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
  let drag = null;       // moving a .pp-el
  let colDrag = null;    // moving a .pp-col
  let colResize = null;  // resizing a .pp-col width
  const EDGE = 8;        // px hot-zone at a column's right edge = resize handle

  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    if (e.target.isContentEditable) return;    // let inline text editing happen
    const c = canvas.getBoundingClientRect();
    const col = e.target.closest('.pp-col');
    if (col) {
      selectEl(col);                              // show the font toolbar for the band
      const r = col.getBoundingClientRect();
      if (e.clientX >= r.right - EDGE) {
        // grab the right edge -> resize width
        colResize = { col, startW: parseInt(col.style.width) || Math.round(r.width), startX: e.clientX };
      } else {
        colDrag = { col, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
      }
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
    if (colResize) {
      const w = Math.max(20, Math.min(canvas.clientWidth, colResize.startW + (e.clientX - colResize.startX)));
      colResize.col.style.width = Math.round(w) + 'px';      // cells follow the column width
      return;
    }
    if (colDrag) {
      const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - colDrag.c.left - colDrag.dx)));
      const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - colDrag.c.top - colDrag.dy)));
      colDrag.col.style.left = x + 'px';                     // this column's x
      // shared band top -> rows aligned; each column keeps its own row offset
      const top = y - (parseInt(colDrag.col.dataset.dy) || 0);
      cols().forEach((c) => { c.style.top = (top + (parseInt(c.dataset.dy) || 0)) + 'px'; });
      const em = endMark();
      if (em) em.style.top = (endBase(top) + (parseInt(em.dataset.dy) || 0)) + 'px';
      return;
    }
    if (!drag) {
      // hover cursor hint: resize near the right edge, move elsewhere
      const hov = e.target.closest && e.target.closest('.pp-col');
      if (hov) {
        const r = hov.getBoundingClientRect();
        hov.style.cursor = (e.clientX >= r.right - EDGE) ? 'ew-resize' : 'move';
      }
      return;
    }
    const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - drag.c.left - drag.dx)));
    const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - drag.c.top - drag.dy)));
    drag.el.style.left = x + 'px';
    if (isEndMark(drag.el)) {
      // the end marker follows the rows; a vertical drag sets its offset from them
      const base = endBase(bandTop());
      const dy = Math.max(-80, Math.min(80, y - base));
      drag.el.dataset.dy = dy;
      drag.el.style.top = (base + dy) + 'px';
      return;
    }
    drag.el.style.top = y + 'px';
  });

  function endDrag() { drag = null; colDrag = null; colResize = null; positionBar(); }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    const box = (el) => ({
      align: el.style.textAlign === 'right' ? 'right' : 'left',
      width: parseInt(el.style.width) || 0,
    });
    canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra]):not(.pp-text):not(.pp-endmark)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        hidden: el.classList.contains('pp-field-hidden'),
        ...box(el),
      };
    });
    const extras = [...canvas.querySelectorAll('.pp-el[data-extra]')].map((el) => {
      const cs = getComputedStyle(el);
      return {
        key: el.dataset.el,
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        ...box(el),
      };
    });
    const texts = [...canvas.querySelectorAll('.pp-text')].map((el) => {
      const cs = getComputedStyle(el);
      return {
        id: el.dataset.text,
        text: el.textContent,
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 10,
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
      dy: parseInt(c.dataset.dy) || 0,
    }));
    const em = endMark();
    return {
      paper: (paperSel && paperSel.value) || document.body.dataset.paper || 'continuous',
      // Echoed back so save_print_layout can verify the invoice's own branch
      // still matches the currently selected branch at SAVE time (a render-time
      // UI gate alone can't catch the selected branch changing between page
      // load and this POST -- e.g. a second tab switches branch).
      branchId: document.body.dataset.invoiceBranchId != null
        ? parseInt(document.body.dataset.invoiceBranchId, 10) : null,
      dateFormat: (dateSel && dateSel.value) || 'long',
      extras,
      texts,
      // read the select (exact ALLOWED_FONTS string) rather than the computed
      // stack, so the value round-trips through the server-side whitelist.
      page: { fontFamily: (fontSel && fontSel.value) || getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        y: first ? bandTop() : 300,
        rowHeight: parseInt(li().dataset.rowheight) || 20,
        fontSize: lics ? (parseInt(lics.fontSize) || 10) : 10,
        bold: lics ? (lics.fontWeight === '700' || lics.fontWeight === 'bold') : false,
        columns,
        endMarker: em ? {
          text: em.textContent.trim(),
          x: parseInt(em.style.left) || 0,
          dy: parseInt(em.dataset.dy) || 0,
          visible: !em.classList.contains('pp-field-hidden'),
        } : undefined,
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
        let reason = 'Save failed. Please try again.';
        try {
          const body = await resp.json();
          if (body && body.error) reason = body.error;
        } catch (parseErr) { /* non-JSON error body -- keep the generic reason */ }
        showNotice(reason);
      }
    } catch (err) {
      saveBtn.textContent = 'Save failed';
      showNotice('Save failed. Please try again.');
    }
  });

  // --- "+ Add text": drop a fresh, deletable layout text onto the canvas ---
  let addTextSeq = 0;
  addTextBtn.addEventListener('click', () => {
    const el = document.createElement('div');
    el.className = 'pp-el pp-text';
    el.dataset.text = 'text_' + Date.now() + '_' + (++addTextSeq);
    el.dataset.label = 'New text';
    el.textContent = 'New text';
    el.style.left = '80px';
    el.style.top = '120px';
    el.style.fontSize = '10px';
    el.style.fontWeight = 'normal';
    canvas.appendChild(el);
    selectEl(el);
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
      case 'full': return MONTHS[mi] + ' ' + d + ', ' + y;
      case 'us_dash': return m + '-' + d + '-' + y;
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
      if (ps) ps.textContent = '@page { size: ' + opt.dataset.css + '; margin: 0; }';
    });
  }
})();
