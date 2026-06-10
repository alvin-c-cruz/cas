# Code Metrics Comparative Dashboard — Design Spec

**Date:** 2026-06-10  
**Status:** Approved  
**Use Case:** Compare project complexity and structure across all 10 projects in C:\envs

---

## Executive Summary

Build a standalone Python script and HTML dashboard that analyzes all 10 projects under C:\envs and generates a comparative code metrics report. The report visualizes LOC, file counts, routes, dependencies, and code quality metrics in a single interactive HTML page for quick project comparison.

---

## Scope

**In scope:**
- Analyze 10 projects: accounting, accounting_philgen, accounting_ultimate, cas, inventory_program, LTV, philgen_flask, rowell_indutrial_flask, sales_invoice, the_health_collective_inc
- Collect metrics: LOC, file counts, routes, dependencies, test coverage, languages, directories
- Generate sortable HTML table with charts (bar, pie)
- Detect project types (Flask, Node.js, Django, etc.)

**Out of scope:**
- Running full linters or security scans
- Tracking git history or commit metrics
- Real-time monitoring or dashboards
- Integration into any CI/CD pipeline

---

## Architecture

### High-Level Flow

```
1. Script discovers all projects in C:\envs
2. For each project:
   a. Detect project type (Flask/Node/Django/etc.) via marker files
   b. Count files (excluding junk: node_modules, .venv, __pycache__, .git, .pytest_cache)
   c. Count lines of code (LOC) using cloc or manual counting
   d. Find routes/endpoints via grep (Flask @app.route, Express app.get/post, etc.)
   e. Parse dependencies (requirements.txt, package.json)
   f. Detect test files and estimate coverage if available
   g. Count models, templates, controllers
3. Aggregate all data into a dict
4. Generate interactive HTML report with:
   - Sortable summary table
   - Bar chart (LOC by project)
   - Bar chart (file count)
   - Bar chart (routes by project)
   - Pie chart (language distribution)
   - Click-to-expand project details
5. Output: projects_metrics.html (standalone, no external assets)
```

---

## Metrics Collected

| Category | Metric | Method | Example |
|----------|--------|--------|---------|
| **Size** | Total files | Directory walk | 240 |
| | Source files | Exclude junk dirs | 150 |
| | Lines of code (LOC) | cloc or line count | 8250 |
| | Blank lines | Track in LOC count | 890 |
| | Comment lines | Track in LOC count | 450 |
| **Structure** | Directories | Count subdirs | 25 |
| | Languages detected | File extension scan | Python, HTML, CSS, JS |
| **Web** | Routes/endpoints | Grep `@app.route` / `app.get` | 34 |
| | Models | Count model files | 8 |
| | Templates | Count .html/.jsx files | 12 |
| **Dependencies** | Total packages | Parse requirements.txt / package.json | 18 |
| | Python packages | Count pip packages | 15 |
| | Node packages | Count npm packages | 3 |
| **Testing** | Test files | Count test_*.py, *.test.js | 12 |
| | Test LOC | Sum LOC in test files | 1200 |
| **Code Quality** | Cyclomatic complexity | Optional (radon for Python) | Average 3.2 |

---

## HTML Report Structure

### Page Layout

**Single-page, responsive design with:**

1. **Header**
   - Title: "Code Metrics Comparative Dashboard"
   - Generation timestamp
   - Projects analyzed count
   - Last updated

2. **Summary Table** (sortable, filterable)
   - Rows: projects (alphabetically or by LOC)
   - Columns: LOC, Files, Routes, Dependencies, Languages, Test Files, Code Quality Score
   - Click row to expand details

3. **Charts** (using Chart.js, inline)
   - LOC by Project (horizontal bar chart)
   - File Count by Project (vertical bar chart)
   - Routes by Project (vertical bar chart)
   - Language Distribution (pie chart)
   - Dependencies by Project (bubble or bar)

4. **Project Details Panel** (expandable)
   - Shows when user clicks a project row
   - Breakdown: files by language, directory structure, routes list, dependencies, test coverage, notes

5. **Footer**
   - Script version, analysis date
   - Any warnings (e.g., "cloc not found, using line-count fallback")

---

## Implementation Details

### Script: `analyze_projects.py`

**Class: `ProjectAnalyzer`**
```python
class ProjectAnalyzer:
    def __init__(self, project_path)
    def detect_type() -> str              # Returns "Flask", "Node", "Django", "Unknown"
    def count_files() -> dict             # Returns {total, source, by_extension}
    def count_loc() -> dict               # Returns {loc, blank_lines, comment_lines}
    def find_routes() -> list             # Returns list of route strings
    def parse_dependencies() -> list      # Returns list of package names
    def count_tests() -> dict             # Returns {test_files, test_loc}
    def analyze() -> dict                 # Runs all above, returns aggregated metrics
```

**Class: `HTMLReporter`**
```python
class HTMLReporter:
    def __init__(self, project_metrics: list[dict])
    def generate_table() -> str           # Returns HTML table
    def generate_charts() -> str          # Returns Chart.js code
    def render(output_path: str)          # Writes standalone HTML file
```

**Main script:**
```python
def main():
    projects = discover_projects(r"C:\envs")
    metrics = []
    for project in projects:
        analyzer = ProjectAnalyzer(project)
        metrics.append(analyzer.analyze())
    reporter = HTMLReporter(metrics)
    reporter.render("projects_metrics.html")
    print(f"Report generated: projects_metrics.html ({len(projects)} projects analyzed)")
```

### Dependencies

**Required:**
- Python 3.8+
- Built-ins: os, re, json, subprocess, datetime

**Optional (graceful fallback if not found):**
- `cloc` (external tool for accurate LOC counting) — if not available, use line-by-line counting
- `radon` (Python code complexity) — if not available, skip complexity metrics

### Detection Logic

**Flask projects:** Marker files = `app.py`, `flask_app.py`, or `requirements.txt` containing `flask`  
**Node projects:** Marker files = `package.json`, `server.js`, `index.js`  
**Django projects:** Marker files = `manage.py`, `requirements.txt` containing `django`  
**Unknown:** If no markers found, treat as generic project

### Route Detection

**Flask:** Grep for `@app.route(`, `@bp.route(`, `@[a-z_]+.route(`  
**Express (Node):** Grep for `app.get(`, `app.post(`, `app.put(`, `app.delete(`, `router.get(`, etc.  
**Django:** Grep for `path(`, `url(` in urls.py files  
**Generic:** Fall back to counting HTTP verb patterns

### File Exclusion List

Exclude from analysis:
- `.git`, `.github`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.pytest_cache`
- `.pyc`, `.o`, `.exe`, `.zip`, `.tar.gz`
- Build dirs: `dist`, `build`, `coverage`
- IDEs: `.vscode`, `.idea`, `.DS_Store`

---

## Testing

**Manual validation:**
- Run script on each of the 10 projects
- Verify LOC counts match cloc (spot-check 2-3 projects)
- Verify route counts by manual inspection of code
- Check HTML renders in browser (Chrome, Firefox, Safari, mobile)
- Validate sorting and charts work interactively

**No automated tests needed** (script is one-off analysis tool, not library).

---

## Success Criteria

- [ ] Script runs without errors on all 10 projects
- [ ] HTML report loads and displays in browser (standalone, no external CDN)
- [ ] Summary table shows all 10 projects with all metrics
- [ ] Charts render correctly and are responsive
- [ ] Sorting/filtering works in the summary table
- [ ] Click-to-expand project details works
- [ ] Report generation completes in < 10 seconds
- [ ] User can compare project complexity at a glance

---

## Deliverables

1. `scripts/cas/analyze_projects.py` — Main analysis script
2. `projects_metrics.html` — Generated report (output, not checked in)
3. `docs/superpowers/plans/2026-06-10-code-metrics-implementation.md` — Implementation plan (optional)

---

## Notes

- Script is designed to be re-runnable — user can run it anytime to get fresh metrics
- HTML output is a single, standalone file (includes Chart.js inline)
- No database or configuration needed — point it at C:\envs and run
- Future: could be extended to track metrics over time or integrate into a CI pipeline
