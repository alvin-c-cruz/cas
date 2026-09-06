/* APV pre-printed layout designer (clone of SI/CRV) -- the thin drag/serialize/save layer.
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
  const jeModeSel = document.getElementById('ppJEMode');  // APV JE combined/separated
  const fieldStrip = document.getElementById('ppFieldControls');
  const colStrip = document.getElementById('ppColControls');
  const jeColStrip = document.getElementById('ppJEColControls');
  const printBtn = document.querySelector('.btn-print');
  const liToggle = document.getElementById('ppLineItemsToggle');
  const jeColsToggle = document.getElementById('ppJEColsToggle');
  const jeColsWrap = document.getElementById('ppJEColsWrap');
  const liWrap = document.getElementById('ppLineItemsWrap');
  // The server's own sanitized lineItems, so a save while the band is hidden round-trips
  // the stored values instead of overwriting them with client-side defaults.
  const liDataEl = document.getElementById('ppServerLineItems');
  const SERVER_LI = liDataEl ? JSON.parse(liDataEl.textContent) : null;
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
    '<input type="number" id="ppWidthInput" min="0" max="912" step="10" ' +
    'title="Wrap width in px (0 = keep on one line)" ' +
    'placeholder="wrap px" style="display:none;width:78px;">';
  document.body.appendChild(elBar);
  const textInput = elBar.querySelector('#ppTextInput');
  const widthInput = elBar.querySelector('#ppWidthInput');

  // A field with a wrap width wraps at it and honours newlines already in the value;
  // 0 clears it back to the historic single-line behaviour. Setting the width via a
  // typed number rather than only a drag handle is deliberate: an un-wrapped Notes
  // value runs off the page, so its right edge is not on screen to be grabbed.
  function isWrappableField(el) {
    return !!el && el.classList.contains('pp-el')
      && !el.classList.contains('pp-text')
      && !el.classList.contains('pp-je')
      && !el.classList.contains('pp-je-untied');
  }
  function setWrapWidth(el, w) {
    if (w > 0) {
      el.style.width = w + 'px';
      el.classList.add('pp-wrap');
    } else {
      el.style.width = '';
      el.classList.remove('pp-wrap');
    }
  }
  widthInput.addEventListener('input', () => {
    if (selected && isWrappableField(selected)) {
      setWrapWidth(selected, parseInt(widthInput.value) || 0);
      positionBar();
    }
  });
  widthInput.addEventListener('pointerdown', (e) => e.stopPropagation());
  // Editing a layout text -> live-update its content.
  textInput.addEventListener('input', () => {
    if (selected && selected.classList.contains('pp-text')) selected.textContent = textInput.value;
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
    if (dupBtn) dupBtn.style.display = (isText || el.classList.contains('pp-col') || el.classList.contains('pp-je')) ? 'none' : '';
    // Layout texts get an editable text box in the toolbar.
    textInput.style.display = isText ? '' : 'none';
    if (isText) textInput.value = el.textContent;
    const wrappable = isWrappableField(el);
    widthInput.style.display = wrappable ? '' : 'none';
    if (wrappable) widthInput.value = parseInt(el.style.width) || 0;
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
  // A line-item column shares the band font, so font changes apply to every column.
  function fontTargets() {
    return (selected && selected.classList.contains('pp-col')) ? cols() : [selected];
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

  const li = () => canvas.querySelector('.pp-lineitems');
  const cols = () => [...canvas.querySelectorAll('.pp-col')];
  // JE columns are .pp-jecol, NOT .pp-col, so cols() cannot sweep them into
  // lineItems.columns on save -- doing so discarded every stored line-item
  // position (BUG-APV-CDV-DESIGNER-SAVE-OVERWRITES-COLUMN-LAYOUT). Every
  // selector below that means "a draggable column" must name BOTH.
  const jeCols = () => [...canvas.querySelectorAll('.pp-jecol')];
  const anyCol = '.pp-col, .pp-jecol';
  const fieldEls = () => [...canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra]):not(.pp-je):not(.pp-je-untied)')];

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
    colStrip.dataset.built = '1';
  }

  // --- JE column show/hide strip (built once) ---
  // Deliberately NOT folded into buildColControls: that one queries .pp-col/data-col,
  // and the whole point of the JE band's separate class names is that neither sweep can
  // reach the other's columns (BUG-APV-CDV-DESIGNER-SAVE-OVERWRITES-COLUMN-LAYOUT).
  function setJEColVisible(key, visible) {
    canvas.querySelectorAll('.pp-jecol[data-jecol="' + key + '"]').forEach((c) =>
      c.classList.toggle('pp-col-hidden', !visible));
  }
  function buildJEColControls() {
    if (!jeColStrip || jeColStrip.dataset.built) return;
    const band = jeCols();
    // No JE face on this voucher (no entry, or an untied one): leave the strip empty
    // rather than showing a heading over nothing.
    if (!band.length) return;
    jeColStrip.appendChild(stripHeading('JE columns:'));
    band.forEach((col) => {
      const key = col.dataset.jecol;
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.jecoltoggle = key;
      cb.checked = !col.classList.contains('pp-col-hidden');
      cb.addEventListener('change', () => setJEColVisible(key, cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (col.dataset.label || key)));
      jeColStrip.appendChild(label);
    });
    jeColStrip.dataset.built = '1';
  }

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    addTextBtn.style.display = editing ? '' : 'none';
    if (fontSel) fontSel.style.display = editing ? '' : 'none';
    if (paperSel) paperSel.style.display = editing ? '' : 'none';
    if (dateSel) dateSel.style.display = editing ? '' : 'none';
    if (jeModeSel) jeModeSel.style.display = editing ? '' : 'none';
    if (liWrap) liWrap.style.display = editing ? '' : 'none';
    if (jeColsWrap) jeColsWrap.style.display = editing ? '' : 'none';
    if (printBtn) printBtn.style.display = editing ? 'none' : '';  // no printing while designing
    if (fieldStrip) { buildFieldControls(); fieldStrip.classList.toggle('pp-show', editing); }
    if (colStrip) { buildColControls(); colStrip.classList.toggle('pp-show', editing); }
    if (jeColStrip) { buildJEColControls(); jeColStrip.classList.toggle('pp-show', editing); }
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
    const col = e.target.closest(anyCol);
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
    if (el.classList.contains('pp-wrap') && e.clientX >= r.right - EDGE) {
      colResize = { col: el, startW: parseInt(el.style.width) || Math.round(r.width),
                    startX: e.clientX };
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  canvas.addEventListener('pointermove', (e) => {
    if (colResize) {
      const w = Math.max(20, Math.min(canvas.clientWidth, colResize.startW + (e.clientX - colResize.startX)));
      colResize.col.style.width = Math.round(w) + 'px';      // cells follow the column width
      if (colResize.col === selected && isWrappableField(colResize.col)) {
        widthInput.value = Math.round(w);                    // keep the box honest
      }
      return;
    }
    if (colDrag) {
      const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - colDrag.c.left - colDrag.dx)));
      const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - colDrag.c.top - colDrag.dy)));
      colDrag.col.style.left = x + 'px';                     // this column's x
      // Shared band top -> rows aligned. Scoped to the band the dragged column
      // belongs to: the line-item and JE faces have independent tops, and moving
      // one must not drag the other off its printed boxes.
      const band = colDrag.col.classList.contains('pp-jecol') ? jeCols() : cols();
      band.forEach((c) => { c.style.top = y + 'px'; });
      return;
    }
    if (!drag) {
      // hover cursor hint: resize near the right edge, move elsewhere
      const hov = e.target.closest && e.target.closest(anyCol + ', .pp-el.pp-wrap');
      if (hov) {
        const r = hov.getBoundingClientRect();
        hov.style.cursor = (e.clientX >= r.right - EDGE) ? 'ew-resize' : 'move';
      }
      return;
    }
    const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - drag.c.left - drag.dx)));
    const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - drag.c.top - drag.dy)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });

  function endDrag() { drag = null; colDrag = null; colResize = null; positionBar(); }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra]):not(.pp-text):not(.pp-je):not(.pp-je-untied)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        hidden: el.classList.contains('pp-field-hidden'),
        width: el.classList.contains('pp-wrap') ? (parseInt(el.style.width) || 0) : 0,
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
        width: el.classList.contains('pp-wrap') ? (parseInt(el.style.width) || 0) : 0,
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
    }));
    // Journal-entry face: start from the server layout, override x/y/width from the
    // DOM bands (present even when hidden) and mode from the select.
    let jeLayout = {};
    const jeEl = document.getElementById('ppJELayout');
    if (jeEl) { try { jeLayout = JSON.parse(jeEl.textContent) || {}; } catch (e) { jeLayout = {}; } }
    ['combined', 'debit', 'credit'].forEach((k) => {
      const el = canvas.querySelector('.pp-je[data-je="' + k + '"]');
      if (el) jeLayout[k] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        width: parseInt(el.style.width) || (jeLayout[k] && jeLayout[k].width) || 100,
      };
    });
    if (jeModeSel) jeLayout.mode = jeModeSel.value;
    // JE column face. Same round-trip rule as lineItems below: fall back to what the
    // server sent rather than inventing client-side defaults -- writing fallbacks here
    // is how the line-item columns were silently reset once. Since 2026-09-06 the band
    // is rendered even while disabled (so the toggle previews live), so the fallback is
    // reached only when the face is absent altogether: no JE lines, or an untied entry.
    if (jeColsToggle) jeLayout.columnsEnabled = !!jeColsToggle.checked;
    const jeColEls = jeCols();
    if (jeColEls.length) {
      jeLayout.columns = jeColEls.map((c) => ({
        key: c.dataset.jecol,
        x: parseInt(c.style.left) || 0,
        visible: !c.classList.contains('pp-col-hidden'),
        width: parseInt(c.style.width) || 60,
      }));
      // The columns carry the band's top; the server stores it on `combined.y`,
      // which both faces share so switching between them does not jump.
      const top = parseInt(jeColEls[0].style.top);
      if (!isNaN(top)) jeLayout.combined = Object.assign({}, jeLayout.combined, { y: top });
      const fs = parseInt(getComputedStyle(jeColEls[0]).fontSize);
      if (fs) jeLayout.fontSize = fs;
    }
    const jeAny = canvas.querySelector('.pp-je');
    if (jeAny) jeLayout.fontSize = parseInt(getComputedStyle(jeAny).fontSize) || jeLayout.fontSize || 9;
    return {
      paper: (paperSel && paperSel.value) || document.body.dataset.paper || 'continuous',
      dateFormat: (dateSel && dateSel.value) || 'long',
      extras,
      texts,
      journalEntry: jeLayout,
      // read the select (exact ALLOWED_FONTS string) rather than the computed
      // stack, so the value round-trips through the server-side whitelist.
      page: { fontFamily: (fontSel && fontSel.value) || getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        // Preserve the values the server sent when the band is absent, rather than
        // inventing defaults -- writing fallbacks here is
        // BUG-APV-CDV-DESIGNER-SAVE-OVERWRITES-COLUMN-LAYOUT, which silently discarded
        // every stored column position on each save. The band is now rendered even while
        // disabled (live preview, 2026-09-06), so these fallbacks are the belt to that
        // braces: `enabled` is read from the checkbox either way.
        enabled: !!(liToggle && liToggle.checked),
        y: first ? (parseInt(first.style.top) || SERVER_LI.y) : SERVER_LI.y,
        rowHeight: li() ? (parseInt(li().dataset.rowheight) || SERVER_LI.rowHeight) : SERVER_LI.rowHeight,
        fontSize: lics ? (parseInt(lics.fontSize) || SERVER_LI.fontSize) : SERVER_LI.fontSize,
        bold: lics ? (lics.fontWeight === '700' || lics.fontWeight === 'bold') : SERVER_LI.bold,
        columns: cols().length ? columns : SERVER_LI.columns,
      },
    };
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.textContent = 'Saving…';
    try {
      const resp = await fetch('/accounts-payable/print-layout', {
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

  // JE combined/separated: toggle which band(s) are the inactive mode (greyed in edit).
  function applyJEMode(mode) {
    // The column face wins over the mode select: it draws the same figures as the two
    // legacy bands, so when it is on neither of them may show. One face, always.
    const colsOn = !!(jeColsToggle && jeColsToggle.checked);
    canvas.querySelectorAll('.pp-je').forEach((el) => {
      const active = !colsOn && ((mode === 'combined') ? (el.dataset.je === 'combined')
                                                       : (el.dataset.je !== 'combined'));
      el.classList.toggle('pp-je-inactive', !active);
    });
  }
  if (jeModeSel) jeModeSel.addEventListener('change', () => applyJEMode(jeModeSel.value));

  // Both opt-in bands preview LIVE. They used to be gated server-side, so the markup
  // was absent until a save + reload -- ticking the box appeared to do nothing, and the
  // columns could not be dragged into place in the same sitting they were turned on.
  // Both are now always rendered and hidden with .pp-band-off, so the toggle is a class
  // flip. collect() still reads the checkbox, so what is SAVED is unchanged.
  function applyBand(el, on) { if (el) el.classList.toggle('pp-band-off', !on); }

  if (liToggle) {
    liToggle.addEventListener('change', () => applyBand(li(), liToggle.checked));
  }
  if (jeColsToggle) {
    jeColsToggle.addEventListener('change', () => {
      applyBand(canvas.querySelector('.pp-jecols'), jeColsToggle.checked);
      applyJEMode(jeModeSel ? jeModeSel.value : 'combined');   // hand the legacy bands back
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
