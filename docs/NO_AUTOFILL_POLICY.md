# No Autofill Policy

## Overview
This application has a strict **NO AUTOFILL** policy across all forms to ensure data security and prevent accidental data leakage from browser password managers and saved information.

## Implementation Guidelines

### 1. Global Form Attributes
All forms throughout the application must include:
```html
<form method="POST" novalidate autocomplete="off">
```

### 2. Individual Field Attributes
Every input field must have these attributes:
```html
autocomplete="new-password"
data-lpignore="true"
data-form-type="other"
```

### 3. Hidden Decoy Fields
Add hidden fields at the beginning of each form to catch autofill attempts:
```html
<input type="text" name="prevent_autofill" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">
<input type="password" name="prevent_password" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">
```

## Affected Forms

### ✅ Already Updated
- Login Form (`app/users/templates/users/login.html`)
- Vendor Create/Edit Form (`app/vendors/templates/vendors/form.html`)

### 🔄 To Be Updated
- Customer Create/Edit Form (`app/customers/templates/customers/form.html`)
- VAT Category Form (`app/vat_categories/templates/vat_categories/form.html`)
- Withholding Tax Form (`app/withholding_tax/templates/withholding_tax/form.html`)
- User Registration Form (`app/users/templates/users/register.html`)
- User Management Forms (`app/users/templates/users/`)
- All other forms in the application

## Why This Policy?

1. **Security**: Prevents sensitive financial data from being stored in browsers
2. **Privacy**: Stops personal/company information from appearing in shared computers
3. **Accuracy**: Ensures users enter current, correct data rather than outdated saved info
4. **Compliance**: Helps meet data protection requirements for financial systems
5. **OneDrive Compatibility**: Prevents creation of problematic filenames like "nul"

## Testing Checklist

When testing forms, verify:
- [ ] No "Saved info" dropdown appears
- [ ] No email addresses are auto-suggested
- [ ] No passwords are auto-filled
- [ ] No personal information is auto-completed
- [ ] Browser password managers don't activate
- [ ] LastPass and similar extensions ignore the fields

## Code Example

### Flask-WTF Template (Jinja2)
```jinja2
<form method="POST" novalidate autocomplete="off">
    {{ form.hidden_tag() }}

    <!-- Hidden decoy fields -->
    <input type="text" name="prevent_autofill" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">
    <input type="password" name="prevent_password" style="position:absolute;top:-9999px;left:-9999px;" autocomplete="off" tabindex="-1" aria-hidden="true">

    <!-- Regular form fields -->
    {{ form.field_name(class="form-control", autocomplete="new-password", **{'data-lpignore': 'true', 'data-form-type': 'other'}) }}
</form>
```

## Browser Compatibility

This approach works with:
- Chrome/Edge (Chromium-based)
- Firefox
- Safari
- Opera

## Maintenance

Regularly audit new forms and updates to ensure they comply with this policy. Any new form added to the application must follow these guidelines.

## Last Updated
June 2, 2026