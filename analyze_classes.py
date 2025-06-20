#!/usr/bin/env python3
"""
Analyze all Python classes in the backtrader package to build a comprehensive
inheritance hierarchy and identify metaclass usage.
"""

import ast
import os
import re
from collections import defaultdict, OrderedDict
from typing import Dict, List, Tuple, Set

class ClassAnalyzer(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.classes = []
        self.imports = []
        self.current_class = None
        
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        if node.module:
            for alias in node.names:
                self.imports.append(f"{node.module}.{alias.name}")
        self.generic_visit(node)
        
    def visit_ClassDef(self, node):
        # Extract base classes
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(self._get_attribute_name(base))
            elif isinstance(base, ast.Call):
                # Handle metaclass calls like with_metaclass(MetaClass, BaseClass)
                if isinstance(base.func, ast.Name) and base.func.id == 'with_metaclass':
                    if len(base.args) >= 2:
                        metaclass = self._get_node_name(base.args[0])
                        base_class = self._get_node_name(base.args[1])
                        bases.append(f"with_metaclass({metaclass}, {base_class})")
                else:
                    bases.append(self._get_node_name(base))
        
        # Check for metaclass in keywords
        metaclass = None
        for keyword in node.keywords:
            if keyword.arg == 'metaclass':
                metaclass = self._get_node_name(keyword.value)
        
        # Look for with_metaclass pattern in bases
        uses_metaclass = any('with_metaclass' in base for base in bases)
        
        class_info = {
            'name': node.name,
            'bases': bases,
            'metaclass': metaclass,
            'uses_metaclass': uses_metaclass or metaclass is not None,
            'file': self.filename,
            'lineno': node.lineno,
            'docstring': ast.get_docstring(node),
            'methods': []
        }
        
        # Extract method names
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                class_info['methods'].append(child.name)
        
        self.classes.append(class_info)
        self.generic_visit(node)
    
    def _get_attribute_name(self, node):
        """Get the full name of an attribute like a.b.c"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attribute_name(node.value)}.{node.attr}"
        return str(node)
    
    def _get_node_name(self, node):
        """Get the name from various AST node types"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_attribute_name(node)
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Str):  # Python < 3.8
            return str(node.s)
        return str(node)

def analyze_file(filepath: str) -> List[Dict]:
    """Analyze a single Python file for class definitions"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        analyzer = ClassAnalyzer(filepath)
        analyzer.visit(tree)
        return analyzer.classes
    except Exception as e:
        print(f"Error analyzing {filepath}: {e}")
        return []

def find_python_files(directory: str) -> List[str]:
    """Find all Python files in the directory"""
    python_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files

def build_inheritance_tree(all_classes: List[Dict]) -> Dict:
    """Build inheritance relationships"""
    # Create class name to class info mapping
    class_map = {}
    for cls in all_classes:
        class_map[cls['name']] = cls
    
    # Build inheritance relationships
    inheritance = defaultdict(list)  # parent -> [children]
    child_to_parent = {}  # child -> parent
    
    for cls in all_classes:
        for base in cls['bases']:
            # Clean up base class name
            if 'with_metaclass' in base:
                # Extract actual base class from with_metaclass call
                match = re.search(r'with_metaclass\([^,]+,\s*([^)]+)\)', base)
                if match:
                    base = match.group(1).strip()
            
            # Remove module prefixes for known classes
            base_clean = base.split('.')[-1]
            if base_clean in class_map:
                inheritance[base_clean].append(cls['name'])
                child_to_parent[cls['name']] = base_clean
    
    return inheritance, child_to_parent

def generate_markdown_report(all_classes: List[Dict], inheritance: Dict, child_to_parent: Dict) -> str:
    """Generate detailed markdown report"""
    
    # Count statistics
    total_classes = len(all_classes)
    metaclass_classes = [cls for cls in all_classes if cls['uses_metaclass']]
    
    # Group classes by file
    classes_by_file = defaultdict(list)
    for cls in all_classes:
        relative_path = cls['file'].replace('/Users/yunjinqi/Documents/source_code/backtrader/backtrader/', '')
        classes_by_file[relative_path].append(cls)
    
    # Find root classes (no parents in our codebase)
    root_classes = []
    for cls in all_classes:
        is_root = True
        for base in cls['bases']:
            base_clean = base.split('.')[-1]
            if 'with_metaclass' in base:
                match = re.search(r'with_metaclass\([^,]+,\s*([^)]+)\)', base)
                if match:
                    base_clean = match.group(1).strip().split('.')[-1]
            if base_clean in [c['name'] for c in all_classes]:
                is_root = False
                break
        if is_root:
            root_classes.append(cls)
    
    report = f"""# Backtrader 类继承关系分析报告

## 总体统计

- **总类数量**: {total_classes}
- **使用元类的类数量**: {len(metaclass_classes)}
- **根类数量**: {len(root_classes)}
- **核心文件数量**: {len(classes_by_file)}

## 1. 元类和元编程技术

### 1.1 元类定义

以下类定义了元类或使用了元编程技术：

"""
    
    for cls in metaclass_classes:
        relative_path = cls['file'].replace('/Users/yunjinqi/Documents/source_code/backtrader/backtrader/', '')
        report += f"- **{cls['name']}** ({relative_path}:{cls['lineno']})\n"
        if cls['metaclass']:
            report += f"  - 显式元类: `{cls['metaclass']}`\n"
        if cls['uses_metaclass']:
            report += f"  - 使用 with_metaclass 或其他元编程技术\n"
        if cls['bases']:
            report += f"  - 基类: {', '.join(cls['bases'])}\n"
        report += "\n"
    
    report += "\n### 1.2 主要元类层次结构\n\n"
    
    # Show metaclass hierarchy
    metaclass_names = {'MetaBase', 'MetaParams', 'MetaLineRoot', 'MetaLineSeries', 
                      'MetaLineIterator', 'MetaStrategy', 'MetaIndicator', 'MetaAbstractDataBase'}
    
    for metaclass in metaclass_names:
        metaclass_obj = next((cls for cls in all_classes if cls['name'] == metaclass), None)
        if metaclass_obj:
            report += f"#### {metaclass}\n"
            relative_path = metaclass_obj['file'].replace('/Users/yunjinqi/Documents/source_code/backtrader/backtrader/', '')
            report += f"- 文件: `{relative_path}`\n"
            report += f"- 基类: {', '.join(metaclass_obj['bases']) if metaclass_obj['bases'] else 'type'}\n"
            
            # Find classes using this metaclass
            users = [cls for cls in all_classes if metaclass in str(cls['bases']) or cls['metaclass'] == metaclass]
            if users:
                report += "- 使用该元类的类:\n"
                for user in users[:10]:  # Limit to first 10
                    report += f"  - {user['name']}\n"
                if len(users) > 10:
                    report += f"  - ... 和其他 {len(users) - 10} 个类\n"
            report += "\n"
    
    report += "\n## 2. 核心基类层次结构\n\n"
    
    # Core base classes
    core_classes = ['LineRoot', 'LineSingle', 'LineMultiple', 'LineBuffer', 'LineActions', 
                   'LineSeries', 'LineIterator', 'IndicatorBase', 'StrategyBase', 'DataAccessor']
    
    def print_inheritance_tree(class_name, level=0, visited=None):
        if visited is None:
            visited = set()
        if class_name in visited:
            return ""
        visited.add(class_name)
        
        indent = "  " * level
        result = f"{indent}- **{class_name}**"
        
        # Find class info
        cls_info = next((cls for cls in all_classes if cls['name'] == class_name), None)
        if cls_info:
            relative_path = cls_info['file'].replace('/Users/yunjinqi/Documents/source_code/backtrader/backtrader/', '')
            result += f" (`{relative_path}`)"
        
        result += "\n"
        
        # Add children
        if class_name in inheritance:
            for child in inheritance[class_name][:5]:  # Limit children shown
                result += print_inheritance_tree(child, level + 1, visited.copy())
            if len(inheritance[class_name]) > 5:
                result += f"{'  ' * (level + 1)}- ... 和其他 {len(inheritance[class_name]) - 5} 个子类\n"
        
        return result
    
    for core_class in core_classes:
        if core_class in [cls['name'] for cls in all_classes]:
            report += print_inheritance_tree(core_class)
            report += "\n"
    
    report += "\n## 3. 按功能分类的类统计\n\n"
    
    # Categorize by functionality
    categories = {
        'Core/Meta': ['metabase.py', 'lineroot.py', 'linebuffer.py', 'lineiterator.py', 'lineseries.py'],
        'Strategy': ['strategy.py'],
        'Indicators': ['indicator.py', 'indicators/'],
        'Data/Feeds': ['feed.py', 'feeds/', 'dataseries.py'],
        'Broker': ['broker.py', 'brokers/'],
        'Analysis': ['analyzer.py', 'analyzers/'],
        'Observers': ['observer.py', 'observers/'],
        'Engine': ['cerebro.py'],
        'Utilities': ['utils/', 'plot/', 'stores/']
    }
    
    for category, patterns in categories.items():
        count = 0
        files = []
        for file_path, classes in classes_by_file.items():
            for pattern in patterns:
                if pattern in file_path:
                    count += len(classes)
                    files.append(file_path)
                    break
        report += f"### {category}\n"
        report += f"- 类数量: {count}\n"
        report += f"- 主要文件: {', '.join(files[:5])}\n"
        if len(files) > 5:
            report += f"- ... 和其他 {len(files) - 5} 个文件\n"
        report += "\n"
    
    report += "\n## 4. 详细类列表 (按文件分组)\n\n"
    
    for file_path in sorted(classes_by_file.keys()):
        classes = classes_by_file[file_path]
        report += f"### {file_path}\n\n"
        
        for cls in classes:
            report += f"#### {cls['name']}\n"
            if cls['bases']:
                report += f"- **基类**: {', '.join(cls['bases'])}\n"
            if cls['uses_metaclass']:
                report += f"- **使用元类**: 是"
                if cls['metaclass']:
                    report += f" (显式: {cls['metaclass']})"
                report += "\n"
            if cls['docstring']:
                # Truncate long docstrings
                doc = cls['docstring'][:200] + "..." if len(cls['docstring']) > 200 else cls['docstring']
                report += f"- **说明**: {doc}\n"
            
            # Show some key methods
            important_methods = [m for m in cls['methods'] if m in ['__init__', '__new__', '__call__', 'next', 'once', 'prenext']]
            if important_methods:
                report += f"- **关键方法**: {', '.join(important_methods)}\n"
            
            report += "\n"
        
        report += "\n"
    
    report += "\n## 5. 继承关系图表总结\n\n"
    
    report += """
### 元类继承链

```
type (Python 内置)
 └── MetaBase (metabase.py)
     └── MetaParams (metabase.py)
         ├── MetaLineRoot (lineroot.py)
         ├── MetaLineSeries (lineseries.py)
         ├── MetaLineIterator (lineiterator.py)
         ├── MetaStrategy (strategy.py)
         ├── MetaIndicator (indicator.py)
         └── MetaAbstractDataBase (feed.py)
```

### 核心基类继承链

```
LineRoot (lineroot.py)
 ├── LineSingle (lineroot.py)
 │   └── LineBuffer (linebuffer.py)
 │       └── LineActions (linebuffer.py)
 └── LineMultiple (lineroot.py)
     └── LineSeries (lineseries.py)
         └── LineIterator (lineiterator.py)
             ├── DataAccessor (lineiterator.py)
             │   ├── IndicatorBase (lineiterator.py)
             │   │   └── Indicator (indicator.py)
             │   ├── StrategyBase (lineiterator.py)
             │   │   └── Strategy (strategy.py)
             │   └── ObserverBase (lineiterator.py)
             └── AbstractDataBase (feed.py)
```

### 主要组件层次

1. **元编程层**: MetaBase → MetaParams → 各种具体元类
2. **数据结构层**: LineRoot → LineSingle/LineMultiple → LineBuffer/LineSeries
3. **迭代器层**: LineIterator → DataAccessor → 各种功能基类
4. **应用层**: Strategy, Indicator, Observer, DataFeed 等具体实现

"""
    
    return report

def main():
    # Analyze all Python files in backtrader directory
    backtrader_dir = "/Users/yunjinqi/Documents/source_code/backtrader/backtrader"
    python_files = find_python_files(backtrader_dir)
    
    print(f"Found {len(python_files)} Python files")
    
    all_classes = []
    for filepath in python_files:
        classes = analyze_file(filepath)
        all_classes.extend(classes)
    
    print(f"Found {len(all_classes)} classes total")
    
    # Build inheritance relationships
    inheritance, child_to_parent = build_inheritance_tree(all_classes)
    
    # Generate report
    report = generate_markdown_report(all_classes, inheritance, child_to_parent)
    
    # Write report to file
    output_file = "/Users/yunjinqi/Documents/source_code/backtrader/backtrader_class_analysis.md"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Analysis complete. Report written to: {output_file}")
    
    # Print summary
    print(f"\nSummary:")
    print(f"- Total classes: {len(all_classes)}")
    print(f"- Classes using metaclasses: {len([cls for cls in all_classes if cls['uses_metaclass']])}")
    print(f"- Inheritance relationships: {len(inheritance)}")

if __name__ == "__main__":
    main()