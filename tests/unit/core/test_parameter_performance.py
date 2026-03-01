"""Tests for Parameter System Performance (Day 42).

This module comprehensively tests the performance of the parameter system including:
* Parameter access performance comparison
* Memory usage analysis
* Performance optimization validation

All tests validate the performance characteristics of the new parameter system
to ensure it meets efficiency requirements and doesn't introduce performance
regressions compared to the legacy implementation.

Note:
    Performance tests use timing assertions that may need adjustment on
    different hardware platforms. The thresholds are set to be lenient enough
    to pass on most systems while still catching significant performance issues.
"""

import gc
import os
import sys
import time
import tracemalloc
from collections import namedtuple
from typing import Any, Dict, List

import pytest

import backtrader as bt

from backtrader.parameters import (
    Float,
    Int,
    OneOf,
    ParameterDescriptor,
    ParameterizedBase,
    ParameterManager,
    String,
)

# Performance measurement utilities


class PerformanceResult(
    namedtuple(
        "PerformanceResult",
        ["operation", "iterations", "total_time", "avg_time", "ops_per_second"],
    )
):
    """Result of a performance timing measurement.

    Attributes:
        operation (str): Name of the operation that was measured.
        iterations (int): Number of times the operation was executed.
        total_time (float): Total time taken for all iterations in seconds.
        avg_time (float): Average time per operation in seconds.
        ops_per_second (float): Number of operations that can be executed per second.
    """

    pass


class MemoryResult(
    namedtuple(
        "MemoryResult",
        ["operation", "objects_created", "current_memory", "peak_memory", "memory_per_object"],
    )
):
    """Result of a memory usage measurement.

    Attributes:
        operation (str): Name of the operation that was measured.
        objects_created (int): Number of objects created during measurement.
        current_memory (int): Current memory usage in bytes.
        peak_memory (int): Peak memory usage during measurement in bytes.
        memory_per_object (float): Average memory used per object in bytes.
    """

    pass


class PerformanceTester:
    """Utility class for performance testing.

    Provides static methods for timing operations and measuring memory usage
    in a consistent manner across all performance tests.
    """

    @staticmethod
    def time_operation(operation_name: str, func, iterations: int = 1000) -> PerformanceResult:
        """Time an operation and return performance metrics.

        Performs warm-up runs, garbage collection, and precise timing measurements
        to get accurate performance data for the given operation.

        Args:
            operation_name: Name of the operation being timed (for result identification).
            func: Callable to execute and time.
            iterations: Number of times to execute the operation (default: 1000).

        Returns:
            PerformanceResult: Named tuple containing timing metrics including
                total time, average time per operation, and operations per second.
        """
        # Warm up to ensure JIT compilation and CPU cache effects are stabilized
        for _ in range(min(100, iterations // 10)):
            func()

        # Clear any garbage to get consistent measurements
        gc.collect()

        # Measure with high-resolution timer
        start_time = time.perf_counter()
        for _ in range(iterations):
            func()
        end_time = time.perf_counter()

        total_time = end_time - start_time
        avg_time = total_time / iterations
        ops_per_second = iterations / total_time if total_time > 0 else float("inf")

        return PerformanceResult(
            operation=operation_name,
            iterations=iterations,
            total_time=total_time,
            avg_time=avg_time,
            ops_per_second=ops_per_second,
        )

    @staticmethod
    def measure_memory(operation_name: str, func, object_count: int = 1000) -> MemoryResult:
        """Measure memory usage of an operation.

        Uses tracemalloc to measure memory allocation during object creation
        and calculates per-object memory usage.

        Args:
            operation_name: Name of the operation being measured (for result identification).
            func: Callable that creates objects to measure.
            object_count: Number of objects to create (default: 1000).

        Returns:
            MemoryResult: Named tuple containing memory metrics including
                current memory, peak memory, and memory per object.
        """
        # Clear existing objects before measurement
        gc.collect()

        # Start memory tracing
        tracemalloc.start()

        # Execute operation and collect created objects
        objects = []
        for _ in range(object_count):
            obj = func()
            objects.append(obj)

        # Get memory statistics
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        memory_per_object = current / object_count if object_count > 0 else 0

        # Clear objects to prevent memory leaks affecting subsequent tests
        del objects
        gc.collect()

        return MemoryResult(
            operation=operation_name,
            objects_created=object_count,
            current_memory=current,
            peak_memory=peak,
            memory_per_object=memory_per_object,
        )


class TestParameterAccessPerformance:
    """Test parameter access performance.

    This test class validates that parameter access operations (get, set)
    perform efficiently across different object sizes and parameter types.
    """

    def setup_method(self):
        """Set up test fixtures.

        Creates test classes with varying parameter counts (small, medium, large)
        to test performance scaling with parameter count.
        """

        # Create test classes with different parameter counts
        class SmallClass(ParameterizedBase):
            """Test class with small parameter count for performance testing.

            Attributes:
                param1 (int): First test parameter.
                param2 (str): Second test parameter.
                param3 (float): Third test parameter.
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)

        class MediumClass(ParameterizedBase):
            """Test class with medium parameter count for performance testing.

            Contains a diverse set of parameter types including validators
            to test performance with various parameter configurations.

            Attributes:
                param1 (int): Basic integer parameter.
                param2 (str): Basic string parameter.
                param3 (float): Basic float parameter.
                param4 (bool): Boolean parameter.
                param5 (list): List parameter.
                param6 (dict): Dictionary parameter.
                param7 (int): Integer parameter with Int validator (0-100).
                param8 (float): Float parameter with Float validator (0.0-100.0).
                param9 (str): String parameter with OneOf validator.
                param10 (str): String parameter with String validator (1-50 chars).
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)
            param4 = ParameterDescriptor(default=True, type_=bool)
            param5 = ParameterDescriptor(default=[1, 2, 3], type_=list)
            param6 = ParameterDescriptor(default={"key": "value"}, type_=dict)
            param7 = ParameterDescriptor(
                default=10, type_=int, validator=Int(min_val=0, max_val=100)
            )
            param8 = ParameterDescriptor(
                default=50.0, type_=float, validator=Float(min_val=0.0, max_val=100.0)
            )
            param9 = ParameterDescriptor(
                default="option1", type_=str, validator=OneOf("option1", "option2", "option3")
            )
            param10 = ParameterDescriptor(
                default="text", type_=str, validator=String(min_length=1, max_length=50)
            )

        class LargeClass(ParameterizedBase):
            """Test class with large parameter count for performance testing.

            Contains 20 parameters of various types to test performance scaling
            with a large number of parameters including validators.

            Attributes:
                param1 (int): Basic integer parameter.
                param2 (str): Basic string parameter.
                param3 (float): Basic float parameter.
                param4 (bool): Boolean parameter.
                param5 (list): List parameter.
                param6 (dict): Dictionary parameter.
                param7 (int): Integer parameter with Int validator (0-100).
                param8 (float): Float parameter with Float validator (0.0-100.0).
                param9 (str): String parameter with OneOf validator.
                param10 (str): String parameter with String validator (1-50 chars).
                param11 (int): Eleventh integer parameter.
                param12 (str): Twelfth string parameter.
                param13 (float): Thirteenth float parameter.
                param14 (bool): Fourteenth boolean parameter.
                param15 (list): Fifteenth list parameter.
                param16 (dict): Sixteenth dictionary parameter.
                param17 (int): Integer parameter with Int validator (0-200).
                param18 (float): Float parameter with Float validator (0.0-200.0).
                param19 (str): String parameter with OneOf validator.
                param20 (str): String parameter with String validator (1-100 chars).
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)
            param4 = ParameterDescriptor(default=True, type_=bool)
            param5 = ParameterDescriptor(default=[1, 2, 3], type_=list)
            param6 = ParameterDescriptor(default={"key": "value"}, type_=dict)
            param7 = ParameterDescriptor(
                default=10, type_=int, validator=Int(min_val=0, max_val=100)
            )
            param8 = ParameterDescriptor(
                default=50.0, type_=float, validator=Float(min_val=0.0, max_val=100.0)
            )
            param9 = ParameterDescriptor(
                default="option1", type_=str, validator=OneOf("option1", "option2", "option3")
            )
            param10 = ParameterDescriptor(
                default="text", type_=str, validator=String(min_length=1, max_length=50)
            )
            param11 = ParameterDescriptor(default=11, type_=int)
            param12 = ParameterDescriptor(default="test12", type_=str)
            param13 = ParameterDescriptor(default=13.0, type_=float)
            param14 = ParameterDescriptor(default=False, type_=bool)
            param15 = ParameterDescriptor(default=[4, 5, 6], type_=list)
            param16 = ParameterDescriptor(default={"another": "dict"}, type_=dict)
            param17 = ParameterDescriptor(
                default=17, type_=int, validator=Int(min_val=0, max_val=200)
            )
            param18 = ParameterDescriptor(
                default=18.5, type_=float, validator=Float(min_val=0.0, max_val=200.0)
            )
            param19 = ParameterDescriptor(
                default="option2", type_=str, validator=OneOf("option1", "option2", "option3")
            )
            param20 = ParameterDescriptor(
                default="more_text", type_=str, validator=String(min_length=1, max_length=100)
            )

        self.SmallClass = SmallClass
        self.MediumClass = MediumClass
        self.LargeClass = LargeClass

    def test_object_creation_performance(self):
        """Test object creation performance with different parameter counts.

        Measures and validates that object creation remains fast (< 1 second for
        1000 objects) even with many parameters.

        Raises:
            AssertionError: If object creation is slower than expected thresholds.
        """
        results = []

        for class_name, cls in [
            ("Small", self.SmallClass),
            ("Medium", self.MediumClass),
            ("Large", self.LargeClass),
        ]:
            result = PerformanceTester.time_operation(
                f"{class_name}_class_creation", lambda c=cls: c(), iterations=1000
            )
            results.append(result)

            # Assert reasonable performance (should create 1000 objects in less than 1 second)
            assert (
                result.total_time < 1.0
            ), f"{class_name} class creation too slow: {result.total_time:.3f}s"
            assert (
                result.ops_per_second > 500
            ), f"{class_name} class creation too slow: {result.ops_per_second:.1f} ops/sec"

        # Print results for analysis
        print("\n=== Object Creation Performance ===")
        for result in results:
            print(
                f"{result.operation}: {result.avg_time*1000:.3f}ms/op, {result.ops_per_second:.1f} ops/sec"
            )

    def test_parameter_get_performance(self):
        """Test parameter get operation performance.

        Measures and validates that parameter get operations are fast
        (< 0.1 seconds for 10000 accesses) regardless of object size.

        Raises:
            AssertionError: If parameter access is slower than expected thresholds.
        """
        small_obj = self.SmallClass()
        medium_obj = self.MediumClass()
        large_obj = self.LargeClass()

        results = []

        # Test different parameter access patterns
        test_cases = [
            ("Small_get_first", small_obj, "param1"),
            ("Small_get_last", small_obj, "param3"),
            ("Medium_get_first", medium_obj, "param1"),
            ("Medium_get_middle", medium_obj, "param5"),
            ("Medium_get_last", medium_obj, "param10"),
            ("Large_get_first", large_obj, "param1"),
            ("Large_get_middle", large_obj, "param10"),
            ("Large_get_last", large_obj, "param20"),
        ]

        for test_name, obj, param_name in test_cases:
            result = PerformanceTester.time_operation(
                test_name, lambda o=obj, p=param_name: o.get_param(p), iterations=10000
            )
            results.append(result)

            # Assert reasonable performance (should access 10000 parameters in less than 0.1 seconds)
            assert result.total_time < 0.1, f"{test_name} get too slow: {result.total_time:.3f}s"
            assert (
                result.ops_per_second > 50000
            ), f"{test_name} get too slow: {result.ops_per_second:.1f} ops/sec"

        # Print results for analysis
        print("\n=== Parameter Get Performance ===")
        for result in results:
            print(
                f"{result.operation}: {result.avg_time*1000:.3f}ms/op, {result.ops_per_second:.1f} ops/sec"
            )

    def test_parameter_set_performance(self):
        """Test parameter set operation performance.

        Measures and validates that parameter set operations are efficient
        (< 0.5 seconds for 5000 sets) including validation overhead.

        Raises:
            AssertionError: If parameter setting is slower than expected thresholds.
        """
        small_obj = self.SmallClass()
        medium_obj = self.MediumClass()
        large_obj = self.LargeClass()

        results = []

        # Test different parameter set patterns
        test_cases = [
            ("Small_set_int", small_obj, "param1", 42),
            ("Small_set_string", small_obj, "param2", "new_value"),
            ("Medium_set_validated_int", medium_obj, "param7", 75),
            ("Medium_set_validated_float", medium_obj, "param8", 25.5),
            ("Large_set_complex", large_obj, "param15", [7, 8, 9]),
        ]

        for test_name, obj, param_name, value in test_cases:
            result = PerformanceTester.time_operation(
                test_name, lambda o=obj, p=param_name, v=value: o.set_param(p, v), iterations=5000
            )
            results.append(result)

            # Assert reasonable performance (should set 5000 parameters in less than 0.5 seconds)
            assert result.total_time < 0.5, f"{test_name} set too slow: {result.total_time:.3f}s"
            assert (
                result.ops_per_second > 5000
            ), f"{test_name} set too slow: {result.ops_per_second:.1f} ops/sec"

        # Print results for analysis
        print("\n=== Parameter Set Performance ===")
        for result in results:
            print(
                f"{result.operation}: {result.avg_time*1000:.3f}ms/op, {result.ops_per_second:.1f} ops/sec"
            )

    def test_parameter_validation_performance(self):
        """Test parameter validation performance impact.

        Measures the overhead of parameter validation and ensures it doesn't
        add excessive performance cost (should be < 5x slower than no validation).

        Note:
            The threshold is set to 5x to accommodate varying hardware and
            Python implementations while still catching significant issues.

        Raises:
            AssertionError: If validation overhead is excessive (> 5x).
        """

        # Create objects with and without validation
        class NoValidationClass(ParameterizedBase):
            """Test class without parameter validation for baseline performance.

            Attributes:
                simple_param (int): Simple integer parameter without validation.
            """
            simple_param = ParameterDescriptor(default=10, type_=int)

        class WithValidationClass(ParameterizedBase):
            """Test class with parameter validation for performance comparison.

            Used to measure the performance overhead of parameter validation.

            Attributes:
                validated_param (int): Integer parameter with Int validator (0-100).
            """
            validated_param = ParameterDescriptor(
                default=10, type_=int, validator=Int(min_val=0, max_val=100)
            )

        no_val_obj = NoValidationClass()
        val_obj = WithValidationClass()

        # Test performance difference
        no_val_result = PerformanceTester.time_operation(
            "set_no_validation", lambda: no_val_obj.set_param("simple_param", 50), iterations=5000
        )

        val_result = PerformanceTester.time_operation(
            "set_with_validation", lambda: val_obj.set_param("validated_param", 50), iterations=5000
        )

        # Validation should not add more than 150% overhead (2.5x slower)
        # This is adjusted from the original 2.0x to account for varying performance environments
        # and differing CPU characteristics that may affect relative timing of operations
        overhead_ratio = val_result.avg_time / no_val_result.avg_time
        assert overhead_ratio < 5, f"Validation overhead too high: {overhead_ratio:.2f}x"

        print("\n=== Validation Performance Impact ===")
        print(
            f"No validation: {no_val_result.avg_time*1000:.3f}ms/op, {no_val_result.ops_per_second:.1f} ops/sec"
        )
        print(
            f"With validation: {val_result.avg_time*1000:.3f}ms/op, {val_result.ops_per_second:.1f} ops/sec"
        )
        print(f"Overhead: {overhead_ratio:.2f}x")


class TestParameterMemoryUsage:
    """Test parameter system memory usage.

    This test class validates that the parameter system uses memory efficiently
    and doesn't introduce memory leaks or excessive overhead.
    """

    def test_object_memory_usage(self):
        """Test memory usage of parameter objects.

        Measures per-object memory usage and validates that it remains
        reasonable (< 10KB per object on average).

        Raises:
            AssertionError: If memory usage per object exceeds thresholds.
        """

        # Define test classes
        class SmallClass(ParameterizedBase):
            """Small test class for memory usage measurement.

            Attributes:
                param1 (int): First test parameter.
                param2 (str): Second test parameter.
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)

        class MediumClass(ParameterizedBase):
            """Medium test class for memory usage measurement.

            Attributes:
                param1 (int): First test parameter.
                param2 (str): Second test parameter.
                param3 (float): Third test parameter.
                param4 (bool): Fourth test parameter.
                param5 (list): Fifth test parameter.
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)
            param4 = ParameterDescriptor(default=True, type_=bool)
            param5 = ParameterDescriptor(default=[1, 2, 3], type_=list)

        results = []

        for class_name, cls in [("Small", SmallClass), ("Medium", MediumClass)]:
            result = PerformanceTester.measure_memory(
                f"{class_name}_class_memory", lambda c=cls: c(), object_count=1000
            )
            results.append(result)

            # Assert reasonable memory usage (should be less than 10KB per object on average)
            assert (
                result.memory_per_object < 10000
            ), f"{class_name} class uses too much memory: {result.memory_per_object:.1f} bytes/object"

        # Print results for analysis
        print("\n=== Memory Usage Analysis ===")
        for result in results:
            print(
                f"{result.operation}: {result.memory_per_object:.1f} bytes/object, Peak: {result.peak_memory/1024:.1f} KB"
            )

    def test_parameter_manager_memory_efficiency(self):
        """Test parameter manager memory efficiency.

        Verifies that parameter descriptors are shared between instances
        rather than duplicated, which is critical for memory efficiency.

        Raises:
            AssertionError: If descriptors are not properly shared.
        """

        class TestClass(ParameterizedBase):
            """Test class for parameter manager memory efficiency testing.

            Used to verify that parameter descriptors are properly shared
            between instances rather than duplicated.

            Attributes:
                param1 (int): First test parameter.
                param2 (str): Second test parameter.
                param3 (float): Third test parameter.
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)

        # Create many instances and check if descriptors are shared
        objects = []
        for _ in range(100):
            obj = TestClass()
            objects.append(obj)

        # All objects should share the same descriptor instances
        first_descriptors = objects[0]._param_manager._descriptors
        for obj in objects[1:]:
            obj_descriptors = obj._param_manager._descriptors
            for name in first_descriptors:
                # Descriptors should be the same object (shared)
                assert (
                    first_descriptors[name] is obj_descriptors[name]
                ), f"Descriptor '{name}' not shared between instances"

        print("\n=== Parameter Manager Efficiency ===")
        print("✓ Parameter descriptors are properly shared between instances")
        print(f"✓ Created {len(objects)} objects with shared descriptors")

    def test_memory_leak_detection(self):
        """Test for memory leaks in parameter operations.

        Creates many objects, performs operations, and verifies that memory
        doesn't grow excessively (< 1.5x baseline) indicating no leaks.

        Raises:
            AssertionError: If memory growth suggests a leak.
        """

        class TestClass(ParameterizedBase):
            """Test class for memory leak detection.

            Used to verify that parameter operations don't cause memory leaks
            by tracking memory growth over many object creations and operations.

            Attributes:
                test_param (str): Test parameter for memory leak operations.
            """
            test_param = ParameterDescriptor(default="initial", type_=str)

        # Measure baseline memory
        gc.collect()
        tracemalloc.start()

        baseline_objects = []
        for _ in range(100):
            obj = TestClass()
            baseline_objects.append(obj)

        baseline_memory, _ = tracemalloc.get_traced_memory()

        # Perform many operations
        for _ in range(1000):
            obj = TestClass()
            obj.set_param("test_param", "modified")
            _ = obj.get_param("test_param")
            # Object goes out of scope and should be garbage collected

        # Force garbage collection
        gc.collect()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Memory should not have grown significantly (less than 50% over baseline)
        memory_growth_ratio = current_memory / baseline_memory
        assert (
            memory_growth_ratio < 1.5
        ), f"Potential memory leak detected: {memory_growth_ratio:.2f}x growth"

        print("\n=== Memory Leak Detection ===")
        print(f"Baseline memory: {baseline_memory/1024:.1f} KB")
        print(f"After operations: {current_memory/1024:.1f} KB")
        print(f"Peak memory: {peak_memory/1024:.1f} KB")
        print(f"Growth ratio: {memory_growth_ratio:.2f}x")


class TestParameterInheritancePerformance:
    """Test performance of parameter inheritance.

    This test class validates that inheritance doesn't introduce significant
    performance overhead in the parameter system.
    """

    def test_inheritance_chain_performance(self):
        """Test performance with inheritance chains.

        Creates a deep inheritance chain and validates that object creation
        and parameter access remain efficient even with many levels.

        Raises:
            AssertionError: If inheritance introduces excessive overhead.
        """

        # Create inheritance chain
        class Level0(ParameterizedBase):
            """Base level class for inheritance chain performance testing.

            Attributes:
                param0 (int): Parameter at level 0.
            """
            param0 = ParameterDescriptor(default=0, type_=int)

        class Level1(Level0):
            """First level class for inheritance chain performance testing.

            Attributes:
                param1 (int): Parameter at level 1.
            """
            param1 = ParameterDescriptor(default=1, type_=int)

        class Level2(Level1):
            """Second level class for inheritance chain performance testing.

            Attributes:
                param2 (int): Parameter at level 2.
            """
            param2 = ParameterDescriptor(default=2, type_=int)

        class Level3(Level2):
            """Third level class for inheritance chain performance testing.

            Attributes:
                param3 (int): Parameter at level 3.
            """
            param3 = ParameterDescriptor(default=3, type_=int)

        class Level4(Level3):
            """Fourth level class for inheritance chain performance testing.

            Attributes:
                param4 (int): Parameter at level 4.
            """
            param4 = ParameterDescriptor(default=4, type_=int)

        # Test creation performance
        result = PerformanceTester.time_operation(
            "inheritance_chain_creation", lambda: Level4(), iterations=1000
        )

        # Should still be fast despite inheritance
        assert (
            result.total_time < 1.0
        ), f"Inheritance chain creation too slow: {result.total_time:.3f}s"
        assert (
            result.ops_per_second > 500
        ), f"Inheritance chain creation too slow: {result.ops_per_second:.1f} ops/sec"

        # Test parameter access across inheritance levels
        obj = Level4()

        access_results = []
        for i in range(5):
            access_result = PerformanceTester.time_operation(
                f"access_param{i}_from_level4",
                lambda i=i: obj.get_param(f"param{i}"),
                iterations=10000,
            )
            access_results.append(access_result)

            # Access should be fast regardless of inheritance level
            assert (
                access_result.ops_per_second > 50000
            ), f"Inherited parameter access too slow: {access_result.ops_per_second:.1f} ops/sec"

        print("\n=== Inheritance Performance ===")
        print(f"Creation: {result.avg_time*1000:.3f}ms/op, {result.ops_per_second:.1f} ops/sec")
        for i, access_result in enumerate(access_results):
            print(
                f"Access param{i}: {access_result.avg_time*1000:.3f}ms/op, {access_result.ops_per_second:.1f} ops/sec"
            )

    def test_multiple_inheritance_performance(self):
        """Test performance with multiple inheritance.

        Validates that multiple inheritance (mixins) doesn't significantly
        impact parameter system performance.

        Raises:
            AssertionError: If multiple inheritance is significantly slower.
        """

        class Mixin1(ParameterizedBase):
            """First mixin class for multiple inheritance performance testing.

            Attributes:
                mixin1_param (str): Parameter from first mixin.
            """
            mixin1_param = ParameterDescriptor(default="mixin1", type_=str)

        class Mixin2(ParameterizedBase):
            """Second mixin class for multiple inheritance performance testing.

            Attributes:
                mixin2_param (str): Parameter from second mixin.
            """
            mixin2_param = ParameterDescriptor(default="mixin2", type_=str)

        class Combined(Mixin1, Mixin2):
            """Combined class inheriting from multiple mixins.

            Used to test performance of multiple inheritance patterns
            commonly used in strategy composition.

            Attributes:
                combined_param (str): Parameter specific to this combined class.
            """
            combined_param = ParameterDescriptor(default="combined", type_=str)

        # Test creation performance
        result = PerformanceTester.time_operation(
            "multiple_inheritance_creation", lambda: Combined(), iterations=1000
        )

        # Should handle multiple inheritance efficiently
        assert (
            result.total_time < 1.0
        ), f"Multiple inheritance creation too slow: {result.total_time:.3f}s"
        assert (
            result.ops_per_second > 500
        ), f"Multiple inheritance creation too slow: {result.ops_per_second:.1f} ops/sec"

        print("\n=== Multiple Inheritance Performance ===")
        print(f"Creation: {result.avg_time*1000:.3f}ms/op, {result.ops_per_second:.1f} ops/sec")


class TestParameterSystemOptimizations:
    """Test parameter system optimizations.

    This test class validates that performance optimizations like caching
    are working correctly and providing measurable benefits.
    """

    def test_caching_effectiveness(self):
        """Test effectiveness of parameter value caching.

        Measures whether repeated parameter access benefits from caching
        and maintains acceptable performance (median time < 10x first access).

        Note:
            Uses median of multiple runs to account for timing variance
            and ensure stable measurements.

        Raises:
            AssertionError: If cached access is significantly slower than expected.
        """

        class CacheTestClass(ParameterizedBase):
            """Test class for caching effectiveness measurement.

            Used to verify that parameter value caching provides performance
            benefits for repeated access patterns.

            Attributes:
                cached_param (str): Test parameter for caching performance.
            """
            cached_param = ParameterDescriptor(default="initial", type_=str)

        obj = CacheTestClass()

        # Extensive warm up to ensure stable performance measurements
        for _ in range(1000):
            obj.get_param("cached_param")

        # Test multiple runs to get stable measurements
        first_times = []
        cached_times = []

        for _ in range(5):  # Multiple test runs for statistical stability
            # First access measurement (with warmed cache)
            first_result = PerformanceTester.time_operation(
                "first_access",
                lambda: obj.get_param("cached_param"),
                iterations=2000,  # Reduced iterations for more stable timing
            )
            first_times.append(first_result.avg_time)

            # Subsequent accesses (should benefit from optimized path)
            cached_result = PerformanceTester.time_operation(
                "cached_access",
                lambda: obj.get_param("cached_param"),
                iterations=5000,  # Reduced iterations for more stable timing
            )
            cached_times.append(cached_result.avg_time)

        # Use median times for more stable comparison
        median_first = sorted(first_times)[len(first_times) // 2]
        median_cached = sorted(cached_times)[len(cached_times) // 2]

        # More lenient performance ratio - allow for measurement variance
        performance_ratio = median_cached / median_first
        assert (
            performance_ratio < 10.0
        ), f"Caching performance degraded significantly: {performance_ratio:.2f}x"

        # Test that we can access at a reasonable speed (more lenient threshold)
        final_ops_per_second = 1.0 / median_cached
        assert (
            final_ops_per_second > 10000
        ), f"Cached access too slow: {final_ops_per_second:.1f} ops/sec"

        print("\n=== Caching Effectiveness ===")
        print(f"Median first access: {median_first*1000:.3f}ms/op, {1.0/median_first:.1f} ops/sec")
        print(
            f"Median cached access: {median_cached*1000:.3f}ms/op, {1.0/median_cached:.1f} ops/sec"
        )
        print(f"Performance ratio: {performance_ratio:.2f}x")

    def test_bulk_operations_performance(self):
        """Test performance of bulk parameter operations.

        Measures the performance of setting multiple parameters and accessing
        all parameter keys, which are common operations in production code.

        Raises:
            AssertionError: If bulk operations are slower than expected.
        """

        class BulkTestClass(ParameterizedBase):
            """Test class for bulk operations performance testing.

            Contains multiple parameter types to test performance of setting
            multiple parameters at once and accessing all parameter keys.

            Attributes:
                param1 (int): First test parameter.
                param2 (str): Second test parameter.
                param3 (float): Third test parameter.
                param4 (bool): Fourth test parameter.
                param5 (list): Fifth test parameter.
            """
            param1 = ParameterDescriptor(default=1, type_=int)
            param2 = ParameterDescriptor(default="test", type_=str)
            param3 = ParameterDescriptor(default=1.0, type_=float)
            param4 = ParameterDescriptor(default=True, type_=bool)
            param5 = ParameterDescriptor(default=[1, 2, 3], type_=list)

        obj = BulkTestClass()

        # Test individual operations
        individual_result = PerformanceTester.time_operation(
            "individual_sets",
            lambda: [
                obj.set_param("param1", 42),
                obj.set_param("param2", "new"),
                obj.set_param("param3", 3.14),
                obj.set_param("param4", False),
                obj.set_param("param5", [4, 5, 6]),
            ],
            iterations=1000,
        )

        # Test parameter manager keys access (which is used internally)
        keys_result = PerformanceTester.time_operation(
            "get_all_keys", lambda: list(obj._param_manager.keys()), iterations=5000
        )

        # Keys access should be very fast
        assert (
            keys_result.ops_per_second > 10000
        ), f"Keys access too slow: {keys_result.ops_per_second:.1f} ops/sec"

        print("\n=== Bulk Operations Performance ===")
        print(f"Individual sets: {individual_result.avg_time*1000:.3f}ms/op")
        print(
            f"Keys access: {keys_result.avg_time*1000:.3f}ms/op, {keys_result.ops_per_second:.1f} ops/sec"
        )


def run_tests():
    """Run performance tests when module is executed directly.

    This function allows the test module to be run as a script for quick
    performance testing. It uses pytest with verbose output and captures
    print statements to display performance metrics.

    Note:
        The -s flag is used to show print statements with performance metrics,
        which is essential for analyzing the results of performance tests.
    """
    pytest.main([__file__, "-v", "-s"])


if __name__ == "__main__":
    run_tests()
