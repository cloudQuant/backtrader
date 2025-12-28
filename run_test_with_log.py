#!/usr/bin/env python
"""
运行测试文件并将输出同时显示在终端和保存到日志文件中
日志文件名包含当前git分支名称

用法:
    python run_test_with_log.py <test_script> [--both]
    
参数:
    test_script: 要测试的脚本路径
    --both: 在master和remove-metaprogramming两个分支上都运行测试
            如果不指定，则只在当前分支运行测试
            
示例:
    # 只在当前分支运行
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py
    
    # 在两个分支上运行
    python run_test_with_log.py tests/strategies/test_18_etf_rotation_strategy.py --both
"""

import argparse
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


def git_stash():
    """暂存未提交的更改"""
    try:
        # 检查是否有需要暂存的更改
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip():
            print("发现未提交的更改，执行 git stash...")
            result = subprocess.run(
                ["git", "stash", "push", "-m", "auto-stash-by-run_test_with_log"],
                capture_output=True,
                text=True,
                check=True
            )
            print("暂存成功")
            return True
        else:
            print("没有需要暂存的更改")
            return False
    except subprocess.CalledProcessError as e:
        print(f"暂存失败: {e.stderr}")
        return False


def git_stash_pop():
    """恢复暂存的更改"""
    try:
        # 检查是否有暂存
        result = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        if "auto-stash-by-run_test_with_log" in result.stdout:
            print("恢复暂存的更改...")
            result = subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True,
                check=True
            )
            print("恢复成功")
            return True
        return False
    except subprocess.CalledProcessError as e:
        print(f"恢复暂存失败: {e.stderr}")
        return False


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


def run_on_both_branches(script_path, log_dir="logs"):
    """
    在master和remove-metaprogramming两个分支上运行测试
    
    Args:
        script_path: 要运行的脚本路径
        log_dir: 日志目录
    """
    original_branch = get_git_branch()
    print(f"当前分支: {original_branch}")
    
    # 先暂存未提交的更改
    stashed = git_stash()
    
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
        
        # 3. 输出日志文件路径
        print("\n" + "="*60)
        print("测试完成，日志文件:")
        print("="*60)
        if master_log:
            print(f"  Master: {master_log}")
        if refactor_log:
            print(f"  Remove-metaprogramming: {refactor_log}")
        
    finally:
        # 切回原分支
        print(f"\n切回原分支: {original_branch}")
        switch_branch(original_branch)
        
        # 恢复暂存的更改
        if stashed:
            git_stash_pop()


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
