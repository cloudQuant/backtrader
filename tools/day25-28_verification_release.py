#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
Day 25-28 验证和发布主执行脚本
按顺序运行完整的回归测试、用户验收测试、文档完善和代码审查
"""

import os
import sys
import time
import subprocess
import json
from pathlib import Path


class Day25To28Orchestrator:
    """Day 25-28 验证和发布协调器"""
    
    def __init__(self, project_root="."):
        self.project_root = Path(project_root)
        self.results = {}
        self.start_time = time.time()
        self.phase_results = {}
        
    def print_phase_header(self, phase_name, emoji="🔍"):
        """打印阶段标题"""
        print("\n" + "="*80)
        print(f"{emoji} Day 25-28: {phase_name}")
        print("="*80)
        
    def run_regression_tests(self):
        """运行完整的回归测试"""
        self.print_phase_header("完整回归测试", "🧪")
        
        phase_start = time.time()
        
        # 运行现有的 Store 系统测试
        print("\n📋 Running existing Store system tests...")
        
        test_files = [
            'tests/test_store_system.py',
            'tools/store_performance_benchmark.py'
        ]
        
        test_results = {}
        
        for test_file in test_files:
            if (self.project_root / test_file).exists():
                print(f"   🔍 Running {test_file}...")
                
                try:
                    result = subprocess.run([
                        sys.executable, test_file
                    ], capture_output=True, text=True, timeout=300)
                    
                    test_results[test_file] = {
                        'success': result.returncode == 0,
                        'output': result.stdout,
                        'error': result.stderr if result.returncode != 0 else None
                    }
                    
                    if result.returncode == 0:
                        print(f"      ✅ {test_file} passed")
                    else:
                        print(f"      ❌ {test_file} failed")
                        
                except subprocess.TimeoutExpired:
                    test_results[test_file] = {
                        'success': False,
                        'error': 'Test timed out'
                    }
                    print(f"      ⏰ {test_file} timed out")
                    
            else:
                print(f"   ⚠️ Test file not found: {test_file}")
                test_results[test_file] = {
                    'success': False,
                    'error': 'File not found'
                }
                
        # 运行 Python 单元测试
        print("\n🧪 Running Python unit tests...")
        
        try:
            result = subprocess.run([
                sys.executable, '-m', 'pytest', 'tests/', '-v'
            ], capture_output=True, text=True, timeout=600)
            
            test_results['pytest'] = {
                'success': result.returncode == 0,
                'output': result.stdout,
                'error': result.stderr if result.returncode != 0 else None
            }
            
            if result.returncode == 0:
                print("   ✅ PyTest unit tests passed")
            else:
                print("   ❌ PyTest unit tests failed")
                
        except subprocess.TimeoutExpired:
            test_results['pytest'] = {
                'success': False,
                'error': 'PyTest timed out'
            }
            print("   ⏰ PyTest timed out")
        except FileNotFoundError:
            test_results['pytest'] = {
                'success': False,
                'error': 'PyTest not available'
            }
            print("   ⚠️ PyTest not available")
            
        phase_time = time.time() - phase_start
        
        # 汇总回归测试结果
        passed_tests = sum(1 for r in test_results.values() if r['success'])
        total_tests = len(test_results)
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        
        regression_summary = {
            'passed_tests': passed_tests,
            'total_tests': total_tests,
            'success_rate': success_rate,
            'phase_time': phase_time,
            'test_results': test_results
        }
        
        print(f"\n📊 Regression Test Summary:")
        print(f"   Tests passed: {passed_tests}/{total_tests} ({success_rate:.1f}%)")
        print(f"   Execution time: {phase_time:.2f}s")
        
        if success_rate >= 80:
            print("   ✅ Regression tests PASSED")
        else:
            print("   ❌ Regression tests FAILED")
            
        self.phase_results['regression_tests'] = regression_summary
        return regression_summary
        
    def run_user_acceptance_tests(self):
        """运行用户验收测试"""
        self.print_phase_header("用户验收测试", "👥")
        
        phase_start = time.time()
        
        uat_script = 'tools/user_acceptance_test.py'
        
        if (self.project_root / uat_script).exists():
            print(f"\n🚀 Running user acceptance tests...")
            
            try:
                result = subprocess.run([
                    sys.executable, uat_script
                ], capture_output=True, text=True, timeout=600)
                
                uat_success = result.returncode == 0
                
                if uat_success:
                    print("   ✅ User acceptance tests PASSED")
                else:
                    print("   ❌ User acceptance tests FAILED")
                    print(f"   Error: {result.stderr}")
                    
                # 尝试加载 UAT 报告
                uat_report_file = self.project_root / 'day25-28_uat_report.json'
                uat_details = None
                
                if uat_report_file.exists():
                    try:
                        with open(uat_report_file) as f:
                            uat_details = json.load(f)
                    except Exception as e:
                        print(f"   ⚠️ Could not load UAT report: {e}")
                        
            except subprocess.TimeoutExpired:
                uat_success = False
                print("   ⏰ User acceptance tests timed out")
                uat_details = None
                
        else:
            uat_success = False
            uat_details = None
            print(f"   ⚠️ UAT script not found: {uat_script}")
            
        phase_time = time.time() - phase_start
        
        uat_summary = {
            'success': uat_success,
            'phase_time': phase_time,
            'details': uat_details,
            'output': result.stdout if 'result' in locals() else None,
            'error': result.stderr if 'result' in locals() and result.returncode != 0 else None
        }
        
        print(f"\n📊 User Acceptance Test Summary:")
        print(f"   Status: {'PASSED' if uat_success else 'FAILED'}")
        print(f"   Execution time: {phase_time:.2f}s")
        
        if uat_details:
            print(f"   Test scenarios: {len(uat_details.get('test_results', {}))}")
            if 'user_feedback' in uat_details:
                feedback = uat_details['user_feedback']
                overall = feedback.get('overall_satisfaction', {})
                rating = overall.get('rating', 0)
                print(f"   User satisfaction: {rating:.1f}/5.0 ⭐")
                
        self.phase_results['user_acceptance_tests'] = uat_summary
        return uat_summary
        
    def run_documentation_update(self):
        """运行文档完善"""
        self.print_phase_header("文档完善", "📚")
        
        phase_start = time.time()
        
        doc_script = 'tools/documentation_updater.py'
        
        if (self.project_root / doc_script).exists():
            print(f"\n📝 Running documentation update...")
            
            try:
                result = subprocess.run([
                    sys.executable, doc_script
                ], capture_output=True, text=True, timeout=300)
                
                doc_success = result.returncode == 0
                
                if doc_success:
                    print("   ✅ Documentation update COMPLETED")
                else:
                    print("   ❌ Documentation update FAILED")
                    print(f"   Error: {result.stderr}")
                    
                # 尝试加载文档报告
                doc_report_file = self.project_root / 'day25-28_documentation_report.json'
                doc_details = None
                
                if doc_report_file.exists():
                    try:
                        with open(doc_report_file) as f:
                            doc_details = json.load(f)
                    except Exception as e:
                        print(f"   ⚠️ Could not load documentation report: {e}")
                        
            except subprocess.TimeoutExpired:
                doc_success = False
                print("   ⏰ Documentation update timed out")
                doc_details = None
                
        else:
            doc_success = False
            doc_details = None
            print(f"   ⚠️ Documentation script not found: {doc_script}")
            
        phase_time = time.time() - phase_start
        
        doc_summary = {
            'success': doc_success,
            'phase_time': phase_time,
            'details': doc_details,
            'output': result.stdout if 'result' in locals() else None,
            'error': result.stderr if 'result' in locals() and result.returncode != 0 else None
        }
        
        print(f"\n📊 Documentation Update Summary:")
        print(f"   Status: {'COMPLETED' if doc_success else 'FAILED'}")
        print(f"   Execution time: {phase_time:.2f}s")
        
        if doc_details:
            files_updated = doc_details.get('files_updated', [])
            print(f"   Files updated: {len(files_updated)}")
            for file_info in files_updated[:5]:  # 显示前5个
                print(f"     📄 {file_info}")
            if len(files_updated) > 5:
                print(f"     ... and {len(files_updated) - 5} more")
                
        self.phase_results['documentation_update'] = doc_summary
        return doc_summary
        
    def run_code_review(self):
        """运行代码审查"""
        self.print_phase_header("代码审查", "🔍")
        
        phase_start = time.time()
        
        review_script = 'tools/code_review_automation.py'
        
        if (self.project_root / review_script).exists():
            print(f"\n🔎 Running automated code review...")
            
            try:
                result = subprocess.run([
                    sys.executable, review_script
                ], capture_output=True, text=True, timeout=600)
                
                review_success = result.returncode == 0
                
                if review_success:
                    print("   ✅ Code review PASSED")
                else:
                    print("   ❌ Code review FAILED")
                    
                # 尝试加载审查报告
                review_report_file = self.project_root / 'day25-28_code_review_report.json'
                review_details = None
                
                if review_report_file.exists():
                    try:
                        with open(review_report_file) as f:
                            review_details = json.load(f)
                    except Exception as e:
                        print(f"   ⚠️ Could not load code review report: {e}")
                        
            except subprocess.TimeoutExpired:
                review_success = False
                print("   ⏰ Code review timed out")
                review_details = None
                
        else:
            review_success = False
            review_details = None
            print(f"   ⚠️ Code review script not found: {review_script}")
            
        phase_time = time.time() - phase_start
        
        review_summary = {
            'success': review_success,
            'phase_time': phase_time,
            'details': review_details,
            'output': result.stdout if 'result' in locals() else None,
            'error': result.stderr if 'result' in locals() and result.returncode != 0 else None
        }
        
        print(f"\n📊 Code Review Summary:")
        print(f"   Status: {'PASSED' if review_success else 'FAILED'}")
        print(f"   Execution time: {phase_time:.2f}s")
        
        if review_details and 'review_summary' in review_details:
            summary = review_details['review_summary']
            total_checks = summary.get('total_checks', 0)
            passed_checks = summary.get('passed_checks', 0)
            critical_issues = summary.get('critical_issues', 0)
            
            print(f"   Total checks: {total_checks}")
            print(f"   Passed checks: {passed_checks}")
            print(f"   Critical issues: {critical_issues}")
            
            decision = summary.get('review_decision', 'Unknown')
            print(f"   Decision: {decision}")
            
        self.phase_results['code_review'] = review_summary
        return review_summary
        
    def generate_final_release_report(self):
        """生成最终发布报告"""
        self.print_phase_header("发布决定", "🎯")
        
        total_time = time.time() - self.start_time
        
        # 评估所有阶段的结果
        all_phases_passed = all(
            phase.get('success', False) 
            for phase in self.phase_results.values()
        )
        
        # 计算整体健康度
        health_score = 0
        total_weight = 0
        
        phase_weights = {
            'regression_tests': 0.3,
            'user_acceptance_tests': 0.3,
            'code_review': 0.25,
            'documentation_update': 0.15
        }
        
        for phase_name, weight in phase_weights.items():
            if phase_name in self.phase_results:
                phase_result = self.phase_results[phase_name]
                if phase_result.get('success', False):
                    health_score += weight * 100
                total_weight += weight
                
        health_percentage = health_score / total_weight if total_weight > 0 else 0
        
        # 生成发布决定
        if health_percentage >= 90:
            release_decision = "✅ APPROVED FOR RELEASE"
            decision_color = "🟢"
        elif health_percentage >= 75:
            release_decision = "⚠️ CONDITIONAL APPROVAL"
            decision_color = "🟡"
        else:
            release_decision = "❌ REJECTED - NOT READY FOR RELEASE"
            decision_color = "🔴"
            
        # 打印最终报告
        print(f"\n📋 Day 25-28 Final Release Report")
        print(f"{'='*60}")
        
        print(f"\n⏱️ Total Execution Time: {total_time:.2f}s")
        print(f"🎯 Overall Health Score: {health_percentage:.1f}%")
        
        print(f"\n📊 Phase Results:")
        for phase_name, result in self.phase_results.items():
            status = "✅ PASS" if result.get('success', False) else "❌ FAIL"
            phase_time = result.get('phase_time', 0)
            print(f"   {phase_name}: {status} ({phase_time:.1f}s)")
            
        print(f"\n{decision_color} Release Decision: {release_decision}")
        
        # 关键指标摘要
        if 'regression_tests' in self.phase_results:
            regression = self.phase_results['regression_tests']
            success_rate = regression.get('success_rate', 0)
            print(f"\n🧪 Regression Tests: {success_rate:.1f}% pass rate")
            
        if 'user_acceptance_tests' in self.phase_results:
            uat = self.phase_results['user_acceptance_tests']
            if uat.get('details') and 'user_feedback' in uat['details']:
                feedback = uat['details']['user_feedback']
                overall = feedback.get('overall_satisfaction', {})
                rating = overall.get('rating', 0)
                print(f"👥 User Satisfaction: {rating:.1f}/5.0 ⭐")
                
        if 'code_review' in self.phase_results:
            review = self.phase_results['code_review']
            if review.get('details') and 'review_summary' in review['details']:
                summary = review['details']['review_summary']
                critical_issues = summary.get('critical_issues', 0)
                print(f"🔍 Critical Issues: {critical_issues}")
                
        # 保存最终报告
        final_report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'phase': 'Day 25-28 Verification and Release',
            'total_time': total_time,
            'health_score': health_percentage,
            'release_decision': release_decision,
            'phase_results': self.phase_results
        }
        
        report_file = self.project_root / 'day25-28_final_release_report.json'
        with open(report_file, 'w') as f:
            json.dump(final_report, f, indent=2, default=str)
            
        print(f"\n📄 Final report saved to: {report_file}")
        
        return {
            'health_score': health_percentage,
            'release_decision': release_decision,
            'all_phases_passed': all_phases_passed,
            'total_time': total_time,
            'report_file': str(report_file)
        }
        
    def run_complete_verification_and_release(self):
        """运行完整的验证和发布流程"""
        print("\n" + "🚀" * 30)
        print("Day 25-28: Store System Verification and Release")
        print("🚀" * 30)
        
        print(f"\n📅 Start Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📁 Project Root: {self.project_root.absolute()}")
        
        try:
            # 阶段 1: 回归测试
            regression_result = self.run_regression_tests()
            
            # 阶段 2: 用户验收测试
            uat_result = self.run_user_acceptance_tests()
            
            # 阶段 3: 文档完善
            doc_result = self.run_documentation_update()
            
            # 阶段 4: 代码审查
            review_result = self.run_code_review()
            
            # 最终发布决定
            final_result = self.generate_final_release_report()
            
            return final_result
            
        except Exception as e:
            print(f"\n❌ Day 25-28 execution failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'health_score': 0,
                'release_decision': "❌ EXECUTION FAILED",
                'all_phases_passed': False,
                'error': str(e)
            }


def main():
    """主执行函数"""
    orchestrator = Day25To28Orchestrator()
    
    try:
        # 运行完整的验证和发布流程
        result = orchestrator.run_complete_verification_and_release()
        
        # 基于健康评分确定退出码
        health_score = result.get('health_score', 0)
        
        if health_score >= 75:
            print(f"\n✅ Day 25-28 completed successfully!")
            print(f"🎯 Health Score: {health_score:.1f}%")
            return True
        else:
            print(f"\n❌ Day 25-28 failed to meet release criteria")
            print(f"🎯 Health Score: {health_score:.1f}%")
            return False
            
    except Exception as e:
        print(f"\n💥 Day 25-28 execution failed: {str(e)}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 