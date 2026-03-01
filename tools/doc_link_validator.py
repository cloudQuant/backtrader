#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Documentation Link Validator for Backtrader.

This tool validates internal and external links in Markdown and RST documentation files.

Usage:
    python tools/doc_link_validator.py
    python tools/doc_link_validator.py --check-external
    python tools/doc_link_validator.py --output docs/link_validation_report.md
"""

import re
import os
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse
import concurrent.futures


@dataclass
class LinkIssue:
    """Represents a link validation issue."""
    file_path: str
    line_number: int
    link_text: str
    link_target: str
    issue_type: str  # 'broken', 'external_down', 'anchor_missing', 'file_missing'
    severity: str  # 'error', 'warning', 'info'


class DocLinkValidator:
    """Validator for documentation links."""
    
    def __init__(self, docs_root: str = "docs"):
        self.docs_root = Path(docs_root)
        self.issues: List[LinkIssue] = []
        self.checked_files: Set[Path] = set()
        self.external_links: Set[str] = set()
        self.check_external = False
        
        # Patterns for different link types
        self.md_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        self.rst_link_pattern = re.compile(r':(?:doc|ref):`([^`]+)`')
        self.rst_external_pattern = re.compile(r'`([^<]+)<([^>]+)>`_')
        self.url_pattern = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')
    
    def validate_all(self, check_external: bool = False) -> None:
        """Validate all documentation files."""
        self.check_external = check_external
        
        # Find all documentation files
        md_files = list(self.docs_root.rglob('*.md'))
        rst_files = list(self.docs_root.rglob('*.rst'))
        
        all_files = md_files + rst_files
        print(f"Found {len(all_files)} documentation files to validate")
        
        for file_path in all_files:
            if self._should_skip_file(file_path):
                continue
            self._validate_file(file_path)
        
        # Check external links if requested
        if check_external and self.external_links:
            print(f"\nChecking {len(self.external_links)} external links...")
            self._check_external_links()
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_patterns = ['_build', 'build', '__pycache__', '.git']
        return any(pattern in str(file_path) for pattern in skip_patterns)
    
    def _validate_file(self, file_path: Path) -> None:
        """Validate links in a single file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            self.checked_files.add(file_path)
            
            if file_path.suffix == '.md':
                self._validate_markdown(file_path, lines)
            elif file_path.suffix == '.rst':
                self._validate_rst(file_path, lines)
        
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
    
    def _validate_markdown(self, file_path: Path, lines: List[str]) -> None:
        """Validate Markdown file links."""
        for line_num, line in enumerate(lines, 1):
            # Find Markdown links [text](url)
            for match in self.md_link_pattern.finditer(line):
                link_text = match.group(1)
                link_target = match.group(2)
                
                # Skip anchors within same page
                if link_target.startswith('#'):
                    continue
                
                # Check if it's an external link
                if link_target.startswith(('http://', 'https://')):
                    self.external_links.add(link_target)
                    continue
                
                # Validate internal link
                self._validate_internal_link(
                    file_path, line_num, link_text, link_target
                )
    
    def _validate_rst(self, file_path: Path, lines: List[str]) -> None:
        """Validate RST file links."""
        for line_num, line in enumerate(lines, 1):
            # Find RST doc/ref links
            for match in self.rst_link_pattern.finditer(line):
                link_target = match.group(1)
                self._validate_internal_link(
                    file_path, line_num, link_target, link_target
                )
            
            # Find external links
            for match in self.rst_external_pattern.finditer(line):
                link_url = match.group(2)
                if link_url.startswith(('http://', 'https://')):
                    self.external_links.add(link_url)
    
    def _validate_internal_link(
        self, 
        file_path: Path, 
        line_num: int, 
        link_text: str, 
        link_target: str
    ) -> None:
        """Validate an internal documentation link."""
        # Parse the link target
        if '#' in link_target:
            target_file, anchor = link_target.split('#', 1)
        else:
            target_file = link_target
            anchor = None
        
        # Resolve relative path
        if target_file:
            target_path = (file_path.parent / target_file).resolve()
            
            # Check if target file exists
            if not target_path.exists():
                # Try adding .md or .rst extension
                if not target_path.suffix:
                    for ext in ['.md', '.rst']:
                        test_path = target_path.with_suffix(ext)
                        if test_path.exists():
                            target_path = test_path
                            break
                
                if not target_path.exists():
                    self.issues.append(LinkIssue(
                        file_path=str(file_path.relative_to(self.docs_root.parent)),
                        line_number=line_num,
                        link_text=link_text,
                        link_target=link_target,
                        issue_type='file_missing',
                        severity='error'
                    ))
                    return
            
            # Check anchor if present
            if anchor:
                self._validate_anchor(
                    file_path, line_num, link_text, target_path, anchor
                )
    
    def _validate_anchor(
        self,
        file_path: Path,
        line_num: int,
        link_text: str,
        target_path: Path,
        anchor: str
    ) -> None:
        """Validate that an anchor exists in the target file."""
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for anchor in Markdown headers or RST labels
            anchor_patterns = [
                f'#{anchor}',  # Markdown header
                f'.. _{anchor}:',  # RST label
                f'<a name="{anchor}"',  # HTML anchor
            ]
            
            found = any(pattern in content for pattern in anchor_patterns)
            
            if not found:
                self.issues.append(LinkIssue(
                    file_path=str(file_path.relative_to(self.docs_root.parent)),
                    line_number=line_num,
                    link_text=link_text,
                    link_target=f"{target_path.name}#{anchor}",
                    issue_type='anchor_missing',
                    severity='warning'
                ))
        
        except Exception as e:
            print(f"Error checking anchor in {target_path}: {e}", file=sys.stderr)
    
    def _check_external_links(self) -> None:
        """Check external links for availability."""
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
        except ImportError:
            print("Warning: requests library not installed. Skipping external link check.")
            print("Install with: pip install requests")
            return
        
        # Configure session with retries
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        def check_url(url: str) -> Tuple[str, bool, Optional[str]]:
            """Check if URL is accessible."""
            try:
                response = session.head(url, timeout=10, allow_redirects=True)
                if response.status_code >= 400:
                    return url, False, f"HTTP {response.status_code}"
                return url, True, None
            except Exception as e:
                return url, False, str(e)
        
        # Check URLs in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(check_url, self.external_links))
        
        # Record issues
        for url, is_valid, error in results:
            if not is_valid:
                # Find files containing this URL
                for file_path in self.checked_files:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if url in content:
                            line_num = content[:content.index(url)].count('\n') + 1
                            self.issues.append(LinkIssue(
                                file_path=str(file_path.relative_to(self.docs_root.parent)),
                                line_number=line_num,
                                link_text=url,
                                link_target=url,
                                issue_type='external_down',
                                severity='warning'
                            ))
                    except:
                        pass
    
    def generate_report(self, output_file: Optional[str] = None) -> str:
        """Generate validation report in Markdown format."""
        from datetime import datetime
        
        # Group issues by type
        issues_by_type = {
            'file_missing': [],
            'anchor_missing': [],
            'external_down': []
        }
        
        for issue in self.issues:
            if issue.issue_type in issues_by_type:
                issues_by_type[issue.issue_type].append(issue)
        
        # Generate report
        report_lines = [
            "# Documentation Link Validation Report",
            "",
            f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Files Checked**: {len(self.checked_files)}",
            f"**Total Issues**: {len(self.issues)}",
            "",
            "## Summary",
            "",
            "| Issue Type | Count | Severity |",
            "|------------|-------|----------|",
            f"| Missing Files | {len(issues_by_type['file_missing'])} | Error |",
            f"| Missing Anchors | {len(issues_by_type['anchor_missing'])} | Warning |",
            f"| Broken External Links | {len(issues_by_type['external_down'])} | Warning |",
            "",
        ]
        
        # Detailed issues
        if issues_by_type['file_missing']:
            report_lines.extend([
                "## Missing Files (Errors)",
                "",
                "| File | Line | Link Text | Target |",
                "|------|------|-----------|--------|",
            ])
            for issue in sorted(issues_by_type['file_missing'], key=lambda x: x.file_path):
                report_lines.append(
                    f"| `{issue.file_path}` | {issue.line_number} | {issue.link_text} | `{issue.link_target}` |"
                )
            report_lines.append("")
        
        if issues_by_type['anchor_missing']:
            report_lines.extend([
                "## Missing Anchors (Warnings)",
                "",
                "| File | Line | Link Text | Target |",
                "|------|------|-----------|--------|",
            ])
            for issue in sorted(issues_by_type['anchor_missing'], key=lambda x: x.file_path):
                report_lines.append(
                    f"| `{issue.file_path}` | {issue.line_number} | {issue.link_text} | `{issue.link_target}` |"
                )
            report_lines.append("")
        
        if issues_by_type['external_down']:
            report_lines.extend([
                "## Broken External Links (Warnings)",
                "",
                "| File | Line | URL |",
                "|------|------|-----|",
            ])
            for issue in sorted(issues_by_type['external_down'], key=lambda x: x.file_path):
                report_lines.append(
                    f"| `{issue.file_path}` | {issue.line_number} | {issue.link_target} |"
                )
            report_lines.append("")
        
        if not self.issues:
            report_lines.extend([
                "## ✅ All Links Valid!",
                "",
                "No broken links found in the documentation.",
                "",
            ])
        
        report_lines.extend([
            "## Recommendations",
            "",
            "1. Fix all missing file links (errors) immediately",
            "2. Review missing anchor warnings - may be false positives",
            "3. Check external links periodically as they may change",
            "4. Use relative paths for internal documentation links",
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
    
    parser = argparse.ArgumentParser(description="Validate documentation links")
    parser.add_argument(
        '--docs-root',
        default='docs',
        help='Root directory of documentation (default: docs)'
    )
    parser.add_argument(
        '--check-external',
        action='store_true',
        help='Check external links (requires requests library)'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Output file for report (default: print to stdout)'
    )
    
    args = parser.parse_args()
    
    validator = DocLinkValidator(docs_root=args.docs_root)
    validator.validate_all(check_external=args.check_external)
    
    print(f"\nFound {len(validator.issues)} link issues")
    
    report = validator.generate_report(output_file=args.output)
    
    if not args.output:
        print(report)
    
    # Exit with error code if there are errors
    error_count = sum(1 for issue in validator.issues if issue.severity == 'error')
    sys.exit(1 if error_count > 0 else 0)


if __name__ == '__main__':
    main()
