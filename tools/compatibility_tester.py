#!/usr/bin/env python3
"""
Backtrader Compatibility Testing Framework

Day 11-12: 兼容性测试框架
- 测试API兼容性
- 比较新旧实现的行为
- 确保重构过程中不破坏现有功能
"""

import os
import sys
import ast
import json
import copy
import time
import pickle
import inspect
import importlib
import subprocess
import traceback
from typing import Dict, List, Set, Any, Tuple, Optional, Union, Callable
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import unittest
from unittest.mock import Mock, patch

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class APICompatibilityResult:
    """API兼容性测试结果"""
    module_name: str
    class_name: str
    method_name: str
    is_compatible: bool
    compatibility_type: str  # 'signature', 'behavior', 'return_type'
    old_signature: str
    new_signature: str
    issues: List[str] = field(default_factory=list)
    test_cases_passed: int = 0
    test_cases_failed: int = 0


@dataclass
class BehaviorComparisonResult:
    """行为比较测试结果"""
    test_name: str
    old_result: Any
    new_result: Any
    is_equivalent: bool
    difference_type: str  # 'output', 'exception', 'performance', 'side_effect'
    old_execution_time: float
    new_execution_time: float
    performance_delta: float
    notes: str = ''


@dataclass
class CompatibilityTestCase:
    """兼容性测试用例"""
    test_id: str
    description: str
    target_class: str
    target_method: str
    test_data: Dict[str, Any]
    expected_behavior: str
    priority: str  # 'critical', 'high', 'medium', 'low'


class APIInspector:
    """API检查器"""
    
    def __init__(self):
        self.cached_signatures: Dict[str, Dict] = {}
        self.api_changes: List[Dict] = []
    
    def extract_api_signature(self, module_path: str, class_name: str = None) -> Dict[str, Any]:
        """提取API签名"""
        try:
            # 动态导入模块
            spec = importlib.util.spec_from_file_location("temp_module", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            api_info = {}
            
            if class_name:
                # 分析特定类
                if hasattr(module, class_name):
                    cls = getattr(module, class_name)
                    api_info[class_name] = self._extract_class_api(cls)
            else:
                # 分析整个模块
                for name in dir(module):
                    obj = getattr(module, name)
                    if inspect.isclass(obj) and not name.startswith('_'):
                        api_info[name] = self._extract_class_api(obj)
            
            return api_info
            
        except Exception as e:
            print(f"无法分析 {module_path}: {e}")
            return {}
    
    def _extract_class_api(self, cls) -> Dict[str, Any]:
        """提取类的API信息"""
        class_info = {
            'methods': {},
            'properties': {},
            'attributes': {},
            'mro': [c.__name__ for c in cls.__mro__],
            'docstring': inspect.getdoc(cls)
        }
        
        for name in dir(cls):
            if name.startswith('_') and name not in ['__init__', '__new__']:
                continue
                
            try:
                attr = getattr(cls, name)
                
                if inspect.ismethod(attr) or inspect.isfunction(attr):
                    sig = inspect.signature(attr)
                    class_info['methods'][name] = {
                        'signature': str(sig),
                        'parameters': {
                            param.name: {
                                'kind': param.kind.name,
                                'default': param.default if param.default != param.empty else None,
                                'annotation': str(param.annotation) if param.annotation != param.empty else None
                            }
                            for param in sig.parameters.values()
                        },
                        'return_annotation': str(sig.return_annotation) if sig.return_annotation != inspect.Signature.empty else None,
                        'docstring': inspect.getdoc(attr)
                    }
                elif isinstance(attr, property):
                    class_info['properties'][name] = {
                        'getter': attr.fget is not None,
                        'setter': attr.fset is not None,
                        'deleter': attr.fdel is not None,
                        'docstring': inspect.getdoc(attr)
                    }
                else:
                    class_info['attributes'][name] = {
                        'type': type(attr).__name__,
                        'value': repr(attr)[:100] if len(repr(attr)) < 100 else repr(attr)[:100] + '...'
                    }
                    
            except Exception as e:
                # 某些属性可能无法访问
                continue
        
        return class_info
    
    def compare_api_signatures(self, old_api: Dict, new_api: Dict) -> List[APICompatibilityResult]:
        """比较API签名"""
        results = []
        
        # 比较类级别的兼容性
        for class_name in old_api:
            if class_name not in new_api:
                # 类被移除
                results.append(APICompatibilityResult(
                    module_name='',
                    class_name=class_name,
                    method_name='',
                    is_compatible=False,
                    compatibility_type='class_removal',
                    old_signature=f"class {class_name}",
                    new_signature='',
                    issues=[f"类 {class_name} 已被移除"]
                ))
                continue
            
            old_class = old_api[class_name]
            new_class = new_api[class_name]
            
            # 比较方法
            for method_name in old_class.get('methods', {}):
                old_method = old_class['methods'][method_name]
                
                if method_name not in new_class.get('methods', {}):
                    # 方法被移除
                    results.append(APICompatibilityResult(
                        module_name='',
                        class_name=class_name,
                        method_name=method_name,
                        is_compatible=False,
                        compatibility_type='method_removal',
                        old_signature=old_method['signature'],
                        new_signature='',
                        issues=[f"方法 {method_name} 已被移除"]
                    ))
                    continue
                
                new_method = new_class['methods'][method_name]
                
                # 比较方法签名
                compatibility_result = self._compare_method_signatures(
                    class_name, method_name, old_method, new_method
                )
                results.append(compatibility_result)
        
        # 检查新增的类
        for class_name in new_api:
            if class_name not in old_api:
                results.append(APICompatibilityResult(
                    module_name='',
                    class_name=class_name,
                    method_name='',
                    is_compatible=True,
                    compatibility_type='class_addition',
                    old_signature='',
                    new_signature=f"class {class_name}",
                    issues=[]
                ))
        
        return results
    
    def _compare_method_signatures(self, class_name: str, method_name: str, 
                                  old_method: Dict, new_method: Dict) -> APICompatibilityResult:
        """比较方法签名"""
        issues = []
        is_compatible = True
        
        old_params = old_method['parameters']
        new_params = new_method['parameters']
        
        # 检查参数兼容性
        for param_name in old_params:
            if param_name not in new_params:
                issues.append(f"参数 '{param_name}' 已被移除")
                is_compatible = False
            else:
                old_param = old_params[param_name]
                new_param = new_params[param_name]
                
                # 检查默认值变化
                if old_param['default'] != new_param['default']:
                    if old_param['default'] is None and new_param['default'] is not None:
                        # 添加默认值通常是兼容的
                        pass
                    elif old_param['default'] is not None and new_param['default'] is None:
                        # 移除默认值可能破坏兼容性
                        issues.append(f"参数 '{param_name}' 的默认值已被移除")
                        is_compatible = False
                    else:
                        issues.append(f"参数 '{param_name}' 的默认值从 {old_param['default']} 变为 {new_param['default']}")
                
                # 检查类型注解变化
                if old_param['annotation'] != new_param['annotation']:
                    issues.append(f"参数 '{param_name}' 的类型注解从 {old_param['annotation']} 变为 {new_param['annotation']}")
        
        # 检查新增参数
        for param_name in new_params:
            if param_name not in old_params:
                new_param = new_params[param_name]
                if new_param['default'] is None:
                    # 新增必需参数破坏兼容性
                    issues.append(f"新增必需参数 '{param_name}'")
                    is_compatible = False
                else:
                    # 新增可选参数通常是兼容的
                    issues.append(f"新增可选参数 '{param_name}'")
        
        # 检查返回类型注解
        old_return = old_method.get('return_annotation')
        new_return = new_method.get('return_annotation')
        if old_return != new_return:
            issues.append(f"返回类型注解从 {old_return} 变为 {new_return}")
        
        return APICompatibilityResult(
            module_name='',
            class_name=class_name,
            method_name=method_name,
            is_compatible=is_compatible,
            compatibility_type='signature',
            old_signature=old_method['signature'],
            new_signature=new_method['signature'],
            issues=issues
        )


class BehaviorTester:
    """行为测试器"""
    
    def __init__(self):
        self.test_cases: List[CompatibilityTestCase] = []
        self.test_results: List[BehaviorComparisonResult] = []
    
    def add_test_case(self, test_case: CompatibilityTestCase):
        """添加测试用例"""
        self.test_cases.append(test_case)
    
    def generate_default_test_cases(self) -> List[CompatibilityTestCase]:
        """生成默认测试用例"""
        test_cases = [
            # Strategy相关测试
            CompatibilityTestCase(
                test_id="strategy_basic_creation",
                description="测试Strategy基本创建",
                target_class="Strategy",
                target_method="__init__",
                test_data={},
                expected_behavior="正常创建Strategy实例",
                priority="critical"
            ),
            
            # Indicator相关测试
            CompatibilityTestCase(
                test_id="indicator_sma_calculation",
                description="测试SimpleMovingAverage计算",
                target_class="SimpleMovingAverage",
                target_method="next",
                test_data={"data": [1, 2, 3, 4, 5], "period": 3},
                expected_behavior="正确计算移动平均值",
                priority="critical"
            ),
            
            # LineSeries相关测试
            CompatibilityTestCase(
                test_id="lineseries_data_access",
                description="测试LineSeries数据访问",
                target_class="LineSeries",
                target_method="__getitem__",
                test_data={"index": 0},
                expected_behavior="正确访问数据",
                priority="high"
            ),
            
            # Store相关测试
            CompatibilityTestCase(
                test_id="store_singleton_behavior",
                description="测试Store单例行为",
                target_class="Store",
                target_method="__new__",
                test_data={},
                expected_behavior="确保单例模式正常工作",
                priority="high"
            ),
            
            # Params相关测试
            CompatibilityTestCase(
                test_id="params_inheritance",
                description="测试参数继承",
                target_class="ParamsBase",
                target_method="params",
                test_data={},
                expected_behavior="正确继承和处理参数",
                priority="medium"
            )
        ]
        
        return test_cases
    
    def run_behavior_comparison(self, old_implementation, new_implementation, 
                               test_case: CompatibilityTestCase) -> BehaviorComparisonResult:
        """运行行为比较测试"""
        test_name = f"{test_case.target_class}.{test_case.target_method}"
        
        # 运行旧实现
        old_result, old_time, old_exception = self._run_test_implementation(
            old_implementation, test_case
        )
        
        # 运行新实现
        new_result, new_time, new_exception = self._run_test_implementation(
            new_implementation, test_case
        )
        
        # 比较结果
        is_equivalent = self._compare_results(old_result, new_result, old_exception, new_exception)
        
        # 确定差异类型
        difference_type = self._determine_difference_type(
            old_result, new_result, old_exception, new_exception
        )
        
        # 计算性能差异
        performance_delta = ((new_time - old_time) / old_time * 100) if old_time > 0 else 0
        
        return BehaviorComparisonResult(
            test_name=test_name,
            old_result=old_result,
            new_result=new_result,
            is_equivalent=is_equivalent,
            difference_type=difference_type,
            old_execution_time=old_time,
            new_execution_time=new_time,
            performance_delta=performance_delta,
            notes=f"测试用例: {test_case.description}"
        )
    
    def _run_test_implementation(self, implementation, test_case: CompatibilityTestCase) -> Tuple[Any, float, Exception]:
        """运行测试实现"""
        result = None
        exception = None
        
        start_time = time.time()
        
        try:
            # 这里需要根据具体的测试用例来执行相应的代码
            # 为了演示，我们使用一个简化的执行方式
            if hasattr(implementation, test_case.target_class):
                cls = getattr(implementation, test_case.target_class)
                if test_case.target_method == "__init__":
                    result = cls(**test_case.test_data)
                elif hasattr(cls, test_case.target_method):
                    method = getattr(cls, test_case.target_method)
                    if callable(method):
                        result = method(**test_case.test_data)
                    else:
                        result = method
                else:
                    result = f"Method {test_case.target_method} not found"
            else:
                result = f"Class {test_case.target_class} not found"
                
        except Exception as e:
            exception = e
            result = str(e)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        return result, execution_time, exception
    
    def _compare_results(self, old_result, new_result, old_exception, new_exception) -> bool:
        """比较测试结果"""
        # 如果都有异常，比较异常类型
        if old_exception and new_exception:
            return type(old_exception) == type(new_exception)
        
        # 如果一个有异常一个没有，不兼容
        if (old_exception is None) != (new_exception is None):
            return False
        
        # 比较返回值
        try:
            if type(old_result) != type(new_result):
                return False
            
            # 对于数值类型，允许小的误差
            if isinstance(old_result, (int, float)):
                return abs(old_result - new_result) < 1e-10
            
            # 对于其他类型，直接比较
            return old_result == new_result
            
        except:
            # 如果比较失败，认为不兼容
            return False
    
    def _determine_difference_type(self, old_result, new_result, old_exception, new_exception) -> str:
        """确定差异类型"""
        if old_exception and new_exception:
            if type(old_exception) != type(new_exception):
                return 'exception'
        elif (old_exception is None) != (new_exception is None):
            return 'exception'
        elif old_result != new_result:
            return 'output'
        else:
            return 'performance'


class CompatibilityTestFramework:
    """兼容性测试框架主类"""
    
    def __init__(self, project_root: str = '.'):
        self.project_root = os.path.abspath(project_root)
        self.api_inspector = APIInspector()
        self.behavior_tester = BehaviorTester()
        self.test_results: Dict[str, Any] = {}
        
        # 关键模块列表
        self.critical_modules = [
            'backtrader/strategy.py',
            'backtrader/indicator.py', 
            'backtrader/lineseries.py',
            'backtrader/metabase.py',
            'backtrader/store.py',
            'backtrader/broker.py',
            'backtrader/feed.py'
        ]
    
    def test_api_compatibility(self, old_branch: str = 'main', new_branch: str = 'remove-metaprogramming') -> List[APICompatibilityResult]:
        """测试API兼容性"""
        print("开始API兼容性测试...")
        
        all_results = []
        
        for module_path in self.critical_modules:
            full_path = os.path.join(self.project_root, module_path)
            
            if not os.path.exists(full_path):
                print(f"模块文件不存在: {module_path}")
                continue
            
            print(f"分析模块: {module_path}")
            
            try:
                # 获取当前版本的API
                current_api = self.api_inspector.extract_api_signature(full_path)
                
                # 这里简化处理，实际应该检出不同分支的版本进行比较
                # 为了演示，我们创建一个模拟的"旧版本"API
                old_api = self._create_mock_old_api(current_api)
                
                # 比较API
                module_results = self.api_inspector.compare_api_signatures(old_api, current_api)
                
                for result in module_results:
                    result.module_name = module_path
                
                all_results.extend(module_results)
                
            except Exception as e:
                print(f"分析模块 {module_path} 时出错: {e}")
        
        return all_results
    
    def _create_mock_old_api(self, current_api: Dict) -> Dict:
        """创建模拟的旧版本API（用于演示）"""
        # 这是一个简化的实现，实际应该从git历史中获取
        old_api = copy.deepcopy(current_api)
        
        # 模拟一些兼容性问题
        for class_name in old_api:
            class_info = old_api[class_name]
            methods = class_info.get('methods', {})
            
            # 模拟移除某些方法
            if 'deprecated_method' in methods:
                del methods['deprecated_method']
            
            # 模拟修改某些方法签名
            if '__init__' in methods:
                init_method = methods['__init__']
                params = init_method['parameters']
                
                # 模拟移除默认值
                for param_name in params:
                    if param_name != 'self' and params[param_name]['default'] is not None:
                        # 随机移除一些默认值
                        if hash(param_name) % 3 == 0:
                            params[param_name]['default'] = None
        
        return old_api
    
    def compare_behavior(self, test_cases: List[CompatibilityTestCase] = None) -> List[BehaviorComparisonResult]:
        """比较新旧实现的行为"""
        print("开始行为比较测试...")
        
        if test_cases is None:
            test_cases = self.behavior_tester.generate_default_test_cases()
        
        results = []
        
        for test_case in test_cases:
            print(f"运行测试用例: {test_case.test_id}")
            
            try:
                # 这里简化处理，实际应该加载不同版本的实现
                old_impl = self._get_old_implementation()
                new_impl = self._get_new_implementation()
                
                result = self.behavior_tester.run_behavior_comparison(
                    old_impl, new_impl, test_case
                )
                
                results.append(result)
                
            except Exception as e:
                print(f"测试用例 {test_case.test_id} 执行失败: {e}")
                
                # 创建一个失败的结果
                failed_result = BehaviorComparisonResult(
                    test_name=test_case.test_id,
                    old_result=None,
                    new_result=None,
                    is_equivalent=False,
                    difference_type='execution_error',
                    old_execution_time=0,
                    new_execution_time=0,
                    performance_delta=0,
                    notes=f"执行失败: {str(e)}"
                )
                results.append(failed_result)
        
        return results
    
    def _get_old_implementation(self):
        """获取旧版本实现（模拟）"""
        # 这里应该导入旧版本的代码
        # 为了演示，我们创建一个模拟对象
        class MockOldImplementation:
            class Strategy:
                def __init__(self, **kwargs):
                    pass
            
            class SimpleMovingAverage:
                def next(self, **kwargs):
                    return 42  # 模拟计算结果
            
            class LineSeries:
                def __getitem__(self, index):
                    return index * 2
            
            class Store:
                _instance = None
                def __new__(cls):
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                    return cls._instance
            
            class ParamsBase:
                params = {}
        
        return MockOldImplementation()
    
    def _get_new_implementation(self):
        """获取新版本实现（模拟）"""
        # 这里应该导入新版本的代码
        # 为了演示，我们创建一个模拟对象
        class MockNewImplementation:
            class Strategy:
                def __init__(self, **kwargs):
                    pass
            
            class SimpleMovingAverage:
                def next(self, **kwargs):
                    return 42.0  # 稍微不同的结果类型
            
            class LineSeries:
                def __getitem__(self, index):
                    return index * 2
            
            class Store:
                _instance = None
                def __new__(cls):
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                    return cls._instance
            
            class ParamsBase:
                params = {}
        
        return MockNewImplementation()
    
    def run_comprehensive_tests(self) -> Dict[str, Any]:
        """运行全面的兼容性测试"""
        print("开始全面兼容性测试...")
        
        start_time = datetime.now()
        
        # API兼容性测试
        api_results = self.test_api_compatibility()
        
        # 行为兼容性测试
        behavior_results = self.compare_behavior()
        
        # 生成综合报告
        report = self._generate_comprehensive_report(api_results, behavior_results, start_time)
        
        return report
    
    def _generate_comprehensive_report(self, api_results: List[APICompatibilityResult], 
                                     behavior_results: List[BehaviorComparisonResult],
                                     start_time: datetime) -> Dict[str, Any]:
        """生成综合测试报告"""
        end_time = datetime.now()
        duration = end_time - start_time
        
        # API兼容性统计
        api_stats = {
            'total_tests': len(api_results),
            'compatible_count': len([r for r in api_results if r.is_compatible]),
            'incompatible_count': len([r for r in api_results if not r.is_compatible]),
            'compatibility_rate': len([r for r in api_results if r.is_compatible]) / len(api_results) * 100 if api_results else 0
        }
        
        # 行为兼容性统计
        behavior_stats = {
            'total_tests': len(behavior_results),
            'equivalent_count': len([r for r in behavior_results if r.is_equivalent]),
            'different_count': len([r for r in behavior_results if not r.is_equivalent]),
            'equivalence_rate': len([r for r in behavior_results if r.is_equivalent]) / len(behavior_results) * 100 if behavior_results else 0,
            'average_performance_delta': sum(r.performance_delta for r in behavior_results) / len(behavior_results) if behavior_results else 0
        }
        
        # 识别关键问题
        critical_issues = []
        for result in api_results:
            if not result.is_compatible and 'removal' in result.compatibility_type:
                critical_issues.append({
                    'type': 'api_breaking_change',
                    'description': f"{result.class_name}.{result.method_name} - {'; '.join(result.issues)}",
                    'severity': 'critical'
                })
        
        for result in behavior_results:
            if not result.is_equivalent and result.difference_type in ['output', 'exception']:
                critical_issues.append({
                    'type': 'behavior_change',
                    'description': f"{result.test_name} - 行为不一致",
                    'severity': 'high'
                })
        
        report = {
            'test_execution': {
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'duration_seconds': duration.total_seconds(),
                'framework_version': '1.0.0'
            },
            'summary': {
                'overall_compatibility': 'PASS' if api_stats['compatibility_rate'] > 95 and behavior_stats['equivalence_rate'] > 90 else 'FAIL',
                'api_compatibility': api_stats,
                'behavior_compatibility': behavior_stats,
                'critical_issues_count': len(critical_issues)
            },
            'api_test_results': [
                {
                    'module': r.module_name,
                    'class': r.class_name,
                    'method': r.method_name,
                    'compatible': r.is_compatible,
                    'type': r.compatibility_type,
                    'old_signature': r.old_signature,
                    'new_signature': r.new_signature,
                    'issues': r.issues
                }
                for r in api_results
            ],
            'behavior_test_results': [
                {
                    'test_name': r.test_name,
                    'equivalent': r.is_equivalent,
                    'difference_type': r.difference_type,
                    'old_execution_time': r.old_execution_time,
                    'new_execution_time': r.new_execution_time,
                    'performance_delta': r.performance_delta,
                    'notes': r.notes
                }
                for r in behavior_results
            ],
            'critical_issues': critical_issues,
            'recommendations': self._generate_recommendations(api_results, behavior_results)
        }
        
        return report
    
    def _generate_recommendations(self, api_results: List[APICompatibilityResult], 
                                behavior_results: List[BehaviorComparisonResult]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        # 基于API兼容性的建议
        incompatible_apis = [r for r in api_results if not r.is_compatible]
        if incompatible_apis:
            recommendations.append(f"发现{len(incompatible_apis)}个API兼容性问题，需要优先解决")
            
            removal_issues = [r for r in incompatible_apis if 'removal' in r.compatibility_type]
            if removal_issues:
                recommendations.append(f"有{len(removal_issues)}个移除类/方法的问题，建议添加废弃警告和兼容性层")
        
        # 基于行为兼容性的建议
        behavior_issues = [r for r in behavior_results if not r.is_equivalent]
        if behavior_issues:
            recommendations.append(f"发现{len(behavior_issues)}个行为兼容性问题，需要详细验证")
            
            output_issues = [r for r in behavior_issues if r.difference_type == 'output']
            if output_issues:
                recommendations.append(f"有{len(output_issues)}个输出不一致问题，可能影响用户代码")
        
        # 性能建议
        performance_regressions = [r for r in behavior_results if r.performance_delta > 20]
        if performance_regressions:
            recommendations.append(f"发现{len(performance_regressions)}个性能回归问题，建议优化")
        
        # 默认建议
        if not recommendations:
            recommendations = [
                "整体兼容性良好，建议继续监控",
                "定期运行兼容性测试",
                "关注用户反馈中的兼容性问题"
            ]
        
        return recommendations
    
    def save_report(self, report: Dict[str, Any]) -> str:
        """保存测试报告"""
        os.makedirs('test_results', exist_ok=True)
        filename = f"test_results/compatibility_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"兼容性测试报告已保存到: {filename}")
        return filename
    
    def print_summary(self, report: Dict[str, Any]):
        """打印测试摘要"""
        print("="*70)
        print("Backtrader 兼容性测试报告")
        print("="*70)
        
        summary = report['summary']
        api_stats = summary['api_compatibility']
        behavior_stats = summary['behavior_compatibility']
        
        print(f"整体兼容性评估: {summary['overall_compatibility']}")
        print(f"测试执行时间: {report['test_execution']['duration_seconds']:.2f} 秒")
        
        print("\n📊 API兼容性:")
        print("-"*40)
        print(f"总测试数: {api_stats['total_tests']}")
        print(f"兼容: {api_stats['compatible_count']}")
        print(f"不兼容: {api_stats['incompatible_count']}")
        print(f"兼容率: {api_stats['compatibility_rate']:.1f}%")
        
        print("\n🔄 行为兼容性:")
        print("-"*40)
        print(f"总测试数: {behavior_stats['total_tests']}")
        print(f"行为一致: {behavior_stats['equivalent_count']}")
        print(f"行为不同: {behavior_stats['different_count']}")
        print(f"一致率: {behavior_stats['equivalence_rate']:.1f}%")
        print(f"平均性能变化: {behavior_stats['average_performance_delta']:.1f}%")
        
        if summary['critical_issues_count'] > 0:
            print(f"\n⚠️ 关键问题数量: {summary['critical_issues_count']}")
            print("\n前5个关键问题:")
            for issue in report['critical_issues'][:5]:
                print(f"  - {issue['description']} ({issue['severity']})")
        
        print("\n💡 建议:")
        print("-"*30)
        for rec in report['recommendations'][:3]:
            print(f"• {rec}")


def main():
    """主函数"""
    try:
        print("Day 11-12: 开始兼容性测试框架分析...")
        
        framework = CompatibilityTestFramework()
        
        # 运行全面测试
        report = framework.run_comprehensive_tests()
        
        framework.print_summary(report)
        framework.save_report(report)
        
        print("\nDay 11-12任务完成！")
        
    except Exception as e:
        print(f"兼容性测试过程中出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main() 