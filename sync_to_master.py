#!/usr/bin/env python
"""
将当前分支的文件同步到 master 分支

用法:
    python sync_to_master.py <file_path>

示例:
    python sync_to_master.py tests/strategies/test_58_data_replay.py
    python sync_to_master.py backtrader/indicators/sma.py
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def get_git_branch():
    """获取当前git分支名称"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def file_exists(filepath):
    """检查文件是否存在"""
    return os.path.exists(filepath)


def sync_to_master(file_path, run_test=False, stay_on_master=False, commit=False,
                   commit_message=None):
    """
    将当前分支的文件同步到 master 分支

    Args:
        file_path: 要同步的文件路径
        run_test: 同步后是否运行测试
        stay_on_master: 是否停留在 master 分支
        commit: 同步后是否提交变化
        commit_message: 自定义提交信息
    """
    original_branch = get_git_branch()
    print(f"当前分支: {original_branch}")

    # 检查文件是否存在
    if not file_exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return False

    # 获取绝对路径
    abs_path = os.path.abspath(file_path)

    # 创建临时文件保存当前分支的内容
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='_sync') as tmp_file:
        temp_path = tmp_file.name
        with open(abs_path, 'rb') as f:
            shutil.copyfileobj(f, tmp_file)

    print(f"已备份当前分支的文件: {file_path}")

    try:
        # 切换到 master 分支
        print(f"\n切换到 master 分支...")
        result = subprocess.run(
            ["git", "checkout", "master"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # 尝试处理未提交的更改
            if "changes" in result.stderr.lower():
                print("检测到未提交的更改，尝试 stash...")
                subprocess.run(["git", "stash", "push", "-m", "auto-stash-by-sync"],
                             capture_output=True, text=True)
                subprocess.run(["git", "checkout", "master"], capture_output=True, text=True)

        print(f"已切换到 master 分支")

        # 覆盖 master 分支的文件
        target_path = os.path.abspath(file_path)
        target_dir = os.path.dirname(target_path)

        # 确保目标目录存在
        os.makedirs(target_dir, exist_ok=True)

        # 先用 git checkout 恢复目标文件到 git 仓库的状态
        # 这样可以清除任何未提交的更改
        subprocess.run(
            ["git", "checkout", "HEAD", "--", target_path],
            capture_output=True,
            text=True
        )

        # 然后复制当前分支的文件覆盖
        shutil.copy2(temp_path, target_path)
        print(f"已同步文件到 master: {file_path}")

        # 显示文件差异的前几行
        print("\n--- 文件预览 (前30行) ---")
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= 30:
                        break
                    print(f"{i+1:3d}: {line.rstrip()}")
        except Exception as e:
            print(f"预览失败: {e}")

        # 是否运行测试
        if run_test:
            print("\n--- 运行测试 ---")
            if file_path.endswith('.py'):
                result = subprocess.run(
                    [sys.executable, target_path],
                    capture_output=False,
                    text=True
                )
                if result.returncode == 0:
                    print("\n✓ 测试通过")
                else:
                    print(f"\n✗ 测试失败 (退出码: {result.returncode})")

        # 是否提交变化
        if commit:
            print("\n--- 提交变化 ---")
            # 添加文件到暂存区
            subprocess.run(
                ["git", "add", target_path],
                capture_output=True,
                text=True
            )

            # 生成提交信息
            if commit_message is None:
                commit_message = f"update {file_path} from {original_branch}"
            else:
                commit_message = commit_message.replace("{branch}", original_branch)
                commit_message = commit_message.replace("{file}", file_path)

            # 提交
            result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                print(f"✓ 已提交: {commit_message}")
            else:
                print(f"✗ 提交失败或无变化")
                print(result.stdout)
                print(result.stderr)

        # 是否停留在 master 分支
        if not stay_on_master:
            print(f"\n切回原分支: {original_branch}")
            subprocess.run(
                ["git", "checkout", original_branch],
                capture_output=True,
                text=True
            )
            print(f"已切回 {original_branch} 分支")
        else:
            print(f"\n停留在 master 分支")

        print("\n✓ 同步完成")
        return True

    except Exception as e:
        print(f"\n错误: {e}")
        # 尝试切回原分支
        subprocess.run(
            ["git", "checkout", original_branch],
            capture_output=True,
            text=True
        )
        return False

    finally:
        # 清理临时文件
        try:
            os.remove(temp_path)
        except:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="将当前分支的文件同步到 master 分支",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 同步单个文件
    python sync_to_master.py tests/strategies/test_58_data_replay.py

    # 同步文件并在 master 分支上运行测试
    python sync_to_master.py tests/strategies/test_58_data_replay.py --run

    # 同步文件后停留在 master 分支
    python sync_to_master.py tests/strategies/test_58_data_replay.py --stay

    # 同步文件并提交变化
    python sync_to_master.py tests/strategies/test_58_data_replay.py --commit

    # 同步文件、提交并运行测试
    python sync_to_master.py tests/strategies/test_58_data_replay.py -c -r

    # 同步文件并使用自定义提交信息
    python sync_to_master.py tests/strategies/test_58_data_replay.py -c -m "update from {branch}"
        """
    )

    parser.add_argument(
        "file_path",
        help="要同步的文件路径"
    )

    parser.add_argument(
        "-r", "--run",
        action="store_true",
        help="同步后在 master 分支上运行测试"
    )

    parser.add_argument(
        "-s", "--stay",
        action="store_true",
        help="同步后停留在 master 分支"
    )

    parser.add_argument(
        "-c", "--commit",
        action="store_true",
        help="同步后在 master 分支上提交变化"
    )

    parser.add_argument(
        "-m", "--message",
        default=None,
        help="自定义提交信息（可使用 {branch} 和 {file} 占位符）"
    )

    args = parser.parse_args()

    sync_to_master(args.file_path, run_test=args.run, stay_on_master=args.stay,
                   commit=args.commit, commit_message=args.message)


if __name__ == "__main__":
    main()
