"""
Remove stale/temporary documentation files.
"""

import os
from pathlib import Path

class StaleDocCleaner:
    def __init__(self, root_path: str = "."):
        self.root = Path(root_path)
        self.stale_patterns = [
            "*_TEMP.md",
            "*_OLD.md",
            "*_BACKUP.md",
            "*_DRAFT.md",
            "TODO_*.md",
            "WIP_*.md",
            "DEPRECATED_*.md",
        ]

    def find_stale_docs(self) -> list:
        """Find documentation files matching stale patterns"""
        stale_files = []
        for pattern in self.stale_patterns:
            stale_files.extend(self.root.glob(pattern))
        return stale_files

    def remove_stale_docs(self) -> None:
        """Remove identified stale documentation files"""
        stale_files = self.find_stale_docs()
        
        if not stale_files:
            print("✓ No stale documentation files found")
            return
        
        for file in stale_files:
            try:
                file.unlink()
                print(f"✓ Removed stale doc: {file.name}")
            except Exception as e:
                print(f"✗ Failed to remove {file.name}: {e}")

    def run(self) -> None:
        """Execute stale doc cleanup"""
        print("🧹 Cleaning up stale documentation...")
        self.remove_stale_docs()
        print("✓ Stale doc cleanup complete")

if __name__ == "__main__":
    cleaner = StaleDocCleaner()
    cleaner.run()
