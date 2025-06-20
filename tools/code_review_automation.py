#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
Day 25-28 代码审查自动化工具
基于 Day 13-14 建立的审查规范，自动执行代码质量检查和审查流程
"""

import os
import subprocess
import time
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ReviewResult:
    """审查结果数据类"""
    category: str
    priority: str  # high, medium, low
    status: str    # pass, fail, warning
    message: str
    details: Optional[str] = None
    fix_suggestion: Optional[str] = None


class CodeReviewAutomation:
    """代码审查自动化工具"""
    
    def __init__(self, project_root="."):
        self.project_root = Path(project_root)
        self.review_results = []
        self.review_summary = {}
        self.standards = self.load_review_standards()
        
    def load_review_standards(self):
        """加载审查标准"""
        return {
            'code_quality': {
                'max_line_length': 88,
                'max_function_length': 50,
                'max_class_length': 500,
                'max_complexity': 10
            },
            'coverage': {
                'min_coverage': 80,
                'critical_coverage': 95
            },
            'performance': {
                'max_execution_time': 10.0,
                'max_memory_increase': 1024 * 1024  # 1MB
            }
        }
        
    def run_metaclass_detection_review(self):
        """运行元类检测审查"""
        print("🔍 Running Metaclass Detection Review...")
        
        try:
            # 运行元类检测工具
            result = subprocess.run([
                sys.executable, 'tools/metaclass_detector.py'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # 解析输出查找元类使用
                output = result.stdout
                if 'MetaSingleton' in output or 'metaclass=' in output:
                    self.review_results.append(ReviewResult(
                        category='metaclass_removal',
                        priority='high',
                        status='fail',
                        message='Metaclass usage detected in Store system',
                        details=output,
                        fix_suggestion='Remove remaining metaclass usage and use Mixin pattern'
                    ))
                else:
                    self.review_results.append(ReviewResult(
                        category='metaclass_removal',
                        priority='high', 
                        status='pass',
                        message='No metaclass usage detected - Store system refactoring complete'
                    ))
                    
            else:
                self.review_results.append(ReviewResult(
                    category='metaclass_removal',
                    priority='medium',
                    status='warning',
                    message='Metaclass detection tool failed to run',
                    details=result.stderr
                ))
                
        except subprocess.TimeoutExpired:
            self.review_results.append(ReviewResult(
                category='metaclass_removal',
                priority='medium',
                status='warning',
                message='Metaclass detection timed out'
            ))
            
    def run_api_compatibility_review(self):
        """运行 API 兼容性审查"""
        print("🔄 Running API Compatibility Review...")
        
        try:
            # 运行兼容性测试工具
            result = subprocess.run([
                sys.executable, 'tools/compatibility_tester.py'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                # 解析兼容性测试结果
                output = result.stdout
                if 'API兼容性: 100.0%' in output or 'API compatibility: 100.0%' in output:
                    self.review_results.append(ReviewResult(
                        category='api_compatibility',
                        priority='high',
                        status='pass',
                        message='100% API compatibility maintained'
                    ))
                else:
                    self.review_results.append(ReviewResult(
                        category='api_compatibility',
                        priority='high',
                        status='fail',
                        message='API compatibility issues detected',
                        details=output,
                        fix_suggestion='Review and fix API compatibility issues'
                    ))
                    
            else:
                self.review_results.append(ReviewResult(
                    category='api_compatibility',
                    priority='high',
                    status='fail',
                    message='Compatibility testing failed',
                    details=result.stderr,
                    fix_suggestion='Fix compatibility test failures'
                ))
                
        except subprocess.TimeoutExpired:
            self.review_results.append(ReviewResult(
                category='api_compatibility',
                priority='high',
                status='warning',
                message='Compatibility testing timed out'
            ))
            
    def run_performance_review(self):
        """运行性能审查"""
        print("⚡ Running Performance Review...")
        
        try:
            # 运行性能基准测试
            result = subprocess.run([
                sys.executable, 'tools/performance_benchmark.py'
            ], capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                output = result.stdout
                
                # 检查性能改进
                if 'performance improvement' in output.lower() or '提升' in output:
                    self.review_results.append(ReviewResult(
                        category='performance',
                        priority='medium',
                        status='pass',
                        message='Performance improvements detected'
                    ))
                else:
                    self.review_results.append(ReviewResult(
                        category='performance',
                        priority='medium',
                        status='warning',
                        message='No clear performance improvements detected',
                        fix_suggestion='Review performance optimizations'
                    ))
                    
            else:
                self.review_results.append(ReviewResult(
                    category='performance',
                    priority='medium',
                    status='warning',
                    message='Performance testing failed',
                    details=result.stderr
                ))
                
        except subprocess.TimeoutExpired:
            self.review_results.append(ReviewResult(
                category='performance',
                priority='medium',
                status='warning',
                message='Performance testing timed out'
            ))
            
    def run_code_quality_review(self):
        """运行代码质量审查"""
        print("📋 Running Code Quality Review...")
        
        # 运行各种代码质量工具
        quality_tools = [
            ('black', ['black', '--check', 'backtrader/', '--diff']),
            ('pylint', ['pylint', 'backtrader/', '--score=yes']),
            ('mypy', ['mypy', 'backtrader/', '--ignore-missing-imports']),
        ]
        
        for tool_name, command in quality_tools:
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=60
                )
                
                if tool_name == 'black':
                    if result.returncode == 0:
                        self.review_results.append(ReviewResult(
                            category='code_quality',
                            priority='medium',
                            status='pass',
                            message='Code formatting (black) check passed'
                        ))
                    else:
                        self.review_results.append(ReviewResult(
                            category='code_quality',
                            priority='medium',
                            status='fail',
                            message='Code formatting issues detected',
                            details=result.stdout,
                            fix_suggestion='Run: black backtrader/'
                        ))
                        
                elif tool_name == 'pylint':
                    # Pylint 分数解析
                    output = result.stdout
                    if 'Your code has been rated at' in output:
                        score_line = [line for line in output.split('\n') 
                                    if 'Your code has been rated at' in line]
                        if score_line:
                            score = score_line[0]
                            if '/10' in score:
                                try:
                                    score_num = float(score.split('/10')[0].split()[-1])
                                    if score_num >= 8.0:
                                        status = 'pass'
                                    elif score_num >= 6.0:
                                        status = 'warning'
                                    else:
                                        status = 'fail'
                                        
                                    self.review_results.append(ReviewResult(
                                        category='code_quality',
                                        priority='medium',
                                        status=status,
                                        message=f'Pylint score: {score_num}/10'
                                    ))
                                except:
                                    pass
                                    
                elif tool_name == 'mypy':
                    if 'Success: no issues found' in result.stdout:
                        self.review_results.append(ReviewResult(
                            category='code_quality',
                            priority='low',
                            status='pass',
                            message='MyPy type checking passed'
                        ))
                    else:
                        self.review_results.append(ReviewResult(
                            category='code_quality',
                            priority='low',
                            status='warning',
                            message='Type checking issues detected',
                            details=result.stdout[:500]  # 限制输出长度
                        ))
                        
            except subprocess.TimeoutExpired:
                self.review_results.append(ReviewResult(
                    category='code_quality',
                    priority='medium',
                    status='warning',
                    message=f'{tool_name} timed out'
                ))
            except FileNotFoundError:
                self.review_results.append(ReviewResult(
                    category='code_quality',
                    priority='low',
                    status='warning',
                    message=f'{tool_name} not installed'
                ))
                
    def run_test_coverage_review(self):
        """运行测试覆盖率审查"""
        print("🧪 Running Test Coverage Review...")
        
        try:
            # 运行测试覆盖率检查
            result = subprocess.run([
                sys.executable, '-m', 'pytest', 'tests/', 
                '--cov=backtrader', '--cov-report=term-missing'
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                output = result.stdout
                
                # 解析覆盖率
                coverage_lines = [line for line in output.split('\n') 
                                if 'TOTAL' in line and '%' in line]
                
                if coverage_lines:
                    coverage_line = coverage_lines[0]
                    try:
                        # 提取覆盖率百分比
                        coverage_str = coverage_line.split('%')[0].split()[-1]
                        coverage = int(coverage_str)
                        
                        if coverage >= self.standards['coverage']['min_coverage']:
                            status = 'pass'
                            message = f'Test coverage: {coverage}% (meets standard)'
                        else:
                            status = 'fail'
                            message = f'Test coverage: {coverage}% (below {self.standards["coverage"]["min_coverage"]}%)'
                            
                        self.review_results.append(ReviewResult(
                            category='test_coverage',
                            priority='high',
                            status=status,
                            message=message,
                            fix_suggestion='Add more tests to improve coverage' if status == 'fail' else None
                        ))
                        
                    except (ValueError, IndexError):
                        self.review_results.append(ReviewResult(
                            category='test_coverage',
                            priority='medium',
                            status='warning',
                            message='Could not parse coverage percentage'
                        ))
                else:
                    self.review_results.append(ReviewResult(
                        category='test_coverage',
                        priority='medium',
                        status='warning',
                        message='No coverage data found in test output'
                    ))
                    
            else:
                self.review_results.append(ReviewResult(
                    category='test_coverage',
                    priority='high',
                    status='fail',
                    message='Test execution failed',
                    details=result.stderr[:500],
                    fix_suggestion='Fix failing tests'
                ))
                
        except subprocess.TimeoutExpired:
            self.review_results.append(ReviewResult(
                category='test_coverage',
                priority='medium',
                status='warning',
                message='Test coverage analysis timed out'
            ))
            
    def run_security_review(self):
        """运行安全审查"""
        print("🔒 Running Security Review...")
        
        security_tools = [
            ('bandit', ['bandit', '-r', 'backtrader/', '-f', 'txt']),
            ('safety', ['safety', 'check'])
        ]
        
        for tool_name, command in security_tools:
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=60
                )
                
                if tool_name == 'bandit':
                    if result.returncode == 0:
                        self.review_results.append(ReviewResult(
                            category='security',
                            priority='high',
                            status='pass',
                            message='Bandit security scan passed'
                        ))
                    else:
                        # Bandit 发现问题
                        severity_count = self.count_bandit_issues(result.stdout)
                        if severity_count['high'] > 0:
                            status = 'fail'
                            priority = 'high'
                        elif severity_count['medium'] > 0:
                            status = 'warning'
                            priority = 'medium'
                        else:
                            status = 'warning'
                            priority = 'low'
                            
                        self.review_results.append(ReviewResult(
                            category='security',
                            priority=priority,
                            status=status,
                            message=f'Security issues found: {severity_count}',
                            details=result.stdout[:500],
                            fix_suggestion='Review and fix security issues'
                        ))
                        
                elif tool_name == 'safety':
                    if 'No known security vulnerabilities found' in result.stdout:
                        self.review_results.append(ReviewResult(
                            category='security',
                            priority='medium',
                            status='pass',
                            message='No known vulnerabilities in dependencies'
                        ))
                    else:
                        self.review_results.append(ReviewResult(
                            category='security',
                            priority='medium',
                            status='warning',
                            message='Potential vulnerabilities in dependencies',
                            details=result.stdout[:500]
                        ))
                        
            except subprocess.TimeoutExpired:
                self.review_results.append(ReviewResult(
                    category='security',
                    priority='medium',
                    status='warning',
                    message=f'{tool_name} timed out'
                ))
            except FileNotFoundError:
                self.review_results.append(ReviewResult(
                    category='security',
                    priority='low',
                    status='warning',
                    message=f'{tool_name} not installed'
                ))
                
    def count_bandit_issues(self, output):
        """统计 bandit 问题数量"""
        severity_count = {'high': 0, 'medium': 0, 'low': 0}
        
        for line in output.split('\n'):
            line_lower = line.lower()
            if 'severity: high' in line_lower:
                severity_count['high'] += 1
            elif 'severity: medium' in line_lower:
                severity_count['medium'] += 1
            elif 'severity: low' in line_lower:
                severity_count['low'] += 1
                
        return severity_count
        
    def run_documentation_review(self):
        """运行文档审查"""
        print("📚 Running Documentation Review...")
        
        # 检查关键文档文件是否存在
        required_docs = [
            'docs/store_system_api.md',
            'docs/store_migration_guide.md', 
            'docs/store_performance_guide.md',
            'docs/CHANGELOG_store_system.md'
        ]
        
        missing_docs = []
        for doc_path in required_docs:
            if not (self.project_root / doc_path).exists():
                missing_docs.append(doc_path)
                
        if missing_docs:
            self.review_results.append(ReviewResult(
                category='documentation',
                priority='medium',
                status='fail',
                message=f'Missing documentation files: {missing_docs}',
                fix_suggestion='Generate missing documentation'
            ))
        else:
            self.review_results.append(ReviewResult(
                category='documentation',
                priority='medium',
                status='pass',
                message='All required documentation files present'
            ))
            
        # 检查文档内容质量
        try:
            result = subprocess.run([
                sys.executable, 'tools/documentation_updater.py'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                self.review_results.append(ReviewResult(
                    category='documentation',
                    priority='medium',
                    status='pass',
                    message='Documentation validation passed'
                ))
            else:
                self.review_results.append(ReviewResult(
                    category='documentation',
                    priority='medium',
                    status='warning',
                    message='Documentation validation issues',
                    details=result.stderr[:500]
                ))
                
        except subprocess.TimeoutExpired:
            self.review_results.append(ReviewResult(
                category='documentation',
                priority='low',
                status='warning',
                message='Documentation validation timed out'
            ))
            
    def run_comprehensive_code_review(self):
        """运行完整的代码审查"""
        print("\n" + "="*80)
        print("🔍 Day 25-28 Comprehensive Code Review")
        print("="*80)
        
        start_time = time.time()
        
        # 按优先级运行各种审查
        print("\n⭐⭐⭐⭐⭐ CRITICAL REVIEWS")
        self.run_metaclass_detection_review()
        self.run_api_compatibility_review()
        self.run_test_coverage_review()
        
        print("\n⭐⭐⭐⭐ HIGH PRIORITY REVIEWS")
        self.run_security_review()
        
        print("\n⭐⭐⭐ MEDIUM PRIORITY REVIEWS")
        self.run_performance_review()
        self.run_code_quality_review()
        self.run_documentation_review()
        
        review_time = time.time() - start_time
        
        # 生成审查摘要
        self.generate_review_summary(review_time)
        
        return {
            'review_results': self.review_results,
            'review_summary': self.review_summary,
            'review_time': review_time
        }
        
    def generate_review_summary(self, review_time):
        """生成审查摘要"""
        print("\n" + "="*80)
        print("📋 Code Review Summary")
        print("="*80)
        
        # 统计结果
        total_checks = len(self.review_results)
        passed_checks = sum(1 for r in self.review_results if r.status == 'pass')
        failed_checks = sum(1 for r in self.review_results if r.status == 'fail')
        warning_checks = sum(1 for r in self.review_results if r.status == 'warning')
        
        # 按优先级统计
        high_priority_issues = sum(1 for r in self.review_results 
                                 if r.priority == 'high' and r.status != 'pass')
        medium_priority_issues = sum(1 for r in self.review_results 
                                   if r.priority == 'medium' and r.status != 'pass')
        low_priority_issues = sum(1 for r in self.review_results 
                                if r.priority == 'low' and r.status != 'pass')
        
        # 按类别统计
        categories = {}
        for result in self.review_results:
            if result.category not in categories:
                categories[result.category] = {'pass': 0, 'fail': 0, 'warning': 0}
            categories[result.category][result.status] += 1
            
        print(f"⏱️ Review Time: {review_time:.2f}s")
        print(f"🔍 Total Checks: {total_checks}")
        print(f"✅ Passed: {passed_checks}")
        print(f"❌ Failed: {failed_checks}")
        print(f"⚠️ Warnings: {warning_checks}")
        
        print(f"\n📊 Priority Breakdown:")
        print(f"   🔥 High Priority Issues: {high_priority_issues}")
        print(f"   ⚠️ Medium Priority Issues: {medium_priority_issues}")
        print(f"   💡 Low Priority Issues: {low_priority_issues}")
        
        print(f"\n📋 Category Results:")
        for category, stats in categories.items():
            total = sum(stats.values())
            pass_rate = (stats['pass'] / total) * 100 if total > 0 else 0
            print(f"   {category}: {pass_rate:.1f}% pass rate ({stats['pass']}/{total})")
            
        # 生成审查决定
        review_decision = self.make_review_decision()
        print(f"\n🎯 Review Decision: {review_decision}")
        
        # 关键问题报告
        critical_issues = [r for r in self.review_results 
                         if r.priority == 'high' and r.status == 'fail']
        if critical_issues:
            print(f"\n🚨 Critical Issues Requiring Immediate Attention:")
            for issue in critical_issues:
                print(f"   ❌ {issue.message}")
                if issue.fix_suggestion:
                    print(f"      💡 Fix: {issue.fix_suggestion}")
                    
        self.review_summary = {
            'total_checks': total_checks,
            'passed_checks': passed_checks,
            'failed_checks': failed_checks,
            'warning_checks': warning_checks,
            'high_priority_issues': high_priority_issues,
            'medium_priority_issues': medium_priority_issues,
            'low_priority_issues': low_priority_issues,
            'category_stats': categories,
            'review_decision': review_decision,
            'critical_issues': len(critical_issues)
        }
        
    def make_review_decision(self):
        """做出审查决定"""
        # 计算关键问题
        critical_failures = sum(1 for r in self.review_results 
                              if r.priority == 'high' and r.status == 'fail')
        
        major_failures = sum(1 for r in self.review_results 
                           if r.priority == 'medium' and r.status == 'fail')
        
        # 特殊检查：元类移除和API兼容性
        metaclass_passed = any(r.category == 'metaclass_removal' and r.status == 'pass' 
                             for r in self.review_results)
        api_compat_passed = any(r.category == 'api_compatibility' and r.status == 'pass' 
                              for r in self.review_results)
        
        if critical_failures > 0:
            return "❌ REJECTED - Critical issues must be resolved"
        elif not metaclass_passed:
            return "❌ REJECTED - Metaclass removal not complete"
        elif not api_compat_passed:
            return "❌ REJECTED - API compatibility not maintained" 
        elif major_failures > 3:
            return "⚠️ CONDITIONAL APPROVAL - Address major issues"
        else:
            return "✅ APPROVED - Ready for next phase"
            
    def save_review_report(self, filename="day25-28_code_review_report.json"):
        """保存审查报告"""
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'review_phase': 'Day 25-28 Code Review',
            'review_results': [
                {
                    'category': r.category,
                    'priority': r.priority,
                    'status': r.status,
                    'message': r.message,
                    'details': r.details,
                    'fix_suggestion': r.fix_suggestion
                }
                for r in self.review_results
            ],
            'review_summary': self.review_summary
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"📄 Code review report saved to: {filename}")
        return filename


def main():
    """主代码审查执行"""
    reviewer = CodeReviewAutomation()
    
    try:
        # 运行完整代码审查
        results = reviewer.run_comprehensive_code_review()
        
        # 保存报告
        report_file = reviewer.save_review_report()
        
        print(f"\n✅ Code review completed!")
        print(f"🔍 Total checks: {len(results['review_results'])}")
        print(f"📄 Report: {report_file}")
        
        # 基于审查结果确定退出码
        critical_issues = reviewer.review_summary.get('critical_issues', 0)
        if critical_issues > 0:
            print(f"\n❌ Code review failed with {critical_issues} critical issues")
            return False
        else:
            print(f"\n✅ Code review passed!")
            return True
        
    except Exception as e:
        print(f"\n❌ Code review failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 