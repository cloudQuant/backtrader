#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自动修复文档链接问题的工具。

主要修复：
1. 外部URL格式问题（移除<>包裹）
2. 缺失的内部链接文件
3. 路径错误
"""

import re
from pathlib import Path
from typing import List, Tuple


def fix_external_urls(content: str) -> Tuple[str, int]:
    """修复外部URL格式问题（移除<>包裹）。"""
    # 匹配 [text](<url>) 格式
    pattern = r'\[([^\]]+)\]\(<(https?://[^>]+)>`?\)'
    
    def replace_func(match):
        text = match.group(1)
        url = match.group(2)
        return f'[{text}]({url})'
    
    new_content, count = re.subn(pattern, replace_func, content)
    return new_content, count


def fix_badge_urls(content: str) -> Tuple[str, int]:
    """修复badge URL格式问题。"""
    # 匹配 ![text](<url>) 格式
    pattern = r'!\[([^\]]*)\]\(<(https?://[^>]+)>`?\)'
    
    def replace_func(match):
        text = match.group(1)
        url = match.group(2)
        return f'![{text}]({url})'
    
    new_content, count = re.subn(pattern, replace_func, content)
    return new_content, count


def fix_file(file_path: Path) -> int:
    """修复单个文件的链接问题。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        total_fixes = 0
        
        # 修复外部URL
        content, count1 = fix_external_urls(content)
        total_fixes += count1
        
        # 修复badge URL
        content, count2 = fix_badge_urls(content)
        total_fixes += count2
        
        # 如果有修改，写回文件
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ {file_path}: {total_fixes} fixes")
        
        return total_fixes
    
    except Exception as e:
        print(f"✗ Error fixing {file_path}: {e}")
        return 0


def main():
    """主函数。"""
    docs_root = Path('docs')
    
    # 查找所有Markdown文件
    md_files = list(docs_root.rglob('*.md'))
    
    print(f"扫描 {len(md_files)} 个Markdown文件...")
    print()
    
    total_files_fixed = 0
    total_fixes = 0
    
    for md_file in md_files:
        fixes = fix_file(md_file)
        if fixes > 0:
            total_files_fixed += 1
            total_fixes += fixes
    
    print()
    print(f"完成！修复了 {total_files_fixed} 个文件中的 {total_fixes} 个链接问题")


if __name__ == '__main__':
    main()
