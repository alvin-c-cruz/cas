import os
import re
import json
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


def discover_projects(base_path: str) -> List[str]:
    """Discover all projects in base_path."""
    base = Path(base_path)
    projects = [d for d in base.iterdir() if d.is_dir()]
    return sorted([str(p) for p in projects])


def main():
    base_path = r"C:\envs"
    projects = discover_projects(base_path)
    print(f"Found {len(projects)} projects:\n")

    total_cost = 0
    for p in projects:
        analyzer = ProjectAnalyzer(p)
        result = analyzer.analyze()
        cost = result["cost"]

        print(f"{result['name']} ({result['type']})")
        print(f"  Complexity: {cost['complexity_score']}/10")
        print(f"  Effort: {cost['adjusted_hours']} hours")
        print(f"  Est. Cost: PHP {cost['total_cost_pesos']:,}")
        total_cost += cost['total_cost_pesos']
        print()

    print(f"TOTAL PORTFOLIO VALUE: PHP {total_cost:,}")


if __name__ == "__main__":
    main()
