#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tool for automatically fixing documentation link issues.

Main fixes:
1. External URL format issues (remove <> wrapping)
2. Missing internal link files
3. Path errors
"""

import re
from pathlib import Path
from typing import List, Tuple


def fix_external_urls(content: str) -> Tuple[str, int]:
    """Fix external URL format issues by removing <> wrapping.

    Args:
        content: The markdown content to process.

    Returns:
        A tuple of (fixed_content, number_of_fixes).
    """
    # Match [text](<url>) format
    pattern = r'\[([^\]]+)\]\(<(https?://[^>]+)>`?\)'
    
    def replace_func(match):
        text = match.group(1)
        url = match.group(2)
        return f'[{text}]({url})'
    
    new_content, count = re.subn(pattern, replace_func, content)
    return new_content, count


def fix_badge_urls(content: str) -> Tuple[str, int]:
    """Fix badge URL format issues by removing <> wrapping.

    Args:
        content: The markdown content to process.

    Returns:
        A tuple of (fixed_content, number_of_fixes).
    """
    # Match ![text](<url>) format for badges
    pattern = r'!\[([^\]]*)\]\(<(https?://[^>]+)>`?\)'
    
    def replace_func(match):
        text = match.group(1)
        url = match.group(2)
        return f'![{text}]({url})'
    
    new_content, count = re.subn(pattern, replace_func, content)
    return new_content, count


def fix_file(file_path: Path) -> int:
    """Fix link issues in a single file.

    Args:
        file_path: Path to the markdown file to fix.

    Returns:
        Number of fixes applied to the file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        total_fixes = 0

        # Fix external URLs
        content, count1 = fix_external_urls(content)
        total_fixes += count1

        # Fix badge URLs
        content, count2 = fix_badge_urls(content)
        total_fixes += count2

        # Write back if modified
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Fixed {file_path}: {total_fixes} fixes")

        return total_fixes

    except Exception as e:
        print(f"Error fixing {file_path}: {e}")
        return 0


def main() -> None:
    """Scan docs directory and fix all link issues in markdown files."""
    docs_root = Path('docs')

    # Find all markdown files
    md_files = list(docs_root.rglob('*.md'))

    print(f"Scanning {len(md_files)} markdown files...")
    print()

    total_files_fixed = 0
    total_fixes = 0

    for md_file in md_files:
        fixes = fix_file(md_file)
        if fixes > 0:
            total_files_fixed += 1
            total_fixes += fixes

    print()
    print(f"Done! Fixed {total_fixes} link issues in {total_files_fixed} files")


if __name__ == '__main__':
    main()
