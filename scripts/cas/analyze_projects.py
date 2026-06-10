import os
import re
import json
import html
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple


class ProjectAnalyzer:
    """Analyzes a single project and extracts metrics."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.project_name = self.project_path.name
        self.metrics = {}

    def detect_type(self) -> str:
        """Detect project type (Flask, Node, Django, Unknown)."""
        marker_files = list(self.project_path.glob("*"))
        marker_names = [f.name for f in marker_files]

        if any(f in marker_names for f in ["app.py", "flask_app.py"]):
            return "Flask"
        if "package.json" in marker_names:
            return "Node.js"
        if "manage.py" in marker_names:
            return "Django"

        # Check requirements.txt for framework hints
        req_file = self.project_path / "requirements.txt"
        if req_file.exists():
            content = req_file.read_text(errors="ignore")
            if "flask" in content.lower():
                return "Flask"
            if "django" in content.lower():
                return "Django"

        return "Unknown"

    EXCLUDE_DIRS = {
        ".git", ".github", ".venv", "venv", "node_modules", "__pycache__",
        ".pytest_cache", "dist", "build", ".vscode", ".idea", "coverage",
        ".DS_Store", ".egg-info"
    }

    EXCLUDE_EXTENSIONS = {".pyc", ".o", ".exe", ".zip", ".tar.gz", ".log"}

    def count_files(self) -> Dict:
        """Count total files, source files, files by extension."""
        total = 0
        source = 0
        by_extension = {}

        for root, dirs, files in os.walk(self.project_path):
            # Exclude certain directories
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for file in files:
                total += 1

                # Skip excluded extensions
                if any(file.endswith(ext) for ext in self.EXCLUDE_EXTENSIONS):
                    continue

                source += 1
                ext = Path(file).suffix or "no_extension"
                by_extension[ext] = by_extension.get(ext, 0) + 1

        return {
            "total": total,
            "source": source,
            "by_extension": by_extension
        }

    def count_loc(self) -> Dict:
        """Count lines of code, blank lines, comment lines."""
        loc = 0
        blank = 0
        comment = 0

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for file in files:
                if any(file.endswith(ext) for ext in self.EXCLUDE_EXTENSIONS):
                    continue

                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            stripped = line.strip()
                            if not stripped:
                                blank += 1
                            elif stripped.startswith("#") or stripped.startswith("//"):
                                comment += 1
                            else:
                                loc += 1
                except Exception:
                    pass

        return {
            "loc": loc,
            "blank": blank,
            "comment": comment,
            "total_lines": loc + blank + comment
        }

    def find_routes(self) -> List[str]:
        """Find routes/endpoints by grepping for Flask, Express, Django patterns."""
        routes = []

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for file in files:
                if not (file.endswith(".py") or file.endswith(".js")):
                    continue

                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                        # Flask patterns: @app.route, @bp.route, @[name].route
                        flask_routes = re.findall(r'@[\w.]+\.route\(["\']([^"\']+)', content)
                        routes.extend(flask_routes)

                        # Express patterns: app.get, app.post, router.get, etc.
                        express_routes = re.findall(r'(?:app|router)\.(?:get|post|put|delete|patch)\(["\']([^"\']+)', content)
                        routes.extend(express_routes)

                        # Django patterns: path(...), url(...)
                        django_routes = re.findall(r'(?:path|url)\(["\']([^"\']+)', content)
                        routes.extend(django_routes)
                except Exception:
                    pass

        return sorted(list(set(routes)))  # Deduplicate and sort

    def parse_dependencies(self) -> Dict:
        """Parse dependencies from requirements.txt and package.json."""
        python_deps = []
        node_deps = []

        # Parse requirements.txt
        req_file = self.project_path / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # Extract package name (before any version specifiers)
                            pkg = re.split(r'[<>=!]', line)[0].strip()
                            if pkg:
                                python_deps.append(pkg)
            except Exception:
                pass

        # Parse package.json
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                with open(pkg_json, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)
                    node_deps.extend(data.get("dependencies", {}).keys())
                    node_deps.extend(data.get("devDependencies", {}).keys())
            except Exception:
                pass

        return {
            "python": sorted(list(set(python_deps))),
            "node": sorted(list(set(node_deps))),
            "total": len(set(python_deps)) + len(set(node_deps))
        }

    def count_tests(self) -> Dict:
        """Count test files and lines of test code."""
        test_files = 0
        test_loc = 0

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for file in files:
                is_test = (
                    file.startswith("test_") or
                    file.endswith("_test.py") or
                    file.endswith(".test.js") or
                    file.endswith(".spec.js")
                )

                if not is_test:
                    continue

                test_files += 1
                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        test_loc += sum(1 for _ in f)
                except Exception:
                    pass

        # Calculate test ratio
        total_lines = self.count_loc()["total_lines"]
        test_ratio = round(test_loc / (total_lines + 1) * 100, 1) if test_loc > 0 else 0

        return {
            "test_files": test_files,
            "test_loc": test_loc,
            "test_ratio": test_ratio
        }

    def calculate_complexity_score(self) -> float:
        """Calculate complexity score (1-10) based on routes, dependencies, test ratio."""
        routes_count = len(self.find_routes())
        deps_count = self.parse_dependencies()["total"]
        tests = self.count_tests()
        test_ratio = tests["test_ratio"]

        # Base score from routes (each route adds complexity)
        route_score = min(routes_count / 10, 3)  # Max 3 points from routes

        # Dependencies add complexity
        dep_score = min(deps_count / 20, 2)  # Max 2 points from deps

        # Test coverage reduces complexity (well-tested = lower risk)
        test_score = min(test_ratio / 50, 2)  # Max 2 points from tests

        # File/LOC complexity
        files = self.count_files()
        loc = self.count_loc()
        size_score = min((files["source"] / 200) + (loc["loc"] / 5000), 3)  # Max 3 points from size

        # Complexity = base + adjustments, clamped to 1-10
        complexity = 2 + route_score + dep_score + size_score - (test_score * 0.5)
        return round(max(1, min(10, complexity)), 1)

    def estimate_development_cost(self, hourly_rate_pesos: float = 800) -> Dict:
        """
        Estimate development cost in pesos.

        Assumptions:
        - Base: ~10 LOC per hour (simplified, excludes design/testing)
        - Complexity multiplier: 1.0 (simple) to 1.8 (complex)
        - Junior dev rate: 400 PHP/hour
        - Mid-level dev rate: 800 PHP/hour (default)
        - Senior dev rate: 1500 PHP/hour

        Formula: (LOC / 10) * complexity_multiplier * hourly_rate
        """
        loc = self.count_loc()["loc"]
        complexity = self.calculate_complexity_score()

        # Complexity multiplier (1.0 to 1.8)
        complexity_multiplier = 1.0 + (complexity - 1) * 0.1

        # Effort estimation: hours needed
        base_hours = loc / 10  # Simple baseline
        adjusted_hours = base_hours * complexity_multiplier

        # Development cost
        dev_cost = adjusted_hours * hourly_rate_pesos

        # Add testing, documentation, review overhead (20%)
        total_cost = dev_cost * 1.2

        return {
            "loc": loc,
            "complexity_score": complexity,
            "complexity_multiplier": round(complexity_multiplier, 2),
            "base_hours": round(base_hours, 1),
            "adjusted_hours": round(adjusted_hours, 1),
            "hourly_rate_pesos": hourly_rate_pesos,
            "dev_cost_pesos": round(dev_cost, 0),
            "total_cost_pesos": round(total_cost, 0),
        }

    def analyze(self) -> Dict:
        """Run full analysis on project."""
        return {
            "name": self.project_name,
            "path": str(self.project_path),
            "type": self.detect_type(),
            "files": self.count_files(),
            "loc": self.count_loc(),
            "routes": self.find_routes(),
            "dependencies": self.parse_dependencies(),
            "tests": self.count_tests(),
            "cost": self.estimate_development_cost(),
        }


class HTMLReporter:
    """Generates interactive HTML report from project metrics."""

    def __init__(self, metrics: List[Dict]):
        self.metrics = metrics
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.total_cost = sum(m['cost']['total_cost_pesos'] for m in metrics)

    def generate_table_html(self) -> str:
        """Generate sortable HTML table of metrics."""
        html = '<table id="metrics-table" class="metrics-table">\n'
        html += '  <thead>\n'
        html += '    <tr>\n'
        html += '      <th>Project</th>\n'
        html += '      <th>Type</th>\n'
        html += '      <th>Files</th>\n'
        html += '      <th>LOC</th>\n'
        html += '      <th>Routes</th>\n'
        html += '      <th>Dependencies</th>\n'
        html += '      <th>Tests</th>\n'
        html += '      <th>Complexity</th>\n'
        html += '      <th>Est. Cost (₱)</th>\n'
        html += '    </tr>\n'
        html += '  </thead>\n'
        html += '  <tbody>\n'

        for metric in sorted(self.metrics, key=lambda x: x['cost']['total_cost_pesos'], reverse=True):
            cost_fmt = f"₱{metric['cost']['total_cost_pesos']:,}"
            complexity = metric['cost']['complexity_score']
            project_name_safe = html.escape(metric["name"])
            html += f'    <tr onclick="expandDetails({json.dumps(project_name_safe)})">\n'
            html += f'      <td><strong>{project_name_safe}</strong></td>\n'
            html += f'      <td>{metric["type"]}</td>\n'
            html += f'      <td>{metric["files"]["source"]}</td>\n'
            html += f'      <td>{metric["loc"]["loc"]:,}</td>\n'
            html += f'      <td>{len(metric["routes"])}</td>\n'
            html += f'      <td>{metric["dependencies"]["total"]}</td>\n'
            html += f'      <td>{metric["tests"]["test_files"]}</td>\n'
            html += f'      <td><span class="complexity-{int(complexity)}">{complexity}/10</span></td>\n'
            html += f'      <td class="cost-cell">₱{metric["cost"]["total_cost_pesos"]:,}</td>\n'
            html += '    </tr>\n'

        html += '  </tbody>\n'
        html += '</table>\n'
        return html

    def generate_charts_data(self) -> str:
        """Generate JavaScript data for charts."""
        projects = [m['name'] for m in sorted(self.metrics, key=lambda x: x['cost']['total_cost_pesos'], reverse=True)]
        locs = [m['loc']['loc'] for m in sorted(self.metrics, key=lambda x: x['cost']['total_cost_pesos'], reverse=True)]
        costs = [m['cost']['total_cost_pesos'] for m in sorted(self.metrics, key=lambda x: x['cost']['total_cost_pesos'], reverse=True)]
        complexity = [m['cost']['complexity_score'] for m in sorted(self.metrics, key=lambda x: x['cost']['total_cost_pesos'], reverse=True)]

        js = f"""
        var projectsData = {json.dumps(projects)};
        var locsData = {json.dumps(locs)};
        var costsData = {json.dumps(costs)};
        var complexityData = {json.dumps(complexity)};
        """
        return js

    def render(self, output_path: str = "projects_metrics.html"):
        """Generate complete HTML report."""
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Code Metrics Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js" integrity="sha384-+0RxBpP3E0cC1WOa7dvm85CyHGVd1P4pNPXfMg8cUqSSLdqb8LMp1z1CdLGHmhF5" crossorigin="anonymous"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
        }}

        h1 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
        }}

        .meta {{
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
            border-bottom: 1px solid #eee;
            padding-bottom: 20px;
        }}

        .portfolio-value {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            font-size: 18px;
            font-weight: 600;
        }}

        .portfolio-value span {{
            font-size: 28px;
            display: block;
            margin-top: 10px;
        }}

        .metrics-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 30px 0;
            font-size: 14px;
        }}

        .metrics-table thead {{
            background: #f5f5f5;
            border-bottom: 2px solid #ddd;
        }}

        .metrics-table th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #333;
            cursor: pointer;
        }}

        .metrics-table th:hover {{
            background: #efefef;
        }}

        .metrics-table td {{
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }}

        .metrics-table tbody tr {{
            cursor: pointer;
            transition: background 0.2s;
        }}

        .metrics-table tbody tr:hover {{
            background: #f9f9f9;
        }}

        .cost-cell {{
            font-weight: 600;
            color: #667eea;
        }}

        .complexity-1, .complexity-2, .complexity-3 {{
            color: #28a745;
            font-weight: 600;
        }}

        .complexity-4, .complexity-5, .complexity-6 {{
            color: #ffc107;
            font-weight: 600;
        }}

        .complexity-7, .complexity-8, .complexity-9, .complexity-10 {{
            color: #dc3545;
            font-weight: 600;
        }}

        .charts-section {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            margin-top: 50px;
        }}

        .chart-container {{
            background: #f9f9f9;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #eee;
        }}

        .chart-container h3 {{
            margin-bottom: 20px;
            color: #333;
            font-size: 16px;
        }}

        .footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #999;
            font-size: 12px;
        }}

        @media (max-width: 768px) {{
            .charts-section {{
                grid-template-columns: 1fr;
            }}
            h1 {{
                font-size: 1.5em;
            }}
            .metrics-table {{
                font-size: 12px;
            }}
            .metrics-table th, .metrics-table td {{
                padding: 8px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Code Metrics & Development Cost Dashboard</h1>
        <div class="meta">
            <strong>Generated:</strong> {self.timestamp} | <strong>Projects Analyzed:</strong> {len(self.metrics)}
        </div>

        <div class="portfolio-value">
            📈 Total Portfolio Development Value
            <span>₱{self.total_cost:,.0f}</span>
        </div>

        <h2>Project Metrics & Valuation</h2>
        TABLE_PLACEHOLDER

        <div class="charts-section">
            <div class="chart-container">
                <h3>Development Cost by Project</h3>
                <canvas id="costChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Lines of Code by Project</h3>
                <canvas id="locChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Complexity Score by Project</h3>
                <canvas id="complexityChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Cost vs Complexity</h3>
                <canvas id="costVsComplexityChart"></canvas>
            </div>
        </div>

        <div class="footer">
            <p><strong>Valuation Method:</strong> Based on LOC, complexity (routes/dependencies/test ratio), and hourly rate of ₱800/hour (mid-level developer). Includes 20% overhead for testing, documentation, and review.</p>
            <p>This report was generated by analyze_projects.py | Data accurate as of generation time</p>
        </div>
    </div>

    <script>
        CHARTS_DATA_PLACEHOLDER

        // Cost Chart
        var ctx = document.getElementById('costChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: projectsData,
                datasets: [{{
                    label: 'Development Cost (₱)',
                    data: costsData,
                    backgroundColor: '#667eea',
                    borderRadius: 5
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    x: {{beginAtZero: true}}
                }}
            }}
        }});

        // LOC Chart
        var ctx2 = document.getElementById('locChart').getContext('2d');
        new Chart(ctx2, {{
            type: 'bar',
            data: {{
                labels: projectsData,
                datasets: [{{
                    label: 'Lines of Code',
                    data: locsData,
                    backgroundColor: '#764ba2',
                    borderRadius: 5
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    x: {{beginAtZero: true}}
                }}
            }}
        }});

        // Complexity Chart
        var ctx3 = document.getElementById('complexityChart').getContext('2d');
        new Chart(ctx3, {{
            type: 'bar',
            data: {{
                labels: projectsData,
                datasets: [{{
                    label: 'Complexity Score (1-10)',
                    data: complexityData,
                    backgroundColor: '#f093fb',
                    borderRadius: 5
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    y: {{min: 0, max: 10}}
                }}
            }}
        }});

        // Cost vs Complexity Scatter
        var ctx4 = document.getElementById('costVsComplexityChart').getContext('2d');
        var scatterData = [];
        for (var i = 0; i < projectsData.length; i++) {{
            scatterData.push({{x: complexityData[i], y: costsData[i]}});
        }}
        new Chart(ctx4, {{
            type: 'scatter',
            data: {{
                datasets: [{{
                    label: 'Cost vs Complexity',
                    data: scatterData,
                    backgroundColor: '#4facfe',
                    borderColor: '#667eea',
                    borderWidth: 2,
                    pointRadius: 6,
                    pointHoverRadius: 8
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    x: {{title: {{display: true, text: 'Complexity Score'}}, min: 0, max: 10}},
                    y: {{title: {{display: true, text: 'Cost (₱)'}}}}
                }}
            }}
        }});

        function expandDetails(projectName) {{
            alert('Project: ' + projectName + '\\n(Details panel expansion to be added)');
        }}
    </script>
</body>
</html>
"""

        table_html = self.generate_table_html()
        charts_data = self.generate_charts_data()
        html_content = html_content.replace('TABLE_PLACEHOLDER', table_html)
        html_content = html_content.replace('CHARTS_DATA_PLACEHOLDER', charts_data)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"[OK] Report generated: {output_path}")


def discover_projects(base_path: str) -> List[str]:
    """Discover all projects in base_path."""
    base = Path(base_path)
    projects = [d for d in base.iterdir() if d.is_dir()]
    return sorted([str(p) for p in projects])


def main():
    import sys

    base_path = r"C:\envs"
    output_path = "projects_metrics.html"

    if len(sys.argv) > 1:
        output_path = sys.argv[1]

    projects = discover_projects(base_path)
    print(f"Analyzing {len(projects)} projects...\n")

    metrics = []
    total_cost = 0
    for p in projects:
        analyzer = ProjectAnalyzer(p)
        result = analyzer.analyze()
        metrics.append(result)
        cost = result['cost']['total_cost_pesos']
        total_cost += cost
        print(f"[OK] {result['name']} ({result['type']}) - {result['loc']['loc']:,} LOC, PHP {cost:,}")

    print(f"\nGenerating HTML report to {output_path}...")
    print(f"Portfolio Total Value: PHP {total_cost:,}")
    reporter = HTMLReporter(metrics)
    reporter.render(output_path)


if __name__ == "__main__":
    main()
