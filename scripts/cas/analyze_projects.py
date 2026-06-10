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

    def analyze(self) -> Dict:
        """Run full analysis on project."""
        return {
            "name": self.project_name,
            "path": str(self.project_path),
            "type": self.detect_type(),
            "files": self.count_files(),
            "loc": self.count_loc(),
            "routes": self.find_routes(),
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

    for p in projects:
        analyzer = ProjectAnalyzer(p)
        result = analyzer.analyze()
        files = result["files"]
        loc = result["loc"]
        routes = result["routes"]

        print(f"{result['name']} ({result['type']})")
        print(f"  Files: {files['total']} total, {files['source']} source")
        print(f"  LOC: {loc['loc']} lines")
        print(f"  Routes: {len(routes)} found")
        if routes:
            print(f"    Sample: {', '.join(routes[:3])}")
        print()


if __name__ == "__main__":
    main()
