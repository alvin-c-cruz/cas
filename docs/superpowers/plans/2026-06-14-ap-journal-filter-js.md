# AP Journal Filter — JavaScript Fetch + Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the AP Journal's full-page-reload filter with a JavaScript fetch + content swap so filtering never reloads the page.

**Architecture:** A single template file change — wrap the swappable region in `#ap-journal-content`, add `id="apExportLink"` to the Excel link, and replace the existing inline `<script>` with a new IIFE that intercepts form submit and toggle clicks, fetches the same URL, parses the returned HTML with DOMParser, and swaps only the content div in-place. URL bar is updated via `history.pushState`. Falls back to normal form submit on any fetch error.

**Tech Stack:** Vanilla JavaScript (no new dependencies), Jinja2 template, Flask (no server changes)

---

### Task 1: Wrap swappable region and update export link id

**Files:**
- Modify: `app/journals/templates/journals/ap_journal.html`

This is a pure HTML/template change — no JS yet. It sets up the stable DOM targets the JS will need.

- [ ] **Step 1: Add `id="ap-journal-content"` wrapper**

In `app/journals/templates/journals/ap_journal.html`, find the `ap-jrnl-meta` div (line ~75). Replace:

```html
    <div class="ap-jrnl-meta">
        <h3>Accounts Payable Journal</h3>
        <p>{{ period.label }} &mdash; {{ current_branch.name if current_branch else 'All Branches' }}</p>
    </div>

    <div class="card-body">
```

With:

```html
    <div id="ap-journal-content">
    <div class="ap-jrnl-meta">
        <h3>Accounts Payable Journal</h3>
        <p>{{ period.label }} &mdash; {{ current_branch.name if current_branch else 'All Branches' }}</p>
    </div>

    <div class="card-body">
```

And close the wrapper before `</div>` that closes the outer `.card` — find the last `</div>` after the empty-state block and add `</div>` before it:

```html
        {% endif %}
    </div>{# card-body #}
    </div>{# ap-journal-content #}
</div>{# card #}
```

- [ ] **Step 2: Add `id="apExportLink"` to the Excel download link**

Find (line ~39):

```html
            <a href="{{ url_for('journals.ap_journal_export', **request.args) }}" class="btn btn-primary btn-sm">Download Excel</a>
```

Replace with:

```html
            <a id="apExportLink" href="{{ url_for('journals.ap_journal_export', **request.args) }}" class="btn btn-primary btn-sm">Download Excel</a>
```

- [ ] **Step 3: Verify template renders correctly**

Navigate to `http://127.0.0.1:5000/journals/ap` in the browser and confirm:
- Page loads without errors
- Table still renders
- No visual change from the user's perspective

- [ ] **Step 4: Commit**

```
git add app/journals/templates/journals/ap_journal.html
git commit -m "refactor: wrap AP journal content in #ap-journal-content; id export link"
```

---

### Task 2: Replace inline script with fetch + swap IIFE

**Files:**
- Modify: `app/journals/templates/journals/ap_journal.html` — replace the `<script>` block at the bottom

- [ ] **Step 1: Replace the existing `<script>` block**

Find the current script block (lines ~149-159):

```html
<script>
(function () {
    var toggle = document.getElementById('toggleCustom');
    var mode = document.getElementById('apMode');
    if (!toggle) return;
    toggle.addEventListener('click', function () {
        mode.value = (mode.value === 'custom') ? 'month' : 'custom';
        document.getElementById('apFilter').submit();
    });
})();
</script>
```

Replace it entirely with:

```html
<script>
(function () {
    var form   = document.getElementById('apFilter');
    var toggle = document.getElementById('toggleCustom');
    var mode   = document.getElementById('apMode');
    if (!form || !toggle || !mode) return;

    function showFields(isCustom) {
        document.getElementById('monthFields').style.display = isCustom ? 'none' : '';
        document.getElementById('yearField').style.display   = isCustom ? 'none' : '';
        document.getElementById('fromField').style.display   = isCustom ? '' : 'none';
        document.getElementById('toField').style.display     = isCustom ? '' : 'none';
        toggle.textContent = isCustom ? 'Use month' : 'Custom range';
    }

    function fetchAndSwap(params) {
        var url = '/journals/ap?' + params.toString();
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (html) {
                var doc   = new DOMParser().parseFromString(html, 'text/html');
                var fresh = doc.getElementById('ap-journal-content');
                if (!fresh) throw new Error('no content');
                document.getElementById('ap-journal-content').replaceWith(fresh);
                var exportLink = document.getElementById('apExportLink');
                if (exportLink) exportLink.href = '/journals/ap/export?' + params.toString();
                history.pushState({}, '', url);
            })
            .catch(function () {
                /* fallback: let the browser do a normal GET */
                window.location.href = url;
            });
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        fetchAndSwap(new URLSearchParams(new FormData(form)));
    });

    toggle.addEventListener('click', function () {
        var isCustom = mode.value !== 'custom';
        mode.value = isCustom ? 'custom' : 'month';
        showFields(isCustom);
        fetchAndSwap(new URLSearchParams(new FormData(form)));
    });

    /* restore field visibility on back/forward navigation */
    window.addEventListener('popstate', function () {
        var params = new URLSearchParams(window.location.search);
        var isCustom = params.get('mode') === 'custom';
        mode.value = isCustom ? 'custom' : 'month';
        showFields(isCustom);
        fetchAndSwap(params);
    });
})();
</script>
```

- [ ] **Step 2: Manual verification — Filter button**

In the browser at `http://127.0.0.1:5000/journals/ap`:
- Change the month selector and click Filter
- Confirm: table updates, URL bar changes, sidebar does NOT re-render (no full reload)

- [ ] **Step 3: Manual verification — Custom range toggle**

- Click "Custom range" → month/year fields hide, date pickers appear, table refreshes
- Enter a custom date range and click Filter → table updates
- Click "Use month" → date pickers hide, month/year appear, table refreshes

- [ ] **Step 4: Manual verification — Excel link**

- Filter to a specific month → click Download Excel → confirm the downloaded file reflects that month, not the default period

- [ ] **Step 5: Manual verification — Back button**

- Filter to March 2026, then filter to April 2026
- Press browser Back → confirm URL changes to March params and table refreshes to March data

- [ ] **Step 6: Commit**

```
git add app/journals/templates/journals/ap_journal.html
git commit -m "feat: AP journal filter via JS fetch + swap — no full page reload"
```
