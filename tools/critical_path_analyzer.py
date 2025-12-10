#!/usr/bin/env python3
"""
Backtrader Critical Path Analyzer

识别重构过程中的关键路径和风险点，分析依赖链和瓶颈。
"""

import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class CriticalPath:
    """关键路径"""

    path_id: str
    classes: List[str]
    total_complexity: float
    estimated_duration: int
    bottlenecks: List[str]
    risk_level: str
    impact_scope: str


@dataclass
class Bottleneck:
    """瓶颈点"""

    class_name: str
    bottleneck_type: str  # 'dependency', 'complexity', 'risk'
    severity: str  # 'low', 'medium', 'high', 'critical'
    affected_classes: List[str]
    suggested_resolution: str


class CriticalPathAnalyzer:
    """关键路径分析器"""

    def __init__(self):
        self.dependency_data: Dict[str, Any] = {}
        self.implementation_plan: Dict[str, Any] = {}
        self.critical_paths: List[CriticalPath] = []
        self.bottlenecks: List[Bottleneck] = []

        # 预定义的核心类（框架关键节点）
        self.core_classes = {
            "Cerebro",
            "Strategy",
            "Indicator",
            "LineSeriesBase",
            "DataBase",
            "BrokerBase",
            "FeedBase",
            "MetaParams",
            "MetaLineSeries",
            "MetaSingleton",
            "MetaBase",
            "LineIterator",
        }

    def load_analysis_data(self):
        """加载分析数据"""
        # 加载依赖分析数据
        try:
            dep_files = [
                f for f in os.listdir("analysis_results") if f.startswith("dependency_analysis_")
            ]
            if dep_files:
                latest_dep = sorted(dep_files)[-1]
                with open(f"analysis_results/{latest_dep}", encoding="utf-8") as f:
                    self.dependency_data = json.load(f)
                print(f"已加载依赖分析数据: {latest_dep}")
        except Exception as e:
            print(f"无法加载依赖分析数据: {e}")

        # 加载实施计划数据
        try:
            plan_files = [
                f for f in os.listdir("planning_results") if f.startswith("implementation_plan_")
            ]
            if plan_files:
                latest_plan = sorted(plan_files)[-1]
                with open(f"planning_results/{latest_plan}", encoding="utf-8") as f:
                    self.implementation_plan = json.load(f)
                print(f"已加载实施计划数据: {latest_plan}")
        except Exception as e:
            print(f"无法加载实施计划数据: {e}")

    def analyze_critical_paths(self):
        """分析关键路径"""
        if not self.dependency_data:
            print("缺少依赖数据，使用模拟分析")
            self._create_mock_analysis()
            return

        # 从依赖数据中分析路径
        priority_matrix = self.dependency_data.get("priority_matrix", {})
        risk_assessments = self.dependency_data.get("risk_assessments", [])

        # 1. 基于依赖关系的路径
        dependency_paths = self._analyze_dependency_paths(priority_matrix)

        # 2. 基于风险评估的路径
        risk_paths = self._analyze_risk_paths(risk_assessments)

        # 3. 基于复杂度的路径
        complexity_paths = self._analyze_complexity_paths(priority_matrix)

        self.critical_paths = dependency_paths + risk_paths + complexity_paths

        # 去重和排序
        self._deduplicate_and_sort_paths()

        print(f"分析出 {len(self.critical_paths)} 条关键路径")

    def _analyze_dependency_paths(self, priority_matrix: Dict) -> List[CriticalPath]:
        """分析依赖路径"""
        paths = []

        # 构建依赖图
        dependencies = defaultdict(list)
        for class_name, info in priority_matrix.items():
            for prerequisite in info.get("prerequisites", []):
                if "重构基类:" in prerequisite:
                    base_class = prerequisite.split(":")[1].strip()
                    dependencies[base_class].append(class_name)

        # 找到依赖链
        for root_class, dependent_classes in dependencies.items():
            if len(dependent_classes) >= 2:  # 至少2个依赖类
                chain = [root_class] + dependent_classes
                path = self._create_path_from_chain(chain, "dependency")
                paths.append(path)

        return paths

    def _analyze_risk_paths(self, risk_assessments: List) -> List[CriticalPath]:
        """分析风险路径"""
        paths = []

        # 按风险级别分组
        high_risk_classes = []
        for assessment in risk_assessments:
            if assessment["risk_level"] in ["critical", "high"]:
                high_risk_classes.append(assessment["class_name"])

        # 创建高风险路径
        if len(high_risk_classes) >= 3:
            # 将高风险类分组（每3个一组）
            for i in range(0, len(high_risk_classes), 3):
                group = high_risk_classes[i : i + 3]
                if len(group) >= 2:
                    path = self._create_path_from_chain(group, "high_risk")
                    paths.append(path)

        return paths

    def _analyze_complexity_paths(self, priority_matrix: Dict) -> List[CriticalPath]:
        """分析复杂度路径"""
        paths = []

        # 按复杂度排序
        complex_classes = []
        for class_name, info in priority_matrix.items():
            if info.get("complexity_score", 0) >= 4.0:
                complex_classes.append((class_name, info["complexity_score"]))

        complex_classes.sort(key=lambda x: x[1], reverse=True)

        # 创建复杂度路径（每5个高复杂度类一组）
        for i in range(0, len(complex_classes), 5):
            group = [item[0] for item in complex_classes[i : i + 5]]
            if len(group) >= 3:
                path = self._create_path_from_chain(group, "complexity")
                paths.append(path)

        return paths

    def _create_path_from_chain(self, chain: List[str], path_type: str) -> CriticalPath:
        """从类链创建关键路径"""
        path_id = f"{path_type}_{len(chain)}_{hash(tuple(chain)) % 10000}"

        # 从依赖数据计算复杂度
        total_complexity = 0.0
        if self.dependency_data:
            priority_matrix = self.dependency_data.get("priority_matrix", {})
            for class_name in chain:
                if class_name in priority_matrix:
                    total_complexity += priority_matrix[class_name].get("complexity_score", 1.0)
        else:
            total_complexity = len(chain) * 2.0  # 默认估算

        # 估算持续时间
        estimated_duration = max(len(chain), int(total_complexity))

        # 识别瓶颈
        bottlenecks = []
        for class_name in chain:
            if class_name in self.core_classes:
                bottlenecks.append(f"{class_name}: 核心类")

        # 确定风险级别
        if path_type == "high_risk":
            risk_level = "high"
        elif total_complexity >= 15.0:
            risk_level = "critical"
        elif total_complexity >= 10.0:
            risk_level = "high"
        elif total_complexity >= 5.0:
            risk_level = "medium"
        else:
            risk_level = "low"

        # 评估影响范围
        if len(chain) >= 5:
            impact_scope = "全项目影响"
        elif len(chain) >= 3:
            impact_scope = "模块级影响"
        else:
            impact_scope = "局部影响"

        return CriticalPath(
            path_id=path_id,
            classes=chain,
            total_complexity=total_complexity,
            estimated_duration=estimated_duration,
            bottlenecks=bottlenecks,
            risk_level=risk_level,
            impact_scope=impact_scope,
        )

    def _deduplicate_and_sort_paths(self):
        """去重和排序路径"""
        # 简单去重（基于路径类的集合）
        seen_class_sets = set()
        unique_paths = []

        for path in self.critical_paths:
            class_set = tuple(sorted(path.classes))
            if class_set not in seen_class_sets:
                seen_class_sets.add(class_set)
                unique_paths.append(path)

        # 按风险级别和复杂度排序
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        unique_paths.sort(
            key=lambda p: (risk_order.get(p.risk_level, 3), -p.total_complexity, -len(p.classes))
        )

        self.critical_paths = unique_paths

    def analyze_bottlenecks(self):
        """分析瓶颈"""
        if not self.dependency_data:
            self._create_mock_bottlenecks()
            return

        priority_matrix = self.dependency_data.get("priority_matrix", {})

        # 1. 依赖瓶颈
        for class_name, info in priority_matrix.items():
            dependent_count = info.get("dependent_classes", 0)
            if dependent_count >= 5:
                severity = (
                    "critical"
                    if dependent_count >= 15
                    else "high" if dependent_count >= 10 else "medium"
                )

                bottleneck = Bottleneck(
                    class_name=class_name,
                    bottleneck_type="dependency",
                    severity=severity,
                    affected_classes=[],  # 简化处理
                    suggested_resolution=f"优先重构 {class_name}，采用渐进式迁移",
                )
                self.bottlenecks.append(bottleneck)

        # 2. 复杂度瓶颈
        for class_name, info in priority_matrix.items():
            complexity = info.get("complexity_score", 0.0)
            if complexity >= 4.0:
                severity = "critical" if complexity >= 6.0 else "high"

                bottleneck = Bottleneck(
                    class_name=class_name,
                    bottleneck_type="complexity",
                    severity=severity,
                    affected_classes=[class_name],
                    suggested_resolution=f"分解 {class_name} 的复杂功能",
                )
                self.bottlenecks.append(bottleneck)

        # 3. 风险瓶颈
        for class_name, info in priority_matrix.items():
            if info.get("risk_level") in ["critical", "high"] and class_name in self.core_classes:
                bottleneck = Bottleneck(
                    class_name=class_name,
                    bottleneck_type="risk",
                    severity=info.get("risk_level", "medium"),
                    affected_classes=[class_name],
                    suggested_resolution=f"为 {class_name} 制定详细重构计划",
                )
                self.bottlenecks.append(bottleneck)

        # 排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.bottlenecks.sort(key=lambda b: severity_order.get(b.severity, 3))

        print(f"识别出 {len(self.bottlenecks)} 个瓶颈点")

    def _create_mock_analysis(self):
        """创建模拟分析（当缺少数据时）"""
        # 模拟关键路径
        mock_paths = [
            CriticalPath(
                path_id="critical_meta_1",
                classes=["MetaParams", "Strategy", "Indicator"],
                total_complexity=12.0,
                estimated_duration=15,
                bottlenecks=["MetaParams: 核心类"],
                risk_level="critical",
                impact_scope="全项目影响",
            ),
            CriticalPath(
                path_id="high_lines_1",
                classes=["MetaLineSeries", "LineSeriesBase", "DataBase"],
                total_complexity=10.0,
                estimated_duration=12,
                bottlenecks=["MetaLineSeries: 核心类"],
                risk_level="high",
                impact_scope="模块级影响",
            ),
        ]
        self.critical_paths = mock_paths

    def _create_mock_bottlenecks(self):
        """创建模拟瓶颈（当缺少数据时）"""
        mock_bottlenecks = [
            Bottleneck(
                class_name="MetaParams",
                bottleneck_type="dependency",
                severity="critical",
                affected_classes=["Strategy", "Indicator", "BrokerBase"],
                suggested_resolution="优先重构MetaParams，采用参数描述符替代",
            ),
            Bottleneck(
                class_name="Cerebro",
                bottleneck_type="complexity",
                severity="high",
                affected_classes=["Cerebro"],
                suggested_resolution="分解Cerebro的复杂功能，分阶段重构",
            ),
        ]
        self.bottlenecks = mock_bottlenecks

    def generate_report(self) -> Dict[str, Any]:
        """生成分析报告"""
        report = {
            "analysis_time": datetime.now().isoformat(),
            "summary": {
                "total_critical_paths": len(self.critical_paths),
                "total_bottlenecks": len(self.bottlenecks),
                "critical_risk_paths": len(
                    [p for p in self.critical_paths if p.risk_level == "critical"]
                ),
                "high_risk_paths": len([p for p in self.critical_paths if p.risk_level == "high"]),
                "critical_bottlenecks": len(
                    [b for b in self.bottlenecks if b.severity == "critical"]
                ),
                "high_severity_bottlenecks": len(
                    [b for b in self.bottlenecks if b.severity == "high"]
                ),
            },
            "critical_paths": [
                {
                    "path_id": path.path_id,
                    "classes": path.classes,
                    "total_complexity": path.total_complexity,
                    "estimated_duration": path.estimated_duration,
                    "bottlenecks": path.bottlenecks,
                    "risk_level": path.risk_level,
                    "impact_scope": path.impact_scope,
                }
                for path in self.critical_paths[:15]  # Top 15
            ],
            "bottlenecks": [
                {
                    "class_name": bottleneck.class_name,
                    "bottleneck_type": bottleneck.bottleneck_type,
                    "severity": bottleneck.severity,
                    "affected_classes_count": len(bottleneck.affected_classes),
                    "suggested_resolution": bottleneck.suggested_resolution,
                }
                for bottleneck in self.bottlenecks[:10]  # Top 10
            ],
            "recommendations": self._generate_recommendations(),
        }

        return report

    def _generate_recommendations(self) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于关键路径的建议
        if len(self.critical_paths) > 5:
            recommendations.append("关键路径较多，建议制定并行执行计划")

        # 基于瓶颈的建议
        critical_bottlenecks = [b for b in self.bottlenecks if b.severity == "critical"]
        if critical_bottlenecks:
            recommendations.append(f"发现 {len(critical_bottlenecks)} 个关键瓶颈，建议优先处理")

        # 基于风险的建议
        high_risk_paths = [p for p in self.critical_paths if p.risk_level in ["critical", "high"]]
        if len(high_risk_paths) > 3:
            recommendations.append("高风险路径较多，建议增加测试覆盖")

        # 默认建议
        if not recommendations:
            recommendations = ["建立关键路径监控机制", "制定瓶颈应急预案", "定期评估重构进度"]

        return recommendations

    def save_report(self, report: Dict[str, Any]) -> str:
        """保存分析报告"""
        os.makedirs("analysis_results", exist_ok=True)
        filename = f"analysis_results/critical_path_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"关键路径分析报告已保存到: {filename}")
        return filename

    def print_summary(self, report: Dict[str, Any]):
        """打印分析摘要"""
        print("=" * 70)
        print("Backtrader 关键路径分析报告")
        print("=" * 70)

        summary = report["summary"]
        print(f"关键路径总数: {summary['total_critical_paths']}")
        print(f"瓶颈点总数: {summary['total_bottlenecks']}")
        print(f"关键风险路径: {summary['critical_risk_paths']}")
        print(f"高风险路径: {summary['high_risk_paths']}")
        print(f"关键瓶颈: {summary['critical_bottlenecks']}")
        print(f"高严重性瓶颈: {summary['high_severity_bottlenecks']}")

        print("\n🛤️ 最高风险关键路径 (Top 5):")
        print("-" * 60)
        print(f"{'路径ID':<20} {'类数':<6} {'风险级别':<10} {'预计天数':<8}")
        print("-" * 60)
        for path in report["critical_paths"][:5]:
            print(
                f"{path['path_id']:<20} {len(path['classes']):<6} "
                f"{path['risk_level']:<10} {path['estimated_duration']:<8}"
            )

        print("\n🔒 最严重瓶颈 (Top 5):")
        print("-" * 60)
        print(f"{'类名':<25} {'类型':<12} {'严重性':<8} {'影响类数':<8}")
        print("-" * 60)
        for bottleneck in report["bottlenecks"][:5]:
            print(
                f"{bottleneck['class_name']:<25} {bottleneck['bottleneck_type']:<12} "
                f"{bottleneck['severity']:<8} {bottleneck['affected_classes_count']:<8}"
            )

        print("\n💡 建议:")
        print("-" * 30)
        for rec in report["recommendations"]:
            print(f"• {rec}")


def main():
    """主函数"""
    try:
        analyzer = CriticalPathAnalyzer()

        print("开始关键路径分析...")
        analyzer.load_analysis_data()
        analyzer.analyze_critical_paths()
        analyzer.analyze_bottlenecks()

        report = analyzer.generate_report()
        analyzer.print_summary(report)
        analyzer.save_report(report)

        print("\nDay 5-7关键路径分析完成！")

    except Exception as e:
        print(f"关键路径分析时出错: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
