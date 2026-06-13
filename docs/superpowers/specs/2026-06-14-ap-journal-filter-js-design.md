# AP Journal Filter — JavaScript Fetch + Swap Design Spec

**Date:** 2026-06-14  
**Status:** Approved

---

## Problem

The AP Journal filter (month/year selects, custom date range, Filter button, "Custom range" toggle) performs a full page reload on every interaction. This is jarring — the sidebar re-renders, scroll position resets, and the user loses context.

---

## Solution

Intercept filter interactions in JavaScript. Use `fetch()` to request the same `/journals/ap` URL with updated query params, parse the returned HTML, and swap only the journal content region in-place. No new server endpoint, no JSON API, no new dependency.

---

## Template Changes (`app/journals/templates/journals/ap_journal.html`)

### 1. Wrap the swappable region

Wrap `ap-jrnl-meta` and `card-body` in a single div with a stable ID:

```html
<div id="ap-journal-content">
    <div class="ap-jrnl-meta">...</div>
    <div class="card-body">...</div>
</div>
```

### 2. Download Excel link

The Excel export link currently bakes `request.args` at render time. After a JS filter, the args change but the link doesn't update. Add `id="apExportLink"` to it and update its `href` after each successful fetch.

### 3. JavaScript — replace the existing `<script>` block

Remove the current toggle script and replace with a single self-contained IIFE that handles:

**Filter button:** intercept `apFilter` form submit → build URLSearchParams from form data → `fetch()` → swap → `history.pushState()`.

**Custom range toggle:** intercept click → toggle `apMode` value and field visibility → trigger the same fetch-and-swap (no form submit).

**Swap logic:**
```js
const parser = new DOMParser();
const doc = parser.parseFromString(html, 'text/html');
const fresh = doc.getElementById('ap-journal-content');
document.getElementById('ap-journal-content').replaceWith(fresh);
```

**Export link update:** after each swap, rebuild the export href from current params:
```js
const exportLink = document.getElementById('apExportLink');
if (exportLink) exportLink.href = '/journals/ap/export?' + params.toString();
```

**URL bar update:**
```js
history.pushState({}, '', '/journals/ap?' + params.toString());
```

**Fallback:** wrap fetch in try/catch; on any error, fall back to `form.submit()` so the page still works without JS or on network failure.

---

## Behaviour Summary

| Interaction | Before | After |
|---|---|---|
| Click Filter | Full page reload | Fetch + content swap, URL updated |
| Click "Custom range" | Full page reload | Field visibility toggle + fetch + swap |
| Click "Use month" | Full page reload | Field visibility toggle + fetch + swap |
| Download Excel | Works (server-rendered href) | Works (href updated after each swap) |
| Print | Works | Works (print CSS unchanged) |
| No JS / network error | N/A | Falls back to normal form submit |

---

## No Server Changes

The `/journals/ap` view, `ap_journal_data.py`, and all tests are untouched. The server continues to return full HTML — JavaScript simply discards the chrome and splices in the content region.

---

## Testing

- Manual: filter by month, filter by custom range, toggle between modes — table updates without page reload, URL bar updates, back button restores previous filter
- Manual: Download Excel after a filter change — verify href reflects the current filter params
- Manual: disable JS — verify Filter button still works via normal form submit
