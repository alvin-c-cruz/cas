# Search-Select — feature reference

The **search-select** is CAS's shared, typeahead-friendly dropdown built on Choices.js. One
initializer — `initSearchSelect(selectEl, options)` in
[`app/static/search-select.js`](../../app/static/search-select.js) — turns a plain `<select>`
into a predictable, coded-data-friendly picker and returns the underlying Choices instance.

The vendor picker on the AP/CD transaction forms is the reference implementation
([`app/static/vendor-quick-add.js`](../../app/static/vendor-quick-add.js) is a thin caller).

---

## Why it exists

Choices.js out of the box has two behaviours that are wrong for coded accounting data:
1. its fuzzy search re-ranks and over-matches (e.g. typing `v002` still shows every vendor), and
2. it sorts/filters in ways that move coded rows around unpredictably.

`initSearchSelect` layers a deterministic, code-aware typeahead on top while staying XSS-safe.

---

## Final feature set

Every behaviour below works for **any** picker that calls `initSearchSelect`:

1. **Sane Choices defaults** — `searchEnabled`, `itemSelectText: ''`, `shouldSort: false`,
   `allowHTML: false`. (`shouldSort:false` because we do our own ordering.)
2. **Stable label ordering** — on open *and* on every keystroke, options are re-sorted by label
   with numeric-aware `localeCompare` (so `V2` < `V10`). Counters Choices' fuzzy re-ranking and
   keeps freshly-added entries in their sorted spot without a page reload.
3. **Substring filtering on the actual typed characters** — only options whose label *contains*
   what you typed survive; the rest are removed. (Replaces Choices' too-loose fuzzy match.)
4. **Best-match targeting** — the highlighted row is the first that **starts with** the query,
   else the first that **contains** it, else the first row. Uses Choices' own `_highlightChoice`
   so arrow-keys / Enter stay in sync with the visual highlight.
5. **Inline autocomplete** — the input is filled with the target's full label and the
   *un-typed remainder is selected*, so the next keystroke overwrites it. Skipped on
   Backspace/Delete, and only when the target actually starts with the typed text.
6. **Bold matched run** — the matched substring is wrapped in `<strong>` inside each option,
   rebuilt with text nodes (never `innerHTML`), so it stays XSS-safe.
7. **No-results notice** — when nothing matches, shows a single "No results found" while keeping
   the add-action reachable (you usually want to *add* something precisely when nothing matched).
8. **Pinned add-action** (optional `addAction`) — an "➕ Add …" entry kept at the **top** of the
   list and **always reachable**: when the filter would drop it, a clickable fallback is injected.
   Selecting it runs your `onSelect` and **restores the previous value**, so the picker never gets
   stuck on the sentinel option.
9. **Returns the Choices instance** — callers use `setChoices` / `setChoiceByValue` etc.

---

## API

```js
const choices = initSearchSelect(selectEl, {
  choicesOptions: { searchResultLimit: 50 },          // merged OVER the defaults
  addAction: {                                        // optional
    value: '__add_vendor__',                          // sentinel <option> value
    label: '➕ Add Vendor…',
    onSelect: openModal,                              // run when chosen
  },
});
```

- `choicesOptions` — any extra Choices config; merged over the defaults via `Object.assign`.
  **This is the extension point** for display variations (see below).
- `addAction` — pin an add-new entry. The sentinel `<option>` is inserted right after the
  placeholder before Choices reads the select.

---

## Variations

### A. No code column (plain labels)
Pickers like **Payment Terms** have label-only options. Nothing special needed — just call
`initSearchSelect(sel)` (or even plain `new Choices` if you don't need the typeahead). Ordering,
filtering, bold, and autocomplete all operate on the label text.

### B. Selected chip differs from the dropdown (the VT/WT "code-only" tag)
The line-item **VAT** and **Withholding Tax** pickers show `CODE — Name` in the dropdown but
collapse to **CODE only** once selected (to fit the narrow column). This is a Choices template
override, passed through `choicesOptions`:

```js
const choices = initSearchSelect(sel, {
  choicesOptions: {
    searchResultLimit: 50,
    callbackOnCreateTemplates: function (tmpl) {
      return {
        // `item` = the SELECTED chip; `choice` = a DROPDOWN row (left default → full label).
        item: function (cfg, data) {
          const cn = cfg.classNames;
          const code = (data.customProperties && data.customProperties.code) || data.value || '—';
          return tmpl(`<div class="${cn.item} ${data.highlighted ? cn.highlightedState : cn.itemSelectable}"
                            data-item data-id="${data.id}" data-value="${data.value}"
                            ${data.active ? 'aria-selected="true"' : ''}
                            ${data.disabled ? 'aria-disabled="true"' : ''}>${code}</div>`);
        }
      };
    }
  }
});
```

- Each `<option>` must carry the code in `customProperties` (Choices reads `data-custom-properties`
  on the option, or you pass it via `setChoices`). The dropdown keeps the full `CODE — Name`
  label so typeahead still matches on both code and name.
- Override `choice` too if you also want the dropdown rows to render differently.
- **Note:** today the line-item VT/WT selects in `accounts_payable/form.html` call
  `new Choices(sel, codeOnlyOpts)` **directly** (the `codeOnlyOpts` object), so they get the
  code-only chip but **not** the shared typeahead. To get both, route them through
  `initSearchSelect` with the template in `choicesOptions`. (Tracked as a unification follow-up.)

---

## Caller responsibilities & gotchas

- **Load order:** `choices.min.css` + `choices.min.js`, then `search-select.js`, then your init.
- **Placeholder option:** the `<select>`'s first `<option value="">` is the placeholder; an
  `addAction` sentinel is inserted right after it.
- **`setChoiceByValue` does NOT fire a native `change`** on the underlying `<select>`. If page
  logic listens on the select (it usually does), dispatch it yourself:
  `selectEl.dispatchEvent(new Event('change', { bubbles: true }))`.
- **Choices strips the real `<option>`s** out of the native select (only the placeholder
  remains) and manages them internally. For tests / browser automation you **cannot** select by
  setting `select.value` — drive the Choices UI: click `.choices:has(#id) .choices__inner`, then
  click `.choices__list--dropdown .choices__item` by text. (See `tests/e2e/test_ap_smoke.py`.)
- **Regression coverage:** `search-select.js` is a high-blast-radius shared file. If you change
  it, `/guard` runs the AP e2e smoke. New shared pickers should be added to
  `.claude/regression-map.json` and ideally get e2e coverage.

---

## Related
- Implementation skill: `/search-select` (`.claude/skills/search-select/SKILL.md`)
- Memory: `search-select-pattern` (older Choices convention), `project-search-select` (history),
  `project-regression-guard` (e2e + the Choices-strips-options gotcha).
