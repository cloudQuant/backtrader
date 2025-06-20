#!/usr/bin/env python3
"""
深入分析backtrader项目中的元类使用情况
重点关注MetaLineRoot和MetaLineSeries的具体使用模式
"""

import ast
import os
import sys
from pathlib import Path
from collections import defaultdict, Counter
import re

class MetaclassAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.classes = []
        self.imports = []
        self.metaclass_usage = defaultdict(list)
        self.inheritance_chains = []
        self.method_overrides = defaultdict(list)
        self.current_file = None

    def analyze_file(self, filepath):
        self.current_file = filepath
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the AST
            tree = ast.parse(content)
            self.visit(tree)
            
        except Exception as e:
            print(f"Error analyzing {filepath}: {e}")

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append({
                'type': 'import',
                'module': alias.name,
                'asname': alias.asname,
                'file': self.current_file
            })

    def visit_ImportFrom(self, node):
        if node.module:
            for alias in node.names:
                self.imports.append({
                    'type': 'from_import',
                    'module': node.module,
                    'name': alias.name,
                    'asname': alias.asname,
                    'file': self.current_file
                })

    def visit_ClassDef(self, node):
        # Get base classes
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(f"{base.value.id}.{base.attr}" if hasattr(base.value, 'id') else str(base.attr))

        # Check for metaclass usage
        metaclass = None
        for keyword in node.keywords:
            if keyword.arg == 'metaclass':
                if isinstance(keyword.value, ast.Name):
                    metaclass = keyword.value.id
                elif isinstance(keyword.value, ast.Attribute):
                    metaclass = f"{keyword.value.value.id}.{keyword.value.attr}" if hasattr(keyword.value.value, 'id') else str(keyword.value.attr)

        class_info = {
            'name': node.name,
            'bases': bases,
            'metaclass': metaclass,
            'file': self.current_file,
            'lineno': node.lineno,
            'methods': [method.name for method in node.body if isinstance(method, ast.FunctionDef)]
        }
        
        self.classes.append(class_info)
        
        # Track specific metaclass usage
        if metaclass in ['MetaLineRoot', 'MetaLineSeries']:
            self.metaclass_usage[metaclass].append(class_info)

        # Track inheritance from core classes
        for base in bases:
            if base in ['LineRoot', 'LineSeries', 'LineIterator', 'LineMultiple', 'LineSingle']:
                self.inheritance_chains.append({
                    'class': node.name,
                    'base': base,
                    'file': self.current_file
                })

        self.generic_visit(node)

def analyze_backtrader_structure():
    """Analyze the structure and metaclass usage in backtrader"""
    
    project_root = Path("/Users/yunjinqi/Documents/source_code/backtrader")
    analyzer = MetaclassAnalyzer()
    
    # Find all Python files
    python_files = list(project_root.rglob("*.py"))
    
    print("=== 深入分析backtrader项目中的元类使用情况 ===\n")
    
    # Analyze each file
    for filepath in python_files:
        if '/tests/' not in str(filepath) and '/tools/' not in str(filepath):  # Skip tests and tools for core analysis
            analyzer.analyze_file(filepath)
    
    # 1. 分析MetaLineRoot和MetaLineSeries的具体使用情况
    print("1. MetaLineRoot 和 MetaLineSeries 使用情况:")
    print("=" * 60)
    
    for metaclass, usages in analyzer.metaclass_usage.items():
        print(f"\n{metaclass} 被以下类使用:")
        for usage in usages:
            rel_path = str(usage['file']).replace(str(project_root), '')
            print(f"  - {usage['name']} ({rel_path}:{usage['lineno']})")
            print(f"    继承: {', '.join(usage['bases']) if usage['bases'] else 'None'}")
            if usage['methods']:
                print(f"    方法: {', '.join(usage['methods'][:5])}{'...' if len(usage['methods']) > 5 else ''}")
    
    # 2. 分析核心Line类的继承链
    print(f"\n\n2. 核心Line类的继承关系:")
    print("=" * 60)
    
    inheritance_graph = defaultdict(list)
    for chain in analyzer.inheritance_chains:
        inheritance_graph[chain['base']].append(chain)
    
    for base_class, inheritors in inheritance_graph.items():
        print(f"\n{base_class} 被以下类继承:")
        for inheritor in inheritors:
            rel_path = str(inheritor['file']).replace(str(project_root), '')
            print(f"  - {inheritor['class']} ({rel_path})")
    
    # 3. 分析指标系统中的使用情况
    print(f"\n\n3. 指标系统中的Line类使用情况:")
    print("=" * 60)
    
    indicator_files = [f for f in python_files if '/indicators/' in str(f)]
    indicator_usage = defaultdict(list)
    
    for cls in analyzer.classes:
        if '/indicators/' in str(cls['file']):
            for base in cls['bases']:
                if base in ['Indicator', 'MovingAverageBase', 'LineIterator', 'LineSeries']:
                    indicator_usage[base].append(cls)
    
    for base_class, indicators in indicator_usage.items():
        print(f"\n{base_class} 在指标中的使用 ({len(indicators)} 个):")
        for ind in indicators[:10]:  # Show first 10
            rel_path = str(ind['file']).replace(str(project_root), '')
            print(f"  - {ind['name']} ({rel_path})")
        if len(indicators) > 10:
            print(f"  ... 还有 {len(indicators) - 10} 个")
    
    # 4. 分析策略和观察者系统
    print(f"\n\n4. 策略和观察者系统中的使用情况:")
    print("=" * 60)
    
    strategy_observer_usage = defaultdict(list)
    for cls in analyzer.classes:
        for base in cls['bases']:
            if base in ['Strategy', 'StrategyBase', 'Observer', 'ObserverBase']:
                strategy_observer_usage[base].append(cls)
    
    for base_class, classes in strategy_observer_usage.items():
        print(f"\n{base_class} 的使用情况 ({len(classes)} 个):")
        for cls in classes:
            rel_path = str(cls['file']).replace(str(project_root), '')
            print(f"  - {cls['name']} ({rel_path})")
    
    # 5. 分析现代化替代方案的使用情况
    print(f"\n\n5. 现代化替代方案的使用情况:")
    print("=" * 60)
    
    modern_classes = ['ModernLineRoot', 'ModernLineSeries', 'ModernLineIterator']
    modern_usage = defaultdict(list)
    
    for cls in analyzer.classes:
        for base in cls['bases']:
            if base in modern_classes:
                modern_usage[base].append(cls)
        if cls['name'] in modern_classes:
            modern_usage[cls['name']].append(cls)
    
    if modern_usage:
        for modern_class, usages in modern_usage.items():
            print(f"\n{modern_class} 的使用情况:")
            for usage in usages:
                rel_path = str(usage['file']).replace(str(project_root), '')
                print(f"  - {usage['name']} ({rel_path})")
    else:
        print("\n目前没有发现现代化替代方案的实际使用。")
    
    # 6. 风险评估和迁移建议
    print(f"\n\n6. 风险评估和迁移建议:")
    print("=" * 60)
    
    # Count total classes using old vs new patterns
    old_metaclass_classes = len([cls for cls in analyzer.classes if cls['metaclass'] in ['MetaLineRoot', 'MetaLineSeries']])
    line_inheritors = len([cls for cls in analyzer.classes if any(base in ['LineRoot', 'LineSeries', 'LineIterator'] for base in cls['bases'])])
    
    print(f"\n统计信息:")
    print(f"- 直接使用MetaLineRoot/MetaLineSeries的类: {old_metaclass_classes}")
    print(f"- 继承自LineRoot/LineSeries/LineIterator的类: {line_inheritors}")
    print(f"- 总的指标文件数: {len(indicator_files)}")
    
    print(f"\n迁移风险评估:")
    print("- 🔴 高风险: 核心类 LineRoot, LineSeries, LineIterator (基础设施)")
    print("- 🟡 中风险: Indicator, Strategy, Observer 基类 (框架核心)")
    print("- 🟢 低风险: 具体指标实现 (用户层)")
    
    print(f"\n迁移建议:")
    print("1. 第一阶段 - 建立现代化兼容层:")
    print("   - 完善 ModernLineRoot, ModernLineSeries, ModernLineIterator")
    print("   - 提供向后兼容的别名和适配器")
    print("   - 添加详细的测试覆盖")
    
    print("2. 第二阶段 - 逐步迁移用户代码:")
    print("   - 首先迁移具体指标实现")
    print("   - 提供迁移工具和文档")
    print("   - 保持API兼容性")
    
    print("3. 第三阶段 - 核心架构现代化:")
    print("   - 迁移基础类到现代实现")
    print("   - 移除元类依赖")
    print("   - 性能优化和清理")
    
    return analyzer

def analyze_third_party_impact():
    """分析第三方扩展可能的影响"""
    print(f"\n\n7. 第三方扩展影响分析:")
    print("=" * 60)
    
    print("可能受影响的第三方扩展模式:")
    print("- 自定义指标 (继承自 Indicator)")
    print("- 自定义策略 (继承自 Strategy)")
    print("- 自定义数据源 (继承自 DataSeries)")
    print("- 自定义观察者 (继承自 Observer)")
    
    print("\n兼容性保证措施:")
    print("- 保持所有公共API不变")
    print("- 保持导入路径不变") 
    print("- 保持类名和方法名不变")
    print("- 添加弃用警告而非立即移除")
    print("- 提供迁移指南和工具")

if __name__ == "__main__":
    analyzer = analyze_backtrader_structure()
    analyze_third_party_impact()
    
    print(f"\n\n分析完成。发现的关键信息:")
    print("- 项目中元类使用集中在核心基础类")
    print("- 大量用户代码通过继承间接使用元类功能")
    print("- 需要谨慎设计兼容层以确保平滑迁移")
    print("- 建议采用渐进式迁移策略")