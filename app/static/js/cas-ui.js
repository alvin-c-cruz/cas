/*  cas-ui.js — reusable, data-agnostic UI utilities extracted from mockup/js/app.js.
    Loaded by templates/base.html. Safe to use in any Django template.

    Provides:
      window.fmt(n), window.fmtP(n), window.parseAmt(v)
      window.openModal(id), window.closeModal(id)
      window.showToast(msg, type)
      window.createSearchSelectTag(container, data, options)
      Auto-wiring for: .amt inputs · [data-open-modal] / [data-close-modal] · .overlay backdrop · .tabs
*/
(function () {
  'use strict';

  /* ─── Number formatting ─────────────────────────────────────── */
  const fmt      = n => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtP     = n => n < 0 ? `(${fmt(Math.abs(n))})` : fmt(n);
  const parseAmt = v => parseFloat(String(v).replace(/,/g, '')) || 0;

  window.fmt = fmt;
  window.fmtP = fmtP;
  window.parseAmt = parseAmt;

  /* ─── Amount input formatting — for any <input class="amt"> ─── */
  document.addEventListener('focusin', e => {
    if (!e.target.matches('input.amt')) return;
    const raw = parseAmt(e.target.value);
    e.target.value = raw === 0 ? '' : raw.toFixed(2);
    e.target.select();
  });
  document.addEventListener('focusout', e => {
    if (!e.target.matches('input.amt')) return;
    const raw = parseAmt(e.target.value);
    e.target.value = raw === 0 ? '' : fmt(raw);
  });

  /* ─── Modal open/close ─────────────────────────────────────── */
  function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const already = document.querySelectorAll('.overlay.open').length;
    el.style.zIndex = already > 0 ? 400 : '';
    el.classList.add('open');
    el.dispatchEvent(new CustomEvent('modal:open'));
  }
  function closeModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('open');
    el.style.zIndex = '';
    el.dispatchEvent(new CustomEvent('modal:close'));
  }
  window.openModal  = openModal;
  window.closeModal = closeModal;

  // Auto-wire any [data-open-modal] / [data-close-modal] triggers
  document.addEventListener('click', e => {
    const opener = e.target.closest('[data-open-modal]');
    if (opener) { openModal(opener.dataset.openModal); return; }
    const closer = e.target.closest('[data-close-modal]');
    if (closer) { closeModal(closer.dataset.closeModal); return; }
    // Click on overlay backdrop (but not its inner card) closes
    if (e.target.classList?.contains('overlay') && e.target.classList.contains('open')) {
      closeModal(e.target.id);
    }
  });

  // Escape closes the top-most open modal
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const open = [...document.querySelectorAll('.overlay.open')];
    if (open.length) closeModal(open[open.length - 1].id);
  });

  /* ─── Toast ────────────────────────────────────────────────── */
  function showToast(msg, type = 'success') {
    let el = document.getElementById('app-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'app-toast';
      el.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;color:#fff;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,.18)';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.background = type === 'success'                    ? '#15803d'
                         : type === 'warn' || type === 'warning' ? '#d97706'
                         : type === 'error'                       ? '#dc2626'
                         : '#334155';
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 3500);
  }
  window.showToast = showToast;

  /* ─── Tabs ─────────────────────────────────────────────────── */
  document.addEventListener('click', e => {
    const tab = e.target.closest('.tabs .tab[data-tab-group][data-tab]');
    if (!tab) return;
    const group  = tab.dataset.tabGroup;
    const target = tab.dataset.tab;
    document.querySelectorAll(`[data-tab-group="${group}"]`).forEach(t => t.classList.remove('active'));
    document.querySelectorAll(`[data-tab-panel="${group}"]`).forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`${group}-${target}`)?.classList.add('active');
  });

  /* ─── SearchSelectTag — typeahead account picker ───────────── */
  /*  createSearchSelectTag(container, data, options)
        container : HTMLElement to host the input
        data      : Array of { code, name, rate?, ... }
        options   : { inputClass?, placeholder?, onSelect?, actions? }
      Returns the <input> element. Selected code lives in `input.dataset.code`. */
  function createSearchSelectTag(container, data, options = {}) {
    const inputClass  = options.inputClass  || 'line-input acct-input';
    const placeholder = options.placeholder || 'Search…';
    const onSelect    = options.onSelect    || null;
    const actions     = options.actions     || [];

    const wrap = document.createElement('div');
    wrap.className = 'acct-wrap';

    const input = document.createElement('input');
    input.className = inputClass;
    input.type = 'text';
    input.placeholder = placeholder;
    input.autocomplete = 'off';
    input.dataset.code = '';

    const dropdown = document.createElement('div');
    dropdown.className = 'acct-dropdown';
    document.body.appendChild(dropdown);

    let activeIdx = -1;

    function position() {
      const r = input.getBoundingClientRect();
      dropdown.style.top   = `${r.bottom + 2}px`;
      dropdown.style.left  = `${r.left}px`;
      dropdown.style.width = `${Math.max(r.width, 240)}px`;
    }
    function getOpts() {
      return [...dropdown.querySelectorAll('.acct-option:not(.acct-no-result)')];
    }
    function setActive(idx) {
      const opts = getOpts();
      opts.forEach(o => o.classList.remove('active'));
      activeIdx = Math.max(0, Math.min(idx, opts.length - 1));
      if (opts[activeIdx]) {
        opts[activeIdx].classList.add('active');
        opts[activeIdx].scrollIntoView({ block: 'nearest' });
      }
    }
    function selectAccount(a) {
      input.value        = `${a.code} — ${a.name}`;
      input.dataset.code = a.code;
      hide();
      if (onSelect) onSelect(a);
    }
    function build(q = '') {
      const ql = q.toLowerCase();
      const hits = data.filter(a =>
        !ql || String(a.code).toLowerCase().startsWith(ql) || a.name.toLowerCase().includes(ql)
      );
      dropdown.innerHTML = '';
      activeIdx = -1;

      actions.forEach(action => {
        const opt = document.createElement('div');
        opt.className = 'acct-option acct-action';
        opt.innerHTML = `<span class="acct-action-label">${action.label}</span>`;
        opt.addEventListener('mousedown', e => { e.preventDefault(); action.onAction(); hide(); });
        dropdown.appendChild(opt);
      });

      if (!hits.length) {
        if (!actions.length) { hide(); return; }
        dropdown.style.display = 'block';
        return;
      }
      if (hits.length === 1 && !actions.length) {
        selectAccount(hits[0]);
        return;
      }
      if (actions.length) {
        const sep = document.createElement('div');
        sep.className = 'acct-action-sep';
        dropdown.appendChild(sep);
      }
      hits.forEach(a => {
        const opt = document.createElement('div');
        opt.className = 'acct-option';
        opt.dataset.code = a.code;
        const rateBadge = a.rate != null ? `<span class="acct-opt-rate">${a.rate}</span>` : '';
        opt.innerHTML = `<span class="acct-opt-code">${a.code}</span><span class="acct-opt-name">${a.name}</span>${rateBadge}`;
        opt.addEventListener('mousedown', e => { e.preventDefault(); selectAccount(a); });
        dropdown.appendChild(opt);
      });
    }
    function show() { position(); build(input.value); dropdown.style.display = 'block'; }
    function hide() { dropdown.style.display = 'none'; activeIdx = -1; }

    input.addEventListener('focus', () => { input.select(); show(); });
    input.addEventListener('input', () => {
      input.dataset.code = '';
      build(input.value);
      position();
      dropdown.style.display = 'block';
    });
    input.addEventListener('blur', () => setTimeout(hide, 150));
    input.addEventListener('keydown', e => {
      const opts = getOpts();
      if (e.key === 'ArrowDown')  { e.preventDefault(); setActive(activeIdx < 0 ? 0 : activeIdx + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIdx - 1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        const opt = opts[activeIdx];
        if (opt) {
          const a = data.find(a => String(a.code) === opt.dataset.code);
          if (a) selectAccount(a);
        }
      } else if (e.key === 'Escape') { hide(); input.blur(); }
    });

    // Auto-clean dropdown when host input is removed
    const observer = new MutationObserver(() => {
      if (!document.body.contains(input)) { dropdown.remove(); observer.disconnect(); }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    wrap.appendChild(input);
    container.appendChild(wrap);
    return input;
  }
  window.createSearchSelectTag = createSearchSelectTag;

  /* ─── Generic click-outside-to-close for elements marked
         data-toggle-on="parent-selector".  Pattern:
           <div class="user-menu-wrap"><div class="user-menu" data-close-on-outside=".user-menu-wrap">…</div></div>
  */
  document.addEventListener('click', e => {
    document.querySelectorAll('[data-close-on-outside]').forEach(el => {
      const scope = el.dataset.closeOnOutside;
      if (!e.target.closest(scope)) el.classList.remove('open');
    });
  });

})();
