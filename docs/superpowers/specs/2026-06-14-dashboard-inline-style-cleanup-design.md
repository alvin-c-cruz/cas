# Dashboard Inline Style Cleanup — Design Spec

**Date:** 2026-06-14
**Status:** Approved

## Goal

Remove all `style=""` attributes from `app/dashboard/templates/dashboard/index.html` and replace them with named CSS classes in `app/static/css/style.css`, using existing design tokens (CSS variables).

## Scope

- `app/dashboard/templates/dashboard/index.html` — template cleanup only
- `app/static/css/style.css` — new classes appended in a `/* Dashboard */` section

No other files touched. No model changes. No migration.

## New CSS Classes

All added to `style.css` under a `/* ─── Dashboard ───` section. They use existing `:root` tokens — no new hardcoded hex values.

### Hero Header

| Class | Purpose |
|---|---|
| `.dashboard-hero` | Outer `.card` — gradient bg (`--login-grad-start`/`--login-grad-end`), no border, white text |
| `.dashboard-hero-layout` | Inner flex row — `space-between`, `center`, `wrap`, `gap:16px` |
| `.dashboard-hero-title` | `<h2>` — `28px / 700 / white` |
| `.dashboard-hero-subtitle` | `<p>` — `14px / opacity 0.9` |
| `.dashboard-datepicker-wrap` | Glass container — `rgba(255,255,255,0.15)` bg, `backdrop-filter:blur(10px)`, `border-radius:8px`, padding |
| `.dashboard-datepicker-inner` | Column-flex wrapper for label + form, `align-items:flex-end`, `margin-right:8px` |
| `.dashboard-datepicker-label` | `<label>` — `11px / 600 / uppercase / letter-spacing / opacity 0.9` |
| `.dashboard-datepicker-form` | `<form>` — `display:flex; gap:8px; align-items:center` |
| `.dashboard-datepicker-input` | `<input type="date">` — white bg, semi-transparent border, dark text, `font-weight:600`, `width:160px` |
| `.dashboard-today-btn` | "Today" button — `rgba(255,255,255,0.25)` bg, white text, semi-transparent border, `white-space:nowrap` |

### Stat Grid

| Class | Purpose |
|---|---|
| `.stat-grid--2col` | Modifier on `.stat-grid` — overrides column count to `repeat(2,1fr)` |

### Charts

| Class | Purpose |
|---|---|
| `.dashboard-chart` | `<canvas>` — `max-height:300px` |

### Table Utilities

| Class | Purpose |
|---|---|
| `.text-right` | `text-align:right` |
| `.text-center` | `text-align:center` |
| `.font-mono` | `font-family:var(--mono)` |

## Template Changes Summary

- Hero card outer `<div class="card mb-4" style="...">` → `<div class="card mb-4 dashboard-hero">`
- All nested hero divs: inline styles → semantic class names from the table above
- Stat grid: `style="grid-template-columns:repeat(2,1fr)"` → `class="stat-grid stat-grid--2col"`
- Both `<canvas>` elements: `style="max-height:300px"` → `class="dashboard-chart"`
- Top customers/vendors table `<th>`/`<td>` cells: inline `text-align` / `font-family` → `.text-right`, `.text-center`, `.font-mono`

## Result

Zero `style=""` attributes remain in `index.html`. All values trace back to named classes whose values use `:root` design tokens where applicable.

## Not in Scope

- Fixing inline styles in `base.html` (e.g. the confirm modal, the hidden user menu — separate task)
- Renaming `--login-grad-start` / `--login-grad-end` to `--brand-grad-*` (possible future cleanup)
- Adding new dashboard data or restructuring layout
