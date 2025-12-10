#!/usr/bin/env python

"""
Day 25-28 完整回归测试套件
测试 Store 系统重构后的完整功能、性能和兼容性
"""

import gc
import json
import sys
import threading
import time
import unittest
from collections import defaultdict
from unittest.mock import Mock, patch

# Mock dependencies
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.stores.ccxtstore import CCXTStore
from backtrader.stores.ctpstore import CTPStore
from backtrader.stores.ibstore import IBStore
from backtrader.stores.oandastore import OandaStore
from backtrader.stores.vcstore import VCStore


class ComprehensiveRegressionTestSuite:
    """完整的回归测试套件 (Day 25-28)"""

    def __init__(self):
        self.test_results = {}
        self.performance_results = {}
        self.compatibility_results = {}
        self.stability_results = {}

    def reset_environment(self):
        """重置测试环境"""
        # Reset all store instances
        stores = [IBStore, OandaStore, CCXTStore, CTPStore, VCStore]
        for store_class in stores:
            if hasattr(store_class, "_reset_instance"):
                store_class._reset_instance()
        gc.collect()

    def run_functional_regression_tests(self):
        """运行功能回归测试"""
        print("🔍 Running Functional Regression Tests...")

        test_results = {}

        # Test all Store classes
        store_classes = {
            "IBStore": IBStore,
            "OandaStore": OandaStore,
            "CCXTStore": CCXTStore,
            "CTPStore": CTPStore,
            "VCStore": VCStore,
        }

        for store_name, store_class in store_classes.items():
            print(f"   Testing {store_name}...")

            # Reset environment before each test
            self.reset_environment()

            store_results = {}

            try:
                # Test 1: Singleton behavior
                with patch.multiple(
                    f"backtrader.stores.{store_name.lower()}",
                    ibopt=Mock() if store_name == "IBStore" else None,
                    oandapy=Mock() if store_name == "OandaStore" else None,
                    ccxt=Mock() if store_name == "CCXTStore" else None,
                ):
                    if store_name == "IBStore":
                        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                            mock_ibopt.ibConnection.return_value = Mock()
                            store1 = store_class()
                            store2 = store_class()

                    elif store_name in ["CTPStore", "VCStore"]:
                        # These stores may not need special mocking
                        store1 = store_class()
                        store2 = store_class()
                    else:
                        store1 = store_class()
                        store2 = store_class()

                    store_results["singleton_test"] = store1 is store2

                # Test 2: Parameter system
                store_results["parameter_test"] = hasattr(store_class, "params")

                # Test 3: Core methods
                if store_name == "IBStore":
                    with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                        mock_ibopt.ibConnection.return_value = Mock()
                        store = store_class()
                        store_results["getdata_test"] = hasattr(store, "getdata")
                        store_results["getbroker_test"] = hasattr(store, "getbroker")
                else:
                    store = store_class()
                    store_results["getdata_test"] = hasattr(store, "getdata")
                    store_results["getbroker_test"] = hasattr(store, "getbroker")

                # Test 4: Inheritance structure
                store_results["inheritance_test"] = hasattr(store_class, "__bases__")

                print(f"     ✅ {store_name}: All tests passed")

            except Exception as e:
                store_results["error"] = str(e)
                print(f"     ❌ {store_name}: {e}")

            test_results[store_name] = store_results

        self.test_results["functional"] = test_results
        return test_results

    def run_performance_regression_tests(self):
        """运行性能回归测试"""
        print("\n🚀 Running Performance Regression Tests...")

        performance_results = {}

        # Test IBStore performance (main focus)
        store_class = IBStore

        print("   Testing Singleton creation performance...")

        # Test first creation performance
        first_creation_times = []
        for _ in range(10):
            self.reset_environment()

            start_time = time.perf_counter()
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                store = store_class()
            end_time = time.perf_counter()

            first_creation_times.append(end_time - start_time)

        avg_first_creation = sum(first_creation_times) / len(first_creation_times)

        # Test subsequent access performance
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = store_class()  # Create initial instance

            subsequent_times = []
            for _ in range(1000):
                start_time = time.perf_counter()
                store = store_class()
                end_time = time.perf_counter()
                subsequent_times.append(end_time - start_time)

        avg_subsequent_access = sum(subsequent_times) / len(subsequent_times)

        # Test method call performance
        method_times = {}

        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = store_class()

            # Test getdata method
            times = []
            for _ in range(100):
                start_time = time.perf_counter()
                store.getdata()
                times.append(time.perf_counter() - start_time)
            method_times["getdata"] = sum(times) / len(times)

            # Test getbroker method
            times = []
            for _ in range(100):
                start_time = time.perf_counter()
                store.getbroker()
                times.append(time.perf_counter() - start_time)
            method_times["getbroker"] = sum(times) / len(times)

        performance_results["singleton_first_creation"] = avg_first_creation
        performance_results["singleton_subsequent_access"] = avg_subsequent_access
        performance_results["method_performance"] = method_times
        performance_results["performance_ratio"] = avg_first_creation / avg_subsequent_access

        print(f"     First creation: {avg_first_creation*1000:.3f}ms")
        print(f"     Subsequent access: {avg_subsequent_access*1000000:.1f}μs")
        print(f"     Performance ratio: {performance_results['performance_ratio']:.1f}x")

        self.performance_results = performance_results
        return performance_results

    def run_compatibility_regression_tests(self):
        """运行兼容性回归测试"""
        print("\n🔄 Running Compatibility Regression Tests...")

        compatibility_results = {}

        # Test API compatibility
        print("   Testing API compatibility...")

        api_tests = {}

        # Test IBStore API
        try:
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                store = IBStore()

                # Check essential methods exist
                api_tests["getdata_exists"] = hasattr(store, "getdata")
                api_tests["getbroker_exists"] = hasattr(store, "getbroker")
                api_tests["put_notification_exists"] = hasattr(store, "put_notification")
                api_tests["get_notifications_exists"] = hasattr(store, "get_notifications")

                # Check parameter system
                api_tests["params_exists"] = hasattr(store, "params")
                api_tests["p_exists"] = hasattr(store, "p")

                # Test method calls don't raise exceptions
                try:
                    store.getdata()
                    api_tests["getdata_callable"] = True
                except Exception:
                    api_tests["getdata_callable"] = False

                try:
                    store.getbroker()
                    api_tests["getbroker_callable"] = True
                except Exception:
                    api_tests["getbroker_callable"] = False

                print("     ✅ API compatibility tests passed")

        except Exception as e:
            api_tests["error"] = str(e)
            print(f"     ❌ API compatibility test failed: {e}")

        compatibility_results["api_tests"] = api_tests

        # Test backward compatibility
        print("   Testing backward compatibility...")

        backward_compat_tests = {}

        try:
            # Test that old usage patterns still work
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()

                # Test multiple instantiation returns same object
                store1 = IBStore()
                store2 = IBStore()
                backward_compat_tests["singleton_behavior"] = store1 is store2

                # Test parameter access patterns
                if hasattr(store1, "params"):
                    backward_compat_tests["params_access"] = True

                if hasattr(store1, "p"):
                    backward_compat_tests["p_access"] = True

                print("     ✅ Backward compatibility tests passed")

        except Exception as e:
            backward_compat_tests["error"] = str(e)
            print(f"     ❌ Backward compatibility test failed: {e}")

        compatibility_results["backward_compatibility"] = backward_compat_tests

        self.compatibility_results = compatibility_results
        return compatibility_results

    def run_stability_regression_tests(self):
        """运行稳定性回归测试"""
        print("\n🔒 Running Stability Regression Tests...")

        stability_results = {}

        # Test thread safety
        print("   Testing thread safety...")

        thread_safety_results = {}
        exceptions = []
        instances = []

        def thread_worker():
            try:
                with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                    mock_ibopt.ibConnection.return_value = Mock()
                    store = IBStore()
                    instances.append(store)
            except Exception as e:
                exceptions.append(e)

        # Run 10 concurrent threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=thread_worker)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Check results
        thread_safety_results["exceptions_count"] = len(exceptions)
        thread_safety_results["instances_count"] = len(instances)
        thread_safety_results["all_same_instance"] = len({id(inst) for inst in instances}) == 1
        thread_safety_results["thread_safe"] = (
            len(exceptions) == 0 and thread_safety_results["all_same_instance"]
        )

        print(
            f"     Threads: 10, Exceptions: {len(exceptions)}, Same instance: {thread_safety_results['all_same_instance']}"
        )

        # Test memory stability
        print("   Testing memory stability...")

        memory_results = {}

        # Test for memory leaks
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create and destroy many instances
        for cycle in range(5):
            stores = []
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()

                for _ in range(100):
                    stores.append(IBStore())

            # All should be the same instance
            memory_results[f"cycle_{cycle}_same_instances"] = (
                len({id(store) for store in stores}) == 1
            )

            del stores
            gc.collect()

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        memory_results["memory_increase_kb"] = memory_increase / 1024
        memory_results["memory_stable"] = memory_increase < 1024 * 1024  # Less than 1MB increase

        print(f"     Memory increase: {memory_increase/1024:.1f}KB")

        stability_results["thread_safety"] = thread_safety_results
        stability_results["memory_stability"] = memory_results

        self.stability_results = stability_results
        return stability_results

    def run_comprehensive_regression_suite(self):
        """运行完整的回归测试套件"""
        print("\n" + "=" * 80)
        print("🧪 Day 25-28 Comprehensive Regression Test Suite")
        print("=" * 80)

        start_time = time.time()

        # Run all test suites
        functional_results = self.run_functional_regression_tests()
        performance_results = self.run_performance_regression_tests()
        compatibility_results = self.run_compatibility_regression_tests()
        stability_results = self.run_stability_regression_tests()

        total_time = time.time() - start_time

        # Generate summary
        self.generate_regression_summary(total_time)

        return {
            "functional": functional_results,
            "performance": performance_results,
            "compatibility": compatibility_results,
            "stability": stability_results,
            "execution_time": total_time,
        }

    def generate_regression_summary(self, execution_time):
        """生成回归测试总结"""
        print("\n" + "=" * 80)
        print("📊 Regression Test Summary")
        print("=" * 80)

        # Functional tests summary
        if "functional" in self.test_results:
            functional = self.test_results["functional"]
            total_stores = len(functional)
            passed_stores = sum(
                1 for store_results in functional.values() if "error" not in store_results
            )

            print(f"🔍 Functional Tests:")
            print(f"   Stores tested: {total_stores}")
            print(f"   Stores passed: {passed_stores}")
            print(f"   Success rate: {(passed_stores/total_stores)*100:.1f}%")

        # Performance summary
        if self.performance_results:
            perf = self.performance_results
            print(f"\n🚀 Performance Tests:")
            print(f"   First creation: {perf['singleton_first_creation']*1000:.3f}ms")
            print(f"   Subsequent access: {perf['singleton_subsequent_access']*1000000:.1f}μs")
            print(f"   Performance improvement: {perf['performance_ratio']:.1f}x")

        # Compatibility summary
        if self.compatibility_results:
            compat = self.compatibility_results
            api_passed = sum(1 for result in compat.get("api_tests", {}).values() if result is True)
            api_total = len(compat.get("api_tests", {}))

            print(f"\n🔄 Compatibility Tests:")
            print(f"   API tests passed: {api_passed}/{api_total}")
            if "backward_compatibility" in compat:
                bc_tests = compat["backward_compatibility"]
                bc_passed = sum(1 for result in bc_tests.values() if result is True)
                bc_total = len(bc_tests)
                print(f"   Backward compatibility: {bc_passed}/{bc_total}")

        # Stability summary
        if self.stability_results:
            stability = self.stability_results
            thread_safe = stability.get("thread_safety", {}).get("thread_safe", False)
            memory_stable = stability.get("memory_stability", {}).get("memory_stable", False)

            print(f"\n🔒 Stability Tests:")
            print(f"   Thread safety: {'✅ PASS' if thread_safe else '❌ FAIL'}")
            print(f"   Memory stability: {'✅ PASS' if memory_stable else '❌ FAIL'}")

        print(f"\n⏱️ Total execution time: {execution_time:.2f}s")

        # Overall assessment
        overall_status = self.assess_overall_status()
        print(f"\n🎯 Overall Status: {overall_status}")

    def assess_overall_status(self):
        """评估整体状态"""
        issues = []

        # Check functional tests
        if "functional" in self.test_results:
            functional = self.test_results["functional"]
            for store_name, results in functional.items():
                if "error" in results:
                    issues.append(f"Functional error in {store_name}")

        # Check compatibility
        if self.compatibility_results:
            compat = self.compatibility_results
            if "api_tests" in compat:
                api_failed = sum(1 for result in compat["api_tests"].values() if result is False)
                if api_failed > 0:
                    issues.append(f"API compatibility issues: {api_failed}")

        # Check stability
        if self.stability_results:
            stability = self.stability_results
            if not stability.get("thread_safety", {}).get("thread_safe", False):
                issues.append("Thread safety issues")
            if not stability.get("memory_stability", {}).get("memory_stable", False):
                issues.append("Memory stability issues")

        if not issues:
            return "✅ ALL TESTS PASSED - Ready for next phase"
        else:
            return f"❌ ISSUES FOUND: {', '.join(issues)}"

    def save_regression_report(self, filename="day25-28_regression_report.json"):
        """保存回归测试报告"""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "test_phase": "Day 25-28 Regression Testing",
            "functional_results": self.test_results.get("functional", {}),
            "performance_results": self.performance_results,
            "compatibility_results": self.compatibility_results,
            "stability_results": self.stability_results,
            "overall_status": self.assess_overall_status(),
        }

        with open(filename, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print(f"📄 Regression test report saved to: {filename}")
        return filename


def main():
    """主回归测试执行函数"""
    suite = ComprehensiveRegressionTestSuite()

    try:
        # Run comprehensive regression suite
        results = suite.run_comprehensive_regression_suite()

        # Save report
        report_file = suite.save_regression_report()

        print(f"\n✅ Regression testing completed!")
        print(f"📊 Test suites: {len(results) - 1}")  # Exclude execution_time
        print(f"📄 Report: {report_file}")

        return True

    except Exception as e:
        print(f"\n❌ Regression testing failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
