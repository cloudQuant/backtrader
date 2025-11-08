#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行测试文件并将输出同时显示在终端和保存到日志文件中
日志文件名包含当前git分支名称
"""

import subprocess
import sys
import os
import glob
from datetime import datetime


def get_git_branch():
    """获取当前git分支名称"""
    try:
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True,
            text=True,
            check=True
        )
        branch = result.stdout.strip()
        if not branch:
            # 如果没有分支名，尝试获取HEAD的描述
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True,
                text=True,
                check=True
            )
            branch = result.stdout.strip()
        return branch if branch else 'unknown'
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'


def cleanup_old_logs(script_path, branch_name, log_dir='logs'):
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
    pattern = os.path.join(log_dir, f'{script_name}_{branch_name}_*.log')
    
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


def run_with_logging(script_path, log_dir='logs'):
    """
    运行指定的脚本，并将输出同时显示在终端和保存到日志文件
    
    Args:
        script_path: 要运行的脚本路径
        log_dir: 日志文件保存目录
    """
    # 创建日志目录
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 获取git分支名称
    branch_name = get_git_branch()
    
    # 清理当前分支的旧日志文件
    cleanup_old_logs(script_path, branch_name, log_dir)
    
    # 生成日志文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    log_filename = f'{script_name}_{branch_name}_{timestamp}.log'
    log_path = os.path.join(log_dir, log_filename)
    
    print(f"{'='*60}")
    print(f"运行脚本: {script_path}")
    print(f"Git分支: {branch_name}")
    print(f"日志文件: {log_path}")
    print(f"{'='*60}\n")
    
    # 打开日志文件
    with open(log_path, 'w', encoding='utf-8') as log_file:
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
                encoding='utf-8',
                errors='replace',  # 遇到无法解码的字符时替换为?
                bufsize=1,  # 行缓冲
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}  # 强制Python使用UTF-8
            )
            
            # 实时读取输出并同时写入终端和日志文件
            for line in process.stdout:
                # 输出到终端
                print(line, end='')
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
            
            return return_code
            
        except Exception as e:
            error_msg = f"\n执行出错: {str(e)}\n"
            print(error_msg)
            log_file.write(error_msg)
            return 1


def main():
    """主函数"""
    # 默认运行 test_02_multi_extend_data.py
    script_path = r'tests\strategies\test_02_multi_extend_data.py'
    
    # 如果命令行提供了参数，使用命令行参数
    if len(sys.argv) > 1:
        script_path = sys.argv[1]
    
    # 检查脚本是否存在
    if not os.path.exists(script_path):
        print(f"错误: 脚本文件不存在: {script_path}")
        sys.exit(1)
    
    # 运行脚本
    return_code = run_with_logging(script_path)
    
    # 使用脚本的返回码退出
    sys.exit(return_code)


if __name__ == '__main__':
    main()

