# CAS - Computerized Accounting System

A professional Flask web application for managing financial accounting operations tailored for Philippine SMEs with BIR compliance features.

## Features

- **Chart of Accounts** - Manage your company's chart of accounts with hierarchical structure
- **Dashboard** - Real-time financial overview with key metrics
- **Modern UI** - Professional, responsive design with custom design system
- **Modular Architecture** - Blueprint-based modular structure for scalability
- **Form Validation** - Secure forms with Flask-WTF and CSRF protection
- **BIR Compliance** - Features designed for Philippine Bureau of Internal Revenue requirements

## Tech Stack

- **Backend:** Flask 3.1.0 (Python)
- **Database:** SQLAlchemy 2.0.36 with SQLite
- **Forms:** Flask-WTF 1.2.2 & WTForms 3.2.1
- **Templates:** Jinja2 3.1.4 with custom macros
- **Design:** Custom CSS design system

## Quick Start

```bash
# Clone and install
git clone <repository-url>
cd cas
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run application
python run.py

# Access at http://127.0.0.1:5000/
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guidelines
- [DESIGN.md](DESIGN.md) - Design system
- [STRUCTURE.md](STRUCTURE.md) - Architecture

## License

For internal use and development.
