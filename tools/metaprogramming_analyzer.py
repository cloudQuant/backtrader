#!/usr/bin/env python3
"""
Backtrader Metaprogramming Usage Analyzer

分析backtrader项目中元编程的使用情况，包括元类、动态类创建、属性访问等。
"""

import ast
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple


@dataclass
class MetaclassUsage:
    """元类使用信息"""

    file_path: str
    class_name: str
    metaclass_name: str
    line_number: int
    usage_type: str  # 'inheritance', 'creation', 'assignment'


@dataclass
class DynamicCreation:
    """动态类/属性创建信息"""

    file_path: str
    line_number: int
    creation_type: str  # 'type_call', 'setattr', 'getattr', '__new__', '__init_subclass__'
    target: str
    context: str


@dataclass
class ParameterUsage:
    """参数系统使用信息"""

    file_path: str
    class_name: str
    line_number: int
    usage_type: str  # 'params_definition', 'params_access', 'MetaParams'


@dataclass
class LineUsage:
    """Lines系统使用信息"""

    file_path: str
    class_name: str
    line_number: int
    usage_type: str  # 'lines_definition', 'lines_access', 'MetaLineSeries'


class MetaprogrammingAnalyzer(ast.NodeVisitor):
    """元编程分析器"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.metaclass_usages: List[MetaclassUsage] = []
        self.dynamic_creations: List[DynamicCreation] = []
        self.parameter_usages: List[ParameterUsage] = []
        self.line_usages: List[LineUsage] = []
        self.current_class = None

        # 已知的元类名称
        self.known_metaclasses = {
            "MetaBase",
            "MetaParams",
            "MetaLineSeries",
            "MetaSingleton",
            "MetaIndicator",
            "MetaStrategy",
            "MetaAnalyzer",
            "MetaObserver",
        }

        # 参数相关的模式
        self.param_patterns = ["params", r"p\.", "MetaParams"]

        # Lines相关的模式
        self.line_patterns = ["lines", "MetaLineSeries", "LineRoot"]

    def visit_ClassDef(self, node: ast.ClassDef):
        """访问类定义"""
        old_class = self.current_class
        self.current_class = node.name

        # 检查元类使用
        if hasattr(node, "metaclass") and node.metaclass:
            metaclass_name = self._get_name(node.metaclass)
            if metaclass_name in self.known_metaclasses:
                self.metaclass_usages.append(
                    MetaclassUsage(
                        file_path=self.file_path,
                        class_name=node.name,
                        metaclass_name=metaclass_name,
                        line_number=node.lineno,
                        usage_type="inheritance",
                    )
                )

        # 检查基类中的元类
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name in self.known_metaclasses:
                self.metaclass_usages.append(
                    MetaclassUsage(
                        file_path=self.file_path,
                        class_name=node.name,
                        metaclass_name=base_name,
                        line_number=node.lineno,
                        usage_type="inheritance",
                    )
                )

        # 检查类体中的参数和Lines定义
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "params":
                            self.parameter_usages.append(
                                ParameterUsage(
                                    file_path=self.file_path,
                                    class_name=node.name,
                                    line_number=stmt.lineno,
                                    usage_type="params_definition",
                                )
                            )
                        elif target.id == "lines":
                            self.line_usages.append(
                                LineUsage(
                                    file_path=self.file_path,
                                    class_name=node.name,
                                    line_number=stmt.lineno,
                                    usage_type="lines_definition",
                                )
                            )

        self.generic_visit(node)
        self.current_class = old_class

    def visit_Call(self, node: ast.Call):
        """访问函数调用"""
        func_name = self._get_name(node.func)

        # 检查type()调用（动态类创建）
        if func_name == "type" and len(node.args) == 3:
            self.dynamic_creations.append(
                DynamicCreation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    creation_type="type_call",
                    target=self._get_name(node.args[0]) if node.args else "unknown",
                    context=f"type({', '.join(self._get_name(arg) for arg in node.args)})",
                )
            )

        # 检查setattr调用
        elif func_name == "setattr":
            self.dynamic_creations.append(
                DynamicCreation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    creation_type="setattr",
                    target=self._get_name(node.args[1]) if len(node.args) > 1 else "unknown",
                    context=f"setattr({', '.join(self._get_name(arg) for arg in node.args[:2])})",
                )
            )

        # 检查getattr调用
        elif func_name == "getattr":
            self.dynamic_creations.append(
                DynamicCreation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    creation_type="getattr",
                    target=self._get_name(node.args[1]) if len(node.args) > 1 else "unknown",
                    context=f"getattr({', '.join(self._get_name(arg) for arg in node.args[:2])})",
                )
            )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """访问属性访问"""
        # 检查参数访问
        if node.attr in ["params", "p"] or (
            isinstance(node.value, ast.Name) and node.value.id in ["params", "p"]
        ):
            self.parameter_usages.append(
                ParameterUsage(
                    file_path=self.file_path,
                    class_name=self.current_class or "unknown",
                    line_number=node.lineno,
                    usage_type="params_access",
                )
            )

        # 检查lines访问
        if node.attr == "lines" or (isinstance(node.value, ast.Name) and node.value.id == "lines"):
            self.line_usages.append(
                LineUsage(
                    file_path=self.file_path,
                    class_name=self.current_class or "unknown",
                    line_number=node.lineno,
                    usage_type="lines_access",
                )
            )

        self.generic_visit(node)

    def _get_name(self, node):
        """获取节点名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Constant):
            return str(node.value)
        else:
            return "unknown"


class ProjectAnalyzer:
    """项目分析器"""

    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)
        self.all_metaclass_usages: List[MetaclassUsage] = []
        self.all_dynamic_creations: List[DynamicCreation] = []
        self.all_parameter_usages: List[ParameterUsage] = []
        self.all_line_usages: List[LineUsage] = []
        self.file_stats: Dict[str, Dict] = {}

    def analyze_project(self):
        """分析整个项目"""
        print("开始分析backtrader项目的元编程使用情况...")

        # 遍历项目中的Python文件
        for root, dirs, files in os.walk(self.project_root):
            # 跳过一些目录
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in ["__pycache__", "build", "dist"]
            ]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_root)

                    # 只分析backtrader包内的文件
                    if rel_path.startswith("backtrader" + os.sep) or file == "__init__.py":
                        try:
                            self.analyze_file(file_path, rel_path)
                        except Exception as e:
                            print(f"分析文件 {rel_path} 时出错: {e}")

    def analyze_file(self, file_path: str, rel_path: str):
        """分析单个文件"""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            analyzer = MetaprogrammingAnalyzer(rel_path)
            analyzer.visit(tree)

            # 收集结果
            self.all_metaclass_usages.extend(analyzer.metaclass_usages)
            self.all_dynamic_creations.extend(analyzer.dynamic_creations)
            self.all_parameter_usages.extend(analyzer.parameter_usages)
            self.all_line_usages.extend(analyzer.line_usages)

            # 文件统计
            self.file_stats[rel_path] = {
                "metaclass_count": len(analyzer.metaclass_usages),
                "dynamic_creation_count": len(analyzer.dynamic_creations),
                "parameter_usage_count": len(analyzer.parameter_usages),
                "line_usage_count": len(analyzer.line_usages),
                "total_metaprogramming": (
                    len(analyzer.metaclass_usages)
                    + len(analyzer.dynamic_creations)
                    + len(analyzer.parameter_usages)
                    + len(analyzer.line_usages)
                ),
            }

            # 正则表达式分析（补充AST分析）
            self._regex_analysis(content, rel_path)

        except Exception as e:
            print(f"无法解析文件 {rel_path}: {e}")

    def _regex_analysis(self, content: str, file_path: str):
        """使用正则表达式进行补充分析"""
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # 检查__metaclass__使用
            if "__metaclass__" in line:
                self.all_metaclass_usages.append(
                    MetaclassUsage(
                        file_path=file_path,
                        class_name="unknown",
                        metaclass_name="__metaclass__",
                        line_number=i,
                        usage_type="assignment",
                    )
                )

            # 检查特定的元编程模式
            if re.search(r"MetaParams|MetaLineSeries|MetaSingleton", line):
                metaclass_match = re.search(r"(MetaParams|MetaLineSeries|MetaSingleton)", line)
                if metaclass_match:
                    self.all_metaclass_usages.append(
                        MetaclassUsage(
                            file_path=file_path,
                            class_name="unknown",
                            metaclass_name=metaclass_match.group(1),
                            line_number=i,
                            usage_type="reference",
                        )
                    )

    def generate_report(self):
        """生成分析报告"""
        report = {
            "analysis_time": datetime.now().isoformat(),
            "project_root": self.project_root,
            "summary": {
                "total_files_analyzed": len(self.file_stats),
                "total_metaclass_usages": len(self.all_metaclass_usages),
                "total_dynamic_creations": len(self.all_dynamic_creations),
                "total_parameter_usages": len(self.all_parameter_usages),
                "total_line_usages": len(self.all_line_usages),
                "total_metaprogramming_instances": (
                    len(self.all_metaclass_usages)
                    + len(self.all_dynamic_creations)
                    + len(self.all_parameter_usages)
                    + len(self.all_line_usages)
                ),
            },
            "metaclass_breakdown": self._get_metaclass_breakdown(),
            "files_with_most_metaprogramming": self._get_top_files(),
            "file_stats": self.file_stats,
            "detailed_usages": {
                "metaclass_usages": [
                    {
                        "file": usage.file_path,
                        "class": usage.class_name,
                        "metaclass": usage.metaclass_name,
                        "line": usage.line_number,
                        "type": usage.usage_type,
                    }
                    for usage in self.all_metaclass_usages
                ],
                "dynamic_creations": [
                    {
                        "file": creation.file_path,
                        "line": creation.line_number,
                        "type": creation.creation_type,
                        "target": creation.target,
                        "context": creation.context,
                    }
                    for creation in self.all_dynamic_creations
                ],
                "parameter_usages": [
                    {
                        "file": usage.file_path,
                        "class": usage.class_name,
                        "line": usage.line_number,
                        "type": usage.usage_type,
                    }
                    for usage in self.all_parameter_usages
                ],
                "line_usages": [
                    {
                        "file": usage.file_path,
                        "class": usage.class_name,
                        "line": usage.line_number,
                        "type": usage.usage_type,
                    }
                    for usage in self.all_line_usages
                ],
            },
        }

        return report

    def _get_metaclass_breakdown(self):
        """获取元类使用分解"""
        breakdown = defaultdict(int)
        for usage in self.all_metaclass_usages:
            breakdown[usage.metaclass_name] += 1
        return dict(breakdown)

    def _get_top_files(self, top_n: int = 10):
        """获取元编程使用最多的文件"""
        sorted_files = sorted(
            self.file_stats.items(), key=lambda x: x[1]["total_metaprogramming"], reverse=True
        )
        return sorted_files[:top_n]

    def print_summary(self, report: Dict):
        """打印分析摘要"""
        print("=" * 60)
        print("Backtrader 元编程使用分析报告")
        print("=" * 60)

        summary = report["summary"]
        print(f"分析文件数: {summary['total_files_analyzed']}")
        print(f"元类使用: {summary['total_metaclass_usages']}")
        print(f"动态创建: {summary['total_dynamic_creations']}")
        print(f"参数系统使用: {summary['total_parameter_usages']}")
        print(f"Lines系统使用: {summary['total_line_usages']}")
        print(f"总元编程实例: {summary['total_metaprogramming_instances']}")

        print("\n元类使用分解:")
        print("-" * 30)
        for metaclass, count in report["metaclass_breakdown"].items():
            print(f"{metaclass}: {count}")

        print("\n元编程使用最多的文件 (Top 10):")
        print("-" * 50)
        print(f"{'文件':<35} {'元编程实例数':<10}")
        print("-" * 50)
        for file_path, stats in report["files_with_most_metaprogramming"]:
            print(f"{file_path:<35} {stats['total_metaprogramming']:<10}")

    def save_report(self, report: Dict):
        """保存分析报告"""
        os.makedirs("analysis_results", exist_ok=True)
        filename = f"analysis_results/metaprogramming_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n详细报告已保存到: {filename}")


def main():
    """主函数"""
    analyzer = ProjectAnalyzer()
    analyzer.analyze_project()

    report = analyzer.generate_report()
    analyzer.print_summary(report)
    analyzer.save_report(report)


if __name__ == "__main__":
    main()
