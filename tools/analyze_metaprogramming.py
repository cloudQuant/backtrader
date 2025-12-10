#!/usr/bin/env python3
"""
元编程分析工具 - 检测backtrader项目中的元编程使用情况
"""

import ast
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


class MetaprogrammingAnalyzer:
    """元编程分析器"""

    def __init__(self, root_path="backtrader"):
        self.root_path = Path(root_path)
        self.results = {
            "metaclass_usage": [],
            "type_creation": [],
            "setattr_usage": [],
            "getattr_usage": [],
            "findowner_usage": [],
            "dynamic_attributes": [],
        }

    def analyze_file(self, file_path):
        """分析单个Python文件"""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # 检查metaclass使用
            metaclass_matches = re.findall(r"metaclass\s*=\s*(\w+)", content)
            if metaclass_matches:
                self.results["metaclass_usage"].extend(
                    [(str(file_path), match) for match in metaclass_matches]
                )

            # 检查type()动态创建
            type_matches = re.findall(r"type\s*\([^)]+\)", content)
            if type_matches:
                self.results["type_creation"].extend(
                    [(str(file_path), match) for match in type_matches]
                )

            # 检查setattr使用
            setattr_matches = re.findall(r"setattr\s*\([^)]+\)", content)
            if setattr_matches:
                self.results["setattr_usage"].extend(
                    [(str(file_path), match) for match in setattr_matches]
                )

            # 检查getattr使用
            getattr_matches = re.findall(r"getattr\s*\([^)]+\)", content)
            if getattr_matches:
                self.results["getattr_usage"].extend(
                    [(str(file_path), match) for match in getattr_matches]
                )

            # 检查findowner使用（backtrader特有的元编程工具）
            findowner_matches = re.findall(r"findowner\s*\([^)]+\)", content)
            if findowner_matches:
                self.results["findowner_usage"].extend(
                    [(str(file_path), match) for match in findowner_matches]
                )

        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")

    def scan_directory(self):
        """扫描整个目录"""
        for file_path in self.root_path.rglob("*.py"):
            if "test" not in str(file_path) and "__pycache__" not in str(file_path):
                self.analyze_file(file_path)

    def generate_report(self):
        """生成分析报告"""
        print("=" * 60)
        print("BACKTRADER 元编程使用分析报告")
        print("=" * 60)

        # 统计metaclass使用
        print(f"\n1. METACLASS 使用情况:")
        print(f"   总计: {len(self.results['metaclass_usage'])} 个")

        files_with_metaclass = set()
        metaclass_types = Counter()

        for file_path, metaclass_name in self.results["metaclass_usage"]:
            files_with_metaclass.add(file_path)
            metaclass_types[metaclass_name] += 1

        print(f"   涉及文件: {len(files_with_metaclass)} 个")
        print("   使用的元类类型:")
        for metaclass, count in metaclass_types.most_common():
            print(f"     - {metaclass}: {count} 次")

        print("\n   使用metaclass的文件:")
        for file_path in sorted(files_with_metaclass):
            relative_path = file_path.replace(str(self.root_path) + os.sep, "")
            print(f"     - {relative_path}")

        # 统计type()动态创建
        print(f"\n2. TYPE() 动态类创建:")
        print(f"   总计: {len(self.results['type_creation'])} 个")

        files_with_type = {file_path for file_path, _ in self.results["type_creation"]}
        print(f"   涉及文件: {len(files_with_type)} 个")

        # 统计setattr使用
        print(f"\n3. SETATTR 动态属性设置:")
        print(f"   总计: {len(self.results['setattr_usage'])} 个")

        files_with_setattr = {file_path for file_path, _ in self.results["setattr_usage"]}
        print(f"   涉及文件: {len(files_with_setattr)} 个")

        # 统计getattr使用
        print(f"\n4. GETATTR 动态属性获取:")
        print(f"   总计: {len(self.results['getattr_usage'])} 个")

        files_with_getattr = {file_path for file_path, _ in self.results["getattr_usage"]}
        print(f"   涉及文件: {len(files_with_getattr)} 个")

        # 统计findowner使用
        print(f"\n5. FINDOWNER 栈帧查找:")
        print(f"   总计: {len(self.results['findowner_usage'])} 个")

        files_with_findowner = {file_path for file_path, _ in self.results["findowner_usage"]}
        print(f"   涉及文件: {len(files_with_findowner)} 个")

        # 重度使用元编程的文件
        print(f"\n6. 元编程使用密度分析:")
        file_complexity = defaultdict(int)

        for category, items in self.results.items():
            for file_path, _ in items:
                file_complexity[file_path] += 1

        print("   元编程使用最频繁的文件 (Top 10):")
        for file_path, count in sorted(file_complexity.items(), key=lambda x: x[1], reverse=True)[
            :10
        ]:
            relative_path = file_path.replace(str(self.root_path) + os.sep, "")
            print(f"     - {relative_path}: {count} 次")

        # 核心文件识别
        print(f"\n7. 核心元编程文件识别:")
        core_files = [
            "metabase.py",
            "strategy.py",
            "lineseries.py",
            "lineiterator.py",
            "indicator.py",
            "feed.py",
            "analyzer.py",
            "broker.py",
        ]

        for core_file in core_files:
            count = sum(1 for file_path in file_complexity.keys() if file_path.endswith(core_file))
            if count > 0:
                total_usage = sum(
                    count
                    for file_path, count in file_complexity.items()
                    if file_path.endswith(core_file)
                )
                print(f"     - {core_file}: {total_usage} 处元编程使用")

        print("\n" + "=" * 60)
        print("分析完成")
        print("=" * 60)

    def save_detailed_report(self, output_file="metaprogramming_analysis.txt"):
        """保存详细报告到文件"""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("BACKTRADER 元编程详细分析报告\n")
            f.write("=" * 60 + "\n\n")

            for category, items in self.results.items():
                f.write(f"{category.upper()}\n")
                f.write("-" * 40 + "\n")

                for file_path, usage in items:
                    relative_path = file_path.replace(str(self.root_path) + os.sep, "")
                    f.write(f"{relative_path}: {usage}\n")

                f.write("\n")


def main():
    """主函数"""
    print("开始分析backtrader项目的元编程使用情况...")

    analyzer = MetaprogrammingAnalyzer()
    analyzer.scan_directory()
    analyzer.generate_report()
    analyzer.save_detailed_report()

    print(f"\n详细报告已保存到: metaprogramming_analysis.txt")


if __name__ == "__main__":
    main()
