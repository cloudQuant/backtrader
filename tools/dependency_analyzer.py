#!/usr/bin/env python3
"""
Backtrader Class Dependency Analyzer

分析backtrader项目中的类依赖关系，生成依赖图，识别关键路径和风险点。
"""

import os
import sys
import ast
import json
import re
from typing import Dict, List, Set, Any, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict, deque
import networkx as nx

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class ClassInfo:
    """类信息"""
    name: str
    file_path: str
    line_number: int
    base_classes: List[str] = field(default_factory=list)
    metaclass: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    has_metaprogramming: bool = False
    metaprogramming_types: List[str] = field(default_factory=list)


@dataclass
class DependencyEdge:
    """依赖边"""
    source: str
    target: str
    edge_type: str  # 'inheritance', 'composition', 'import', 'metaclass'
    file_path: str
    line_number: int


@dataclass
class RiskAssessment:
    """风险评估"""
    class_name: str
    risk_level: str  # 'low', 'medium', 'high', 'critical'
    risk_factors: List[str]
    dependent_classes: int
    complexity_score: float


class ClassDependencyAnalyzer(ast.NodeVisitor):
    """类依赖分析器"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.classes: Dict[str, ClassInfo] = {}
        self.dependencies: List[DependencyEdge] = []
        self.imports: Dict[str, str] = {}  # alias -> full_name
        self.current_class: Optional[str] = None
        
        # 已知的元类
        self.known_metaclasses = {
            'MetaBase', 'MetaParams', 'MetaLineSeries', 'MetaSingleton',
            'MetaIndicator', 'MetaStrategy', 'MetaAnalyzer', 'MetaObserver'
        }
    
    def visit_Import(self, node: ast.Import):
        """处理import语句"""
        for alias in node.names:
            name = alias.name
            as_name = alias.asname or name.split('.')[-1]
            self.imports[as_name] = name
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """处理from import语句"""
        module = node.module or ''
        for alias in node.names:
            name = alias.name
            as_name = alias.asname or name
            full_name = f"{module}.{name}" if module else name
            self.imports[as_name] = full_name
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """访问类定义"""
        class_name = node.name
        self.current_class = class_name
        
        # 解析基类
        base_classes = []
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name:
                # 解析导入的基类
                resolved_name = self.imports.get(base_name, base_name)
                base_classes.append(resolved_name)
                
                # 添加继承依赖
                self.dependencies.append(DependencyEdge(
                    source=class_name,
                    target=base_name,
                    edge_type='inheritance',
                    file_path=self.file_path,
                    line_number=node.lineno
                ))
        
        # 解析元类
        metaclass = None
        if hasattr(node, 'metaclass') and node.metaclass:
            metaclass = self._get_name(node.metaclass)
            if metaclass:
                self.dependencies.append(DependencyEdge(
                    source=class_name,
                    target=metaclass,
                    edge_type='metaclass',
                    file_path=self.file_path,
                    line_number=node.lineno
                ))
        
        # 检查元编程使用
        has_metaprogramming = False
        metaprogramming_types = []
        
        if metaclass and metaclass in self.known_metaclasses:
            has_metaprogramming = True
            metaprogramming_types.append(f'metaclass:{metaclass}')
        
        for base in base_classes:
            if any(meta in base for meta in self.known_metaclasses):
                has_metaprogramming = True
                metaprogramming_types.append(f'inheritance:{base}')
        
        # 创建类信息
        class_info = ClassInfo(
            name=class_name,
            file_path=self.file_path,
            line_number=node.lineno,
            base_classes=base_classes,
            metaclass=metaclass,
            imports=list(self.imports.keys()),
            has_metaprogramming=has_metaprogramming,
            metaprogramming_types=metaprogramming_types
        )
        
        # 分析类体
        self._analyze_class_body(node, class_info)
        
        self.classes[class_name] = class_info
        self.generic_visit(node)
        self.current_class = None
    
    def _analyze_class_body(self, node: ast.ClassDef, class_info: ClassInfo):
        """分析类体"""
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                class_info.methods.append(item.name)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_info.attributes.append(target.id)
                        
                        # 检查特殊属性
                        if target.id in ['params', 'lines']:
                            class_info.has_metaprogramming = True
                            class_info.metaprogramming_types.append(f'attribute:{target.id}')
    
    def visit_Call(self, node: ast.Call):
        """访问函数调用"""
        if self.current_class:
            func_name = self._get_name(node.func)
            if func_name and '.' in func_name:
                # 可能是对其他类的调用
                parts = func_name.split('.')
                if len(parts) >= 2:
                    target_class = parts[0]
                    if target_class in self.imports:
                        resolved_target = self.imports[target_class]
                        self.dependencies.append(DependencyEdge(
                            source=self.current_class,
                            target=resolved_target,
                            edge_type='composition',
                            file_path=self.file_path,
                            line_number=node.lineno
                        ))
        
        self.generic_visit(node)
    
    def _get_name(self, node):
        """获取节点名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return None


class ProjectDependencyAnalyzer:
    """项目依赖分析器"""
    
    def __init__(self, project_root: str = '.'):
        self.project_root = os.path.abspath(project_root)
        self.all_classes: Dict[str, ClassInfo] = {}
        self.all_dependencies: List[DependencyEdge] = []
        self.dependency_graph = nx.DiGraph()
        self.inheritance_graph = nx.DiGraph()
        self.composition_graph = nx.DiGraph()
        self.risk_assessments: List[RiskAssessment] = []
    
    def analyze_project(self):
        """分析整个项目"""
        print("开始分析backtrader项目的类依赖关系...")
        
        # 遍历项目中的Python文件
        for root, dirs, files in os.walk(self.project_root):
            # 跳过一些目录
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'build', 'dist']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_root)
                    
                    # 只分析backtrader包内的文件
                    if rel_path.startswith('backtrader' + os.sep) or file == '__init__.py':
                        try:
                            self.analyze_file(file_path, rel_path)
                        except Exception as e:
                            print(f"分析文件 {rel_path} 时出错: {e}")
        
        # 构建图
        self.build_graphs()
        
        # 风险评估
        self.assess_risks()
    
    def analyze_file(self, file_path: str, rel_path: str):
        """分析单个文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            analyzer = ClassDependencyAnalyzer(rel_path)
            analyzer.visit(tree)
            
            # 收集结果
            self.all_classes.update(analyzer.classes)
            self.all_dependencies.extend(analyzer.dependencies)
            
        except Exception as e:
            print(f"无法解析文件 {rel_path}: {e}")
    
    def build_graphs(self):
        """构建依赖图"""
        # 总依赖图
        for dep in self.all_dependencies:
            self.dependency_graph.add_edge(dep.source, dep.target, 
                                         edge_type=dep.edge_type,
                                         file_path=dep.file_path,
                                         line_number=dep.line_number)
        
        # 继承图
        for dep in self.all_dependencies:
            if dep.edge_type in ['inheritance', 'metaclass']:
                self.inheritance_graph.add_edge(dep.source, dep.target,
                                              edge_type=dep.edge_type)
        
        # 组合图
        for dep in self.all_dependencies:
            if dep.edge_type == 'composition':
                self.composition_graph.add_edge(dep.source, dep.target)
    
    def assess_risks(self):
        """评估重构风险"""
        self.risk_assessments = []
        
        for class_name, class_info in self.all_classes.items():
            risk_factors = []
            risk_level = 'low'
            complexity_score = 0.0
            
            # 计算依赖此类的类的数量
            dependent_classes = len([dep for dep in self.all_dependencies 
                                   if dep.target == class_name])
            
            # 风险因素评估
            if class_info.has_metaprogramming:
                risk_factors.append('使用元编程')
                complexity_score += 2.0
            
            if class_info.metaclass:
                risk_factors.append(f'使用元类: {class_info.metaclass}')
                complexity_score += 3.0
            
            if len(class_info.base_classes) > 2:
                risk_factors.append('多重继承')
                complexity_score += 1.5
            
            if dependent_classes > 10:
                risk_factors.append(f'被{dependent_classes}个类依赖')
                complexity_score += 1.0
            
            if len(class_info.methods) > 20:
                risk_factors.append('方法数量过多')
                complexity_score += 0.5
            
            # 检查是否在关键路径上
            if self.is_in_critical_path(class_name):
                risk_factors.append('位于关键路径')
                complexity_score += 2.0
            
            # 确定风险级别
            if complexity_score >= 6.0:
                risk_level = 'critical'
            elif complexity_score >= 4.0:
                risk_level = 'high'
            elif complexity_score >= 2.0:
                risk_level = 'medium'
            
            assessment = RiskAssessment(
                class_name=class_name,
                risk_level=risk_level,
                risk_factors=risk_factors,
                dependent_classes=dependent_classes,
                complexity_score=complexity_score
            )
            
            self.risk_assessments.append(assessment)
        
        # 按风险级别排序
        self.risk_assessments.sort(key=lambda x: x.complexity_score, reverse=True)
    
    def is_in_critical_path(self, class_name: str) -> bool:
        """检查类是否在关键路径上"""
        # 关键类列表（核心框架类）
        critical_classes = {
            'Cerebro', 'Strategy', 'Indicator', 'LineSeriesBase', 'DataBase',
            'BrokerBase', 'FeedBase', 'MetaParams', 'MetaLineSeries'
        }
        
        if class_name in critical_classes:
            return True
        
        # 检查是否继承自关键类
        try:
            for critical in critical_classes:
                if nx.has_path(self.inheritance_graph, class_name, critical):
                    return True
                if nx.has_path(self.inheritance_graph, critical, class_name):
                    return True
        except:
            pass
        
        return False
    
    def find_inheritance_chains(self) -> Dict[str, List[str]]:
        """查找继承链"""
        chains = {}
        
        for class_name in self.all_classes:
            if class_name not in chains:
                chain = self._get_inheritance_chain(class_name)
                if len(chain) > 1:
                    chains[class_name] = chain
        
        return chains
    
    def _get_inheritance_chain(self, class_name: str) -> List[str]:
        """获取单个类的继承链"""
        chain = [class_name]
        current = class_name
        
        while True:
            parents = [dep.target for dep in self.all_dependencies 
                      if dep.source == current and dep.edge_type == 'inheritance']
            if not parents:
                break
            
            # 选择第一个父类（简化处理）
            parent = parents[0]
            if parent in chain:  # 避免循环
                break
            
            chain.append(parent)
            current = parent
        
        return chain
    
    def identify_critical_paths(self) -> List[List[str]]:
        """识别关键路径"""
        critical_paths = []
        
        # 找到核心节点
        core_nodes = ['Strategy', 'Indicator', 'Cerebro', 'DataBase', 'BrokerBase']
        
        for core in core_nodes:
            if core in self.dependency_graph:
                # 找到所有到达这个核心节点的路径
                for node in self.dependency_graph.nodes():
                    if node != core:
                        try:
                            if nx.has_path(self.dependency_graph, node, core):
                                path = nx.shortest_path(self.dependency_graph, node, core)
                                if len(path) > 2:  # 只关注较长的路径
                                    critical_paths.append(path)
                        except:
                            continue
        
        return critical_paths
    
    def generate_priority_matrix(self) -> Dict[str, Dict[str, Any]]:
        """生成实施优先级矩阵"""
        priority_matrix = {}
        
        # 按风险级别分组
        for assessment in self.risk_assessments:
            class_info = self.all_classes.get(assessment.class_name)
            if not class_info:
                continue
            
            priority_info = {
                'risk_level': assessment.risk_level,
                'complexity_score': assessment.complexity_score,
                'dependent_classes': assessment.dependent_classes,
                'metaprogramming_types': class_info.metaprogramming_types,
                'base_classes': class_info.base_classes,
                'file_path': class_info.file_path,
                'suggested_phase': self._suggest_refactor_phase(assessment, class_info),
                'prerequisites': self._find_prerequisites(class_info),
                'impact_scope': self._assess_impact_scope(assessment.class_name)
            }
            
            priority_matrix[assessment.class_name] = priority_info
        
        return priority_matrix
    
    def _suggest_refactor_phase(self, assessment: RiskAssessment, class_info: ClassInfo) -> str:
        """建议重构阶段"""
        # 根据元编程类型建议阶段
        for mp_type in class_info.metaprogramming_types:
            if 'MetaSingleton' in mp_type:
                return 'Phase 2: Singleton重构'
            elif 'MetaParams' in mp_type or 'params' in mp_type:
                return 'Phase 3: 参数系统重构'
            elif 'MetaLineSeries' in mp_type or 'lines' in mp_type:
                return 'Phase 4: Lines系统重构'
        
        # 根据风险级别
        if assessment.risk_level == 'critical':
            return 'Phase 1: 紧急处理'
        elif assessment.risk_level == 'high':
            return 'Phase 2-3: 高优先级'
        else:
            return 'Phase 4-5: 后期处理'
    
    def _find_prerequisites(self, class_info: ClassInfo) -> List[str]:
        """查找重构前置条件"""
        prerequisites = []
        
        # 基类必须先重构
        for base in class_info.base_classes:
            if any(meta in base for meta in ['Meta', 'Base']):
                prerequisites.append(f'重构基类: {base}')
        
        # 元类必须先重构
        if class_info.metaclass:
            prerequisites.append(f'重构元类: {class_info.metaclass}')
        
        return prerequisites
    
    def _assess_impact_scope(self, class_name: str) -> str:
        """评估影响范围"""
        dependent_count = len([dep for dep in self.all_dependencies 
                             if dep.target == class_name])
        
        if dependent_count >= 20:
            return '全项目影响'
        elif dependent_count >= 10:
            return '模块级影响'
        elif dependent_count >= 5:
            return '局部影响'
        else:
            return '最小影响'
    
    def generate_report(self) -> Dict[str, Any]:
        """生成分析报告"""
        inheritance_chains = self.find_inheritance_chains()
        critical_paths = self.identify_critical_paths()
        priority_matrix = self.generate_priority_matrix()
        
        report = {
            'analysis_time': datetime.now().isoformat(),
            'summary': {
                'total_classes': len(self.all_classes),
                'total_dependencies': len(self.all_dependencies),
                'inheritance_edges': len([d for d in self.all_dependencies if d.edge_type == 'inheritance']),
                'composition_edges': len([d for d in self.all_dependencies if d.edge_type == 'composition']),
                'metaclass_edges': len([d for d in self.all_dependencies if d.edge_type == 'metaclass']),
                'classes_with_metaprogramming': len([c for c in self.all_classes.values() if c.has_metaprogramming]),
                'critical_risk_classes': len([r for r in self.risk_assessments if r.risk_level == 'critical']),
                'high_risk_classes': len([r for r in self.risk_assessments if r.risk_level == 'high'])
            },
            'risk_assessments': [
                {
                    'class_name': r.class_name,
                    'risk_level': r.risk_level,
                    'complexity_score': r.complexity_score,
                    'dependent_classes': r.dependent_classes,
                    'risk_factors': r.risk_factors
                }
                for r in self.risk_assessments[:20]  # Top 20
            ],
            'inheritance_chains': {k: v for k, v in inheritance_chains.items() if len(v) > 3},
            'critical_paths': critical_paths[:10],  # Top 10
            'priority_matrix': priority_matrix,
            'phase_distribution': self._get_phase_distribution(priority_matrix),
            'dependency_statistics': self._get_dependency_statistics()
        }
        
        return report
    
    def _get_phase_distribution(self, priority_matrix: Dict) -> Dict[str, int]:
        """获取各阶段的类分布"""
        distribution = defaultdict(int)
        for info in priority_matrix.values():
            distribution[info['suggested_phase']] += 1
        return dict(distribution)
    
    def _get_dependency_statistics(self) -> Dict[str, Any]:
        """获取依赖统计信息"""
        # 入度统计（被依赖）
        in_degrees = defaultdict(int)
        out_degrees = defaultdict(int)
        
        for dep in self.all_dependencies:
            in_degrees[dep.target] += 1
            out_degrees[dep.source] += 1
        
        # 最高入度（最被依赖的类）
        top_depended = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # 最高出度（依赖最多其他类的类）
        top_depending = sorted(out_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            'most_depended_classes': top_depended,
            'most_depending_classes': top_depending,
            'average_in_degree': sum(in_degrees.values()) / len(in_degrees) if in_degrees else 0,
            'average_out_degree': sum(out_degrees.values()) / len(out_degrees) if out_degrees else 0
        }
    
    def save_report(self, report: Dict[str, Any]):
        """保存分析报告"""
        os.makedirs('analysis_results', exist_ok=True)
        filename = f"analysis_results/dependency_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"依赖分析报告已保存到: {filename}")
        return filename
    
    def print_summary(self, report: Dict[str, Any]):
        """打印分析摘要"""
        print("="*70)
        print("Backtrader 类依赖关系分析报告")
        print("="*70)
        
        summary = report['summary']
        print(f"总类数: {summary['total_classes']}")
        print(f"总依赖关系: {summary['total_dependencies']}")
        print(f"  - 继承关系: {summary['inheritance_edges']}")
        print(f"  - 组合关系: {summary['composition_edges']}")
        print(f"  - 元类关系: {summary['metaclass_edges']}")
        print(f"使用元编程的类: {summary['classes_with_metaprogramming']}")
        print(f"关键风险类: {summary['critical_risk_classes']}")
        print(f"高风险类: {summary['high_risk_classes']}")
        
        print("\n🚨 最高风险类 (Top 10):")
        print("-"*50)
        print(f"{'类名':<25} {'风险级别':<10} {'复杂度':<8} {'被依赖数':<8}")
        print("-"*50)
        for risk in report['risk_assessments'][:10]:
            print(f"{risk['class_name']:<25} {risk['risk_level']:<10} "
                  f"{risk['complexity_score']:<8.1f} {risk['dependent_classes']:<8}")
        
        print("\n📊 阶段分布:")
        print("-"*30)
        for phase, count in report['phase_distribution'].items():
            print(f"{phase}: {count} 个类")
        
        print("\n🔗 最被依赖的类 (Top 5):")
        print("-"*30)
        for class_name, count in report['dependency_statistics']['most_depended_classes'][:5]:
            print(f"{class_name}: {count} 个依赖")


def main():
    """主函数"""
    print("开始分析backtrader项目依赖关系...")
    
    analyzer = ProjectDependencyAnalyzer()
    analyzer.analyze_project()
    
    report = analyzer.generate_report()
    analyzer.print_summary(report)
    analyzer.save_report(report)
    
    print("\nDay 5-7任务完成！")


if __name__ == '__main__':
    # 检查是否安装了networkx
    try:
        import networkx
    except ImportError:
        print("请安装networkx: pip install networkx")
        sys.exit(1)
    
    main() 