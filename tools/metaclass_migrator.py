#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Metaclass Migration Utility

This utility helps migrate classes from metaclass-based implementations
to modern descriptor-based implementations without metaclasses.
"""

import ast
import os
import re
from typing import List, Dict, Tuple, Optional


class MetaclassMigrator:
    """Utility to help migrate from metaclass-based to modern implementations."""
    
    def __init__(self):
        self.migration_mappings = {
            'MetaParams': 'ModernParamsBase',
            'MetaLineRoot': 'ModernLineRoot', 
            'MetaLineIterator': 'ModernLineIterator',
            'MetaBase': 'ModernMetaBase',
            'ParamsBase': 'ModernParamsBase'
        }
        
        self.import_mappings = {
            'ModernParamsBase': 'from backtrader.metabase import ModernParamsBase',
            'ModernLineRoot': 'from backtrader.lineroot import ModernLineRoot',
            'ModernLineIterator': 'from backtrader.lineiterator import ModernLineIterator',
            'ModernMetaBase': 'from backtrader.metabase import ModernMetaBase'
        }
    
    def analyze_file(self, filepath: str) -> Dict[str, List[str]]:
        """
        Analyze a Python file for metaclass usage.
        
        Returns:
            Dictionary with analysis results
        """
        results = {
            'metaclass_classes': [],
            'params_tuples': [],
            'lifecycle_methods': [],
            'needs_migration': False
        }
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find metaclass usage
            metaclass_pattern = r'class\s+(\w+)\s*\([^)]*metaclass\s*=\s*(\w+)'
            metaclass_matches = re.findall(metaclass_pattern, content)
            
            for class_name, metaclass_name in metaclass_matches:
                if metaclass_name in self.migration_mappings:
                    results['metaclass_classes'].append((class_name, metaclass_name))
                    results['needs_migration'] = True
            
            # Find params tuples
            params_pattern = r'params\s*=\s*\('
            if re.search(params_pattern, content):
                results['params_tuples'].append(filepath)
                results['needs_migration'] = True
            
            # Find lifecycle methods
            lifecycle_methods = ['doprenew', 'donew', 'dopreinit', 'doinit', 'dopostinit']
            for method in lifecycle_methods:
                if f'def {method}' in content:
                    results['lifecycle_methods'].append(method)
                    results['needs_migration'] = True
        
        except Exception as e:
            print(f"Error analyzing {filepath}: {e}")
        
        return results
    
    def generate_migration_suggestions(self, analysis: Dict[str, List[str]]) -> List[str]:
        """Generate migration suggestions based on analysis."""
        suggestions = []
        
        # Metaclass replacements
        for class_name, metaclass_name in analysis['metaclass_classes']:
            modern_replacement = self.migration_mappings.get(metaclass_name)
            if modern_replacement:
                suggestions.append(
                    f"Replace 'class {class_name}(metaclass={metaclass_name})' with "
                    f"'class {class_name}({modern_replacement})'"
                )
        
        # Parameter tuple conversions
        if analysis['params_tuples']:
            suggestions.append(
                "Convert params tuples to ParameterDescriptor declarations:\n"
                "  params = (('param1', 10), ('param2', 'value'))\n"
                "  becomes:\n"
                "  param1 = ParameterDescriptor(default=10, name='param1')\n"
                "  param2 = ParameterDescriptor(default='value', name='param2')"
            )
        
        # Lifecycle method migrations
        if analysis['lifecycle_methods']:
            suggestions.append(
                f"Migrate lifecycle methods {analysis['lifecycle_methods']} to use "
                f"regular __init__ and method patterns"
            )
        
        return suggestions
    
    def create_migration_template(self, class_name: str, metaclass_name: str) -> str:
        """Create a migration template for a specific class."""
        modern_class = self.migration_mappings.get(metaclass_name, 'ModernParamsBase')
        
        template = f'''
# Original metaclass-based class:
# class {class_name}(metaclass={metaclass_name}):
#     params = (
#         ('param1', 10),
#         ('param2', 'default_value'),
#     )

# Modern replacement:
from backtrader.parameters import ParameterDescriptor
{self.import_mappings.get(modern_class, f'# Import {modern_class}')}

class Modern{class_name}({modern_class}):
    """Modern replacement for {class_name} without metaclass."""
    
    # Convert params tuple to descriptors
    param1 = ParameterDescriptor(default=10, name='param1')
    param2 = ParameterDescriptor(default='default_value', name='param2')
    
    def __init__(self, **kwargs):
        """Initialize with modern parameter system."""
        super().__init__(**kwargs)
        
        # Add any additional initialization here
    
    # Add any additional methods here
'''
        return template
    
    def scan_directory(self, directory: str, extensions: List[str] = None) -> Dict[str, Dict]:
        """
        Scan a directory for files that need metaclass migration.
        
        Args:
            directory: Directory to scan
            extensions: File extensions to include (default: ['.py'])
            
        Returns:
            Dictionary mapping filepaths to analysis results
        """
        if extensions is None:
            extensions = ['.py']
        
        results = {}
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    filepath = os.path.join(root, file)
                    analysis = self.analyze_file(filepath)
                    if analysis['needs_migration']:
                        results[filepath] = analysis
        
        return results
    
    def generate_migration_report(self, scan_results: Dict[str, Dict]) -> str:
        """Generate a comprehensive migration report."""
        report = []
        report.append("# Backtrader Metaclass Migration Report")
        report.append("=" * 50)
        report.append("")
        
        total_files = len(scan_results)
        total_classes = sum(len(r['metaclass_classes']) for r in scan_results.values())
        
        report.append(f"**Summary:**")
        report.append(f"- Files needing migration: {total_files}")
        report.append(f"- Classes using metaclasses: {total_classes}")
        report.append("")
        
        # Group by metaclass type
        metaclass_usage = {}
        for filepath, analysis in scan_results.items():
            for class_name, metaclass_name in analysis['metaclass_classes']:
                if metaclass_name not in metaclass_usage:
                    metaclass_usage[metaclass_name] = []
                metaclass_usage[metaclass_name].append((filepath, class_name))
        
        report.append("## Metaclass Usage Breakdown")
        for metaclass_name, usages in metaclass_usage.items():
            modern_replacement = self.migration_mappings.get(metaclass_name, 'Unknown')
            report.append(f"### {metaclass_name} -> {modern_replacement}")
            report.append(f"Used in {len(usages)} classes:")
            for filepath, class_name in usages:
                report.append(f"  - {class_name} in {filepath}")
            report.append("")
        
        # Detailed file analysis
        report.append("## File-by-File Analysis")
        for filepath, analysis in scan_results.items():
            report.append(f"### {filepath}")
            
            if analysis['metaclass_classes']:
                report.append("**Metaclass classes:**")
                for class_name, metaclass_name in analysis['metaclass_classes']:
                    report.append(f"  - {class_name} (uses {metaclass_name})")
            
            if analysis['params_tuples']:
                report.append("**Has params tuples** - need to convert to descriptors")
            
            if analysis['lifecycle_methods']:
                report.append(f"**Lifecycle methods:** {', '.join(analysis['lifecycle_methods'])}")
            
            # Migration suggestions
            suggestions = self.generate_migration_suggestions(analysis)
            if suggestions:
                report.append("**Migration suggestions:**")
                for suggestion in suggestions:
                    report.append(f"  - {suggestion}")
            
            report.append("")
        
        return "\n".join(report)


def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate backtrader from metaclasses to modern patterns')
    parser.add_argument('directory', help='Directory to scan for metaclass usage')
    parser.add_argument('--output', '-o', help='Output file for migration report')
    parser.add_argument('--template', '-t', help='Generate template for specific class:metaclass')
    
    args = parser.parse_args()
    
    migrator = MetaclassMigrator()
    
    if args.template:
        if ':' in args.template:
            class_name, metaclass_name = args.template.split(':', 1)
            template = migrator.create_migration_template(class_name, metaclass_name)
            print(template)
        else:
            print("Template format should be 'ClassName:MetaclassName'")
        return
    
    # Scan directory
    print(f"Scanning {args.directory} for metaclass usage...")
    scan_results = migrator.scan_directory(args.directory)
    
    if not scan_results:
        print("No files needing metaclass migration found.")
        return
    
    # Generate report
    report = migrator.generate_migration_report(scan_results)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Migration report written to {args.output}")
    else:
        print(report)


if __name__ == '__main__':
    main()