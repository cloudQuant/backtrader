#!/usr/bin/env python3
"""
性能日志对比分析工具
用于分析 Master 版本和 Remove-Metaprogramming 版本的性能差异
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class FunctionStats:
    """函数统计信息"""

    ncalls: int
    tottime: float
    percall_tot: float
    cumtime: float
    percall_cum: float
    filename: str
    lineno: str
    funcname: str

    @property
    def full_name(self):
        return f"{self.filename}:{self.lineno}({self.funcname})"


@dataclass
class ProfileReport:
    """性能分析报告"""

    branch: str
    commit: str
    total_time: float
    total_calls: int
    primitive_calls: int
    total_functions: int
    functions: Dict[str, FunctionStats]


def parse_log_file(log_path: str) -> ProfileReport:
    """解析性能日志文件"""
    with open(log_path, encoding="utf-8") as f:
        content = f.read()

    # 提取基本信息
    branch_match = re.search(r"Git Branch: (.+)", content)
    commit_match = re.search(r"Git Commit: (.+)", content)
    time_match = re.search(r"Total Execution Time: ([\d.]+) seconds", content)

    branch = branch_match.group(1) if branch_match else "Unknown"
    commit = commit_match.group(1) if commit_match else "Unknown"
    total_time = float(time_match.group(1)) if time_match else 0.0

    # 提取调用统计
    calls_match = re.search(
        r"(\d+) function calls \((\d+) primitive calls\) in ([\d.]+) seconds", content
    )
    if calls_match:
        total_calls = int(calls_match.group(1))
        primitive_calls = int(calls_match.group(2))
    else:
        total_calls = primitive_calls = 0

    # 提取函数数量
    reduced_match = re.search(r"List reduced from (\d+)", content)
    total_functions = int(reduced_match.group(1)) if reduced_match else 0

    # 解析函数统计信息（从 SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME）
    functions = {}

    # 查找 SECTION 2
    section2_start = content.find("SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME")
    if section2_start != -1:
        section2_content = content[section2_start : section2_start + 20000]

        # 匹配函数行
        # 格式: ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        pattern = (
            r"(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?):(\d+)\((.+?)\)"
        )

        for match in re.finditer(pattern, section2_content):
            ncalls_str = match.group(1)
            # 处理 ncalls 可能包含递归调用的情况 (e.g., "1865/1660")
            if "/" in ncalls_str:
                ncalls = int(ncalls_str.split("/")[0])
            else:
                ncalls = int(ncalls_str)

            func_stat = FunctionStats(
                ncalls=ncalls,
                tottime=float(match.group(2)),
                percall_tot=float(match.group(3)),
                cumtime=float(match.group(4)),
                percall_cum=float(match.group(5)),
                filename=match.group(6),
                lineno=match.group(7),
                funcname=match.group(8),
            )

            functions[func_stat.full_name] = func_stat

    return ProfileReport(
        branch=branch,
        commit=commit,
        total_time=total_time,
        total_calls=total_calls,
        primitive_calls=primitive_calls,
        total_functions=total_functions,
        functions=functions,
    )


def compare_reports(master: ProfileReport, remove: ProfileReport) -> None:
    """对比两个性能报告"""

    print("=" * 100)
    print("BACKTRADER 性能对比分析")
    print("=" * 100)
    print()

    # 1. 基本信息对比
    print("【1】基本信息对比")
    print("-" * 100)
    print(f"{'指标':<30} {'Master版本':<20} {'Remove版本':<20} {'变化':<30}")
    print("-" * 100)

    time_diff = remove.total_time - master.total_time
    time_pct = (time_diff / master.total_time) * 100
    print(
        f"{'总执行时间':<30} {master.total_time:<20.4f} {remove.total_time:<20.4f} {f'+{time_pct:.1f}%  (+{time_diff:.2f}秒)':<30}"
    )

    calls_diff = remove.total_calls - master.total_calls
    calls_pct = (calls_diff / master.total_calls) * 100
    print(
        f"{'函数调用总数':<30} {master.total_calls:<20,} {remove.total_calls:<20,} {f'+{calls_pct:.1f}%  (+{calls_diff:,})':<30}"
    )

    funcs_diff = remove.total_functions - master.total_functions
    funcs_pct = (funcs_diff / master.total_functions) * 100
    print(
        f"{'函数种类数':<30} {master.total_functions:<20,} {remove.total_functions:<20,} {f'+{funcs_pct:.1f}%  (+{funcs_diff})':<30}"
    )

    print()
    print()

    # 2. 新增的性能瓶颈（只在remove版本中出现的高耗时函数）
    print("【2】新增的性能瓶颈（只在 Remove 版本中出现且耗时 >0.05秒）")
    print("-" * 100)

    new_bottlenecks = []
    for func_name, func_stat in remove.functions.items():
        if func_name not in master.functions and func_stat.tottime > 0.05:
            new_bottlenecks.append((func_name, func_stat))

    new_bottlenecks.sort(key=lambda x: x[1].tottime, reverse=True)

    if new_bottlenecks:
        print(f"{'函数名':<80} {'调用次数':<15} {'总耗时(秒)':<15}")
        print("-" * 100)
        for func_name, func_stat in new_bottlenecks[:20]:
            print(f"{func_name:<80} {func_stat.ncalls:<15,} {func_stat.tottime:<15.4f}")
    else:
        print("未发现新增的显著性能瓶颈")

    print()
    print()

    # 3. 性能退化最严重的函数（两个版本都有，但remove版本耗时显著增加）
    print("【3】性能退化最严重的函数（总耗时增加 >0.01秒）")
    print("-" * 100)

    degraded_funcs = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            time_diff = remove_stat.tottime - master_stat.tottime
            if time_diff > 0.01:
                degraded_funcs.append(
                    (
                        func_name,
                        master_stat,
                        remove_stat,
                        time_diff,
                        (time_diff / master_stat.tottime * 100) if master_stat.tottime > 0 else 999,
                    )
                )

    degraded_funcs.sort(key=lambda x: x[3], reverse=True)

    if degraded_funcs:
        print(
            f"{'函数名':<70} {'Master(秒)':<12} {'Remove(秒)':<12} {'增加(秒)':<12} {'增幅(%)':<12}"
        )
        print("-" * 100)
        for func_name, master_stat, remove_stat, diff, pct in degraded_funcs[:20]:
            # 截断函数名以适应显示
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            print(
                f"{short_name:<70} {master_stat.tottime:<12.4f} {remove_stat.tottime:<12.4f} {diff:<12.4f} {pct:<12.1f}"
            )
    else:
        print("未发现显著的性能退化")

    print()
    print()

    # 4. 调用次数暴增的函数
    print("【4】调用次数暴增的函数（增加 >10倍）")
    print("-" * 100)

    call_explosion = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            if master_stat.ncalls > 0:
                call_ratio = remove_stat.ncalls / master_stat.ncalls
                if call_ratio > 10:
                    call_explosion.append((func_name, master_stat, remove_stat, call_ratio))

    call_explosion.sort(key=lambda x: x[3], reverse=True)

    if call_explosion:
        print(f"{'函数名':<70} {'Master调用':<15} {'Remove调用':<15} {'倍数':<12}")
        print("-" * 100)
        for func_name, master_stat, remove_stat, ratio in call_explosion[:20]:
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            print(
                f"{short_name:<70} {master_stat.ncalls:<15,} {remove_stat.ncalls:<15,} {ratio:<12.1f}x"
            )
    else:
        print("未发现调用次数暴增的函数")

    print()
    print()

    # 5. 单次调用耗时增加最多的函数
    print("【5】单次调用耗时增加最多的函数（percall 增加 >10倍）")
    print("-" * 100)

    percall_increase = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            if master_stat.percall_tot > 0.000001:  # 避免除以接近0的数
                ratio = remove_stat.percall_tot / master_stat.percall_tot
                if ratio > 10:
                    percall_increase.append((func_name, master_stat, remove_stat, ratio))

    percall_increase.sort(key=lambda x: x[3], reverse=True)

    if percall_increase:
        print(f"{'函数名':<70} {'Master单次(ms)':<15} {'Remove单次(ms)':<15} {'倍数':<12}")
        print("-" * 100)
        for func_name, master_stat, remove_stat, ratio in percall_increase[:20]:
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            master_ms = master_stat.percall_tot * 1000
            remove_ms = remove_stat.percall_tot * 1000
            print(f"{short_name:<70} {master_ms:<15.6f} {remove_ms:<15.6f} {ratio:<12.1f}x")
    else:
        print("未发现单次调用耗时显著增加的函数")

    print()
    print()

    # 6. Top 10 耗时函数对比
    print("【6】Top 10 耗时函数对比")
    print("-" * 100)

    master_top10 = sorted(master.functions.items(), key=lambda x: x[1].tottime, reverse=True)[:10]
    remove_top10 = sorted(remove.functions.items(), key=lambda x: x[1].tottime, reverse=True)[:10]

    print("\nMaster 版本 Top 10:")
    print(f"{'排名':<5} {'函数名':<70} {'耗时(秒)':<12} {'调用次数':<15}")
    print("-" * 100)
    for i, (func_name, func_stat) in enumerate(master_top10, 1):
        short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
        print(f"{i:<5} {short_name:<70} {func_stat.tottime:<12.4f} {func_stat.ncalls:<15,}")

    print()
    print("Remove 版本 Top 10:")
    print(f"{'排名':<5} {'函数名':<70} {'耗时(秒)':<12} {'调用次数':<15}")
    print("-" * 100)
    for i, (func_name, func_stat) in enumerate(remove_top10, 1):
        short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
        print(f"{i:<5} {short_name:<70} {func_stat.tottime:<12.4f} {func_stat.ncalls:<15,}")

    print()
    print()

    # 7. 关键指标汇总
    print("【7】关键发现总结")
    print("-" * 100)

    # 计算 backtrader 相关函数的耗时
    master_bt_time = sum(
        stat.tottime for name, stat in master.functions.items() if "backtrader" in name
    )
    remove_bt_time = sum(
        stat.tottime for name, stat in remove.functions.items() if "backtrader" in name
    )

    print(f"1. 总执行时间增加: {time_pct:.1f}% ({time_diff:.2f}秒)")
    print(f"2. 函数调用次数增加: {calls_pct:.1f}%")
    print(f"3. 新增性能瓶颈函数: {len(new_bottlenecks)} 个")
    print(f"4. 性能显著退化函数: {len(degraded_funcs)} 个")
    print(f"5. 调用次数暴增函数(>10倍): {len(call_explosion)} 个")
    print(f"6. 单次耗时暴增函数(>10倍): {len(percall_increase)} 个")
    print(
        f"7. Backtrader相关函数总耗时: Master={master_bt_time:.2f}秒, Remove={remove_bt_time:.2f}秒 (增加{remove_bt_time-master_bt_time:.2f}秒)"
    )

    print()
    print("=" * 100)


def main():
    """主函数"""
    import sys

    if len(sys.argv) != 3:
        print("用法: python analyze_performance_diff.py <master_log_path> <remove_log_path>")
        print()
        print("示例:")
        print("  python analyze_performance_diff.py \\")
        print("    performance_profile_master_20251026_181304.log \\")
        print("    performance_profile_remove-metaprogramming_20251026_215555.log")
        sys.exit(1)

    master_log = sys.argv[1]
    remove_log = sys.argv[2]

    print(f"正在解析 Master 版本日志: {master_log}")
    master_report = parse_log_file(master_log)
    print(f"  - 分支: {master_report.branch}")
    print(f"  - 提交: {master_report.commit}")
    print(f"  - 总耗时: {master_report.total_time}秒")
    print(f"  - 解析到 {len(master_report.functions)} 个函数")
    print()

    print(f"正在解析 Remove 版本日志: {remove_log}")
    remove_report = parse_log_file(remove_log)
    print(f"  - 分支: {remove_report.branch}")
    print(f"  - 提交: {remove_report.commit}")
    print(f"  - 总耗时: {remove_report.total_time}秒")
    print(f"  - 解析到 {len(remove_report.functions)} 个函数")
    print()
    print()

    # 进行对比分析
    compare_reports(master_report, remove_report)


if __name__ == "__main__":
    main()
