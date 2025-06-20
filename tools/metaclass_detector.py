#!/usr/bin/env python3
"""
Backtrader Metaclass Detection Tool

Day 8-10: 元编程检测工具
- 检测项目中的元类使用
- 分析动态类创建模式
- 生成详细的迁移报告
"""

import os
import sys
import ast
import json
import re
import importlib
import inspect
from typing import Dict, List, Set, Any, Tuple, Optional, Union
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import traceback

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class MetaclassUsage:
    """元类使用记录"""
    class_name: str
    file_path: str
    line_number: int
    metaclass_name: str
    usage_type: str  # 'explicit', 'inheritance', 'dynamic'
    complexity_level: str  # 'simple', 'medium', 'complex'
    dependent_classes: List[str] = field(default_factory=list)
    migration_strategy: str = ''
    migration_priority: int = 3  # 1-5, 1最高


@dataclass
class DynamicCreation:
    """动态类创建记录"""
    creation_id: str
    file_path: str
    line_number: int
    creation_type: str  # 'type_call', 'metaclass_direct', 'factory_pattern'
    target_class: str
    creation_code: str
    complexity_score: float
    migration_difficulty: str  # 'easy', 'medium', 'hard', 'complex'


@dataclass
class MigrationPlan:
    """迁移计划"""
    target_class: str
    current_pattern: str
    target_pattern: str
    migration_steps: List[str]
    estimated_effort: int  # hours
    prerequisites: List[str] = field(default_factory=list)
    test_requirements: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)


class MetaclassDetector(ast.NodeVisitor):
    """元类检测器"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.metaclass_usages: List[MetaclassUsage] = []
        self.dynamic_creations: List[DynamicCreation] = []
        self.imports: Dict[str, str] = {}
        self.class_definitions: Dict[str, ast.ClassDef] = {}
        
        # 已知的元类
        self.known_metaclasses = {
            'MetaBase', 'MetaParams', 'MetaLineSeries', 'MetaSingleton',
            'MetaIndicator', 'MetaStrategy', 'MetaAnalyzer', 'MetaObserver',
            'MetaBroker', 'MetaLineRoot', 'MetaLineIterator', 'MetaLineActions',
            'MetaAbstractDataBase', 'MetaCSVDataBase', 'MetaFilter',
            'MetaMovAvBase', 'MetaDataTrades', 'MetaTimeFrameAnalyzerBase',
            'MetaSigStrategy', 'MetaIBBroker', 'MetaCTPBroker', 'MetaVCBroker',
            'MetaOandaBroker', 'MetaCCXTBroker', 'MetaCryptoBroker',
            'MetaCCXTFeed', 'MetaCryptoFeed', 'MetaCTPData', 'MetaOandaData',
            'MetaRollOver', 'MetaIBData', 'MetaVCData', 'MetaVChartFile',
            'MetaChainer'
        }
        
        # 动态创建模式
        self.dynamic_patterns = [
            r'type\s*\(',  # type() calls
            r'__class__\s*=',  # class assignment
            r'setattr\s*\(\s*\w+\s*,\s*[\'"]__class__[\'"]',  # setattr __class__
            r'metaclass\s*=\s*\w+',  # metaclass assignment
            r'with_metaclass\s*\(',  # six.with_metaclass
        ]
    
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
        self.class_definitions[node.name] = node
        
        # 检查Python 3.x风格的显式元类使用 (class Foo(metaclass=Meta):)
        for keyword in getattr(node, 'keywords', []):
            if keyword.arg == 'metaclass':
                metaclass_name = self._get_name(keyword.value)
                if metaclass_name and metaclass_name in self.known_metaclasses:
                    self._record_metaclass_usage(
                        node.name, metaclass_name, node.lineno, 'explicit'
                    )
        
        # 检查通过继承获得的元类
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name and base_name in self.known_metaclasses:
                self._record_metaclass_usage(
                    node.name, base_name, node.lineno, 'inheritance'
                )
            
            # 检查已知使用元类的基类
            known_metaclass_users = {
                'ParamsBase', 'LineSeries', 'LineMultiple', 'Strategy', 
                'Indicator', 'Observer', 'Analyzer', 'Store', 'BrokerBase',
                'DataBase', 'Timer', 'Sizer', 'Filter', 'LineIterator'
            }
            if base_name and base_name in known_metaclass_users:
                # 推断使用的元类
                inferred_metaclass = self._infer_metaclass_from_base(base_name)
                if inferred_metaclass:
                    self._record_metaclass_usage(
                        node.name, inferred_metaclass, node.lineno, 'inheritance_inferred'
                    )
        
        # 检查类体中的动态创建
        self._analyze_class_body(node)
        
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call):
        """检查函数调用中的动态创建"""
        func_name = self._get_name(node.func)
        
        # 检查type()调用
        if func_name == 'type' and len(node.args) >= 3:
            self._record_dynamic_creation(
                node, 'type_call', 'Dynamic class creation with type()'
            )
        
        # 检查with_metaclass调用
        elif func_name == 'with_metaclass' or 'with_metaclass' in func_name:
            self._record_dynamic_creation(
                node, 'metaclass_direct', 'six.with_metaclass usage'
            )
        
        # 检查其他工厂模式
        elif self._is_factory_pattern(node):
            self._record_dynamic_creation(
                node, 'factory_pattern', 'Factory pattern for class creation'
            )
        
        self.generic_visit(node)
    
    def visit_Assign(self, node: ast.Assign):
        """检查赋值中的动态操作"""
        # 检查__class__赋值
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == '__class__':
                self._record_dynamic_creation(
                    node, 'class_assignment', '__class__ assignment'
                )
        
        self.generic_visit(node)
    
    def _record_metaclass_usage(self, class_name: str, metaclass_name: str, 
                               line_number: int, usage_type: str):
        """记录元类使用"""
        # 评估复杂度
        complexity_level = self._assess_metaclass_complexity(metaclass_name)
        
        # 确定迁移策略
        migration_strategy = self._determine_migration_strategy(metaclass_name)
        
        # 设置优先级
        priority = self._calculate_migration_priority(metaclass_name, usage_type)
        
        usage = MetaclassUsage(
            class_name=class_name,
            file_path=self.file_path,
            line_number=line_number,
            metaclass_name=metaclass_name,
            usage_type=usage_type,
            complexity_level=complexity_level,
            migration_strategy=migration_strategy,
            migration_priority=priority
        )
        
        self.metaclass_usages.append(usage)
    
    def _record_dynamic_creation(self, node: ast.AST, creation_type: str, 
                                description: str):
        """记录动态创建"""
        creation_id = f"{creation_type}_{node.lineno}_{hash(description) % 1000}"
        
        # 获取创建代码
        try:
            code = ast.unparse(node)
        except:
            code = description
        
        # 评估复杂度
        complexity_score = self._assess_dynamic_complexity(node, creation_type)
        
        # 确定迁移难度
        difficulty = self._assess_migration_difficulty(complexity_score)
        
        creation = DynamicCreation(
            creation_id=creation_id,
            file_path=self.file_path,
            line_number=node.lineno,
            creation_type=creation_type,
            target_class=self._extract_target_class(node),
            creation_code=code,
            complexity_score=complexity_score,
            migration_difficulty=difficulty
        )
        
        self.dynamic_creations.append(creation)
    
    def _analyze_class_body(self, node: ast.ClassDef):
        """分析类体中的特殊模式"""
        for item in node.body:
            # 检查特殊方法
            if isinstance(item, ast.FunctionDef):
                if item.name in ['__new__', '__init_subclass__', '__metaclass__']:
                    self._record_metaclass_usage(
                        node.name, f'special_method_{item.name}', 
                        item.lineno, 'special_method'
                    )
            
            # 检查类变量中的元类引用
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == '__metaclass__':
                        metaclass_name = self._get_name(item.value)
                        if metaclass_name:
                            self._record_metaclass_usage(
                                node.name, metaclass_name, item.lineno, 'class_variable'
                            )
    
    def _assess_metaclass_complexity(self, metaclass_name: str) -> str:
        """评估元类复杂度"""
        complex_metaclasses = {
            'MetaLineSeries', 'MetaIndicator', 'MetaStrategy', 'MetaBase'
        }
        medium_metaclasses = {
            'MetaParams', 'MetaBroker', 'MetaObserver', 'MetaAnalyzer'
        }
        
        if metaclass_name in complex_metaclasses:
            return 'complex'
        elif metaclass_name in medium_metaclasses:
            return 'medium'
        else:
            return 'simple'
    
    def _determine_migration_strategy(self, metaclass_name: str) -> str:
        """确定迁移策略"""
        strategies = {
            'MetaSingleton': 'Replace with SingletonMixin',
            'MetaParams': 'Replace with ParameterDescriptor',
            'MetaLineSeries': 'Replace with LineDescriptor',
            'MetaIndicator': 'Refactor to composition-based approach',
            'MetaStrategy': 'Use dependency injection pattern',
            'MetaBroker': 'Implement broker registry pattern',
            'MetaBase': 'Remove and simplify class creation'
        }
        
        return strategies.get(metaclass_name, 'Manual refactoring required')
    
    def _calculate_migration_priority(self, metaclass_name: str, usage_type: str) -> int:
        """计算迁移优先级"""
        # 基础优先级
        base_priority = {
            'MetaSingleton': 2,
            'MetaParams': 1,
            'MetaLineSeries': 1,
            'MetaIndicator': 2,
            'MetaStrategy': 2,
            'MetaBase': 1
        }.get(metaclass_name, 3)
        
        # 根据使用类型调整
        if usage_type == 'explicit':
            return base_priority
        elif usage_type == 'inheritance':
            return min(base_priority + 1, 5)
        else:
            return min(base_priority + 2, 5)
    
    def _assess_dynamic_complexity(self, node: ast.AST, creation_type: str) -> float:
        """评估动态创建复杂度"""
        base_score = {
            'type_call': 3.0,
            'metaclass_direct': 4.0,
            'factory_pattern': 2.0,
            'class_assignment': 5.0
        }.get(creation_type, 2.0)
        
        # 根据节点复杂度调整
        if hasattr(node, 'args') and len(node.args) > 3:
            base_score += 1.0
        
        if hasattr(node, 'keywords') and len(node.keywords) > 2:
            base_score += 0.5
        
        return min(base_score, 5.0)
    
    def _assess_migration_difficulty(self, complexity_score: float) -> str:
        """评估迁移难度"""
        if complexity_score >= 4.0:
            return 'complex'
        elif complexity_score >= 3.0:
            return 'hard'
        elif complexity_score >= 2.0:
            return 'medium'
        else:
            return 'easy'
    
    def _is_factory_pattern(self, node: ast.Call) -> bool:
        """检查是否是工厂模式"""
        func_name = self._get_name(node.func)
        if not func_name:
            return False
        
        factory_patterns = [
            'create_class', 'make_class', 'build_class',
            'class_factory', 'type_factory'
        ]
        
        return any(pattern in func_name.lower() for pattern in factory_patterns)
    
    def _extract_target_class(self, node: ast.AST) -> str:
        """提取目标类名"""
        if isinstance(node, ast.Call):
            if hasattr(node, 'args') and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant):
                    return str(first_arg.value)
                elif isinstance(first_arg, ast.Name):
                    return first_arg.id
        
        return 'unknown'
    
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
    
    def _infer_metaclass_from_base(self, base_name: str) -> Optional[str]:
        """从基类推断元类"""
        metaclass_mapping = {
            'ParamsBase': 'MetaParams',
            'LineSeries': 'MetaLineSeries', 
            'LineMultiple': 'MetaLineSeries',
            'Strategy': 'MetaStrategy',
            'Indicator': 'MetaIndicator',
            'Observer': 'MetaObserver',
            'Analyzer': 'MetaAnalyzer',
            'Store': 'MetaSingleton',
            'BrokerBase': 'MetaBroker',
            'DataBase': 'MetaAbstractDataBase',
            'Timer': 'MetaParams',
            'Sizer': 'MetaParams',
            'Filter': 'MetaParams',
            'LineIterator': 'MetaLineIterator'
        }
        return metaclass_mapping.get(base_name)


class MetaclassDetectionTool:
    """元编程检测工具主类"""
    
    def __init__(self, project_root: str = '.'):
        self.project_root = os.path.abspath(project_root)
        self.all_metaclass_usages: List[MetaclassUsage] = []
        self.all_dynamic_creations: List[DynamicCreation] = []
        self.migration_plans: List[MigrationPlan] = []
        self.file_analysis: Dict[str, Dict] = {}
    
    def detect_metaclass_usage(self):
        """检测项目中的元类使用"""
        print("开始检测元类使用...")
        
        for root, dirs, files in os.walk(self.project_root):
            # 跳过一些目录
            dirs[:] = [d for d in dirs if not d.startswith('.') and 
                      d not in ['__pycache__', 'build', 'dist', 'tests']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_root)
                    
                    # 只分析backtrader包内的文件
                    if rel_path.startswith('backtrader' + os.sep) or file in ['__init__.py']:
                        try:
                            self.analyze_file(file_path, rel_path)
                        except Exception as e:
                            print(f"分析文件 {rel_path} 时出错: {e}")
    
    def analyze_file(self, file_path: str, rel_path: str):
        """分析单个文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 先用正则表达式快速扫描元类使用
            self._regex_scan_metaclass_usage(content, rel_path)
            
            # AST分析
            tree = ast.parse(content)
            detector = MetaclassDetector(rel_path)
            detector.visit(tree)
            
            # 收集结果
            self.all_metaclass_usages.extend(detector.metaclass_usages)
            self.all_dynamic_creations.extend(detector.dynamic_creations)
            
            # 文件级统计
            self.file_analysis[rel_path] = {
                'metaclass_count': len(detector.metaclass_usages),
                'dynamic_creation_count': len(detector.dynamic_creations),
                'complexity_score': self._calculate_file_complexity(detector)
            }
            
        except Exception as e:
            print(f"无法解析文件 {rel_path}: {e}")
    
    def _regex_scan_metaclass_usage(self, content: str, file_path: str):
        """使用正则表达式扫描元类使用"""
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            # 检查metaclass=语法
            metaclass_match = re.search(r'metaclass\s*=\s*(\w+)', line)
            if metaclass_match:
                metaclass_name = metaclass_match.group(1)
                if metaclass_name in {
                    'MetaBase', 'MetaParams', 'MetaLineSeries', 'MetaSingleton',
                    'MetaIndicator', 'MetaStrategy', 'MetaAnalyzer', 'MetaObserver',
                    'MetaBroker', 'MetaLineRoot', 'MetaLineIterator', 'MetaLineActions',
                    'MetaAbstractDataBase', 'MetaCSVDataBase', 'MetaFilter',
                    'MetaMovAvBase', 'MetaDataTrades', 'MetaTimeFrameAnalyzerBase',
                    'MetaSigStrategy', 'MetaIBBroker', 'MetaCTPBroker', 'MetaVCBroker',
                    'MetaOandaBroker', 'MetaCCXTBroker', 'MetaCryptoBroker',
                    'MetaCCXTFeed', 'MetaCryptoFeed', 'MetaCTPData', 'MetaOandaData',
                    'MetaRollOver', 'MetaIBData', 'MetaVCData', 'MetaVChartFile',
                    'MetaChainer'
                }:
                    # 提取类名
                    class_match = re.search(r'class\s+(\w+)', line)
                    class_name = class_match.group(1) if class_match else 'unknown'
                    
                    usage = MetaclassUsage(
                        class_name=class_name,
                        file_path=file_path,
                        line_number=line_num,
                        metaclass_name=metaclass_name,
                        usage_type='explicit_regex',
                        complexity_level=self._assess_metaclass_complexity_quick(metaclass_name),
                        migration_strategy=self._determine_migration_strategy_quick(metaclass_name),
                        migration_priority=self._calculate_migration_priority_quick(metaclass_name)
                    )
                    
                    self.all_metaclass_usages.append(usage)
            
            # 检查class定义中的继承
            class_inherit_match = re.search(r'class\s+(\w+)\s*\([^)]*(\w*Meta\w*)[^)]*\)', line)
            if class_inherit_match:
                class_name = class_inherit_match.group(1)
                inherited_name = class_inherit_match.group(2)
                
                if 'Meta' in inherited_name:
                    usage = MetaclassUsage(
                        class_name=class_name,
                        file_path=file_path,
                        line_number=line_num,
                        metaclass_name=inherited_name,
                        usage_type='inheritance_regex',
                        complexity_level=self._assess_metaclass_complexity_quick(inherited_name),
                        migration_strategy=self._determine_migration_strategy_quick(inherited_name),
                        migration_priority=self._calculate_migration_priority_quick(inherited_name)
                    )
                    
                    self.all_metaclass_usages.append(usage)
    
    def _assess_metaclass_complexity_quick(self, metaclass_name: str) -> str:
        """快速评估元类复杂度"""
        complex_metaclasses = {'MetaLineSeries', 'MetaIndicator', 'MetaStrategy', 'MetaBase'}
        medium_metaclasses = {'MetaParams', 'MetaBroker', 'MetaObserver', 'MetaAnalyzer'}
        
        if metaclass_name in complex_metaclasses:
            return 'complex'
        elif metaclass_name in medium_metaclasses:
            return 'medium'
        else:
            return 'simple'
    
    def _determine_migration_strategy_quick(self, metaclass_name: str) -> str:
        """快速确定迁移策略"""
        strategies = {
            'MetaSingleton': 'Replace with SingletonMixin',
            'MetaParams': 'Replace with ParameterDescriptor',
            'MetaLineSeries': 'Replace with LineDescriptor',
            'MetaIndicator': 'Refactor to composition-based approach',
            'MetaStrategy': 'Use dependency injection pattern',
            'MetaBroker': 'Implement broker registry pattern',
            'MetaBase': 'Remove and simplify class creation'
        }
        return strategies.get(metaclass_name, 'Manual refactoring required')
    
    def _calculate_migration_priority_quick(self, metaclass_name: str) -> int:
        """快速计算迁移优先级"""
        priority_map = {
            'MetaSingleton': 2,
            'MetaParams': 1, 
            'MetaLineSeries': 1,
            'MetaIndicator': 2,
            'MetaStrategy': 2,
            'MetaBase': 1
        }
        return priority_map.get(metaclass_name, 3)
    
    def analyze_dynamic_creation(self):
        """分析动态类创建模式"""
        print("分析动态类创建模式...")
        
        # 按类型分组分析
        creation_types = defaultdict(list)
        for creation in self.all_dynamic_creations:
            creation_types[creation.creation_type].append(creation)
        
        # 分析每种类型的模式
        for creation_type, creations in creation_types.items():
            print(f"  {creation_type}: {len(creations)} 个实例")
            
            # 复杂度分析
            complexities = [c.complexity_score for c in creations]
            if complexities:
                avg_complexity = sum(complexities) / len(complexities)
                print(f"    平均复杂度: {avg_complexity:.2f}")
    
    def generate_migration_report(self) -> Dict[str, Any]:
        """生成迁移报告"""
        print("生成迁移报告...")
        
        # 生成迁移计划
        self._generate_migration_plans()
        
        # 统计信息
        report = {
            'analysis_time': datetime.now().isoformat(),
            'summary': {
                'total_files_analyzed': len(self.file_analysis),
                'total_metaclass_usages': len(self.all_metaclass_usages),
                'total_dynamic_creations': len(self.all_dynamic_creations),
                'total_migration_plans': len(self.migration_plans),
                'high_priority_migrations': len([u for u in self.all_metaclass_usages if u.migration_priority <= 2]),
                'complex_migrations': len([u for u in self.all_metaclass_usages if u.complexity_level == 'complex'])
            },
            'metaclass_breakdown': self._get_metaclass_breakdown(),
            'dynamic_creation_breakdown': self._get_dynamic_creation_breakdown(),
            'migration_plans': [
                {
                    'target_class': plan.target_class,
                    'current_pattern': plan.current_pattern,
                    'target_pattern': plan.target_pattern,
                    'estimated_effort': plan.estimated_effort,
                    'migration_steps': plan.migration_steps,
                    'prerequisites': plan.prerequisites,
                    'risk_factors': plan.risk_factors
                }
                for plan in self.migration_plans
            ],
            'priority_matrix': self._generate_priority_matrix(),
            'file_analysis': self.file_analysis,
            'recommendations': self._generate_recommendations()
        }
        
        return report
    
    def _generate_migration_plans(self):
        """生成迁移计划"""
        # 按元类分组
        metaclass_groups = defaultdict(list)
        for usage in self.all_metaclass_usages:
            metaclass_groups[usage.metaclass_name].append(usage)
        
        # 为每个元类生成迁移计划
        for metaclass_name, usages in metaclass_groups.items():
            plan = self._create_migration_plan(metaclass_name, usages)
            if plan:
                self.migration_plans.append(plan)
    
    def _create_migration_plan(self, metaclass_name: str, 
                              usages: List[MetaclassUsage]) -> Optional[MigrationPlan]:
        """创建单个迁移计划"""
        if not usages:
            return None
        
        # 计算总工作量
        base_effort = len(usages) * 2  # 每个使用点2小时基础工作量
        complexity_multiplier = {
            'simple': 1.0,
            'medium': 1.5,
            'complex': 2.5
        }
        
        total_effort = 0
        for usage in usages:
            multiplier = complexity_multiplier.get(usage.complexity_level, 1.0)
            total_effort += base_effort * multiplier
        
        # 生成迁移步骤
        steps = self._generate_migration_steps(metaclass_name)
        
        # 识别前置条件
        prerequisites = self._identify_prerequisites(metaclass_name)
        
        # 识别风险因素
        risk_factors = self._identify_risk_factors(metaclass_name, usages)
        
        plan = MigrationPlan(
            target_class=metaclass_name,
            current_pattern=f"Metaclass-based: {metaclass_name}",
            target_pattern=self._get_target_pattern(metaclass_name),
            migration_steps=steps,
            estimated_effort=int(total_effort),
            prerequisites=prerequisites,
            test_requirements=self._generate_test_requirements(metaclass_name),
            risk_factors=risk_factors
        )
        
        return plan
    
    def _generate_migration_steps(self, metaclass_name: str) -> List[str]:
        """生成迁移步骤"""
        common_steps = [
            "创建备份分支",
            "编写现有功能的测试用例",
            "分析现有实现的所有功能"
        ]
        
        specific_steps = {
            'MetaSingleton': [
                "实现SingletonMixin基类",
                "替换metaclass=MetaSingleton",
                "验证单例行为",
                "测试线程安全性"
            ],
            'MetaParams': [
                "实现ParameterDescriptor",
                "创建参数管理器",
                "替换参数访问逻辑",
                "验证参数继承"
            ],
            'MetaLineSeries': [
                "实现LineDescriptor",
                "创建LineBuffer系统",
                "替换lines访问逻辑",
                "验证数据访问"
            ]
        }
        
        steps = common_steps + specific_steps.get(metaclass_name, [
            f"分析{metaclass_name}的具体功能",
            "设计替代方案",
            "逐步迁移",
            "验证功能完整性"
        ])
        
        steps.extend([
            "运行回归测试",
            "性能测试对比",
            "代码审查",
            "文档更新"
        ])
        
        return steps
    
    def _identify_prerequisites(self, metaclass_name: str) -> List[str]:
        """识别前置条件"""
        prerequisites = {
            'MetaSingleton': [
                "SingletonMixin基类实现完成"
            ],
            'MetaParams': [
                "ParameterDescriptor系统完成",
                "参数继承机制测试通过"
            ],
            'MetaLineSeries': [
                "LineDescriptor系统完成",
                "LineBuffer性能验证通过"
            ]
        }
        
        return prerequisites.get(metaclass_name, [])
    
    def _identify_risk_factors(self, metaclass_name: str, 
                              usages: List[MetaclassUsage]) -> List[str]:
        """识别风险因素"""
        risk_factors = []
        
        # 基于使用数量的风险
        if len(usages) > 10:
            risk_factors.append(f"大量使用点({len(usages)}个)，影响面广")
        
        # 基于复杂度的风险
        complex_usages = [u for u in usages if u.complexity_level == 'complex']
        if complex_usages:
            risk_factors.append(f"包含{len(complex_usages)}个复杂使用点")
        
        # 特定元类的风险
        specific_risks = {
            'MetaLineSeries': [
                "性能敏感，需要仔细验证",
                "涉及核心数据访问逻辑"
            ],
            'MetaIndicator': [
                "影响所有指标计算",
                "可能影响第三方扩展"
            ],
            'MetaStrategy': [
                "影响策略执行流程",
                "向后兼容性要求高"
            ]
        }
        
        risk_factors.extend(specific_risks.get(metaclass_name, []))
        
        return risk_factors
    
    def _generate_test_requirements(self, metaclass_name: str) -> List[str]:
        """生成测试要求"""
        base_requirements = [
            "功能完整性测试",
            "性能回归测试",
            "内存泄漏检查"
        ]
        
        specific_requirements = {
            'MetaSingleton': [
                "单例模式测试",
                "线程安全测试",
                "多进程环境测试"
            ],
            'MetaParams': [
                "参数继承测试",
                "参数验证测试",
                "默认值处理测试"
            ],
            'MetaLineSeries': [
                "数据访问测试",
                "索引操作测试",
                "大数据集性能测试"
            ]
        }
        
        return base_requirements + specific_requirements.get(metaclass_name, [])
    
    def _get_target_pattern(self, metaclass_name: str) -> str:
        """获取目标模式"""
        patterns = {
            'MetaSingleton': 'SingletonMixin + normal inheritance',
            'MetaParams': 'ParameterDescriptor + configuration system',
            'MetaLineSeries': 'LineDescriptor + buffer management',
            'MetaIndicator': 'Composition-based indicator system',
            'MetaStrategy': 'Dependency injection pattern'
        }
        
        return patterns.get(metaclass_name, 'Standard class inheritance')
    
    def _calculate_file_complexity(self, detector: MetaclassDetector) -> float:
        """计算文件复杂度"""
        score = 0.0
        
        # 元类使用复杂度
        for usage in detector.metaclass_usages:
            complexity_scores = {'simple': 1.0, 'medium': 2.0, 'complex': 3.0}
            score += complexity_scores.get(usage.complexity_level, 1.0)
        
        # 动态创建复杂度
        for creation in detector.dynamic_creations:
            score += creation.complexity_score
        
        return score
    
    def _get_metaclass_breakdown(self) -> Dict[str, int]:
        """获取元类使用统计"""
        breakdown = defaultdict(int)
        for usage in self.all_metaclass_usages:
            breakdown[usage.metaclass_name] += 1
        return dict(breakdown)
    
    def _get_dynamic_creation_breakdown(self) -> Dict[str, int]:
        """获取动态创建统计"""
        breakdown = defaultdict(int)
        for creation in self.all_dynamic_creations:
            breakdown[creation.creation_type] += 1
        return dict(breakdown)
    
    def _generate_priority_matrix(self) -> Dict[str, Dict[str, Any]]:
        """生成优先级矩阵"""
        matrix = {}
        
        for usage in self.all_metaclass_usages:
            key = f"{usage.metaclass_name}_{usage.class_name}"
            matrix[key] = {
                'metaclass_name': usage.metaclass_name,
                'class_name': usage.class_name,
                'file_path': usage.file_path,
                'priority': usage.migration_priority,
                'complexity': usage.complexity_level,
                'migration_strategy': usage.migration_strategy,
                'usage_type': usage.usage_type
            }
        
        return matrix
    
    def _generate_recommendations(self) -> List[str]:
        """生成建议"""
        recommendations = []
        
        # 基于统计的建议
        if len(self.all_metaclass_usages) > 50:
            recommendations.append("元类使用较多，建议分阶段进行迁移")
        
        high_priority = [u for u in self.all_metaclass_usages if u.migration_priority <= 2]
        if high_priority:
            recommendations.append(f"优先处理{len(high_priority)}个高优先级迁移项")
        
        complex_items = [u for u in self.all_metaclass_usages if u.complexity_level == 'complex']
        if complex_items:
            recommendations.append(f"仔细规划{len(complex_items)}个复杂迁移项")
        
        # 基于动态创建的建议
        if self.all_dynamic_creations:
            recommendations.append("发现动态类创建，需要特殊处理")
        
        # 默认建议
        if not recommendations:
            recommendations = [
                "建立详细的测试覆盖",
                "制定回滚计划",
                "分阶段验证迁移结果"
            ]
        
        return recommendations
    
    def save_report(self, report: Dict[str, Any]) -> str:
        """保存检测报告"""
        os.makedirs('analysis_results', exist_ok=True)
        filename = f"analysis_results/metaclass_detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"元编程检测报告已保存到: {filename}")
        return filename
    
    def print_summary(self, report: Dict[str, Any]):
        """打印检测摘要"""
        print("="*70)
        print("Backtrader 元编程检测报告")
        print("="*70)
        
        summary = report['summary']
        print(f"分析文件数: {summary['total_files_analyzed']}")
        print(f"元类使用点: {summary['total_metaclass_usages']}")
        print(f"动态创建点: {summary['total_dynamic_creations']}")
        print(f"迁移计划数: {summary['total_migration_plans']}")
        print(f"高优先级迁移: {summary['high_priority_migrations']}")
        print(f"复杂迁移项: {summary['complex_migrations']}")
        
        print("\n🎯 元类使用统计:")
        print("-"*40)
        for metaclass, count in report['metaclass_breakdown'].items():
            print(f"{metaclass:<20} {count:>3} 次")
        
        print("\n🔧 动态创建统计:")
        print("-"*40)
        for creation_type, count in report['dynamic_creation_breakdown'].items():
            print(f"{creation_type:<20} {count:>3} 次")
        
        print("\n📋 主要迁移计划:")
        print("-"*50)
        print(f"{'目标类':<20} {'预估工时':<10} {'前置条件数':<10}")
        print("-"*50)
        for plan in report['migration_plans'][:10]:
            print(f"{plan['target_class']:<20} {plan['estimated_effort']:<10} {len(plan['prerequisites']):<10}")
        
        print("\n💡 建议:")
        print("-"*30)
        for rec in report['recommendations']:
            print(f"• {rec}")


def main():
    """主函数"""
    try:
        print("Day 8-10: 开始元编程检测工具分析...")
        
        tool = MetaclassDetectionTool()
        
        # 检测元类使用
        tool.detect_metaclass_usage()
        
        # 分析动态创建
        tool.analyze_dynamic_creation()
        
        # 生成迁移报告
        report = tool.generate_migration_report()
        
        tool.print_summary(report)
        tool.save_report(report)
        
        print("\nDay 8-10任务完成！")
        
    except Exception as e:
        print(f"元编程检测过程中出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main() 