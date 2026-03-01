#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Documentation Consistency Checker for Backtrader.

This tool checks documentation files for consistency issues including:
- Terminology consistency
- Formatting consistency
- Cross-reference validity
- Style guide compliance

Usage:
    python tools/doc_consistency_checker.py
    python tools/doc_consistency_checker.py --output docs/consistency_report.md
"""

import re
from pathlib import Path
from typing import List, Dict, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class ConsistencyIssue:
    """Represents a consistency issue."""
    file_path: str
    line_number: int
    issue_type: str
    description: str
    severity: str  # 'error', 'warning', 'info'


class DocConsistencyChecker:
    """Checker for documentation consistency."""
    
    def __init__(self, docs_root: str = "docs"):
        self.docs_root = Path(docs_root)
        self.issues: List[ConsistencyIssue] = []
        
        # Load terminology from glossary
        self.terminology = self._load_terminology()
        
        # Common inconsistencies to check
        self.checks = {
            'terminology': self._check_terminology,
            'formatting': self._check_formatting,
            'headers': self._check_headers,
            'code_blocks': self._check_code_blocks,
            'links': self._check_links,
        }
    
    def _load_terminology(self) -> Dict[str, str]:
        """Load terminology from glossary."""
        glossary_path = self.docs_root / 'TERMINOLOGY_GLOSSARY.md'
        terminology = {}
        
        if glossary_path.exists():
            with open(glossary_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Extract terminology from table
                for line in content.split('\n'):
                    if '|' in line and not line.startswith('|---'):
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 3 and parts[1] and parts[2]:
                            terminology[parts[1].lower()] = parts[2]
        
        return terminology
    
    def check_all(self) -> None:
        """Run all consistency checks."""
        md_files = list(self.docs_root.rglob('*.md'))
        
        print(f"Checking {len(md_files)} documentation files...")
        
        for file_path in md_files:
            if self._should_skip_file(file_path):
                continue
            
            self._check_file(file_path)
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_patterns = ['_build', 'build', '__pycache__', '.git', 'node_modules']
        return any(pattern in str(file_path) for pattern in skip_patterns)
    
    def _check_file(self, file_path: Path) -> None:
        """Check a single file for consistency issues."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for check_name, check_func in self.checks.items():
                check_func(file_path, lines)
        
        except Exception as e:
            print(f"Error checking {file_path}: {e}")
    
    def _check_terminology(self, file_path: Path, lines: List[str]) -> None:
        """Check for terminology consistency."""
        # Check for common misspellings or inconsistent terms
        inconsistent_terms = {
            'back trader': 'Backtrader',
            'back-trader': 'Backtrader',
            'cerebro engine': 'Cerebro',
            'moving average': 'Moving Average',
        }
        
        for line_num, line in enumerate(lines, 1):
            for wrong, correct in inconsistent_terms.items():
                if wrong.lower() in line.lower():
                    self.issues.append(ConsistencyIssue(
                        file_path=str(file_path.relative_to(self.docs_root.parent)),
                        line_number=line_num,
                        issue_type='terminology',
                        description=f"Use '{correct}' instead of '{wrong}'",
                        severity='warning'
                    ))
    
    def _check_formatting(self, file_path: Path, lines: List[str]) -> None:
        """Check for formatting consistency."""
        for line_num, line in enumerate(lines, 1):
            # Check for trailing whitespace
            if line.rstrip() != line.rstrip('\n'):
                self.issues.append(ConsistencyIssue(
                    file_path=str(file_path.relative_to(self.docs_root.parent)),
                    line_number=line_num,
                    issue_type='formatting',
                    description='Trailing whitespace',
                    severity='info'
                ))
            
            # Check for multiple consecutive blank lines
            if line_num > 1 and line.strip() == '' and lines[line_num-2].strip() == '':
                self.issues.append(ConsistencyIssue(
                    file_path=str(file_path.relative_to(self.docs_root.parent)),
                    line_number=line_num,
                    issue_type='formatting',
                    description='Multiple consecutive blank lines',
                    severity='info'
                ))
    
    def _check_headers(self, file_path: Path, lines: List[str]) -> None:
        """Check header consistency."""
        header_levels = []
        
        for line_num, line in enumerate(lines, 1):
            if line.startswith('#'):
                level = len(line) - len(line.lstrip('#'))
                header_levels.append((line_num, level))
                
                # Check for space after #
                if not line[level:level+1] == ' ':
                    self.issues.append(ConsistencyIssue(
                        file_path=str(file_path.relative_to(self.docs_root.parent)),
                        line_number=line_num,
                        issue_type='headers',
                        description='Missing space after # in header',
                        severity='warning'
                    ))
        
        # Check header level progression
        for i in range(1, len(header_levels)):
            prev_level = header_levels[i-1][1]
            curr_level = header_levels[i][1]
            
            if curr_level > prev_level + 1:
                self.issues.append(ConsistencyIssue(
                    file_path=str(file_path.relative_to(self.docs_root.parent)),
                    line_number=header_levels[i][0],
                    issue_type='headers',
                    description=f'Header level skipped (from h{prev_level} to h{curr_level})',
                    severity='warning'
                ))
    
    def _check_code_blocks(self, file_path: Path, lines: List[str]) -> None:
        """Check code block consistency."""
        in_code_block = False
        code_block_start = 0
        
        for line_num, line in enumerate(lines, 1):
            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    code_block_start = line_num
                    
                    # Check for language specification
                    if line.strip() == '```':
                        self.issues.append(ConsistencyIssue(
                            file_path=str(file_path.relative_to(self.docs_root.parent)),
                            line_number=line_num,
                            issue_type='code_blocks',
                            description='Code block missing language specification',
                            severity='info'
                        ))
                else:
                    in_code_block = False
        
        # Check for unclosed code blocks
        if in_code_block:
            self.issues.append(ConsistencyIssue(
                file_path=str(file_path.relative_to(self.docs_root.parent)),
                line_number=code_block_start,
                issue_type='code_blocks',
                description='Unclosed code block',
                severity='error'
            ))
    
    def _check_links(self, file_path: Path, lines: List[str]) -> None:
        """Check link formatting consistency."""
        link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        
        for line_num, line in enumerate(lines, 1):
            for match in link_pattern.finditer(line):
                link_text = match.group(1)
                link_url = match.group(2)
                
                # Check for empty link text
                if not link_text.strip():
                    self.issues.append(ConsistencyIssue(
                        file_path=str(file_path.relative_to(self.docs_root.parent)),
                        line_number=line_num,
                        issue_type='links',
                        description='Empty link text',
                        severity='warning'
                    ))
                
                # Check for spaces in URLs (should be encoded)
                if ' ' in link_url and not link_url.startswith('mailto:'):
                    self.issues.append(ConsistencyIssue(
                        file_path=str(file_path.relative_to(self.docs_root.parent)),
                        line_number=line_num,
                        issue_type='links',
                        description='Unencoded space in URL',
                        severity='warning'
                    ))
    
    def generate_report(self, output_file: str = None) -> str:
        """Generate consistency check report."""
        from datetime import datetime
        
        # Group issues by type and severity
        issues_by_type = defaultdict(list)
        issues_by_severity = defaultdict(list)
        
        for issue in self.issues:
            issues_by_type[issue.issue_type].append(issue)
            issues_by_severity[issue.severity].append(issue)
        
        report_lines = [
            "# Documentation Consistency Report",
            "",
            f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Issues**: {len(self.issues)}",
            "",
            "## Summary by Severity",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Errors | {len(issues_by_severity['error'])} |",
            f"| Warnings | {len(issues_by_severity['warning'])} |",
            f"| Info | {len(issues_by_severity['info'])} |",
            "",
            "## Summary by Type",
            "",
            "| Type | Count |",
            "|------|-------|",
        ]
        
        for issue_type in sorted(issues_by_type.keys()):
            count = len(issues_by_type[issue_type])
            report_lines.append(f"| {issue_type.title()} | {count} |")
        
        report_lines.append("")
        
        # Detailed issues by type
        for issue_type in sorted(issues_by_type.keys()):
            issues = issues_by_type[issue_type]
            report_lines.extend([
                f"## {issue_type.title()} Issues ({len(issues)})",
                "",
                "| File | Line | Description | Severity |",
                "|------|------|-------------|----------|",
            ])
            
            for issue in sorted(issues, key=lambda x: (x.file_path, x.line_number))[:50]:
                report_lines.append(
                    f"| `{issue.file_path}` | {issue.line_number} | {issue.description} | {issue.severity} |"
                )
            
            if len(issues) > 50:
                report_lines.append(f"\n*... and {len(issues) - 50} more*")
            
            report_lines.append("")
        
        report_lines.extend([
            "## Recommendations",
            "",
            "1. Fix all errors immediately",
            "2. Review and fix warnings",
            "3. Consider fixing info-level issues for better consistency",
            "4. Use automated tools to prevent future issues",
            "",
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"Report saved to: {output_file}")
        
        return report


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Check documentation consistency")
    parser.add_argument(
        '--docs-root',
        default='docs',
        help='Root directory of documentation (default: docs)'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Output file for report (default: print to stdout)'
    )
    
    args = parser.parse_args()
    
    checker = DocConsistencyChecker(docs_root=args.docs_root)
    checker.check_all()
    
    print(f"\nFound {len(checker.issues)} consistency issues")
    
    report = checker.generate_report(output_file=args.output)
    
    if not args.output:
        print(report)


if __name__ == '__main__':
    main()
