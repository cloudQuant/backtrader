#!/usr/bin/env python
"""
运行测试文件并将输出同时显示在终端和保存到日志文件中
日志文件名包含当前git分支名称

用法:
    python run_test_with_log.py <test_script> [--both]
    
参数:
    test_script: 要测试的脚本路径
    --both: 在master和remove-metaprogramming两个分支上都运行测试，并对比结果
            如果不指定，则只在当前分支运行测试
            
示例:
    # 只在当前分支运行
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py
    
    # 在两个分支上运行并对比
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both
"""

import argparse
import difflib
import glob
import os
import subprocess
import sys
from datetime import datetime


def get_git_branch():
    """获取当前git分支名称"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, check=True
        )
        branch = result.stdout.strip()
        if not branch:
            # 如果没有分支名，尝试获取HEAD的描述
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            branch = result.stdout.strip()
        return branch if branch else "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def switch_branch(branch_name):
    """切换到指定的git分支"""
    print(f"\n{'='*60}")
    print(f"切换到分支: {branch_name}")
    print(f"{'='*60}\n")
    
    try:
        result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"成功切换到分支: {branch_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"切换分支失败: {e.stderr}")
        return False


def pip_install():
    """执行 pip install -U . 安装当前分支的代码"""
    print(f"\n{'='*60}")
    print("执行 pip install -U . 安装当前代码...")
    print(f"{'='*60}\n")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "."],
            capture_output=True,
            text=True,
            check=True
        )
        print("pip install 成功")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"pip install 失败: {e.stderr}")
        return False


def cleanup_old_logs(script_path, branch_name, log_dir="logs"):
    """
    清理当前分支的旧日志文件

    Args:
        script_path: 脚本路径，用于生成日志文件名模式
        branch_name: git分支名称
        log_dir: 日志目录
    """
    if not os.path.exists(log_dir):
        return

    script_name = os.path.splitext(os.path.basename(script_path))[0]
    # 匹配模式：{script_name}_{branch_name}_*.log
    pattern = os.path.join(log_dir, f"{script_name}_{branch_name}_*.log")

    # 查找所有匹配的旧日志文件
    old_logs = glob.glob(pattern)

    if old_logs:
        print(f"清理 {len(old_logs)} 个旧日志文件...")
        for log_file in old_logs:
            try:
                os.remove(log_file)
                print(f"  已删除: {os.path.basename(log_file)}")
            except Exception as e:
                print(f"  删除失败 {os.path.basename(log_file)}: {e}")
        print()


def run_with_logging(script_path, log_dir="logs", branch_name=None):
    """
    运行指定的脚本，并将输出同时显示在终端和保存到日志文件

    Args:
        script_path: 要运行的脚本路径
        log_dir: 日志文件保存目录
        branch_name: 指定分支名称（如果为None则自动获取）
        
    Returns:
        tuple: (return_code, log_path)
    """
    # 创建日志目录
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 获取git分支名称
    if branch_name is None:
        branch_name = get_git_branch()

    # 清理当前分支的旧日志文件
    cleanup_old_logs(script_path, branch_name, log_dir)

    # 生成日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f"{script_name}_{branch_name}_{timestamp}.log"
    log_path = os.path.join(log_dir, log_filename)

    print(f"{'='*60}")
    print(f"运行脚本: {script_path}")
    print(f"Git分支: {branch_name}")
    print(f"日志文件: {log_path}")
    print(f"{'='*60}\n")

    # 打开日志文件
    with open(log_path, "w", encoding="utf-8") as log_file:
        # 写入文件头信息
        log_file.write(f"{'='*60}\n")
        log_file.write(f"运行脚本: {script_path}\n")
        log_file.write(f"Git分支: {branch_name}\n")
        log_file.write(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*60}\n\n")
        log_file.flush()

        # 运行脚本
        try:
            # 使用Popen以便实时获取输出
            # Windows下使用utf-8编码，避免gbk编码问题
            import locale

            system_encoding = locale.getpreferredencoding()

            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",  # 遇到无法解码的字符时替换为?
                bufsize=1,  # 行缓冲
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # 强制Python使用UTF-8
            )

            # 实时读取输出并同时写入终端和日志文件
            for line in process.stdout:
                # 输出到终端
                print(line, end="")
                # 写入日志文件
                log_file.write(line)
                log_file.flush()

            # 等待进程结束
            return_code = process.wait()

            # 写入结束信息
            end_msg = f"\n{'='*60}\n"
            end_msg += f"脚本执行完成\n"
            end_msg += f"退出代码: {return_code}\n"
            end_msg += f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            end_msg += f"{'='*60}\n"

            print(end_msg)
            log_file.write(end_msg)

            return return_code, log_path

        except Exception as e:
            error_msg = f"\n执行出错: {str(e)}\n"
            print(error_msg)
            log_file.write(error_msg)
            return 1, log_path


def compare_logs(log1_path, log2_path, output_path=None):
    """
    对比两个日志文件的差异
    
    Args:
        log1_path: 第一个日志文件路径 (master分支)
        log2_path: 第二个日志文件路径 (remove-metaprogramming分支)
        output_path: 差异输出文件路径（可选）
    """
    print(f"\n{'='*60}")
    print("对比日志文件差异")
    print(f"{'='*60}\n")
    
    try:
        with open(log1_path, 'r', encoding='utf-8') as f1:
            log1_lines = f1.readlines()
        with open(log2_path, 'r', encoding='utf-8') as f2:
            log2_lines = f2.readlines()
    except Exception as e:
        print(f"读取日志文件失败: {e}")
        return
    
    # 过滤掉时间戳相关的行，因为它们肯定不同
    def filter_lines(lines):
        filtered = []
        for line in lines:
            # 跳过时间戳行和分隔线
            if "运行时间:" in line or "结束时间:" in line:
                continue
            if line.strip().startswith("====="):
                continue
            filtered.append(line)
        return filtered
    
    log1_filtered = filter_lines(log1_lines)
    log2_filtered = filter_lines(log2_lines)
    
    # 生成差异
    diff = list(difflib.unified_diff(
        log1_filtered, 
        log2_filtered,
        fromfile=f"master: {os.path.basename(log1_path)}",
        tofile=f"remove-metaprogramming: {os.path.basename(log2_path)}",
        lineterm=""
    ))
    
    if not diff:
        print("✓ 两个日志文件内容一致（忽略时间戳）")
        diff_content = "两个日志文件内容一致（忽略时间戳）\n"
    else:
        print("✗ 发现差异:")
        print("-" * 40)
        diff_content = "\n".join(diff)
        print(diff_content)
        print("-" * 40)
    
    # 保存差异到文件
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_name = os.path.basename(log1_path).split("_master_")[0]
        output_path = os.path.join("logs", f"{script_name}_diff_{timestamp}.log")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"日志对比结果\n")
        f.write(f"{'='*60}\n")
        f.write(f"Master日志: {log1_path}\n")
        f.write(f"Remove-metaprogramming日志: {log2_path}\n")
        f.write(f"对比时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*60}\n\n")
        f.write(diff_content)
    
    print(f"\n差异已保存到: {output_path}")
    
    # 分析可能的bug
    analyze_differences(log1_filtered, log2_filtered)


def analyze_differences(master_lines, refactor_lines):
    """分析两个分支日志的差异，推测可能的bug"""
    print(f"\n{'='*60}")
    print("差异分析")
    print(f"{'='*60}\n")
    
    # 提取关键信息
    def extract_metrics(lines):
        metrics = {
            'buy_count': None,
            'sell_count': None,
            'final_value': None,
            'errors': [],
            'warnings': []
        }
        for line in lines:
            line_lower = line.lower()
            if 'buy_count' in line_lower or '买入次数' in line_lower:
                metrics['buy_count'] = line.strip()
            if 'sell_count' in line_lower or '卖出次数' in line_lower:
                metrics['sell_count'] = line.strip()
            if 'final_value' in line_lower or '最终资金' in line_lower:
                metrics['final_value'] = line.strip()
            if 'error' in line_lower or '错误' in line_lower:
                metrics['errors'].append(line.strip())
            if 'warning' in line_lower or '警告' in line_lower:
                metrics['warnings'].append(line.strip())
        return metrics
    
    master_metrics = extract_metrics(master_lines)
    refactor_metrics = extract_metrics(refactor_lines)
    
    print("Master分支指标:")
    print(f"  买入: {master_metrics['buy_count']}")
    print(f"  卖出: {master_metrics['sell_count']}")
    print(f"  最终资金: {master_metrics['final_value']}")
    if master_metrics['errors']:
        print(f"  错误数: {len(master_metrics['errors'])}")
    
    print("\nRemove-metaprogramming分支指标:")
    print(f"  买入: {refactor_metrics['buy_count']}")
    print(f"  卖出: {refactor_metrics['sell_count']}")
    print(f"  最终资金: {refactor_metrics['final_value']}")
    if refactor_metrics['errors']:
        print(f"  错误数: {len(refactor_metrics['errors'])}")
        print("  错误详情:")
        for err in refactor_metrics['errors'][:5]:  # 只显示前5个错误
            print(f"    - {err}")
    
    # 分析差异原因
    print("\n可能的问题分析:")
    if master_metrics['buy_count'] != refactor_metrics['buy_count']:
        print("  - 买入次数不一致，可能是订单执行逻辑或信号生成有差异")
    if master_metrics['sell_count'] != refactor_metrics['sell_count']:
        print("  - 卖出次数不一致，可能是平仓逻辑或止损止盈有差异")
    if master_metrics['final_value'] != refactor_metrics['final_value']:
        print("  - 最终资金不一致，可能是交易计算或手续费计算有差异")
    if len(refactor_metrics['errors']) > len(master_metrics['errors']):
        print("  - 重构分支有更多错误，请检查错误日志")


def run_on_both_branches(script_path, log_dir="logs"):
    """
    在master和remove-metaprogramming两个分支上运行测试并对比结果
    
    Args:
        script_path: 要运行的脚本路径
        log_dir: 日志目录
    """
    original_branch = get_git_branch()
    print(f"当前分支: {original_branch}")
    
    master_log = None
    refactor_log = None
    
    try:
        # 1. 切换到master分支并运行测试
        print("\n" + "="*60)
        print("第一步: 在 master 分支上运行测试")
        print("="*60)
        
        if not switch_branch("master"):
            print("无法切换到master分支，终止测试")
            return
        
        if not pip_install():
            print("pip install 失败，继续尝试运行测试...")
        
        return_code1, master_log = run_with_logging(script_path, log_dir, "master")
        print(f"Master分支测试完成，返回码: {return_code1}")
        
        # 2. 切换到remove-metaprogramming分支并运行测试
        print("\n" + "="*60)
        print("第二步: 在 remove-metaprogramming 分支上运行测试")
        print("="*60)
        
        if not switch_branch("remove-metaprogramming"):
            print("无法切换到remove-metaprogramming分支，终止测试")
            # 尝试切回原分支
            switch_branch(original_branch)
            return
        
        if not pip_install():
            print("pip install 失败，继续尝试运行测试...")
        
        return_code2, refactor_log = run_with_logging(script_path, log_dir, "remove-metaprogramming")
        print(f"Remove-metaprogramming分支测试完成，返回码: {return_code2}")
        
        # 3. 对比日志
        if master_log and refactor_log:
            compare_logs(master_log, refactor_log)
        
    finally:
        # 切回原分支
        print(f"\n切回原分支: {original_branch}")
        switch_branch(original_branch)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="运行测试文件并将输出保存到日志文件中",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 只在当前分支运行
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py
    
    # 在两个分支上运行并对比
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both
        """
    )
    
    parser.add_argument(
        "script_path",
        nargs="?",
        default="tests/strategies/test_02_multi_extend_data.py",
        help="要运行的测试脚本路径"
    )
    
    parser.add_argument(
        "--both",
        action="store_true",
        help="在master和remove-metaprogramming两个分支上运行测试并对比结果"
    )
    
    args = parser.parse_args()
    
    # 检查脚本是否存在
    if not os.path.exists(args.script_path):
        print(f"错误: 脚本文件不存在: {args.script_path}")
        sys.exit(1)
    
    if args.both:
        # 在两个分支上运行并对比
        run_on_both_branches(args.script_path)
    else:
        # 只在当前分支运行
        # 先执行pip install
        if not pip_install():
            print("pip install 失败，继续尝试运行测试...")
        
        return_code, _ = run_with_logging(args.script_path)
        sys.exit(return_code)


if __name__ == "__main__":
    main()
