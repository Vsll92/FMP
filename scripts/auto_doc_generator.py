"""
Automatically generate/update project documentation.
"""

import os
from pathlib import Path
from typing import List

class DocumentationGenerator:
    def __init__(self, root_path: str = "."):
        self.root = Path(root_path)
        self.readme_path = self.root / "README.md"

    def generate_structure_section(self) -> str:
        """Generate project structure documentation"""
        lines = ["## Project Structure\n"]
        lines.append("```")
        
        for item in sorted(self.root.iterdir()):
            if item.name.startswith('.') or item.name == '__pycache__':
                continue
            if item.is_dir():
                lines.append(f"{item.name}/")
            else:
                lines.append(f"{item.name}")
        
        lines.append("```\n")
        return "\n".join(lines)

    def generate_quick_start(self) -> str:
        """Generate Quick Start section based on detected project type"""
        lines = ["## Quick Start\n"]
        
        if (self.root / "requirements.txt").exists():
            lines.extend([
                "### Python Setup\n",
                "```bash",
                "python -m venv venv",
                "source venv/bin/activate  # Windows: venv\\Scripts\\activate",
                "pip install -r requirements.txt",
                "```\n"
            ])
        
        if (self.root / "package.json").exists():
            lines.extend([
                "### Node.js Setup\n",
                "```bash",
                "npm install",
                "npm start",
                "```\n"
            ])
        
        return "\n".join(lines)

    def generate_changelog_template(self) -> str:
        """Generate CHANGELOG.md template"""
        lines = [
            "# Changelog\n",
            "All notable changes documented here.\n",
            "## [Unreleased]\n",
            "### Added\n",
            "- \n",
            "### Changed\n",
            "- \n",
            "### Fixed\n",
            "- \n",
            "### Removed\n",
            "- \n"
        ]
        return "\n".join(lines)

    def update_readme(self) -> None:
        """Update or create README with generated sections"""
        if self.readme_path.exists():
            with open(self.readme_path, "r") as f:
                content = f.read()
        else:
            content = "# Project\n\nGenerated documentation\n\n"
        
        if "## Project Structure" not in content:
            content += self.generate_structure_section()
        
        if "## Quick Start" not in content:
            content += self.generate_quick_start()
        
        with open(self.readme_path, "w") as f:
            f.write(content)
        
        print(f"✓ Updated {self.readme_path}")

    def create_changelog(self) -> None:
        """Create CHANGELOG.md if it doesn't exist"""
        changelog_path = self.root / "CHANGELOG.md"
        if not changelog_path.exists():
            with open(changelog_path, "w") as f:
                f.write(self.generate_changelog_template())
            print(f"✓ Created {changelog_path}")

    def create_contributing_guide(self) -> None:
        """Create CONTRIBUTING.md template"""
        contributing_path = self.root / "CONTRIBUTING.md"
        if not contributing_path.exists():
            content = """# Contributing

## Getting Started
1. Fork the repository
2. Clone your fork
3. Create a feature branch
4. Make your changes
5. Write tests
6. Submit a pull request

## Code Standards
- Follow PEP 8 (Python)
- Add docstrings to functions and classes
- Write tests for new features
- Update documentation

## Pull Request Process
1. Update README.md with new features
2. Update CHANGELOG.md
3. Ensure tests pass
4. Get approval from maintainers
"""
            with open(contributing_path, "w") as f:
                f.write(content)
            print(f"✓ Created {contributing_path}")

    def create_gitignore_template(self) -> None:
        """Create or enhance .gitignore"""
        gitignore_path = self.root / ".gitignore"
        
        common_ignores = [
            "# Virtual environments",
            "venv/", "env/", ".env", ".venv",
            "",
            "# Python",
            "__pycache__/", "*.py[cod]", "*.so", ".Python",
            "build/", "dist/", "*.egg-info/", "*.egg",
            "",
            "# IDE",
            ".vscode/", ".idea/", "*.swp", "*.swo",
            "",
            "# OS",
            ".DS_Store", "Thumbs.db",
            "",
            "# Testing",
            ".pytest_cache/", ".coverage", "htmlcov/",
        ]
        
        if gitignore_path.exists():
            with open(gitignore_path, "r") as f:
                existing = f.read()
            if len(existing.strip()) < 50:
                with open(gitignore_path, "w") as f:
                    f.write("\n".join(common_ignores))
                print(f"✓ Enhanced .gitignore")
        else:
            with open(gitignore_path, "w") as f:
                f.write("\n".join(common_ignores))
            print(f"✓ Created .gitignore")

    def run(self) -> None:
        """Generate all documentation"""
        print("📝 Generating documentation...")
        self.update_readme()
        self.create_changelog()
        self.create_contributing_guide()
        self.create_gitignore_template()
        print("✓ Documentation generation complete")

if __name__ == "__main__":
    gen = DocumentationGenerator()
    gen.run()
