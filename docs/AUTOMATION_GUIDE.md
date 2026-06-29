# Automation Guide: Code Analysis & Documentation

## Overview

This project includes automated systems for:
- **Code Analysis**: Detects project type, languages, and entry points
- **Cleanup**: Removes cache files, build artifacts, and IDE-specific configs  
- **Documentation**: Auto-generates README sections, CHANGELOG, and CONTRIBUTING.md

## How It Works

### GitHub Actions Workflow
Location: `.github/workflows/auto-analyze-cleanup-docs.yml`

**Runs automatically on:**
- Push to `main` branch
- Manual trigger via Actions tab

### Scripts

1. **auto_project_analyzer.py**: Analyzes project structure, detects language/type, removes junk files
2. **auto_doc_generator.py**: Creates/updates README, CHANGELOG, CONTRIBUTING.md, .gitignore
3. **cleanup_stale_docs.py**: Removes temporary/draft documentation files

## Running Manually

### Option 1: GitHub UI
1. Go to **Actions** tab
2. Click **Auto Analyze, Cleanup & Update Docs**
3. Click **Run workflow**

### Option 2: Local Command Line

```bash
# Install dependencies
pip install pathspec gitignore-parser pydantic pyyaml

# Run analyzer
python scripts/auto_project_analyzer.py

# Generate docs
python scripts/auto_doc_generator.py

# Clean stale docs
python scripts/cleanup_stale_docs.py
