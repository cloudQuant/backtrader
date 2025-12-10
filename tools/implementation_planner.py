#!/usr/bin/env python3
"""
Backtrader Implementation Priority Planner

基于依赖分析结果，制定详细的实施优先级和重构计划。
"""

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set, Tuple

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class RefactorTask:
    """重构任务"""

    task_id: str
    class_name: str
    task_type: str  # 'singleton', 'parameters', 'lines', 'cleanup'
    priority: int  # 1-5, 1最高
    estimated_days: int
    prerequisites: List[str] = field(default_factory=list)
    risk_level: str = "medium"
    complexity_score: float = 0.0
    impact_scope: str = "local"
    phase: str = "Phase 2"
    week: int = 3
    description: str = ""


@dataclass
class Phase:
    """实施阶段"""

    phase_id: str
    name: str
    description: str
    start_week: int
    end_week: int
    objectives: List[str]
    tasks: List[RefactorTask] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


class ImplementationPlanner:
    """实施规划器"""

    def __init__(self):
        self.tasks: List[RefactorTask] = []
        self.phases: List[Phase] = []
        self.timeline: Dict[int, List[RefactorTask]] = defaultdict(list)
        self.dependency_data: Dict[str, Any] = {}
        self.metaprogramming_data: Dict[str, Any] = {}

        # 预定义阶段
        self.setup_phases()

    def setup_phases(self):
        """设置预定义阶段"""
        self.phases = [
            Phase(
                phase_id="phase_1",
                name="Phase 1: 项目准备",
                description="建立测试环境和分析工具",
                start_week=1,
                end_week=2,
                objectives=["建立开发环境", "创建基准测试", "分析元编程使用"],
            ),
            Phase(
                phase_id="phase_2",
                name="Phase 2: Singleton模式重构",
                description="重构Store系统中的Singleton模式",
                start_week=3,
                end_week=4,
                objectives=["实现SingletonMixin基类", "重构所有Store类", "确保线程安全"],
                dependencies=["phase_1"],
            ),
            Phase(
                phase_id="phase_3",
                name="Phase 3: 参数系统重构",
                description="重构MetaParams系统",
                start_week=5,
                end_week=8,
                objectives=["实现ParameterDescriptor", "重构所有参数化类", "保持向后兼容"],
                dependencies=["phase_2"],
            ),
            Phase(
                phase_id="phase_4",
                name="Phase 4: Lines系统重构",
                description="重构MetaLineSeries系统",
                start_week=9,
                end_week=16,
                objectives=["实现LineBuffer和LineDescriptor", "重构所有LineSeries类", "优化性能"],
                dependencies=["phase_3"],
            ),
            Phase(
                phase_id="phase_5",
                name="Phase 5: 清理和优化",
                description="最终清理和性能优化",
                start_week=17,
                end_week=20,
                objectives=["清理剩余元编程", "性能优化", "文档更新"],
                dependencies=["phase_4"],
            ),
        ]

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

        # 加载元编程分析数据
        try:
            meta_files = [
                f
                for f in os.listdir("analysis_results")
                if f.startswith("metaprogramming_analysis_")
            ]
            if meta_files:
                latest_meta = sorted(meta_files)[-1]
                with open(f"analysis_results/{latest_meta}", encoding="utf-8") as f:
                    self.metaprogramming_data = json.load(f)
                print(f"已加载元编程分析数据: {latest_meta}")
        except Exception as e:
            print(f"无法加载元编程分析数据: {e}")

    def generate_tasks(self):
        """基于分析数据生成任务"""
        if not self.dependency_data:
            print("警告: 缺少依赖分析数据，使用默认任务")
            self._generate_default_tasks()
            return

        # 从优先级矩阵生成任务
        priority_matrix = self.dependency_data.get("priority_matrix", {})

        for class_name, info in priority_matrix.items():
            task = self._create_task_from_class_info(class_name, info)
            if task:
                self.tasks.append(task)

        # 按优先级和依赖关系排序
        self._sort_tasks_by_priority()

        # 分配到阶段和时间线
        self._assign_tasks_to_phases()

    def _create_task_from_class_info(self, class_name: str, info: Dict[str, Any]) -> RefactorTask:
        """根据类信息创建任务"""
        # 确定任务类型
        task_type = "cleanup"
        metaprogramming_types = info.get("metaprogramming_types", [])

        for mp_type in metaprogramming_types:
            if "MetaSingleton" in mp_type:
                task_type = "singleton"
                break
            elif "MetaParams" in mp_type or "params" in mp_type:
                task_type = "parameters"
                break
            elif "MetaLineSeries" in mp_type or "lines" in mp_type:
                task_type = "lines"
                break

        # 确定优先级
        risk_level = info.get("risk_level", "low")
        priority_map = {"critical": 1, "high": 2, "medium": 3, "low": 4}
        priority = priority_map.get(risk_level, 4)

        # 估算工作量
        estimated_days = self._estimate_workload(info)

        # 确定阶段和周
        phase, week = self._determine_phase_and_week(task_type, priority)

        task = RefactorTask(
            task_id=f"{task_type}_{class_name}_{priority}",
            class_name=class_name,
            task_type=task_type,
            priority=priority,
            estimated_days=estimated_days,
            prerequisites=info.get("prerequisites", []),
            risk_level=risk_level,
            complexity_score=info.get("complexity_score", 0.0),
            impact_scope=info.get("impact_scope", "local"),
            phase=phase,
            week=week,
            description=self._generate_task_description(class_name, task_type, info),
        )

        return task

    def _estimate_workload(self, info: Dict[str, Any]) -> int:
        """估算工作量（天）"""
        base_days = 1

        # 根据复杂度调整
        complexity = info.get("complexity_score", 0.0)
        if complexity >= 6.0:
            base_days = 5
        elif complexity >= 4.0:
            base_days = 3
        elif complexity >= 2.0:
            base_days = 2

        # 根据影响范围调整
        impact = info.get("impact_scope", "local")
        if impact == "全项目影响":
            base_days += 2
        elif impact == "模块级影响":
            base_days += 1

        # 根据依赖数量调整
        dependent_classes = info.get("dependent_classes", 0)
        if dependent_classes > 15:
            base_days += 2
        elif dependent_classes > 5:
            base_days += 1

        return min(base_days, 7)  # 最多7天

    def _determine_phase_and_week(self, task_type: str, priority: int) -> Tuple[str, int]:
        """确定任务的阶段和周"""
        type_phase_map = {
            "singleton": ("Phase 2: Singleton重构", 3),
            "parameters": ("Phase 3: 参数系统重构", 5),
            "lines": ("Phase 4: Lines系统重构", 9),
            "cleanup": ("Phase 5: 清理和优化", 17),
        }

        phase, base_week = type_phase_map.get(task_type, ("Phase 5: 清理和优化", 17))

        # 根据优先级微调周数
        week_offset = max(0, priority - 1)
        actual_week = base_week + week_offset

        return phase, actual_week

    def _generate_task_description(
        self, class_name: str, task_type: str, info: Dict[str, Any]
    ) -> str:
        """生成任务描述"""
        descriptions = {
            "singleton": f"重构 {class_name} 的Singleton模式，使用SingletonMixin替代MetaSingleton",
            "parameters": f"重构 {class_name} 的参数系统，使用ParameterDescriptor替代MetaParams",
            "lines": f"重构 {class_name} 的Lines系统，使用LineDescriptor替代MetaLineSeries",
            "cleanup": f"清理 {class_name} 中的剩余元编程代码",
        }

        base_desc = descriptions.get(task_type, f"重构 {class_name}")

        # 添加风险提示
        risk_level = info.get("risk_level", "low")
        if risk_level in ["critical", "high"]:
            base_desc += f" (⚠️ {risk_level.upper()} RISK)"

        return base_desc

    def _sort_tasks_by_priority(self):
        """按优先级排序任务"""
        # 首先按任务类型排序（遵循阶段顺序）
        type_order = {"singleton": 1, "parameters": 2, "lines": 3, "cleanup": 4}

        self.tasks.sort(
            key=lambda t: (
                type_order.get(t.task_type, 5),  # 任务类型
                t.priority,  # 优先级
                -t.complexity_score,  # 复杂度（降序）
                -len(t.prerequisites),  # 依赖数量（降序）
            )
        )

    def _assign_tasks_to_phases(self):
        """将任务分配到阶段"""
        for task in self.tasks:
            # 找到对应的阶段
            for phase in self.phases:
                if phase.name == task.phase:
                    phase.tasks.append(task)
                    break

            # 添加到时间线
            self.timeline[task.week].append(task)

    def _generate_default_tasks(self):
        """生成默认任务（当没有分析数据时）"""
        default_tasks = [
            # Singleton重构任务
            RefactorTask(
                task_id="singleton_ibstore_1",
                class_name="IBStore",
                task_type="singleton",
                priority=1,
                estimated_days=3,
                phase="Phase 2: Singleton重构",
                week=3,
                description="重构IBStore的Singleton模式",
            ),
            # 参数系统重构任务
            RefactorTask(
                task_id="parameters_strategy_2",
                class_name="Strategy",
                task_type="parameters",
                priority=2,
                estimated_days=5,
                phase="Phase 3: 参数系统重构",
                week=5,
                description="重构Strategy的参数系统",
            ),
            # Lines系统重构任务
            RefactorTask(
                task_id="lines_lineseries_2",
                class_name="LineSeries",
                task_type="lines",
                priority=2,
                estimated_days=7,
                phase="Phase 4: Lines系统重构",
                week=9,
                description="重构LineSeries的Lines系统",
            ),
        ]

        self.tasks.extend(default_tasks)
        self._assign_tasks_to_phases()

    def generate_timeline(self) -> Dict[str, Any]:
        """生成详细时间线"""
        timeline = {}

        for week_num in range(1, 21):  # 20周计划
            week_tasks = self.timeline.get(week_num, [])

            # 计算工作量
            total_days = sum(task.estimated_days for task in week_tasks)

            # 按优先级分组
            priority_groups = defaultdict(list)
            for task in week_tasks:
                priority_groups[task.priority].append(task)

            timeline[f"Week {week_num}"] = {
                "tasks": [
                    {
                        "task_id": task.task_id,
                        "class_name": task.class_name,
                        "task_type": task.task_type,
                        "priority": task.priority,
                        "estimated_days": task.estimated_days,
                        "risk_level": task.risk_level,
                        "description": task.description,
                    }
                    for task in week_tasks
                ],
                "total_tasks": len(week_tasks),
                "total_estimated_days": total_days,
                "workload_level": self._assess_workload_level(total_days),
                "priority_distribution": {
                    str(priority): len(tasks) for priority, tasks in priority_groups.items()
                },
            }

        return timeline

    def _assess_workload_level(self, total_days: int) -> str:
        """评估工作量级别"""
        if total_days == 0:
            return "idle"
        elif total_days <= 3:
            return "light"
        elif total_days <= 5:
            return "normal"
        elif total_days <= 7:
            return "heavy"
        else:
            return "overload"

    def identify_bottlenecks(self) -> List[Dict[str, Any]]:
        """识别潜在瓶颈"""
        bottlenecks = []

        # 工作量瓶颈
        for week_num, tasks in self.timeline.items():
            total_days = sum(task.estimated_days for task in tasks)
            if total_days > 7:
                bottlenecks.append(
                    {
                        "type": "workload",
                        "week": week_num,
                        "issue": f"工作量过重 ({total_days} 天)",
                        "suggestion": "考虑将部分任务延后或并行处理",
                    }
                )

        # 依赖瓶颈
        dependency_chains = self._analyze_dependency_chains()
        for chain in dependency_chains:
            if len(chain) > 4:
                bottlenecks.append(
                    {
                        "type": "dependency",
                        "chain": chain,
                        "issue": f"依赖链过长 ({len(chain)} 层)",
                        "suggestion": "考虑并行处理或重新安排顺序",
                    }
                )

        # 风险瓶颈
        high_risk_tasks = [task for task in self.tasks if task.risk_level in ["critical", "high"]]
        if len(high_risk_tasks) > 10:
            bottlenecks.append(
                {
                    "type": "risk",
                    "count": len(high_risk_tasks),
                    "issue": f"高风险任务过多 ({len(high_risk_tasks)} 个)",
                    "suggestion": "增加测试覆盖率和代码审查",
                }
            )

        return bottlenecks

    def _analyze_dependency_chains(self) -> List[List[str]]:
        """分析依赖链"""
        # 简化的依赖链分析
        chains = []
        processed = set()

        for task in self.tasks:
            if task.task_id not in processed:
                chain = self._build_dependency_chain(task, processed)
                if len(chain) > 1:
                    chains.append(chain)

        return chains

    def _build_dependency_chain(self, task: RefactorTask, processed: set) -> List[str]:
        """构建单个依赖链"""
        chain = [task.task_id]
        processed.add(task.task_id)

        # 查找依赖此任务的其他任务
        for other_task in self.tasks:
            if other_task.task_id not in processed and task.class_name in other_task.prerequisites:
                sub_chain = self._build_dependency_chain(other_task, processed)
                chain.extend(sub_chain)

        return chain

    def optimize_timeline(self) -> Dict[str, Any]:
        """优化时间线"""
        optimizations = []

        # 重新分配过重的周 - 先收集需要移动的任务
        tasks_to_move = []
        for week_num, tasks in list(self.timeline.items()):  # 使用list()避免迭代时修改
            total_days = sum(task.estimated_days for task in tasks)
            if total_days > 7:
                # 移动低优先级任务到后续周
                low_priority_tasks = [t for t in tasks if t.priority >= 3]
                for task in low_priority_tasks[: total_days - 7]:
                    # 找到下一个空闲周
                    next_week = self._find_next_available_week(week_num)
                    if next_week:
                        tasks_to_move.append((task, week_num, next_week))

        # 执行任务移动
        for task, from_week, to_week in tasks_to_move:
            self.timeline[from_week].remove(task)
            if to_week not in self.timeline:
                self.timeline[to_week] = []
            self.timeline[to_week].append(task)
            task.week = to_week
            optimizations.append(f"移动任务 {task.task_id} 从第{from_week}周到第{to_week}周")

        return {"optimizations": optimizations}

    def _find_next_available_week(self, start_week: int) -> int:
        """找到下一个可用周"""
        for week in range(start_week + 1, 21):
            current_days = sum(task.estimated_days for task in self.timeline.get(week, []))
            if current_days < 5:
                return week
        return None

    def generate_implementation_plan(self) -> Dict[str, Any]:
        """生成完整实施计划"""
        # 加载数据
        self.load_analysis_data()

        # 生成任务
        self.generate_tasks()

        # 生成时间线
        timeline = self.generate_timeline()

        # 识别瓶颈
        bottlenecks = self.identify_bottlenecks()

        # 优化时间线
        optimization_results = self.optimize_timeline()

        # 重新生成优化后的时间线
        optimized_timeline = self.generate_timeline()

        plan = {
            "plan_generation_time": datetime.now().isoformat(),
            "summary": {
                "total_tasks": len(self.tasks),
                "total_phases": len(self.phases),
                "estimated_duration_weeks": 20,
                "high_priority_tasks": len([t for t in self.tasks if t.priority <= 2]),
                "critical_risk_tasks": len([t for t in self.tasks if t.risk_level == "critical"]),
            },
            "phases": [
                {
                    "phase_id": phase.phase_id,
                    "name": phase.name,
                    "description": phase.description,
                    "start_week": phase.start_week,
                    "end_week": phase.end_week,
                    "objectives": phase.objectives,
                    "task_count": len(phase.tasks),
                    "total_estimated_days": sum(task.estimated_days for task in phase.tasks),
                }
                for phase in self.phases
            ],
            "task_summary": {
                "by_type": self._get_task_distribution_by_type(),
                "by_priority": self._get_task_distribution_by_priority(),
                "by_risk": self._get_task_distribution_by_risk(),
            },
            "timeline": optimized_timeline,
            "bottlenecks": bottlenecks,
            "optimization_results": optimization_results,
            "recommendations": self._generate_recommendations(),
        }

        return plan

    def _get_task_distribution_by_type(self) -> Dict[str, int]:
        """按任务类型分布"""
        distribution = defaultdict(int)
        for task in self.tasks:
            distribution[task.task_type] += 1
        return dict(distribution)

    def _get_task_distribution_by_priority(self) -> Dict[str, int]:
        """按优先级分布"""
        distribution = defaultdict(int)
        for task in self.tasks:
            distribution[f"Priority {task.priority}"] += 1
        return dict(distribution)

    def _get_task_distribution_by_risk(self) -> Dict[str, int]:
        """按风险级别分布"""
        distribution = defaultdict(int)
        for task in self.tasks:
            distribution[task.risk_level] += 1
        return dict(distribution)

    def _generate_recommendations(self) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于任务分析的建议
        high_risk_tasks = [t for t in self.tasks if t.risk_level in ["critical", "high"]]
        if len(high_risk_tasks) > len(self.tasks) * 0.3:
            recommendations.append("高风险任务占比过高，建议增加预研和测试时间")

        # 基于工作量的建议
        total_estimated_days = sum(task.estimated_days for task in self.tasks)
        if total_estimated_days > 100:
            recommendations.append("总工作量较大，建议考虑团队扩容或延长时间线")

        # 基于依赖的建议
        tasks_with_deps = [t for t in self.tasks if t.prerequisites]
        if len(tasks_with_deps) > len(self.tasks) * 0.5:
            recommendations.append("任务间依赖较多，建议仔细规划执行顺序")

        # 默认建议
        if not recommendations:
            recommendations = [
                "定期运行回归测试确保功能不受影响",
                "每个阶段结束后进行代码审查",
                "保持与社区的沟通，及时处理兼容性问题",
            ]

        return recommendations

    def save_plan(self, plan: Dict[str, Any]) -> str:
        """保存实施计划"""
        os.makedirs("planning_results", exist_ok=True)
        filename = (
            f"planning_results/implementation_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        print(f"实施计划已保存到: {filename}")
        return filename

    def print_plan_summary(self, plan: Dict[str, Any]):
        """打印计划摘要"""
        print("=" * 70)
        print("Backtrader 去除元编程实施计划")
        print("=" * 70)

        summary = plan["summary"]
        print(f"总任务数: {summary['total_tasks']}")
        print(f"预计时长: {summary['estimated_duration_weeks']} 周")
        print(f"高优先级任务: {summary['high_priority_tasks']}")
        print(f"关键风险任务: {summary['critical_risk_tasks']}")

        print("\n📊 任务分布:")
        print("-" * 30)
        for task_type, count in plan["task_summary"]["by_type"].items():
            print(f"{task_type}: {count} 个任务")

        print("\n📅 阶段概览:")
        print("-" * 50)
        print(f"{'阶段':<25} {'周期':<10} {'任务数':<8} {'预计天数':<8}")
        print("-" * 50)
        for phase in plan["phases"]:
            print(
                f"{phase['name']:<25} {phase['start_week']}-{phase['end_week']:<8} "
                f"{phase['task_count']:<8} {phase['total_estimated_days']:<8}"
            )

        if plan["bottlenecks"]:
            print("\n⚠️ 潜在瓶颈:")
            print("-" * 30)
            for bottleneck in plan["bottlenecks"][:3]:
                print(f"- {bottleneck['issue']}")

        print("\n💡 建议:")
        print("-" * 30)
        for rec in plan["recommendations"][:3]:
            print(f"- {rec}")


def main():
    """主函数"""
    try:
        planner = ImplementationPlanner()

        print("开始生成实施计划...")
        plan = planner.generate_implementation_plan()

        planner.print_plan_summary(plan)
        planner.save_plan(plan)

        print("\nDay 5-7实施规划完成！")

    except Exception as e:
        print(f"生成实施计划时出错: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
