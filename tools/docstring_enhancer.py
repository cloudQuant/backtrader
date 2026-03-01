#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Docstring Enhancement Tool for Backtrader.

This tool helps add type hints and improve docstrings in Python files.

Usage:
    python tools/docstring_enhancer.py --scan backtrader/cerebro.py
    python tools/docstring_enhancer.py --add-types backtrader/
"""

import ast
import sys
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass


@dataclass
class FunctionInfo:
    """Information about a function/method."""
    name: str
    file_path: str
    line_number: int
    has_docstring: bool
    has_type_hints: bool
    parameters: List[str]
    returns_value: bool
    is_method: bool
    parent_class: Optional[str] = None


class DocstringEnhancer:
    """Tool for enhancing docstrings and type hints."""
    
    def __init__(self):
        self.functions: List[FunctionInfo] = []
    
    def scan_file(self, file_path: Path) -> None:
        """Scan a Python file for functions needing enhancement."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=str(file_path))
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            self._analyze_function(item, file_path, node.name)
                
                elif isinstance(node, ast.FunctionDef):
                    # Top-level function
                    if not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree)):
                        self._analyze_function(item, file_path, None)
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}", file=sys.stderr)
    
    def _analyze_function(
        self, 
        node: ast.FunctionDef, 
        file_path: Path,
        parent_class: Optional[str]
    ) -> None:
        """Analyze a function node."""
        has_docstring = ast.get_docstring(node) is not None
        
        # Check for type hints
        has_return_type = node.returns is not None
        has_param_types = any(
            arg.annotation is not None 
            for arg in node.args.args
        )
        has_type_hints = has_return_type or has_param_types
        
        # Check if function returns a value
        returns_value = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(node)
        )
        
        # Get parameters
        parameters = [arg.arg for arg in node.args.args]
        
        self.functions.append(FunctionInfo(
            name=node.name,
            file_path=str(file_path),
            line_number=node.lineno,
            has_docstring=has_docstring,
            has_type_hints=has_type_hints,
            parameters=parameters,
            returns_value=returns_value,
            is_method=parent_class is not None,
            parent_class=parent_class
        ))
    
    def generate_docstring_template(self, func: FunctionInfo) -> str:
        """Generate a Google-style docstring template."""
        lines = ['"""TODO: Add description.']
        
        if func.parameters and func.parameters != ['self']:
            lines.append('')
            lines.append('Args:')
            for param in func.parameters:
                if param != 'self':
                    lines.append(f'    {param}: TODO: Add description')
        
        if func.returns_value:
            lines.append('')
            lines.append('Returns:')
            lines.append('    TODO: Add return description')
        
        lines.append('"""')
        return '\n'.join(lines)
    
    def generate_report(self) -> str:
        """Generate enhancement report."""
        missing_docs = [f for f in self.functions if not f.has_docstring]
        missing_types = [f for f in self.functions if not f.has_type_hints]
        
        report = [
            "# Docstring Enhancement Report",
            "",
            f"**Total Functions**: {len(self.functions)}",
            f"**Missing Docstrings**: {len(missing_docs)}",
            f"**Missing Type Hints**: {len(missing_types)}",
            "",
            "## Functions Needing Docstrings",
            "",
        ]
        
        for func in missing_docs[:20]:  # Top 20
            report.append(f"- `{func.file_path}:{func.line_number}` - `{func.name}`")
        
        return '\n'.join(report)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhance docstrings and type hints")
    parser.add_argument('--scan', help='File or directory to scan')
    parser.add_argument('--output', '-o', help='Output report file')
    
    args = parser.parse_args()
    
    enhancer = DocstringEnhancer()
    
    if args.scan:
        scan_path = Path(args.scan)
        if scan_path.is_file():
            enhancer.scan_file(scan_path)
        elif scan_path.is_dir():
            for py_file in scan_path.rglob('*.py'):
                enhancer.scan_file(py_file)
    
    report = enhancer.generate_report()
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
    else:
        print(report)


if __name__ == '__main__':
    main()
