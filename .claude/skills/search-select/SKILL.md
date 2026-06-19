---
name: search-select
description: Use when adding or modifying a CAS search-select dropdown (typeahead picker built on Choices.js via initSearchSelect) — e.g. a new vendor/customer/account/code picker, an inline "add new…" action, or a code-only-when-selected tag like the VT/WT line-item selects. Covers the standard pattern and its variations.
---

# /search-select — Implement a search-select picker

CAS pickers use one shared initializer, `initSearchSelect(selectEl, options)`, in
`app/static/search-select.js`. It returns the Choices instance and layers a deterministic,
coded-data-friendly typeahead on top of Choices.js. Full feature reference:
`docs/frontend/search-select.md`. Read it before non-trivial work — don't reinvent behaviours
it already provides (ordering, substring filter, best-match highlight, inline autocomplete,
bold match, pinned add-action).

## Decide the shape first

1. **Plain picker** (label-only or `CODE — Name`, same display selected & in dropdown) → standard pattern.
2. **Picker with an inline "add new…" action** → standard pattern + `addAction` (+ a modal).
3. **Selected chip differs from the dropdown** (e.g. VT/WT show code-only when selected) → standard pattern + a `callbackOnCreateTemplates` `item` template passed via `choicesOptions`.

## Standard pattern

1. **Markup** — a normal `<select>` with a placeholder first option and design-token classes:
   ```html
   <select id="my_thing_id" name="my_thing_id" class="form-control">
     <option value="">Search or select…</option>
     {% for o in options %}<option value="{{ o.id }}">{{ o.code }} — {{ o.name }}</option>{% endfor %}
   </select>
   ```
2. **Load order** in the template: `choices.min.css` + `choices.min.js`, then `search-select.js`,
   then your init script. (Follow how `accounts_payable/templates/accounts_payable/form.html`
   loads them.)
3. **Init:**
   ```js
   const choices = initSearchSelect(document.getElementById('my_thing_id'), {
     choicesOptions: { searchResultLimit: 50 },
   });
   ```
4. **React to selection** on the native select's `change` event:
   `selectEl.addEventListener('change', () => { /* selectEl.value */ });`

## Variation: inline "add new…" action

Mirror the vendor pattern (`app/static/vendor-quick-add.js`):
```js
const choices = initSearchSelect(selectEl, {
  choicesOptions: { searchResultLimit: 50 },
  addAction: { value: '__add_thing__', label: '➕ Add Thing…', onSelect: openModal },
});
```
- Build a CSRF-protected HTML modal (NEVER `confirm()`/`alert()` — project rule). Include a
  `{{ csrf_token() }}` hidden input.
- Make the create endpoint JSON-aware (return `jsonify(ok=True, thing={id,label})` on success,
  `jsonify(ok=False, errors={...}), 422` on validation). See `app/vendors/views.py::create`.
- On success: `choices.setChoices([{value,label}], 'value','label', false)` →
  `choices.setChoiceByValue(value)` → **`selectEl.dispatchEvent(new Event('change',{bubbles:true}))`**
  (setChoiceByValue does NOT fire a native change). Then `form.reset()` and reset any
  Choices-enhanced sub-widgets explicitly (their DOM survives `form.reset()`).
- Any page `change` handler must guard the sentinel: `if (selectEl.value === '__add_thing__') return;`

## Variation: code-only-when-selected (VT/WT-style)

Dropdown shows `CODE — Name`; the selected chip shows `CODE` only. Pass the template through
`choicesOptions` so you keep the shared typeahead:
```js
const choices = initSearchSelect(sel, {
  choicesOptions: {
    searchResultLimit: 50,
    callbackOnCreateTemplates: function (tmpl) {
      return {
        item: function (cfg, data) {                 // `item` = selected chip
          const cn = cfg.classNames;
          const code = (data.customProperties && data.customProperties.code) || data.value || '—';
          return tmpl(`<div class="${cn.item} ${data.highlighted ? cn.highlightedState : cn.itemSelectable}"
                            data-item data-id="${data.id}" data-value="${data.value}"
                            ${data.active ? 'aria-selected="true"' : ''}>${code}</div>`);
        }
      };
    }
  }
});
```
- Each `<option>` must carry the code: `data-custom-properties='{"code":"V12SV"}'` (or pass
  `customProperties` via `setChoices`). Keep the full `CODE — Name` label so search matches both.
- The existing line-item VT/WT selects in `accounts_payable/form.html` use `new Choices(...)`
  **directly** with `codeOnlyOpts` (no shared typeahead). Prefer routing new ones through
  `initSearchSelect` as above.

## Gotchas (always)
- Choices **strips the real `<option>`s** from the native select — for tests/automation drive the
  Choices UI (`.choices:has(#id) .choices__inner` then `.choices__list--dropdown .choices__item`),
  not `select.value`.
- Keep `allowHTML:false` and use `escHtml` for any option text you build in JS (XSS).
- Responsive + design tokens only (no hardcoded colors/styling).

## Verify
- Browser-test via `/run` + Playwright: type a few chars → correct row highlighted + autocompleted;
  matched run bold; add-action reachable even when the query matches nothing; selecting it opens
  the modal and (after save) auto-selects the new row with line items still usable.
- If you touched `app/static/search-select.js` (shared, high blast radius): run `/guard`, and if you
  added a new shared picker file, add it to `.claude/regression-map.json` and consider an e2e smoke.
- Commit + push (auto-commit rule).
