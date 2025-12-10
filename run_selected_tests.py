#!/usr/bin/env python
"""
Backtrader Selected Tests Runner
=================================
运行指定测试目录并生成 HTML 报告

测试目录:
- tests/add_tests
- tests/original_tests
- tests/base_functions

配置:
- 12 核并行执行
- 生成 backtrader_remove_metaprogramming_report.html
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def check_test_directories():
    """检查测试目录是否存在"""
    test_dirs = ["tests/add_tests", "tests/original_tests", "tests/base_functions"]

    missing_dirs = []
    found_dirs = []

    for test_dir in test_dirs:
        if Path(test_dir).exists():
            test_files = list(Path(test_dir).glob("test_*.py"))
            found_dirs.append({"path": test_dir, "count": len(test_files)})
        else:
            missing_dirs.append(test_dir)

    return found_dirs, missing_dirs


def run_tests():
    """运行测试并生成报告"""

    print("=" * 80)
    print("Backtrader Selected Tests Runner")
    print("=" * 80)
    print()

    # 记录脚本开始时间
    script_start_time = time.time()
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 检查测试目录
    print("检查测试目录...")
    found_dirs, missing_dirs = check_test_directories()

    if missing_dirs:
        print()
        print("⚠️  警告：以下目录不存在：")
        for missing in missing_dirs:
            print(f"   - {missing}")
        print()

    if not found_dirs:
        print("❌ 错误：没有找到任何测试目录！")
        return 1

    print()
    print("找到以下测试目录：")
    total_files = 0
    for dir_info in found_dirs:
        print(f"   ✓ {dir_info['path']}: {dir_info['count']} 个测试文件")
        total_files += dir_info["count"]
    print(f"\n总计：{total_files} 个测试文件")
    print()

    # 准备测试路径
    test_paths = [d["path"] for d in found_dirs]

    # 准备 pytest 命令
    output_file = "backtrader_remove_metaprogramming_report.html"

    pytest_args = [sys.executable, "-m", "pytest"]

    # 添加测试路径
    pytest_args.extend(test_paths)

    # 添加报告参数
    pytest_args.extend(
        [
            f"--html={output_file}",
            "--self-contained-html",
            "--tb=short",
            "--verbose",
            "--color=yes",
            "-ra",  # 显示所有测试结果摘要
            "--maxfail=1000",  # 不在首个失败时停止
        ]
    )

    # 添加并行执行参数
    try:
        import xdist

        pytest_args.extend(["-n", "12"])  # 使用 12 核
        print("✓ 使用 12 核并行执行（pytest-xdist 已安装）")
    except ImportError:
        print("⚠️  pytest-xdist 未安装，将使用串行执行")
        print("   安装方法：pip install pytest-xdist")

    print()
    print("-" * 80)
    print("开始执行测试...")
    print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    # 记录pytest开始时间（墙钟时间）
    pytest_start_time = time.time()

    # 运行 pytest
    result = subprocess.run(pytest_args)

    # 记录pytest结束时间
    pytest_end_time = time.time()
    pytest_duration = pytest_end_time - pytest_start_time

    # 计算总时间（包括准备工作）
    total_duration = pytest_end_time - script_start_time

    print()
    print("-" * 80)
    print()
    print("=" * 80)
    print("测试执行完成")
    print("=" * 80)
    print()
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"⏱️  测试执行时间（墙钟时间）: {pytest_duration:.2f} 秒 ({pytest_duration/60:.2f} 分钟)")
    print(f"📊 总耗时（含准备）: {total_duration:.2f} 秒 ({total_duration/60:.2f} 分钟)")
    print(f"📄 HTML 报告: {output_file}")
    print()

    # 将时间信息写入单独的文件以便后续分析
    timing_info = {
        "script_start": datetime.fromtimestamp(script_start_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_start": datetime.fromtimestamp(pytest_start_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_end": datetime.fromtimestamp(pytest_end_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_duration_seconds": pytest_duration,
        "total_duration_seconds": total_duration,
        "report_file": output_file,
        "test_directories": test_paths,
        "parallel_workers": 12,
        "timestamp": datetime.now().isoformat(),
    }

    timing_file = output_file.replace(".html", "_timing.json")
    import json

    with open(timing_file, "w", encoding="utf-8") as f:
        json.dump(timing_info, f, indent=2, ensure_ascii=False)

    print(f"⏰ 时间信息已保存: {timing_file}")
    print()

    if result.returncode == 0:
        print("✓ 所有测试通过！")
        print()
        print(f"查看报告：")
        print(f"  双击打开: {output_file}")
        print(f"  或在浏览器中打开: file:///{Path(output_file).absolute()}")
    else:
        print(f"✗ 部分测试失败（退出码: {result.returncode}）")
        print()
        print(f"请查看 {output_file} 了解详细信息")

    print()
    print("=" * 80)

    return result.returncode


def show_info():
    """显示测试信息"""

    print()
    print("=" * 80)
    print("测试配置信息")
    print("=" * 80)
    print()
    print("测试目录:")
    print("  - tests/add_tests       (新增功能测试)")
    print("  - tests/original_tests  (原始核心测试)")
    print("  - tests/base_functions  (基础功能测试)")
    print()
    print("并行配置:")
    print("  - 12 核并行执行")
    print()
    print("报告输出:")
    print("  - backtrader_remove_metaprogramming_report.html")
    print()
    print("Python 版本:")
    print(f"  - {sys.version.split()[0]}")
    print()

    # 检查目录
    found_dirs, missing_dirs = check_test_directories()

    if found_dirs:
        print("测试统计:")
        for dir_info in found_dirs:
            print(f"  - {dir_info['path']}: {dir_info['count']} 个测试文件")

    print()
    print("=" * 80)
    print()


def main():
    """主入口"""

    # 检查命令行参数
    if "--info" in sys.argv or "-i" in sys.argv:
        show_info()
        return 0

    # 运行测试
    return run_tests()


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print()
        print("测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
