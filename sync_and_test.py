#!/usr/bin/env python
"""
同步测试文件到master分支并在两个分支上运行测试

核心改进:
1. 无需git commit即可同步文件 - 直接复制文件内容
2. 使用PYTHONPATH运行测试 - 确保使用当前工作目录的代码而非pip安装的版本
3. 自动在master和origin分支上运行测试并输出日志

用法:
    python sync_and_test.py <test_file_path>
    
示例:
    python sync_and_test.py tests/strategies/test_120_data_replay_macd.py
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def get_git_root():
    """获取git仓库根目录"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.getcwd()


def get_git_branch():
    """获取当前git分支名称"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        branch = result.stdout.strip()
        if not branch:
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
    """切换git分支，使用--force忽略未提交的更改"""
    print(f"\n{'='*60}")
    print(f"切换到分支: {branch_name}")
    print(f"{'='*60}")

    try:
        # 使用 git checkout --force 强制切换，忽略工作目录的更改
        result = subprocess.run(
            ["git", "checkout", "--force", branch_name],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"成功切换到分支: {branch_name}")

        # 切换分支后执行 pip install -U . 安装当前分支的代码
        print(f"执行 pip install -U . 安装当前分支代码...")
        install_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "."],
            capture_output=True,
            text=True,
            cwd=get_git_root()
        )
        if install_result.returncode == 0:
            print(f"pip install 成功")
        else:
            print(f"pip install 失败: {install_result.stderr}")

        return True
    except subprocess.CalledProcessError as e:
        print(f"操作失败: {e.stderr if e.stderr else str(e)}")
        return False


def run_test_with_pythonpath(script_path, branch_name, log_dir="logs"):
    """
    使用PYTHONPATH运行测试，确保使用当前工作目录的代码
    
    Args:
        script_path: 测试脚本路径
        branch_name: 分支名称（用于日志文件名）
        log_dir: 日志目录
        
    Returns:
        tuple: (return_code, log_path)
    """
    git_root = get_git_root()
    
    # 创建日志目录
    log_dir_path = os.path.join(git_root, log_dir)
    if not os.path.exists(log_dir_path):
        os.makedirs(log_dir_path)
    
    # 生成日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f"{script_name}_{branch_name}_{timestamp}.log"
    log_path = os.path.join(log_dir_path, log_filename)
    
    # 清理同分支的旧日志
    import glob
    pattern = os.path.join(log_dir_path, f"{script_name}_{branch_name}_*.log")
    for old_log in glob.glob(pattern):
        try:
            os.remove(old_log)
            print(f"  已删除旧日志: {os.path.basename(old_log)}")
        except Exception:
            pass
    
    print(f"\n{'='*60}")
    print(f"运行测试: {script_path}")
    print(f"分支: {branch_name}")
    print(f"日志: {log_path}")
    print(f"PYTHONPATH: {git_root}")
    print(f"{'='*60}\n")
    
    # 设置环境变量，使用当前目录的代码
    env = os.environ.copy()
    env["PYTHONPATH"] = git_root
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    # 打开日志文件
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"{'='*60}\n")
        log_file.write(f"测试脚本: {script_path}\n")
        log_file.write(f"Git分支: {branch_name}\n")
        log_file.write(f"PYTHONPATH: {git_root}\n")
        log_file.write(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*60}\n\n")
        log_file.flush()
        
        try:
            # 运行测试脚本
            process = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=0,
                env=env,
                cwd=git_root
            )
            
            # 实时输出并写入日志
            output, _ = process.communicate()
            print(output, end="")
            log_file.write(output)
            log_file.flush()
            
            return_code = process.returncode
            
            # 写入结束信息
            end_msg = f"\n{'='*60}\n"
            end_msg += f"测试完成\n"
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


def sync_and_test(test_file_path):
    """
    同步测试文件到master分支并在两个分支上运行测试
    
    流程:
    1. 保存当前分支名称和测试文件内容
    2. 切换到master分支
    3. 复制测试文件到master
    4. 在master上运行测试
    5. 切换到origin分支
    6. 复制测试文件到origin  
    7. 在origin上运行测试
    8. 切回原分支并恢复文件
    """
    git_root = get_git_root()
    original_branch = get_git_branch()
    
    print(f"{'='*60}")
    print(f"同步并测试: {test_file_path}")
    print(f"当前分支: {original_branch}")
    print(f"Git根目录: {git_root}")
    print(f"{'='*60}")
    
    # 获取测试文件的绝对路径和相对路径
    if os.path.isabs(test_file_path):
        abs_test_path = test_file_path
        rel_test_path = os.path.relpath(test_file_path, git_root)
    else:
        abs_test_path = os.path.join(git_root, test_file_path)
        rel_test_path = test_file_path
    
    # 检查文件是否存在
    if not os.path.exists(abs_test_path):
        print(f"错误: 测试文件不存在: {abs_test_path}")
        return False
    
    # 读取测试文件内容到内存
    print(f"\n读取测试文件内容...")
    with open(abs_test_path, 'rb') as f:
        test_file_content = f.read()
    print(f"  文件大小: {len(test_file_content)} bytes")
    
    # 同时保存当前分支所有修改过的文件（用于恢复）
    modified_files = {}
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
            cwd=git_root
        )
        for rel_path in result.stdout.strip().split('\n'):
            if rel_path:
                full_path = os.path.join(git_root, rel_path)
                if os.path.exists(full_path):
                    with open(full_path, 'rb') as f:
                        modified_files[rel_path] = f.read()
                    print(f"  已备份修改文件: {rel_path}")
    except Exception as e:
        print(f"  备份修改文件时出错: {e}")
    
    master_log = None
    origin_log = None
    
    try:
        # ========== 在 master 分支上测试 ==========
        print("\n" + "="*60)
        print("步骤1: 在 master 分支上运行测试")
        print("="*60)
        
        if not switch_branch("master"):
            print("无法切换到master分支")
            return False
        
        # 复制测试文件到master
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"已复制测试文件到master: {rel_test_path}")
        
        # 运行测试
        return_code1, master_log = run_test_with_pythonpath(target_path, "master")
        print(f"Master分支测试完成，返回码: {return_code1}")
        
        # ========== 在 origin 分支上测试 ==========
        print("\n" + "="*60)
        print("步骤2: 在 origin 分支上运行测试")
        print("="*60)
        
        if not switch_branch("origin"):
            print("无法切换到origin分支")
            switch_branch(original_branch)
            return False
        
        # 复制测试文件到origin
        target_path = os.path.join(git_root, rel_test_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(test_file_content)
        print(f"已复制测试文件到origin: {rel_test_path}")
        
        # 运行测试
        return_code2, origin_log = run_test_with_pythonpath(target_path, "origin")
        print(f"Origin分支测试完成，返回码: {return_code2}")
        
        # ========== 输出结果汇总 ==========
        print("\n" + "="*60)
        print("测试完成! 日志文件:")
        print("="*60)
        if master_log:
            print(f"  Master: {master_log}")
        if origin_log:
            print(f"  Origin: {origin_log}")
        
        print("\n结果对比:")
        print(f"  Master 返回码: {return_code1} {'✓ 通过' if return_code1 == 0 else '✗ 失败'}")
        print(f"  Origin 返回码: {return_code2} {'✓ 通过' if return_code2 == 0 else '✗ 失败'}")
        
        return True
        
    finally:
        # ========== 恢复原始状态 ==========
        print(f"\n{'='*60}")
        print(f"恢复原始状态，切回分支: {original_branch}")
        print(f"{'='*60}")
        
        if not switch_branch(original_branch):
            print("警告: 切回原分支失败!")
        
        # 恢复修改过的文件
        for rel_path, content in modified_files.items():
            try:
                full_path = os.path.join(git_root, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'wb') as f:
                    f.write(content)
                print(f"  已恢复: {rel_path}")
            except Exception as e:
                print(f"  恢复失败 {rel_path}: {e}")
        
        print("\n完成!")


def main():
    parser = argparse.ArgumentParser(
        description="同步测试文件到master分支并在两个分支上运行测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
核心改进:
  - 无需git commit即可同步 - 直接复制文件内容
  - 使用PYTHONPATH运行测试 - 确保使用当前工作目录的代码
  - 自动备份和恢复修改过的文件

示例:
    python sync_and_test.py tests/strategies/test_120_data_replay_macd.py
        """
    )
    
    parser.add_argument(
        "test_file",
        help="要同步和测试的测试文件路径"
    )
    
    args = parser.parse_args()
    
    sync_and_test(args.test_file)


if __name__ == "__main__":
    main()
