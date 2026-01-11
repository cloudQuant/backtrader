#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze Python source files for missing docstrings and Chinese comments.

This script analyzes Python source files to identify:
1. Missing module-level docstrings
2. Missing class-level docstrings
3. Missing method/function docstrings
4. Chinese comments that need translation

Usage:
    # Check all Python files (excluding docs folder)
    python scripts/analyze_docstrings.py
    
    # Check specific file
    python scripts/analyze_docstrings.py backtrader/strategy.py
    
    # Check with verbose output
    python scripts/analyze_docstrings.py --verbose
    
    # Only show summary
    python scripts/analyze_docstrings.py --summary

Example output:
    === Analysis Report for strategy.py ===
    Total lines: 2530
    Suggested segments: 7 (each ~400 lines)

    [Missing Docstrings]
    - Module docstring: MISSING
    - Class 'Strategy' (line 45): MISSING
    - Method 'buy' (line 234): MISSING

    [Chinese Comments]
    - Line 123: # This is a Chinese comment
    - Line 456: # Calculate moving average
"""

import ast
import re
import sys
import argparse
import io
import os
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

# Fix Windows console encoding issue
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def find_python_files(root_dir: str, exclude_dirs: Optional[List[str]] = None) -> List[str]:
    """Find all Python files in the directory, excluding specified directories.
    
    Args:
        root_dir: Root directory to search.
        exclude_dirs: List of directory names to exclude.
        
    Returns:
        List of Python file paths.
    """
    if exclude_dirs is None:
        exclude_dirs = ['docs', '__pycache__', '.git', '.tox', 'build', 'dist', 
                        'egg-info', '.eggs', 'venv', 'env', 'node_modules']
    
    python_files = []
    root_path = Path(root_dir)
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Modify dirnames in-place to skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.endswith('.egg-info')]
        
        for filename in filenames:
            if filename.endswith('.py'):
                python_files.append(os.path.join(dirpath, filename))
    
    return sorted(python_files)


def quick_analyze(filepath: str) -> Dict[str, Any]:
    """Quickly analyze a file and return summary stats.
    
    Args:
        filepath: Path to the Python file.
        
    Returns:
        Dictionary with analysis summary.
    """
    try:
        total_lines = count_lines(filepath)
        ast_results = analyze_ast(filepath)
        chinese_comments = find_chinese_comments(filepath)
        
        if 'error' in ast_results:
            return {
                'filepath': filepath,
                'error': ast_results['error'],
                'total_lines': total_lines,
            }
        
        # Count missing docstrings
        missing_module = 0 if ast_results['module_docstring'] else 1
        
        public_classes = [c for c in ast_results['classes'] if c['is_public']]
        missing_classes = len([c for c in public_classes if not c['has_docstring']])
        
        important_dunders = {'__init__', '__new__', '__call__', '__enter__', '__exit__'}
        public_methods = [
            m for m in ast_results['methods'] 
            if m['is_public'] or m['name'] in important_dunders
        ]
        missing_methods = len([m for m in public_methods if not m['has_docstring']])
        
        public_functions = [f for f in ast_results['functions'] if f['is_public']]
        missing_functions = len([f for f in public_functions if not f['has_docstring']])
        
        total_missing = missing_module + missing_classes + missing_methods + missing_functions
        
        return {
            'filepath': filepath,
            'total_lines': total_lines,
            'missing_docstrings': total_missing,
            'chinese_comments': len(chinese_comments),
            'needs_work': total_missing > 0 or len(chinese_comments) > 0,
        }
    except Exception as e:
        return {
            'filepath': filepath,
            'error': str(e),
            'total_lines': 0,
        }


def count_lines(filepath: str) -> int:
    """Count total lines in a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return sum(1 for _ in f)


def find_chinese_comments(filepath: str) -> List[Tuple[int, str]]:
    """Find lines containing Chinese characters in comments.
    
    Args:
        filepath: Path to the Python file.
        
    Returns:
        List of tuples (line_number, line_content) containing Chinese.
    """
    chinese_pattern = re.compile(r'[\u4e00-\u9fa5]')
    chinese_lines = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            # Check if line contains Chinese characters
            if chinese_pattern.search(line):
                # Skip if it's inside a docstring (we handle those separately)
                stripped = line.strip()
                if stripped.startswith('#') or '"""' in line or "'''" in line:
                    chinese_lines.append((line_num, line.rstrip()))
                elif chinese_pattern.search(line):
                    # Could be inline comment or string
                    chinese_lines.append((line_num, line.rstrip()))
    
    return chinese_lines


def analyze_ast(filepath: str) -> Dict[str, Any]:
    """Analyze Python file AST for missing docstrings.
    
    Args:
        filepath: Path to the Python file.
        
    Returns:
        Dictionary containing analysis results.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {'error': f'Syntax error: {e}'}
    
    results = {
        'module_docstring': ast.get_docstring(tree) is not None,
        'classes': [],
        'functions': [],
        'methods': [],
    }
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            has_docstring = ast.get_docstring(node) is not None
            results['classes'].append({
                'name': node.name,
                'line': node.lineno,
                'has_docstring': has_docstring,
                'is_public': not node.name.startswith('_'),
            })
            
            # Check methods within the class
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                    method_has_docstring = ast.get_docstring(item) is not None
                    results['methods'].append({
                        'name': item.name,
                        'class': node.name,
                        'line': item.lineno,
                        'has_docstring': method_has_docstring,
                        'is_public': not item.name.startswith('_'),
                        'is_dunder': item.name.startswith('__') and item.name.endswith('__'),
                    })
        
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # Top-level functions only
            if hasattr(node, 'col_offset') and node.col_offset == 0:
                has_docstring = ast.get_docstring(node) is not None
                results['functions'].append({
                    'name': node.name,
                    'line': node.lineno,
                    'has_docstring': has_docstring,
                    'is_public': not node.name.startswith('_'),
                })
    
    return results


def suggest_segments(total_lines: int, lines_per_segment: int = 400) -> List[Tuple[int, int]]:
    """Suggest line segments for processing long files.
    
    Args:
        total_lines: Total number of lines in the file.
        lines_per_segment: Target lines per segment.
        
    Returns:
        List of (start_line, end_line) tuples.
    """
    if total_lines <= 500:
        return [(1, total_lines)]
    
    segments = []
    current = 1
    while current <= total_lines:
        end = min(current + lines_per_segment - 1, total_lines)
        segments.append((current, end))
        current = end + 1
    
    return segments


def generate_report(filepath: str, verbose: bool = False) -> str:
    """Generate analysis report for a Python file.
    
    Args:
        filepath: Path to the Python file.
        verbose: If True, include all items; if False, only missing items.
        
    Returns:
        Formatted report string.
    """
    path = Path(filepath)
    if not path.exists():
        return f"Error: File '{filepath}' not found."
    
    total_lines = count_lines(filepath)
    ast_results = analyze_ast(filepath)
    chinese_comments = find_chinese_comments(filepath)
    segments = suggest_segments(total_lines)
    
    report_lines = []
    report_lines.append(f"\n{'='*60}")
    report_lines.append(f"Analysis Report: {path.name}")
    report_lines.append(f"{'='*60}")
    report_lines.append(f"File path: {filepath}")
    report_lines.append(f"Total lines: {total_lines}")
    
    if total_lines > 500:
        report_lines.append(f"Suggested segments: {len(segments)}")
        report_lines.append("\nSegment plan:")
        for i, (start, end) in enumerate(segments, 1):
            report_lines.append(f"  - Segment {i}: lines {start}-{end}")
    else:
        report_lines.append("Processing mode: Single pass (file <= 500 lines)")
    
    # Check for errors
    if 'error' in ast_results:
        report_lines.append(f"\n[ERROR] {ast_results['error']}")
        return '\n'.join(report_lines)
    
    # Missing docstrings section
    report_lines.append(f"\n{'─'*40}")
    report_lines.append("[Missing Docstrings]")
    report_lines.append(f"{'─'*40}")
    
    missing_count = 0
    
    # Module docstring
    if not ast_results['module_docstring']:
        report_lines.append("❌ Module docstring: MISSING")
        missing_count += 1
    elif verbose:
        report_lines.append("✓ Module docstring: Present")
    
    # Classes
    public_classes = [c for c in ast_results['classes'] if c['is_public']]
    missing_classes = [c for c in public_classes if not c['has_docstring']]
    
    if missing_classes:
        report_lines.append(f"\nMissing class docstrings ({len(missing_classes)}):")
        for cls in missing_classes:
            report_lines.append(f"  ❌ Class '{cls['name']}' (line {cls['line']})")
            missing_count += 1
    elif verbose and public_classes:
        report_lines.append(f"\n✓ All {len(public_classes)} public classes have docstrings")
    
    # Methods - only public methods (excluding dunder methods except important ones)
    important_dunders = {'__init__', '__new__', '__call__', '__enter__', '__exit__'}
    
    public_methods = [
        m for m in ast_results['methods'] 
        if m['is_public'] or m['name'] in important_dunders
    ]
    missing_methods = [m for m in public_methods if not m['has_docstring']]
    
    if missing_methods:
        report_lines.append(f"\nMissing method docstrings ({len(missing_methods)}):")
        # Group by class
        by_class = {}
        for m in missing_methods:
            cls = m['class']
            if cls not in by_class:
                by_class[cls] = []
            by_class[cls].append(m)
        
        for cls, methods in by_class.items():
            report_lines.append(f"  Class '{cls}':")
            for m in methods[:10]:  # Limit to first 10 per class
                report_lines.append(f"    ❌ {m['name']}() (line {m['line']})")
                missing_count += 1
            if len(methods) > 10:
                report_lines.append(f"    ... and {len(methods) - 10} more")
                missing_count += len(methods) - 10
    elif verbose and public_methods:
        report_lines.append(f"\n✓ All {len(public_methods)} public methods have docstrings")
    
    # Functions
    public_functions = [f for f in ast_results['functions'] if f['is_public']]
    missing_functions = [f for f in public_functions if not f['has_docstring']]
    
    if missing_functions:
        report_lines.append(f"\nMissing function docstrings ({len(missing_functions)}):")
        for func in missing_functions:
            report_lines.append(f"  ❌ Function '{func['name']}' (line {func['line']})")
            missing_count += 1
    elif verbose and public_functions:
        report_lines.append(f"\n✓ All {len(public_functions)} public functions have docstrings")
    
    # Chinese comments section
    report_lines.append(f"\n{'─'*40}")
    report_lines.append("[Chinese Comments to Translate]")
    report_lines.append(f"{'─'*40}")
    
    if chinese_comments:
        report_lines.append(f"Found {len(chinese_comments)} lines with Chinese characters:")
        for line_num, content in chinese_comments[:20]:  # Limit display
            # Truncate long lines
            display = content[:80] + '...' if len(content) > 80 else content
            report_lines.append(f"  Line {line_num}: {display}")
        if len(chinese_comments) > 20:
            report_lines.append(f"  ... and {len(chinese_comments) - 20} more lines")
    else:
        report_lines.append("✓ No Chinese comments found")
    
    # Summary
    report_lines.append(f"\n{'─'*40}")
    report_lines.append("[Summary]")
    report_lines.append(f"{'─'*40}")
    report_lines.append(f"Missing docstrings: {missing_count}")
    report_lines.append(f"Chinese comments: {len(chinese_comments)}")
    
    if missing_count == 0 and len(chinese_comments) == 0:
        report_lines.append("\n✅ File is fully documented!")
    else:
        report_lines.append(f"\n⚠️  Total items to address: {missing_count + len(chinese_comments)}")
    
    report_lines.append(f"\n{'='*60}\n")
    
    return '\n'.join(report_lines)


def batch_analyze(root_dir: str, summary_only: bool = False, verbose: bool = False) -> None:
    """Analyze all Python files in a directory.
    
    Args:
        root_dir: Root directory to search.
        summary_only: If True, only show summary table.
        verbose: If True, show detailed reports for files needing work.
    """
    print(f"\n{'='*70}")
    print(f"Scanning Python files in: {root_dir}")
    print(f"{'='*70}")
    
    python_files = find_python_files(root_dir)
    print(f"Found {len(python_files)} Python files\n")
    
    # Quick analyze all files
    results = []
    for filepath in python_files:
        result = quick_analyze(filepath)
        results.append(result)
    
    # Separate files needing work
    needs_work = [r for r in results if r.get('needs_work', False)]
    has_errors = [r for r in results if 'error' in r]
    all_good = [r for r in results if not r.get('needs_work', False) and 'error' not in r]
    
    # Print summary table
    print(f"{'─'*70}")
    print(f"{'FILE SUMMARY':^70}")
    print(f"{'─'*70}")
    print(f"{'Status':<12} {'Count':>8}")
    print(f"{'─'*70}")
    print(f"{'✅ Good':<12} {len(all_good):>8}")
    print(f"{'⚠️  Needs work':<12} {len(needs_work):>8}")
    print(f"{'❌ Errors':<12} {len(has_errors):>8}")
    print(f"{'─'*70}")
    print(f"{'Total':<12} {len(results):>8}")
    print(f"{'─'*70}\n")
    
    # Show files needing work
    if needs_work:
        print(f"{'='*70}")
        print(f"FILES NEEDING OPTIMIZATION ({len(needs_work)} files)")
        print(f"{'='*70}")
        
        # Sort by total issues (most issues first)
        needs_work.sort(key=lambda x: x.get('missing_docstrings', 0) + x.get('chinese_comments', 0), reverse=True)
        
        # Print table header
        print(f"\n{'File':<50} {'Lines':>6} {'Missing':>8} {'Chinese':>8}")
        print(f"{'─'*70}")
        
        for r in needs_work:
            rel_path = os.path.relpath(r['filepath'], root_dir)
            if len(rel_path) > 48:
                rel_path = '...' + rel_path[-45:]
            print(f"{rel_path:<50} {r['total_lines']:>6} {r.get('missing_docstrings', 0):>8} {r.get('chinese_comments', 0):>8}")
        
        print(f"{'─'*70}")
        
        # Calculate totals
        total_missing = sum(r.get('missing_docstrings', 0) for r in needs_work)
        total_chinese = sum(r.get('chinese_comments', 0) for r in needs_work)
        print(f"{'TOTAL':<50} {'':<6} {total_missing:>8} {total_chinese:>8}")
        print()
        
        # Show detailed reports if not summary only
        if not summary_only and verbose:
            print(f"\n{'='*70}")
            print("DETAILED REPORTS")
            print(f"{'='*70}")
            for r in needs_work[:10]:  # Limit to first 10
                print(generate_report(r['filepath'], verbose=False))
            if len(needs_work) > 10:
                print(f"\n... and {len(needs_work) - 10} more files. Run with specific file for details.")
    
    # Show errors if any
    if has_errors:
        print(f"\n{'='*70}")
        print(f"FILES WITH ERRORS ({len(has_errors)} files)")
        print(f"{'='*70}")
        for r in has_errors:
            rel_path = os.path.relpath(r['filepath'], root_dir)
            print(f"  {rel_path}: {r.get('error', 'Unknown error')}")
    
    # Final summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    if not needs_work and not has_errors:
        print("✅ All files are fully documented!")
    else:
        if needs_work:
            print(f"⚠️  {len(needs_work)} files need optimization")
            print(f"   - Total missing docstrings: {total_missing}")
            print(f"   - Total Chinese comments: {total_chinese}")
        if has_errors:
            print(f"❌ {len(has_errors)} files have syntax errors")
    print(f"{'='*70}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze Python files for missing docstrings and Chinese comments.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check all files (excluding docs folder)
  python scripts/analyze_docstrings.py
  
  # Check specific file
  python scripts/analyze_docstrings.py backtrader/strategy.py
  
  # Show only summary
  python scripts/analyze_docstrings.py --summary
  
  # Check with verbose output
  python scripts/analyze_docstrings.py --verbose
        """
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Python file(s) to analyze. If not specified, checks all files.'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed reports for files needing work'
    )
    parser.add_argument(
        '-s', '--summary',
        action='store_true',
        help='Only show summary table, no detailed reports'
    )
    parser.add_argument(
        '-d', '--directory',
        default='.',
        help='Root directory to search (default: current directory)'
    )
    
    args = parser.parse_args()
    
    if args.files:
        # Analyze specific files
        for filepath in args.files:
            print(generate_report(filepath, verbose=args.verbose))
    else:
        # Analyze all files in directory
        batch_analyze(args.directory, summary_only=args.summary, verbose=args.verbose)


if __name__ == '__main__':
    main()
