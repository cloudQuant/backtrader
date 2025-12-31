#!/usr/bin/env python
"""
Performance profiling script for backtrader tests
Analyzes function call counts and execution time across multiple strategies

Usage:
    python profile_performance.py [--processes N] [--strategies STRATEGY_LIST]

Options:
    --processes N       Number of parallel processes (default: 7)
    --strategies LIST   Comma-separated strategy numbers or 'all' (default: all)
    --verbose          Show detailed output for each strategy
"""

import argparse
import cProfile
import importlib
import io
import os
import pstats
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add the project root to the path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Strategy configuration: (module_path, test_function_name)
STRATEGY_CONFIGS = {
    # Original test strategies
    0: ("tests.original_tests.test_strategy_optimized", "test_run"),
    # Strategy tests from tests/strategies (21 strategies total including #0)
    1: ("tests.strategies.test_01_premium_rate_strategy", "test_strategy_final_value"),
    2: ("tests.strategies.test_02_multi_extend_data", "test_strategy"),
    3: ("tests.strategies.test_03_two_ma", "test_two_ma_strategy"),
    4: ("tests.strategies.test_04_simple_ma_multi_data", "test_simple_ma_multi_data_strategy"),
    5: ("tests.strategies.test_05_stop_order_strategy", "test_stop_order_strategy"),
    6: ("tests.strategies.test_06_macd_ema_fase_strategy", "test_macd_ema_strategy"),
    7: ("tests.strategies.test_07_macd_ema_true_strategy", "test_macd_ema_true_strategy"),
    8: ("tests.strategies.test_08_kelter_strategy", "test_keltner_strategy"),
    9: ("tests.strategies.test_09_dual_thrust_strategy", "test_dual_thrust_strategy"),
    10: ("tests.strategies.test_10_r_breaker_strategy", "test_r_breaker_strategy"),
    11: ("tests.strategies.test_11_sky_garden_strategy", "test_sky_garden_strategy"),
    12: ("tests.strategies.test_12_abberation_strategy", "test_abberation_strategy"),
    13: ("tests.strategies.test_13_fei_strategy", "test_fei_strategy"),
    14: ("tests.strategies.test_14_hanse123_strategy", "test_hans123_strategy"),
    15: ("tests.strategies.test_15_fenshi_ma_strategy", "test_timeline_ma_strategy"),
    16: ("tests.strategies.test_16_cb_strategy", "test_cb_intraday_strategy"),
    17: ("tests.strategies.test_17_cb_monday_strategy", "test_cb_friday_rotation_strategy"),
    18: ("tests.strategies.test_18_etf_rotation_strategy", "test_etf_rotation_strategy"),
    19: ("tests.strategies.test_19_index_future_momentum", "test_treasury_futures_macd_strategy"),
    20: ("tests.strategies.test_20_arbitrage_strategy", "test_treasury_futures_spread_arbitrage_strategy"),
}


def get_git_branch() -> str:
    """Get current git branch name"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True, cwd=PROJECT_ROOT
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def get_git_commit() -> str:
    """Get current git commit hash"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=PROJECT_ROOT
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def profile_single_strategy(strategy_id: int) -> Tuple[int, Optional[Dict], float, str]:
    """
    Profile a single strategy execution
    
    Args:
        strategy_id: Strategy ID from STRATEGY_CONFIGS
        
    Returns:
        Tuple of (strategy_id, stats_dict, execution_time, status_message)
    """
    if strategy_id not in STRATEGY_CONFIGS:
        return strategy_id, None, 0.0, f"Strategy {strategy_id} not found"
    
    module_path, func_name = STRATEGY_CONFIGS[strategy_id]
    
    # Ensure project root is in path (critical for multiprocessing)
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Change working directory to project root
    os.chdir(project_root)
    
    profiler = cProfile.Profile()
    start_time = time.time()
    
    try:
        # Convert module path to file path and load directly
        file_path = os.path.join(project_root, module_path.replace('.', os.sep) + '.py')
        
        # Load module from file path
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_path, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_path] = module
        spec.loader.exec_module(module)
        
        test_func = getattr(module, func_name)
        
        # Run with profiling
        profiler.enable()
        try:
            # Try to call with main=False first (for original tests)
            test_func(main=False)
        except TypeError:
            # If that fails, call without arguments
            test_func()
        profiler.disable()
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Convert stats to serializable format
        stats = pstats.Stats(profiler)
        stats_dict = {}
        for key, value in stats.stats.items():
            # key is (filename, lineno, funcname)
            # value is (ncalls, totcalls, tottime, cumtime, callers)
            stats_dict[key] = {
                'ncalls': value[0],
                'totcalls': value[1],
                'tottime': value[2],
                'cumtime': value[3],
            }
        
        return strategy_id, stats_dict, execution_time, "SUCCESS"
        
    except Exception as e:
        profiler.disable()
        end_time = time.time()
        return strategy_id, None, end_time - start_time, f"ERROR: {str(e)}"


def aggregate_stats(results: List[Tuple[int, Optional[Dict], float, str]]) -> Dict:
    """
    Aggregate profiling statistics from multiple strategy runs
    
    Args:
        results: List of (strategy_id, stats_dict, time, status) tuples
        
    Returns:
        Aggregated statistics dictionary
    """
    aggregated = defaultdict(lambda: {
        'ncalls': 0,
        'totcalls': 0,
        'tottime': 0.0,
        'cumtime': 0.0,
        'strategies': []
    })
    
    successful_strategies = []
    failed_strategies = []
    total_time = 0.0
    
    for strategy_id, stats_dict, exec_time, status in results:
        total_time += exec_time
        
        if stats_dict is None:
            failed_strategies.append((strategy_id, status))
            continue
            
        successful_strategies.append((strategy_id, exec_time))
        
        for key, value in stats_dict.items():
            aggregated[key]['ncalls'] += value['ncalls']
            aggregated[key]['totcalls'] += value['totcalls']
            aggregated[key]['tottime'] += value['tottime']
            aggregated[key]['cumtime'] += value['cumtime']
            aggregated[key]['strategies'].append(strategy_id)
    
    return {
        'stats': dict(aggregated),
        'successful': successful_strategies,
        'failed': failed_strategies,
        'total_time': total_time,
    }


def generate_aggregated_report(
    aggregated: Dict,
    output_file: str = "performance_profile.log",
    verbose: bool = False
):
    """
    Generate detailed performance report from aggregated statistics
    
    Args:
        aggregated: Aggregated statistics dictionary
        output_file: Output log file path
        verbose: Whether to include verbose output
    """
    branch = get_git_branch()
    commit = get_git_commit()
    
    stats = aggregated['stats']
    successful = aggregated['successful']
    failed = aggregated['failed']
    total_time = aggregated['total_time']
    
    with open(output_file, "w", encoding="utf-8") as f:
        # Header
        f.write("=" * 120 + "\n")
        f.write("BACKTRADER MULTI-STRATEGY PERFORMANCE PROFILING REPORT\n")
        f.write("=" * 120 + "\n\n")
        
        f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Git Branch: {branch}\n")
        f.write(f"Git Commit: {commit}\n")
        f.write(f"Total Strategies Tested: {len(successful) + len(failed)}\n")
        f.write(f"Successful: {len(successful)}, Failed: {len(failed)}\n")
        f.write(f"Total Execution Time: {total_time:.4f} seconds\n")
        f.write("\n" + "=" * 120 + "\n\n")
        
        # Strategy execution summary
        f.write("STRATEGY EXECUTION SUMMARY\n")
        f.write("-" * 120 + "\n\n")
        
        f.write("Successful Strategies:\n")
        for sid, exec_time in sorted(successful, key=lambda x: x[0]):
            module_path = STRATEGY_CONFIGS[sid][0]
            f.write(f"  [{sid:2d}] {module_path:<60} - {exec_time:.4f}s\n")
        
        if failed:
            f.write("\nFailed Strategies:\n")
            for sid, status in sorted(failed, key=lambda x: x[0]):
                module_path = STRATEGY_CONFIGS.get(sid, ("unknown", "unknown"))[0]
                f.write(f"  [{sid:2d}] {module_path:<60} - {status}\n")
        
        f.write("\n" + "=" * 120 + "\n\n")
        
        # Convert stats to sortable format
        def get_sorted_stats(sort_key: str, limit: int = 50, filter_str: str = None):
            items = []
            for key, value in stats.items():
                filename, lineno, funcname = key
                if filter_str and filter_str.lower() not in filename.lower():
                    continue
                items.append({
                    'key': key,
                    'filename': filename,
                    'lineno': lineno,
                    'funcname': funcname,
                    **value
                })
            
            if sort_key == 'ncalls':
                items.sort(key=lambda x: x['ncalls'], reverse=True)
            elif sort_key == 'tottime':
                items.sort(key=lambda x: x['tottime'], reverse=True)
            elif sort_key == 'cumtime':
                items.sort(key=lambda x: x['cumtime'], reverse=True)
            
            return items[:limit]
        
        def write_stats_table(items: List[Dict], title: str):
            f.write(f"{title}\n")
            f.write("-" * 120 + "\n")
            f.write(f"{'ncalls':>12} {'tottime':>12} {'per call':>12} {'cumtime':>12} {'per call':>12}  function\n")
            f.write("-" * 120 + "\n")
            
            for item in items:
                ncalls = item['ncalls']
                tottime = item['tottime']
                cumtime = item['cumtime']
                percall_tot = tottime / ncalls if ncalls > 0 else 0
                percall_cum = cumtime / ncalls if ncalls > 0 else 0
                
                func_info = f"{item['filename']}:{item['lineno']}({item['funcname']})"
                if len(func_info) > 70:
                    func_info = "..." + func_info[-67:]
                
                f.write(f"{ncalls:>12,} {tottime:>12.6f} {percall_tot:>12.6f} "
                       f"{cumtime:>12.6f} {percall_cum:>12.6f}  {func_info}\n")
            f.write("\n\n")
        
        # Section 1: Top functions by cumulative time
        items = get_sorted_stats('cumtime', 50)
        write_stats_table(items, "SECTION 1: TOP 50 FUNCTIONS BY CUMULATIVE TIME (aggregated across all strategies)")
        
        # Section 2: Top functions by total time
        items = get_sorted_stats('tottime', 50)
        write_stats_table(items, "SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME (excluding sub-calls)")
        
        # Section 3: Top functions by call count
        items = get_sorted_stats('ncalls', 50)
        write_stats_table(items, "SECTION 3: TOP 50 FUNCTIONS BY CALL COUNT")
        
        # Section 4: Backtrader-specific functions
        items = get_sorted_stats('cumtime', 100, 'backtrader')
        write_stats_table(items, "SECTION 4: BACKTRADER-SPECIFIC FUNCTIONS (sorted by cumulative time)")
        
        # Section 5: Strategy functions
        items = get_sorted_stats('cumtime', 100, 'strategy')
        write_stats_table(items, "SECTION 5: STRATEGY-RELATED FUNCTIONS (sorted by cumulative time)")
        
        # Section 6: Indicator functions
        items = get_sorted_stats('cumtime', 100, 'indicator')
        write_stats_table(items, "SECTION 6: INDICATOR-RELATED FUNCTIONS (sorted by cumulative time)")
        
        # Section 7: Line buffer operations
        items = get_sorted_stats('cumtime', 100, 'line')
        write_stats_table(items, "SECTION 7: LINE BUFFER OPERATIONS (sorted by cumulative time)")
        
        # Section 8: Summary statistics
        f.write("SECTION 8: SUMMARY STATISTICS\n")
        f.write("-" * 120 + "\n\n")
        
        total_calls = sum(s['ncalls'] for s in stats.values())
        total_primitive_calls = sum(s['totcalls'] for s in stats.values())
        total_functions = len(stats)
        
        f.write(f"Total function calls (aggregated): {total_calls:,}\n")
        f.write(f"Total primitive calls (aggregated): {total_primitive_calls:,}\n")
        f.write(f"Total unique functions: {total_functions:,}\n")
        f.write(f"Total execution time: {total_time:.4f} seconds\n")
        if total_calls > 0:
            f.write(f"Average time per call: {(total_time / total_calls * 1000000):.2f} microseconds\n")
        f.write(f"Strategies tested: {len(successful)}\n")
        if successful:
            avg_time = sum(t for _, t in successful) / len(successful)
            f.write(f"Average time per strategy: {avg_time:.4f} seconds\n")
        
        f.write("\n" + "=" * 120 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 120 + "\n")
    
    print(f"\nReport saved to: {output_file}")


def run_parallel_profiling(
    strategy_ids: List[int],
    num_processes: int = 7,
    verbose: bool = False
) -> Dict:
    """
    Run profiling across multiple strategies in parallel
    
    Args:
        strategy_ids: List of strategy IDs to profile
        num_processes: Number of parallel processes
        verbose: Whether to show verbose output
        
    Returns:
        Aggregated statistics dictionary
    """
    print(f"\nRunning profiling with {num_processes} processes for {len(strategy_ids)} strategies...")
    print("-" * 60)
    
    results = []
    
    with ProcessPoolExecutor(max_workers=num_processes) as executor:
        # Submit all tasks
        future_to_id = {
            executor.submit(profile_single_strategy, sid): sid 
            for sid in strategy_ids
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_id):
            strategy_id = future_to_id[future]
            try:
                result = future.result(timeout=300)  # 5 minute timeout per strategy
                results.append(result)
                
                sid, stats_dict, exec_time, status = result
                module_path = STRATEGY_CONFIGS.get(sid, ("unknown", "unknown"))[0]
                status_icon = "✓" if stats_dict is not None else "✗"
                print(f"  [{sid:2d}] {status_icon} {module_path.split('.')[-1]:<45} - {exec_time:.2f}s - {status}")
                
            except Exception as e:
                results.append((strategy_id, None, 0.0, f"EXCEPTION: {str(e)}"))
                print(f"  [{strategy_id:2d}] ✗ Exception: {str(e)}")
    
    print("-" * 60)
    
    return aggregate_stats(results)


def parse_strategy_list(strategy_arg: str) -> List[int]:
    """Parse strategy list argument"""
    if strategy_arg.lower() == 'all':
        return list(STRATEGY_CONFIGS.keys())
    
    strategy_ids = []
    for part in strategy_arg.split(','):
        part = part.strip()
        if '-' in part:
            # Range like "1-10"
            start, end = part.split('-')
            strategy_ids.extend(range(int(start), int(end) + 1))
        else:
            strategy_ids.append(int(part))
    
    # Filter to only valid IDs
    return [sid for sid in strategy_ids if sid in STRATEGY_CONFIGS]


def main():
    """Main execution function"""
    parser = argparse.ArgumentParser(
        description="Profile backtrader strategies for performance analysis"
    )
    parser.add_argument(
        '--processes', '-p',
        type=int,
        default=7,
        help='Number of parallel processes (default: 7)'
    )
    parser.add_argument(
        '--strategies', '-s',
        type=str,
        default='all',
        help='Strategy IDs to test: "all", "1,2,3", or "1-10" (default: all)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show verbose output'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file path (default: auto-generated)'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("BACKTRADER MULTI-STRATEGY PERFORMANCE PROFILER")
    print("=" * 60)
    
    # Parse strategy list
    strategy_ids = parse_strategy_list(args.strategies)
    print(f"\nStrategies to profile: {len(strategy_ids)}")
    print(f"Parallel processes: {args.processes}")
    
    if not strategy_ids:
        print("Error: No valid strategies specified")
        return 1
    
    try:
        # Run parallel profiling
        start_time = time.time()
        aggregated = run_parallel_profiling(
            strategy_ids,
            num_processes=args.processes,
            verbose=args.verbose
        )
        total_time = time.time() - start_time
        
        # Generate output filename
        if args.output:
            output_file = args.output
        else:
            branch = get_git_branch()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"performance_profile_{branch}_{timestamp}.log"
        
        # Generate report
        generate_aggregated_report(aggregated, output_file, args.verbose)
        
        # Print summary to console
        print("\n" + "=" * 60)
        print("PROFILING SUMMARY")
        print("=" * 60)
        print(f"Total strategies: {len(aggregated['successful']) + len(aggregated['failed'])}")
        print(f"Successful: {len(aggregated['successful'])}")
        print(f"Failed: {len(aggregated['failed'])}")
        print(f"Total profiling time: {total_time:.2f} seconds")
        print(f"Aggregate execution time: {aggregated['total_time']:.2f} seconds")
        
        if aggregated['failed']:
            print("\nFailed strategies:")
            for sid, status in aggregated['failed']:
                print(f"  [{sid}] {status}")
        
        # Print top 20 functions by cumulative time
        print("\n" + "=" * 60)
        print("TOP 20 FUNCTIONS BY CUMULATIVE TIME:")
        print("=" * 60)
        
        stats = aggregated['stats']
        items = []
        for key, value in stats.items():
            items.append({
                'key': key,
                'cumtime': value['cumtime'],
                'ncalls': value['ncalls'],
            })
        items.sort(key=lambda x: x['cumtime'], reverse=True)
        
        print(f"{'ncalls':>12} {'cumtime':>12}  function")
        print("-" * 60)
        for item in items[:20]:
            filename, lineno, funcname = item['key']
            func_info = f"{os.path.basename(filename)}:{lineno}({funcname})"
            if len(func_info) > 45:
                func_info = func_info[:42] + "..."
            print(f"{item['ncalls']:>12,} {item['cumtime']:>12.4f}  {func_info}")
        
    except Exception as e:
        print(f"\nError during profiling: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
