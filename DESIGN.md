# Design System Documentation

This document describes the visual design system for the CAS (Computerized Accounting System) application.

## Design Philosophy

The CAS design system emphasizes:
- **Professional** - Clean, business-appropriate aesthetic
- **Accessible** - High contrast, clear hierarchy
- **Consistent** - Predictable patterns across the application
- **Efficient** - Optimized for accounting workflows
- **Modern** - Contemporary web design patterns

## Color Palette

### Primary Colors

```css
--blue: #3b82f6;        /* Primary actions, links */
--green: #22c55e;       /* Success, revenue, credit */
--red: #ef4444;         /* Errors, liability, debit */
--amber: #f59e0b;       /* Warnings, expenses */
--purple: #8b5cf6;      /* Equity accounts */
```

### Neutral Colors

```css
--sidebar-bg: #0f172a;  /* Dark sidebar background */
--sidebar-text: #94a3b8;/* Sidebar text */
--bg: #f1f5f9;          /* Main background */
--card: #ffffff;        /* Card background */
--border: #e2e8f0;      /* Border color */
--text: #0f172a;        /* Primary text */
--text-2: #475569;      /* Secondary text */
--text-3: #94a3b8;      /* Tertiary text */
```

### Account Type Colors

Each account type has a dedicated color for visual distinction:

| Type      | Color   | Hex       | Usage                    |
|-----------|---------|-----------|--------------------------|
| Asset     | Blue    | `#3b82f6` | Asset accounts, badges   |
| Liability | Red     | `#ef4444` | Liability accounts       |
| Equity    | Purple  | `#8b5cf6` | Equity accounts          |
| Revenue   | Green   | `#22c55e` | Revenue accounts         |
| Expense   | Amber   | `#f59e0b` | Expense accounts         |

### Semantic Colors

```css
/* Success */
--success-bg: #dcfce7;
--success-text: #15803d;
--success-border: #22c55e;

/* Error */
--error-bg: #fee2e2;
--error-text: #dc2626;
--error-border: #ef4444;

/* Warning */
--warning-bg: #fef3c7;
--warning-text: #92400e;
--warning-border: #f59e0b;

/* Info */
--info-bg: #dbeafe;
--info-text: #1e40af;
--info-border: #3b82f6;
```

## Typography

### Font Family

```css
--font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--mono: 'Courier New', Courier, monospace;
```

**Inter** is loaded from Google Fonts with weights: 400, 500, 600, 700, 800

### Font Sizes

| Element           | Size  | Weight | Usage                        |
|-------------------|-------|--------|------------------------------|
| Page Title        | 24px  | 700    | Main page headings           |
| Section Title     | 18px  | 700    | Section headings             |
| Card Title        | 16px  | 600    | Card headers                 |
| Body Text         | 14px  | 400    | Standard text                |
| Small Text        | 13px  | 400    | Secondary information        |
| Form Labels       | 12px  | 700    | Form field labels            |
| Badges            | 11px  | 700    | Status badges, tags          |
| Metadata          | 11px  | 400    | Timestamps, auxiliary info   |

### Typography Utilities

```css
/* Uppercase labels */
text-transform: uppercase;
letter-spacing: 0.5px;

/* Monospace for numbers */
font-family: 'Courier New', monospace;
```

## Spacing System

Use multiples of 4px for consistent spacing:

```css
--spacing-1: 4px;
--spacing-2: 8px;
--spacing-3: 12px;
--spacing-4: 16px;
--spacing-5: 20px;
--spacing-6: 24px;
--spacing-8: 32px;
--spacing-10: 40px;
--spacing-12: 48px;
--spacing-16: 64px;
```

### Common Spacing Patterns

- Form field gap: `16px`
- Card padding: `24px`
- Section margin: `24px`
- Button padding: `10px 20px`
- Input padding: `10px 12px`

## Layout

### Sidebar Layout

```
┌─────────────┬────────────────────────────┐
│             │         Topbar (56px)       │
│   Sidebar   ├────────────────────────────┤
│   (266px)   │                            │
│   Fixed     │      Main Content          │
│             │      (with padding)        │
│             │                            │
└─────────────┴────────────────────────────┘
```

**Dimensions:**
- Sidebar width: `266px`
- Topbar height: `56px`
- Content padding: `24px`

### Grid System

```css
.grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; }
```

## Components

### Buttons

#### Primary Button
```css
background: #3b82f6;
color: white;
padding: 10px 20px;
border-radius: 6px;
font-size: 14px;
font-weight: 600;
```

#### Secondary Button
```css
background: #f1f5f9;
color: #64748b;
padding: 10px 20px;
border-radius: 6px;
font-size: 14px;
font-weight: 600;
```

#### Icon Button
```css
padding: 4px 8px;
border-radius: 4px;
background: transparent;
transition: background 0.15s;
```

### Cards

```css
background: white;
border: 1px solid #e2e8f0;
border-radius: 8px;
box-shadow: 0 1px 3px rgba(0,0,0,.08);
```

**Card Header:**
```css
padding: 16px 24px;
border-bottom: 1px solid #e2e8f0;
```

**Card Body:**
```css
padding: 24px;
```

### Forms

#### Input Fields
```css
padding: 10px 12px;
border: 1px solid #e2e8f0;
border-radius: 6px;
font-size: 14px;
transition: border-color 0.15s;
```

**Focus State:**
```css
border-color: #3b82f6;
box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
```

**Error State:**
```css
border-color: #ef4444;
```

#### Form Labels
```css
font-size: 12px;
font-weight: 700;
text-transform: uppercase;
letter-spacing: 0.5px;
color: #64748b;
margin-bottom: 6px;
```

### Badges

#### Account Type Badges

```css
.badge {
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.badge-asset {
    background: #dbeafe;
    color: #1e40af;
}

.badge-liability {
    background: #fee2e2;
    color: #991b1b;
}

.badge-equity {
    background: #ede9fe;
    color: #6b21a8;
}

.badge-revenue {
    background: #dcfce7;
    color: #15803d;
}

.badge-expense {
    background: #fef3c7;
    color: #92400e;
}
```

#### Status Badges

```css
.badge-draft { background: #f1f5f9; color: #64748b; }
.badge-submitted { background: #dbeafe; color: #1e40af; }
.badge-approved { background: #dcfce7; color: #15803d; }
.badge-pending { background: #fef3c7; color: #92400e; }
```

### Tables

```css
.table {
    width: 100%;
    border-collapse: collapse;
}

.table th {
    padding: 12px 16px;
    text-align: left;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #64748b;
    border-bottom: 2px solid #e2e8f0;
}

.table td {
    padding: 12px 16px;
    border-bottom: 1px solid #f1f5f9;
}

.table tbody tr:hover {
    background: #f8fafc;
}
```

### Alerts/Flash Messages

```css
.alert {
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 12px;
}

.alert-success {
    background: #dcfce7;
    color: #15803d;
    border: 1px solid #22c55e;
}

.alert-error {
    background: #fee2e2;
    color: #dc2626;
    border: 1px solid #ef4444;
}
```

### Modals

```css
.modal-overlay {
    background: rgba(0, 0, 0, 0.5);
    position: fixed;
    inset: 0;
    z-index: 1000;
}

.modal {
    background: white;
    border-radius: 8px;
    max-width: 640px;
    margin: 50px auto;
    box-shadow: 0 20px 50px rgba(0,0,0,0.3);
}

.modal-header {
    padding: 20px 24px;
    border-bottom: 1px solid #e2e8f0;
}

.modal-body {
    padding: 24px;
}

.modal-footer {
    padding: 16px 24px;
    border-top: 1px solid #e2e8f0;
}
```

## Sidebar Navigation

### Navigation Item

```css
.nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 20px;
    color: #94a3b8;
    border-left: 3px solid transparent;
    transition: background 0.15s, color 0.15s;
}

.nav-item:hover {
    background: #1e293b;
    color: #cbd5e1;
}

.nav-item.active {
    background: rgba(59, 130, 246, 0.15);
    color: #93c5fd;
    border-left-color: #3b82f6;
}
```

### Navigation Badge

```css
.nav-badge {
    margin-left: auto;
    background: #dc2626;
    color: white;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 20px;
}
```

## Effects & Animations

### Shadows

```css
--shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
--shadow-md: 0 4px 12px rgba(0,0,0,.12);
--shadow-lg: 0 10px 40px rgba(0,0,0,.15);
```

### Border Radius

```css
--radius: 8px;        /* Standard radius */
--radius-sm: 4px;     /* Small radius */
--radius-md: 6px;     /* Medium radius */
--radius-lg: 12px;    /* Large radius */
--radius-full: 9999px;/* Pill/circle */
```

### Transitions

```css
transition: all 0.15s ease;          /* General */
transition: background 0.15s ease;    /* Background only */
transition: border-color 0.15s ease;  /* Border only */
transition: transform 0.2s ease;      /* Transform */
```

### Hover States

- Buttons: Darken background by 1 shade
- Links: Change color to primary
- Cards: Add subtle shadow
- Sidebar items: Change background and text color

## Number Formatting

### Currency Display

```
Format: ₱1,234,567.89
Font: Courier New (monospace)
Alignment: Right-aligned
```

### Debit/Credit Indicators

```css
/* Debit */
color: #dc2626;  /* Red */
content: "Dr";

/* Credit */
color: #059669;  /* Green */
content: "Cr";
```

## Responsive Design

### Breakpoints

```css
/* Mobile */
@media (max-width: 640px) { ... }

/* Tablet */
@media (max-width: 768px) { ... }

/* Desktop */
@media (max-width: 1024px) { ... }

/* Large Desktop */
@media (max-width: 1280px) { ... }
```

### Mobile Considerations

- Sidebar should collapse to hamburger menu
- Tables should scroll horizontally
- Forms should stack vertically
- Touch targets minimum 44x44px

## Accessibility

### Color Contrast

All text meets WCAG AA standards:
- Normal text: 4.5:1 minimum
- Large text: 3:1 minimum

### Focus States

All interactive elements have visible focus indicators:
```css
outline: 2px solid #3b82f6;
outline-offset: 2px;
```

### Semantic HTML

- Use proper heading hierarchy (h1 → h2 → h3)
- Use semantic tags (`<nav>`, `<main>`, `<section>`)
- Add ARIA labels where needed
- Ensure keyboard navigation works

## Icons

Currently using emoji icons for simplicity:
- 📊 Dashboard
- 📋 Chart of Accounts
- 📓 Journal
- 📄 Invoices
- 💰 Payments
- 👥 Customers
- 🏢 Vendors
- ⚖ Logo

**Future:** Consider icon library like Heroicons or Font Awesome

## Best Practices

1. **Consistency** - Use design tokens (CSS variables)
2. **Spacing** - Use the 4px spacing system
3. **Colors** - Use semantic colors for meaning
4. **Typography** - Maintain hierarchy with sizes and weights
5. **Accessibility** - Ensure keyboard navigation and screen reader support
6. **Performance** - Minimize CSS, use CSS variables
7. **Mobile-first** - Design for mobile, enhance for desktop

## Design Checklist

When creating new components:

- [ ] Uses design tokens (CSS variables)
- [ ] Follows spacing system (multiples of 4px)
- [ ] Has proper focus states
- [ ] Works on mobile screens
- [ ] Meets color contrast requirements
- [ ] Uses semantic HTML
- [ ] Has hover/active states
- [ ] Follows typography scale
- [ ] Includes loading states (if applicable)
- [ ] Includes error states (if applicable)
- [ ] Documented in this file
