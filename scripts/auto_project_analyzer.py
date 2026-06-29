"""
Automated project analysis, cleanup, and documentation generation.
Runs on new project uploads to GitHub.
"""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, List, Set
import subprocess

class ProjectAnalyzer:
    def __init__(self, root_path: str = "."):
        self.root = Path(root_path)
        self.analysis = {
            "structure": {},
            "files_to_remove": [],
            "project_type": None,
            "languages": {},
            "entry_points": [],
            "dependencies": {},
        }

    def analyze_project_type(self) -> None:
        """Detect project type based on key files"""
        indicators = {
            "Python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
            "Node.js": ["package.json"],
            "Go": ["go.mod"],
            "Java": ["pom.xml", "build.gradle"],
            "Rust": ["Cargo.toml"],
            "Ruby": ["Gemfile"],
            "Docker": ["Dockerfile"],
        }
        
        for lang, files in indicators.items():
            if any((self.root / f).exists() for f in files):
                self.analysis["project_type"] = lang
                break

    def identify_useless_files(self) -> None:
        """Find and mark files for removal"""
        useless_patterns = {
            ".DS_Store": "macOS metadata",
            "thumbs.db": "Windows cache",
            "__pycache__": "Python cache",
            ".pytest_cache": "pytest cache",
            "node_modules": "npm dependencies (should be in .gitignore)",
            ".egg-info": "Python packaging artifacts",
            "*.pyc": "Compiled Python files",
            "dist/": "Build artifacts",
            "build/": "Build artifacts",
            ".idea/": "IDE settings",
            ".vscode/settings.json": "IDE-specific settings",
        }

        for pattern, reason in useless_patterns.items():
            for match in self.root.glob(pattern):
                if match.is_file() or match.is_dir():
                    self.analysis["files_to_remove"].append({
                        "path": str(match.relative_to(self.root)),
                        "reason": reason
                    })

    def detect_languages(self) -> None:
        """Detect programming languages used"""
        extensions = {}
        for ext in [".py", ".js", ".go", ".java", ".rs", ".rb", ".css", ".html"]:
            count = len(list(self.root.glob(f"**/*{ext}")))
            if count > 0:
                extensions[ext] = count
        
        self.analysis["languages"] = extensions

    def find_entry_points(self) -> None:
        """Identify main entry points"""
        entry_candidates = [
            ("main.py", "Python entry point"),
            ("app.py", "Python Flask/Dash app"),
            ("index.js", "Node.js entry point"),
            ("main.go", "Go entry point"),
            ("Main.java", "Java entry point"),
            ("Makefile", "Build/run instructions"),
        ]
        
        for filename, desc in entry_candidates:
            if (self.root / filename).exists():
                self.analysis["entry_points"].append(f"{filename} ({desc})")

    def cleanup_project(self) -> None:
        """Remove identified useless files"""
        for item in self.analysis["files_to_remove"]:
            path = self.root / item["path"]
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                    print(f"✓ Removed directory: {item['path']}")
                else:
                    path.unlink()
                    print(f"✓ Removed file: {item['path']}")
            except Exception as e:
                print(f"✗ Failed to remove {item['path']}: {e}")

    def run(self) -> Dict:
        """Execute full analysis"""
        print("🔍 Analyzing project...")
        self.analyze_project_type()
        self.detect_languages()
        self.find_entry_points()
        self.identify_useless_files()
        
        print("🧹 Cleaning up...")
        self.cleanup_project()
        
        # Save analysis report
        report_path = self.root / ".github" / "project_analysis.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(self.analysis, f, indent=2)
        
        print(f"✓ Analysis saved to {report_path}")
        return self.analysis

if __name__ == "__main__":
    analyzer = ProjectAnalyzer()
    analyzer.run()
