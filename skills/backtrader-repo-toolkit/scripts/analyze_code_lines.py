#!/usr/bin/env python3
"""Code line count analysis script.

Analyzes code lines in a project, counting total lines, code lines, and blank
lines by file type and directory.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple


def should_skip(path: Path) -> bool:
    """Determine if a path should be skipped during analysis.

    Args:
        path: The path to check.

    Returns:
        True if the path should be skipped, False otherwise.
    """
    skip_dirs = {
        '.git', '__pycache__', '.pytest_cache', 'node_modules',
        '.venv', 'venv', 'env', '.env', 'dist', 'build',
        '.egg-info', '.tox', '.mypy_cache', '.ruff_cache',
        '.agents', '.claude', '.cursor', '.gemini', '.windsurf',
        '_bmad', '_bmad-output', '.benchmarks', '.kiro'
    }

    # Check if any part of the path is in the skip list
    for part in path.parts:
        if part in skip_dirs or part.startswith('.'):
            return True
    return False


def count_lines(file_path: Path) -> Tuple[int, int, int]:
    """Count lines in a file.

    Args:
        file_path: Path to the file to analyze.

    Returns:
        A tuple of (total_lines, code_lines, blank_lines).
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            total = len(lines)
            blank = sum(1 for line in lines if line.strip() == '')
            code = total - blank
            return total, code, blank
    except Exception as e:
        print(f"Warning: Unable to read file {file_path}: {e}")
        return 0, 0, 0


def analyze_project(root_dir: str = '.') -> Dict:
    """Analyze code lines in a project.

    Args:
        root_dir: Root directory of the project to analyze.

    Returns:
        A dictionary containing statistics by extension, directory, and totals.
    """
    root_path = Path(root_dir).resolve()

    stats = {
        'by_extension': defaultdict(lambda: {'files': 0, 'total': 0, 'code': 0, 'blank': 0}),
        'by_directory': defaultdict(lambda: {'files': 0, 'total': 0, 'code': 0, 'blank': 0}),
        'total': {'files': 0, 'total': 0, 'code': 0, 'blank': 0}
    }

    # Only count these code file types
    code_extensions = {
        '.py', '.pyx', '.pxd',  # Python
        '.js', '.jsx', '.ts', '.tsx',  # JavaScript/TypeScript
        '.java', '.kt',  # Java/Kotlin
        '.c', '.cpp', '.cc', '.h', '.hpp',  # C/C++
        '.go',  # Go
        '.rs',  # Rust
        '.rb',  # Ruby
        '.php',  # PHP
        '.swift',  # Swift
        '.m', '.mm',  # Objective-C
        '.sh', '.bash',  # Shell
        '.sql',  # SQL
        '.yaml', '.yml',  # YAML
        '.json',  # JSON
        '.xml',  # XML
        '.md',  # Markdown
        '.txt',  # Text
    }

    for file_path in root_path.rglob('*'):
        if not file_path.is_file():
            continue

        if should_skip(file_path.relative_to(root_path)):
            continue

        ext = file_path.suffix.lower()
        if ext not in code_extensions:
            continue

        total, code, blank = count_lines(file_path)

        if total == 0:
            continue

        # Count by extension
        stats['by_extension'][ext]['files'] += 1
        stats['by_extension'][ext]['total'] += total
        stats['by_extension'][ext]['code'] += code
        stats['by_extension'][ext]['blank'] += blank

        # Count by directory
        rel_path = file_path.relative_to(root_path)
        if len(rel_path.parts) > 1:
            top_dir = rel_path.parts[0]
        else:
            top_dir = '(root)'

        stats['by_directory'][top_dir]['files'] += 1
        stats['by_directory'][top_dir]['total'] += total
        stats['by_directory'][top_dir]['code'] += code
        stats['by_directory'][top_dir]['blank'] += blank

        # Totals
        stats['total']['files'] += 1
        stats['total']['total'] += total
        stats['total']['code'] += code
        stats['total']['blank'] += blank

    return stats


def print_stats(stats: Dict) -> None:
    """Print statistics report.

    Args:
        stats: Statistics dictionary from analyze_project().
    """
    print("=" * 80)
    print("Code Line Count Report")
    print("=" * 80)

    # Totals
    print("\n[Total]")
    print(f"Files: {stats['total']['files']:,}")
    print(f"Total lines: {stats['total']['total']:,}")
    print(f"Code lines: {stats['total']['code']:,}")
    print(f"Blank lines: {stats['total']['blank']:,}")

    # By file type
    print("\n[By File Type]")
    print(f"{'Type':<10} {'Files':>8} {'Total Lines':>12} {'Code Lines':>12} {'Blank Lines':>12}")
    print("-" * 80)

    sorted_ext = sorted(
        stats['by_extension'].items(),
        key=lambda x: x[1]['code'],
        reverse=True
    )

    for ext, data in sorted_ext:
        print(f"{ext:<10} {data['files']:>8,} {data['total']:>12,} "
              f"{data['code']:>12,} {data['blank']:>12,}")

    # By directory
    print("\n[By Directory]")
    print(f"{'Directory':<30} {'Files':>8} {'Total Lines':>12} {'Code Lines':>12} {'Blank Lines':>12}")
    print("-" * 80)

    sorted_dir = sorted(
        stats['by_directory'].items(),
        key=lambda x: x[1]['code'],
        reverse=True
    )

    for dir_name, data in sorted_dir:
        print(f"{dir_name:<30} {data['files']:>8,} {data['total']:>12,} "
              f"{data['code']:>12,} {data['blank']:>12,}")

    print("=" * 80)


if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    print(f"Analyzing directory: {Path(root).resolve()}\n")

    stats = analyze_project(root)
    print_stats(stats)
