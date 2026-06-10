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

    def analyze(self) -> Dict:
        """Run full analysis on project."""
        return {
            "name": self.project_name,
            "path": str(self.project_path),
            "type": self.detect_type(),
        }


def discover_projects(base_path: str) -> List[str]:
    """Discover all projects in base_path."""
    base = Path(base_path)
    projects = [d for d in base.iterdir() if d.is_dir()]
    return sorted([str(p) for p in projects])


def main():
    base_path = r"C:\envs"
    projects = discover_projects(base_path)
    print(f"Found {len(projects)} projects:")
    for p in projects:
        analyzer = ProjectAnalyzer(p)
        result = analyzer.analyze()
        print(f"  - {result['name']} ({result['type']})")


if __name__ == "__main__":
    main()
