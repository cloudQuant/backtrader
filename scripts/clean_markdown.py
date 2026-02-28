#!/usr/bin/env python3
"""Markdown format cleaner script.

This script fixes formatting issues in Markdown files to ensure they comply
with standard Markdown linting rules (markdownlint).
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Tuple


class MarkdownCleaner:
    """Markdown format cleaner.

    This class provides methods to clean and fix common Markdown formatting
    issues including trailing whitespace, heading spacing, list formatting,
    code block spacing, and more.
    """

    def __init__(self) -> None:
        """Initialize the MarkdownCleaner with counters for tracking changes."""
        self.fixes_applied = 0
        self.files_processed = 0

    def clean_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """Clean a single Markdown file.

        Args:
            file_path: Path to the Markdown file to clean.

        Returns:
            A tuple of (has_changes, fixes_applied) where:
                - has_changes: True if the file was modified
                - fixes_applied: List of fix descriptions applied
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
            except UnicodeDecodeError:
                return False, [f"Unable to read file encoding: {file_path}"]

        original_content = content
        fixes = []

        # 1. Fix trailing whitespace
        if re.search(r' +$', content, re.MULTILINE):
            content = re.sub(r' +$', '', content, flags=re.MULTILINE)
            fixes.append("Remove trailing whitespace")

        # 2. Fix excessive blank lines (more than 2 consecutive blank lines)
        if re.search(r'\n{4,}', content):
            content = re.sub(r'\n{3,}', '\n\n', content)
            fixes.append("Fix excessive blank lines")

        # 3. Fix heading format
        # 3a. Ensure space after #
        if re.search(r'^#{1,6}[^ #\n]', content, re.MULTILINE):
            content = re.sub(r'^(#{1,6})([^ #\n])', r'\1 \2', content, flags=re.MULTILINE)
            fixes.append("Fix heading spacing")

        # 3b. Fix blank lines around headings (MD022)
        # Heading needs blank line before (unless at document start)
        if re.search(r'[^\n]\n(#{1,6} )', content):
            content = re.sub(r'([^\n])\n(#{1,6} )', r'\1\n\n\2', content)
            fixes.append("Fix blank line before heading")

        # Heading needs blank line after (unless followed by another heading or end of document)
        if re.search(r'(#{1,6} [^\n]*)\n([^#\n])', content):
            content = re.sub(r'(#{1,6} [^\n]*)\n([^#\n\s])', r'\1\n\n\2', content)
            fixes.append("Fix blank line after heading")

        # 4. Fix list format
        # 4a. Ensure space after - * +
        if re.search(r'^( *)[-*+][^ \n]', content, re.MULTILINE):
            content = re.sub(r'^( *)([-*+])([^ \n])', r'\1\2 \3', content, flags=re.MULTILINE)
            fixes.append("Fix list item spacing")

        # 4b. Unify list style to dash (MD004)
        if re.search(r'^( *)\*( )', content, re.MULTILINE):
            content = re.sub(r'^( *)\*( )', r'\1-\2', content, flags=re.MULTILINE)
            fixes.append("Unify list style to dash")

        if re.search(r'^( *)\+( )', content, re.MULTILINE):
            content = re.sub(r'^( *)\+( )', r'\1-\2', content, flags=re.MULTILINE)
            fixes.append("Unify list style to dash")

        # Fix special case: * *text** format
        if re.search(r'^\* \*([^*]+)\*\*', content, re.MULTILINE):
            content = re.sub(r'^\* \*([^*]+)\*\*', r'**\1**', content, flags=re.MULTILINE)
            fixes.append("Fix incorrect emphasis format")

        # 4c. Fix blank lines around lists (MD032)
        # More precise list detection and fix, supports unordered and ordered lists
        lines = content.split('\n')
        new_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if current line is a list item (unordered or ordered)
            is_unordered_list = re.match(r'^( *)-[ \t]', line)
            is_ordered_list = re.match(r'^( *)\d+\.[ \t]', line)
            is_list_item = is_unordered_list or is_ordered_list

            if is_list_item:
                # Check if previous line needs blank line
                if (i > 0 and
                    new_lines and
                    new_lines[-1].strip() != '' and
                    not re.match(r'^( *)-[ \t]', new_lines[-1]) and
                    not re.match(r'^( *)\d+\.[ \t]', new_lines[-1]) and
                    not re.match(r'^#{1,6} ', new_lines[-1])):
                    new_lines.append('')
                    fixes.append("Fix blank line before list")

                # Add current list item
                new_lines.append(line)

                # Find end of list
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (re.match(r'^( *)-[ \t]', next_line) or
                        re.match(r'^( *)\d+\.[ \t]', next_line)):
                        # Still a list item, continue
                        new_lines.append(next_line)
                        j += 1
                    elif next_line.strip() == '':
                        # Blank line, continue
                        new_lines.append(next_line)
                        j += 1
                    else:
                        # Non-list item, list ends
                        break

                # Check if blank line needed after list
                if (j < len(lines) and
                    lines[j].strip() != '' and
                    not re.match(r'^#{1,6} ', lines[j]) and
                    (not new_lines or new_lines[-1].strip() != '')):
                    new_lines.append('')
                    fixes.append("Fix blank line after list")

                i = j
            else:
                new_lines.append(line)
                i += 1

        new_content = '\n'.join(new_lines)
        if new_content != content:
            content = new_content

        # 5. Fix code block format (ensure blank lines before and after)
        # Fix missing blank line before code block
        if re.search(r'[^\n]\n```', content):
            content = re.sub(r'([^\n])\n(```)', r'\1\n\n\2', content)
            fixes.append("Fix blank line before code block")

        # Fix missing blank line after code block
        if re.search(r'```\n[^\n]', content):
            content = re.sub(r'(```)\n([^\n])', r'\1\n\n\2', content)
            fixes.append("Fix blank line after code block")

        # 6. Fix link format (remove extra spaces)
        if re.search(r'\[ +([^\]]+) +\]', content):
            content = re.sub(r'\[ +([^\]]+) +\]', r'[\1]', content)
            fixes.append("Fix link format")

        # 7. Fix table format
        # Ensure blank lines before and after tables
        if re.search(r'[^\n]\n\|', content):
            content = re.sub(r'([^\n])\n(\|)', r'\1\n\n\2', content)
            fixes.append("Fix blank line before table")

        if re.search(r'\|[^\n]*\n[^\n|]', content):
            content = re.sub(r'(\|[^\n]*)\n([^\n|])', r'\1\n\n\2', content)
            fixes.append("Fix blank line after table")

        # 8. Fix file ending (ensure single newline at end)
        if not content.endswith('\n'):
            content += '\n'
            fixes.append("Add file ending newline")
        elif content.endswith('\n\n'):
            content = content.rstrip('\n') + '\n'
            fixes.append("Fix excessive file ending newlines")

        # 9. Fix Chinese-English mixed text (add space between Chinese and English)
        # Chinese followed by English/numbers
        if re.search(r'[\u4e00-\u9fff][a-zA-Z0-9]', content):
            content = re.sub(r'([\u4e00-\u9fff])([a-zA-Z0-9])', r'\1 \2', content)
            fixes.append("Fix Chinese-English spacing (after Chinese)")

        # English/numbers followed by Chinese
        if re.search(r'[a-zA-Z0-9][\u4e00-\u9fff]', content):
            content = re.sub(r'([a-zA-Z0-9])([\u4e00-\u9fff])', r'\1 \2', content)
            fixes.append("Fix Chinese-English spacing (after English)")

        # 10. Fix emphasis format (**text** and *text*)
        # Ensure emphasis symbols are tight to content
        if re.search(r'\*\* +([^*]+) +\*\*', content):
            content = re.sub(r'\*\* +([^*]+) +\*\*', r'**\1**', content)
            fixes.append("Fix bold format")

        if re.search(r'(?<!\*)\* +([^*]+) +\*(?!\*)', content):
            content = re.sub(r'(?<!\*)\* +([^*]+) +\*(?!\*)', r'*\1*', content)
            fixes.append("Fix italic format")

        # 11. Fix other markdownlint rules
        # MD009: Trailing spaces (handled in step 1)
        # MD010: Hard tabs
        if '\t' in content:
            content = content.replace('\t', '    ')
            fixes.append("Replace tabs with spaces")

        # MD012: Multiple consecutive blank lines (enhanced check)
        if re.search(r'\n\s*\n\s*\n\s*\n', content):
            content = re.sub(r'\n\s*\n\s*\n\s*\n+', '\n\n', content)
            fixes.append("Fix multiple consecutive blank lines")

        # MD018: No space after hash (handled in step 3)
        # MD019: Multiple spaces after hash
        if re.search(r'^#{1,6}  +', content, re.MULTILINE):
            content = re.sub(r'^(#{1,6})  +', r'\1 ', content, flags=re.MULTILINE)
            fixes.append("Fix excessive heading spaces")

        # MD023: Heading indentation
        if re.search(r'^ +#{1,6}', content, re.MULTILINE):
            content = re.sub(r'^ +(#{1,6})', r'\1', content, flags=re.MULTILINE)
            fixes.append("Fix heading indentation")

        # MD029: Ordered list item number
        # Fix ordered list numbering, use incremental numbering 1. 2. 3. format
        lines = content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if it's an ordered list item
            match = re.match(r'^( *)\d+\. (.+)', line)
            if match:
                indent = match.group(1)

                # Collect continuous same-level ordered list items
                list_items = []
                j = i

                while j < len(lines):
                    current_line = lines[j]
                    current_match = re.match(r'^( *)\d+\. (.+)', current_line)

                    if current_match and current_match.group(1) == indent:
                        # Same level list item
                        list_items.append((j, current_match.group(2)))
                    elif current_line.strip() == '':
                        # Blank line, may be separator between list items, continue
                        pass
                    elif current_match and len(current_match.group(1)) > len(indent):
                        # Deeper nested list, skip
                        pass
                    else:
                        # Non-list content or shallower level, end current list
                        break

                    j += 1

                # Renumber same-level list items
                has_changes = False
                for idx, (line_idx, text) in enumerate(list_items, 1):
                    new_line = f"{indent}{idx}. {text}"
                    if lines[line_idx] != new_line:
                        lines[line_idx] = new_line
                        has_changes = True

                if has_changes:
                    fixes.append("Fix ordered list numbering")

                # Move to next unprocessed line
                if list_items:
                    # Skip to after last processed list item
                    i = list_items[-1][0] + 1
                else:
                    i += 1
            else:
                i += 1

        new_content = '\n'.join(lines)
        if new_content != content:
            content = new_content

        # MD034: Bare URL
        # Wrap bare URLs in <>
        if re.search(r'(?<!<)https?://[^\s<>]+(?!>)', content):
            content = re.sub(r'(?<!<)(https?://[^\s<>]+)(?!>)', r'<\1>', content)
            fixes.append("Fix bare URL format")

        # MD040: Code block language identifier
        # Add language identifier to code blocks without one
        if re.search(r'^```\s*$', content, re.MULTILINE):
            content = re.sub(r'^```\s*$', '```bash', content, flags=re.MULTILINE)
            fixes.append("Add code block language identifier")

        # Check if changes were made
        has_changes = content != original_content

        if has_changes:
            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.fixes_applied += len(fixes)

        return has_changes, fixes

    def find_markdown_files(self, directory: Path,
                           exclude_patterns: List[str] = None) -> List[Path]:
        """Find all Markdown files in a directory.

        Args:
            directory: Directory to search for Markdown files.
            exclude_patterns: List of patterns to exclude from search.

        Returns:
            List of Path objects for found Markdown files.
        """
        if exclude_patterns is None:
            exclude_patterns = [
                'node_modules',
                '.git',
                'venv',
                '.venv',
                '__pycache__',
                '.pytest_cache'
            ]

        markdown_files = []

        for md_file in directory.rglob('*.md'):
            # Check if should be excluded
            should_exclude = False
            for pattern in exclude_patterns:
                if pattern in str(md_file):
                    should_exclude = True
                    break

            if not should_exclude:
                markdown_files.append(md_file)

        return sorted(markdown_files)

    def clean_directory(self, directory: Path, dry_run: bool = False) -> None:
        """Clean all Markdown files in a directory.

        Args:
            directory: Target directory containing Markdown files.
            dry_run: If True, only check files without modifying them.
        """
        markdown_files = self.find_markdown_files(directory)

        if not markdown_files:
            print("No Markdown files found")
            return

        print(f"Found {len(markdown_files)} Markdown file(s)")

        if dry_run:
            print("\nDry run mode - files will not be modified\n")
        else:
            print("\nStarting Markdown file cleaning\n")

        for file_path in markdown_files:
            relative_path = file_path.relative_to(directory)

            if dry_run:
                # Dry run mode: only check without modifying
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    try:
                        with open(file_path, 'r', encoding='gbk') as f:
                            content = f.read()
                    except UnicodeDecodeError:
                        print(f"Unable to read file encoding: {relative_path}")
                        continue

                # Check if fixes are needed
                needs_fix = False
                issues = []

                if re.search(r' +$', content, re.MULTILINE):
                    issues.append("trailing whitespace")
                    needs_fix = True

                if re.search(r'\n{4,}', content):
                    issues.append("excessive blank lines")
                    needs_fix = True

                if re.search(r'^#{1,6}[^ #\n]', content, re.MULTILINE):
                    issues.append("heading format")
                    needs_fix = True

                if re.search(r'^( *)[-*+][^ \n]', content, re.MULTILINE):
                    issues.append("list format")
                    needs_fix = True

                # Check blank line issues around lists
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    # Check ordered and unordered lists
                    if re.match(r'^( *)-[ \t]', line) or re.match(r'^( *)\d+\.[ \t]', line):
                        # Check previous line
                        if (i > 0 and
                            lines[i-1].strip() != '' and
                            not re.match(r'^( *)-[ \t]', lines[i-1]) and
                            not re.match(r'^( *)\d+\.[ \t]', lines[i-1]) and
                            not re.match(r'^#{1,6} ', lines[i-1])):
                            issues.append("missing blank line before list")
                            needs_fix = True
                            break

                if needs_fix:
                    print(f"Needs fix: {relative_path} - {', '.join(issues)}")
                else:
                    print(f"OK: {relative_path}")
            else:
                # Actual cleaning mode
                has_changes, fixes = self.clean_file(file_path)
                self.files_processed += 1

                if has_changes:
                    print(f"Fixed: {relative_path} - {', '.join(fixes)}")
                else:
                    print(f"OK: {relative_path} - no fixes needed")

        if not dry_run:
            print(f"\nCleaning complete:")
            print(f"   Files processed: {self.files_processed}")
            print(f"   Fixes applied: {self.fixes_applied}")
        else:
            print(f"\nCheck complete: {len(markdown_files)} file(s)")


def main() -> None:
    """Main entry point for the Markdown cleaner script.

    Parses command line arguments and initiates the cleaning process.
    """
    parser = argparse.ArgumentParser(
        description="Markdown format cleaning tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python clean_markdown.py                    # Clean current directory
  python clean_markdown.py --dry-run          # Dry run mode
  python clean_markdown.py /path/to/docs      # Clean specific directory
  python clean_markdown.py README.md          # Clean single file
        """
    )

    parser.add_argument(
        'path',
        nargs='?',
        default='.',
        help='File or directory path to clean (default: current directory)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode, only check without modifying files'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='Markdown Cleaner 1.0.0'
    )

    args = parser.parse_args()

    # Resolve path
    target_path = Path(args.path).resolve()

    if not target_path.exists():
        print(f"Error: Path does not exist - {target_path}")
        sys.exit(1)

    cleaner = MarkdownCleaner()

    try:
        if target_path.is_file():
            # Handle single file
            if target_path.suffix.lower() != '.md':
                print(f"Error: Not a Markdown file - {target_path}")
                sys.exit(1)

            print(f"Cleaning file: {target_path.name}")

            if args.dry_run:
                print("Dry run mode - file will not be modified")
                # Add single file dry run logic here if needed
            else:
                has_changes, fixes = cleaner.clean_file(target_path)
                if has_changes:
                    print(f"Fixed: {', '.join(fixes)}")
                else:
                    print("No fixes needed")
        else:
            # Handle directory
            print(f"Cleaning directory: {target_path}")
            cleaner.clean_directory(target_path, args.dry_run)

    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError occurred: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
