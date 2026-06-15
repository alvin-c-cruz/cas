# Print Access Settings — SV + CD

**Date:** 2026-06-14
**Scope:** Extend the company settings "Documents" section with `sv_print_access` and `cd_print_access`; add the CD gate; standardize the SV gate value name.

---

## Problem

- `sv_print_access` is already read in `sales_invoices/views.py` and checked in `detail.html`, but it is absent from `SETTINGS_KEYS`, `CompanySettingsForm`, and `seed_minimal()` — so it is permanently stuck at its `'posted_only'` fallback and cannot be changed through the UI.
- `cd_print_access` does not exist at all. The CDV Print button on `detail.html` is always visible regardless of document status.
- APV uses `'draft_and_posted'` while SV uses `'all'` for the same concept, causing a silent inconsistency.
- CR and JV do not yet have print routes; they are out of scope.

---

## Design

### 1. Shared print access choices

Both new settings use the same two values as APV:

| Value | Meaning |
|-------|---------|
| `posted_only` | Print visible only when status is `posted` (CDV) or `posted / partially_paid / paid` (SV) |
| `draft_and_posted` | Print visible for any non-voided, non-cancelled document |

Default for both: `posted_only`.

---

### 2. Settings layer

#### `company_settings/forms.py`

Add a shared `PRINT_ACCESS_CHOICES` constant (reuse for SV, CD, and future settings):

```python
PRINT_ACCESS_CHOICES = [
    ('posted_only',      'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]
```

Remove the existing `APV_PRINT_ACCESS_CHOICES` and replace its reference with `PRINT_ACCESS_CHOICES`.

Add two new `SelectField`s to `CompanySettingsForm`:

```python
sv_print_access = SelectField(
    'Sales Invoice Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
)
cd_print_access = SelectField(
    'CDV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
)
```

#### `company_settings/views.py` — `SETTINGS_KEYS`

Append after `'apv_print_access'`:

```python
'sv_print_access',
'cd_print_access',
```

#### `company_settings/templates/company_settings/form.html`

Change the Documents card grid from `settings-grid-2` to `settings-grid-3` and add the two new fields:

```html
<div class="settings-grid-3">
    {{ render_field(form.apv_print_access) }}
    {{ render_field(form.sv_print_access) }}
    {{ render_field(form.cd_print_access) }}
</div>
```

#### `app/seeds/seed_data.py` — `seed_minimal()`

Add two rows (count 15 → 17):

```python
{'key': 'sv_print_access', 'value': 'posted_only'},
{'key': 'cd_print_access', 'value': 'posted_only'},
```

Update docstring and print statement accordingly.

---

### 3. SV gate — value rename only

`sales_invoices/templates/sales_invoices/detail.html` line 109:

```diff
- or (sv_print_access == 'all' and invoice.status not in ('voided', 'cancelled')) %}
+ or (sv_print_access == 'draft_and_posted' and invoice.status not in ('voided', 'cancelled')) %}
```

No change to `sales_invoices/views.py` — it already reads `AppSettings.get_setting('sv_print_access', 'posted_only')` and passes the value through.

---

### 4. CD gate — new

#### `cash_disbursements/views.py` — `view()`

Read the setting in the detail view (mirrors the APV pattern) and pass it to `detail.html`:

```python
cd_print_access = AppSettings.get_setting('cd_print_access', 'posted_only')
return render_template('cash_disbursements/detail.html',
                       cdv=cdv, je_entries=je_entries, now=ph_now(),
                       cd_print_access=cd_print_access)
```

`print_cdv()` does not change — it renders the print template unconditionally, matching APV/SV behaviour.

#### `cash_disbursements/templates/cash_disbursements/detail.html` — Print button

Wrap the existing ungated Print link (line 76–77) with the access check:

```html
{% if (cd_print_access == 'posted_only' and cdv.status == 'posted')
   or (cd_print_access == 'draft_and_posted' and cdv.status not in ('voided', 'cancelled')) %}
<a href="{{ url_for('cash_disbursements.print_cdv', id=cdv.id) }}" target="_blank"
   rel="noopener noreferrer" class="btn btn-secondary">Print</a>
{% endif %}
```

The `print_cdv` view itself is not gated (navigating directly to the URL still renders). This matches APV/SV behaviour — the setting controls UI discoverability, not hard access.

`cd_print_access` does **not** need to be passed to `print.html` — the print template renders the document unconditionally; only the detail page button is gated.

---

## Files changed

| File | Change |
|------|--------|
| `app/company_settings/forms.py` | Add `PRINT_ACCESS_CHOICES`; replace `APV_PRINT_ACCESS_CHOICES`; add `sv_print_access`, `cd_print_access` fields |
| `app/company_settings/views.py` | Add `'sv_print_access'`, `'cd_print_access'` to `SETTINGS_KEYS` |
| `app/company_settings/templates/company_settings/form.html` | grid-2 → grid-3; add two `render_field` calls |
| `app/seeds/seed_data.py` | Add 2 seed rows; update count (15 → 17) |
| `app/sales_invoices/templates/sales_invoices/detail.html` | Rename `'all'` → `'draft_and_posted'` |
| `app/cash_disbursements/views.py` | Read `cd_print_access`; pass to template |
| `app/cash_disbursements/templates/cash_disbursements/detail.html` | Gate Print button with `cd_print_access` check |

**No model changes. No migration required.**

---

## Out of scope

- CR print access (no CR print route exists)
- JV print access (no JV print route exists)
- Hard-gating the print URL itself (consistent with existing APV/SV behaviour)
