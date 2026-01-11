#!/usr/bin/env python3
"""
Backtrader Class Dependency Analyzer

Analyzes class dependencies in the backtrader project, generates dependency graphs,
and identifies critical paths and risk points.
"""

import ast
import json
import os
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class ClassInfo:
    """Class information."""

    name: str
    file_path: str
    line_number: int
    base_classes: List[str] = field(default_factory=list)
    metaclass: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    has_metaprogramming: bool = False
    metaprogramming_types: List[str] = field(default_factory=list)


@dataclass
class DependencyEdge:
    """Dependency edge."""

    source: str
    target: str
    edge_type: str  # 'inheritance', 'composition', 'import', 'metaclass'
    file_path: str
    line_number: int


@dataclass
class RiskAssessment:
    """Risk assessment."""

    class_name: str
    risk_level: str  # 'low', 'medium', 'high', 'critical'
    risk_factors: List[str]
    dependent_classes: int
    complexity_score: float


class ClassDependencyAnalyzer(ast.NodeVisitor):
    """Class dependency analyzer."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.classes: Dict[str, ClassInfo] = {}
        self.dependencies: List[DependencyEdge] = []
        self.imports: Dict[str, str] = {}  # alias -> full_name
        self.current_class: Optional[str] = None

        # Known metaclasses
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

    def visit_Import(self, node: ast.Import):
        """Process import statement."""
        for alias in node.names:
            name = alias.name
            as_name = alias.asname or name.split(".")[-1]
            self.imports[as_name] = name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Process from import statement."""
        module = node.module or ""
        for alias in node.names:
            name = alias.name
            as_name = alias.asname or name
            full_name = f"{module}.{name}" if module else name
            self.imports[as_name] = full_name
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definition."""
        class_name = node.name
        self.current_class = class_name

        # Parse base classes
        base_classes = []
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name:
                # Resolve imported base class
                resolved_name = self.imports.get(base_name, base_name)
                base_classes.append(resolved_name)

                # Add inheritance dependency
                self.dependencies.append(
                    DependencyEdge(
                        source=class_name,
                        target=base_name,
                        edge_type="inheritance",
                        file_path=self.file_path,
                        line_number=node.lineno,
                    )
                )

        # Parse metaclass
        metaclass = None
        if hasattr(node, "metaclass") and node.metaclass:
            metaclass = self._get_name(node.metaclass)
            if metaclass:
                self.dependencies.append(
                    DependencyEdge(
                        source=class_name,
                        target=metaclass,
                        edge_type="metaclass",
                        file_path=self.file_path,
                        line_number=node.lineno,
                    )
                )

        # Check metaprogramming usage
        has_metaprogramming = False
        metaprogramming_types = []

        if metaclass and metaclass in self.known_metaclasses:
            has_metaprogramming = True
            metaprogramming_types.append(f"metaclass:{metaclass}")

        for base in base_classes:
            if any(meta in base for meta in self.known_metaclasses):
                has_metaprogramming = True
                metaprogramming_types.append(f"inheritance:{base}")

        # Create class info
        class_info = ClassInfo(
            name=class_name,
            file_path=self.file_path,
            line_number=node.lineno,
            base_classes=base_classes,
            metaclass=metaclass,
            imports=list(self.imports.keys()),
            has_metaprogramming=has_metaprogramming,
            metaprogramming_types=metaprogramming_types,
        )

        # Analyze class body
        self._analyze_class_body(node, class_info)

        self.classes[class_name] = class_info
        self.generic_visit(node)
        self.current_class = None

    def _analyze_class_body(self, node: ast.ClassDef, class_info: ClassInfo):
        """Analyze class body."""
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                class_info.methods.append(item.name)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_info.attributes.append(target.id)

                        # Check special attributes
                        if target.id in ["params", "lines"]:
                            class_info.has_metaprogramming = True
                            class_info.metaprogramming_types.append(f"attribute:{target.id}")

    def visit_Call(self, node: ast.Call):
        """Visit function call."""
        if self.current_class:
            func_name = self._get_name(node.func)
            if func_name and "." in func_name:
                # Possibly a call to another class
                parts = func_name.split(".")
                if len(parts) >= 2:
                    target_class = parts[0]
                    if target_class in self.imports:
                        resolved_target = self.imports[target_class]
                        self.dependencies.append(
                            DependencyEdge(
                                source=self.current_class,
                                target=resolved_target,
                                edge_type="composition",
                                file_path=self.file_path,
                                line_number=node.lineno,
                            )
                        )

        self.generic_visit(node)

    def _get_name(self, node):
        """Get node name."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return None


class ProjectDependencyAnalyzer:
    """Project dependency analyzer."""

    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)
        self.all_classes: Dict[str, ClassInfo] = {}
        self.all_dependencies: List[DependencyEdge] = []
        self.dependency_graph = nx.DiGraph()
        self.inheritance_graph = nx.DiGraph()
        self.composition_graph = nx.DiGraph()
        self.risk_assessments: List[RiskAssessment] = []

    def analyze_project(self):
        """Analyze entire project."""
        print("Starting analysis of backtrader project class dependencies...")

        # Traverse Python files in project
        for root, dirs, files in os.walk(self.project_root):
            # Skip some directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in ["__pycache__", "build", "dist"]
            ]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_root)

                    # Only analyze files within backtrader package
                    if rel_path.startswith("backtrader" + os.sep) or file == "__init__.py":
                        try:
                            self.analyze_file(file_path, rel_path)
                        except Exception as e:
                            print(f"Error analyzing file {rel_path}: {e}")

        # Build graphs
        self.build_graphs()

        # Risk assessment
        self.assess_risks()

    def analyze_file(self, file_path: str, rel_path: str):
        """Analyze single file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            analyzer = ClassDependencyAnalyzer(rel_path)
            analyzer.visit(tree)

            # Collect results
            self.all_classes.update(analyzer.classes)
            self.all_dependencies.extend(analyzer.dependencies)

        except Exception as e:
            print(f"Cannot parse file {rel_path}: {e}")

    def build_graphs(self):
        """Build dependency graphs."""
        # Total dependency graph
        for dep in self.all_dependencies:
            self.dependency_graph.add_edge(
                dep.source,
                dep.target,
                edge_type=dep.edge_type,
                file_path=dep.file_path,
                line_number=dep.line_number,
            )

        # Inheritance graph
        for dep in self.all_dependencies:
            if dep.edge_type in ["inheritance", "metaclass"]:
                self.inheritance_graph.add_edge(dep.source, dep.target, edge_type=dep.edge_type)

        # Composition graph
        for dep in self.all_dependencies:
            if dep.edge_type == "composition":
                self.composition_graph.add_edge(dep.source, dep.target)

    def assess_risks(self):
        """Assess refactoring risks."""
        self.risk_assessments = []

        for class_name, class_info in self.all_classes.items():
            risk_factors = []
            risk_level = "low"
            complexity_score = 0.0

            # Calculate number of classes depending on this class
            dependent_classes = len(
                [dep for dep in self.all_dependencies if dep.target == class_name]
            )

            # Risk factor assessment
            if class_info.has_metaprogramming:
                risk_factors.append("Uses metaprogramming")
                complexity_score += 2.0

            if class_info.metaclass:
                risk_factors.append(f"Uses metaclass: {class_info.metaclass}")
                complexity_score += 3.0

            if len(class_info.base_classes) > 2:
                risk_factors.append("Multiple inheritance")
                complexity_score += 1.5

            if dependent_classes > 10:
                risk_factors.append(f"Depended by {dependent_classes} classes")
                complexity_score += 1.0

            if len(class_info.methods) > 20:
                risk_factors.append("Too many methods")
                complexity_score += 0.5

            # Check if on critical path
            if self.is_in_critical_path(class_name):
                risk_factors.append("On critical path")
                complexity_score += 2.0

            # Determine risk level
            if complexity_score >= 6.0:
                risk_level = "critical"
            elif complexity_score >= 4.0:
                risk_level = "high"
            elif complexity_score >= 2.0:
                risk_level = "medium"

            assessment = RiskAssessment(
                class_name=class_name,
                risk_level=risk_level,
                risk_factors=risk_factors,
                dependent_classes=dependent_classes,
                complexity_score=complexity_score,
            )

            self.risk_assessments.append(assessment)

        # Sort by risk level
        self.risk_assessments.sort(key=lambda x: x.complexity_score, reverse=True)

    def is_in_critical_path(self, class_name: str) -> bool:
        """Check if class is on critical path."""
        # Critical class list (core framework classes)
        critical_classes = {
            "Cerebro",
            "Strategy",
            "Indicator",
            "LineSeriesBase",
            "DataBase",
            "BrokerBase",
            "FeedBase",
            "MetaParams",
            "MetaLineSeries",
        }

        if class_name in critical_classes:
            return True

        # Check if inherits from critical class
        try:
            for critical in critical_classes:
                if nx.has_path(self.inheritance_graph, class_name, critical):
                    return True
                if nx.has_path(self.inheritance_graph, critical, class_name):
                    return True
        except:
            pass

        return False

    def find_inheritance_chains(self) -> Dict[str, List[str]]:
        """Find inheritance chains."""
        chains = {}

        for class_name in self.all_classes:
            if class_name not in chains:
                chain = self._get_inheritance_chain(class_name)
                if len(chain) > 1:
                    chains[class_name] = chain

        return chains

    def _get_inheritance_chain(self, class_name: str) -> List[str]:
        """Get inheritance chain for single class."""
        chain = [class_name]
        current = class_name

        while True:
            parents = [
                dep.target
                for dep in self.all_dependencies
                if dep.source == current and dep.edge_type == "inheritance"
            ]
            if not parents:
                break

            # Select first parent (simplified handling)
            parent = parents[0]
            if parent in chain:  # Avoid cycles
                break

            chain.append(parent)
            current = parent

        return chain

    def identify_critical_paths(self) -> List[List[str]]:
        """Identify critical paths."""
        critical_paths = []

        # Find core nodes
        core_nodes = ["Strategy", "Indicator", "Cerebro", "DataBase", "BrokerBase"]

        for core in core_nodes:
            if core in self.dependency_graph:
                # Find all paths to this core node
                for node in self.dependency_graph.nodes():
                    if node != core:
                        try:
                            if nx.has_path(self.dependency_graph, node, core):
                                path = nx.shortest_path(self.dependency_graph, node, core)
                                if len(path) > 2:  # Only focus on longer paths
                                    critical_paths.append(path)
                        except:
                            continue

        return critical_paths

    def generate_priority_matrix(self) -> Dict[str, Dict[str, Any]]:
        """Generate implementation priority matrix."""
        priority_matrix = {}

        # Group by risk level
        for assessment in self.risk_assessments:
            class_info = self.all_classes.get(assessment.class_name)
            if not class_info:
                continue

            priority_info = {
                "risk_level": assessment.risk_level,
                "complexity_score": assessment.complexity_score,
                "dependent_classes": assessment.dependent_classes,
                "metaprogramming_types": class_info.metaprogramming_types,
                "base_classes": class_info.base_classes,
                "file_path": class_info.file_path,
                "suggested_phase": self._suggest_refactor_phase(assessment, class_info),
                "prerequisites": self._find_prerequisites(class_info),
                "impact_scope": self._assess_impact_scope(assessment.class_name),
            }

            priority_matrix[assessment.class_name] = priority_info

        return priority_matrix

    def _suggest_refactor_phase(self, assessment: RiskAssessment, class_info: ClassInfo) -> str:
        """Suggest refactoring phase."""
        # Suggest phase based on metaprogramming type
        for mp_type in class_info.metaprogramming_types:
            if "MetaSingleton" in mp_type:
                return "Phase 2: Singleton refactoring"
            elif "MetaParams" in mp_type or "params" in mp_type:
                return "Phase 3: Parameter system refactoring"
            elif "MetaLineSeries" in mp_type or "lines" in mp_type:
                return "Phase 4: Lines system refactoring"

        # Based on risk level
        if assessment.risk_level == "critical":
            return "Phase 1: Urgent handling"
        elif assessment.risk_level == "high":
            return "Phase 2-3: High priority"
        else:
            return "Phase 4-5: Later processing"

    def _find_prerequisites(self, class_info: ClassInfo) -> List[str]:
        """Find refactoring prerequisites."""
        prerequisites = []

        # Base classes must be refactored first
        for base in class_info.base_classes:
            if any(meta in base for meta in ["Meta", "Base"]):
                prerequisites.append(f"Refactor base class: {base}")

        # Metaclass must be refactored first
        if class_info.metaclass:
            prerequisites.append(f"Refactor metaclass: {class_info.metaclass}")

        return prerequisites

    def _assess_impact_scope(self, class_name: str) -> str:
        """Assess impact scope."""
        dependent_count = len([dep for dep in self.all_dependencies if dep.target == class_name])

        if dependent_count >= 20:
            return "Project-wide impact"
        elif dependent_count >= 10:
            return "Module-level impact"
        elif dependent_count >= 5:
            return "Local impact"
        else:
            return "Minimal impact"

    def generate_report(self) -> Dict[str, Any]:
        """Generate analysis report."""
        inheritance_chains = self.find_inheritance_chains()
        critical_paths = self.identify_critical_paths()
        priority_matrix = self.generate_priority_matrix()

        report = {
            "analysis_time": datetime.now().isoformat(),
            "summary": {
                "total_classes": len(self.all_classes),
                "total_dependencies": len(self.all_dependencies),
                "inheritance_edges": len(
                    [d for d in self.all_dependencies if d.edge_type == "inheritance"]
                ),
                "composition_edges": len(
                    [d for d in self.all_dependencies if d.edge_type == "composition"]
                ),
                "metaclass_edges": len(
                    [d for d in self.all_dependencies if d.edge_type == "metaclass"]
                ),
                "classes_with_metaprogramming": len(
                    [c for c in self.all_classes.values() if c.has_metaprogramming]
                ),
                "critical_risk_classes": len(
                    [r for r in self.risk_assessments if r.risk_level == "critical"]
                ),
                "high_risk_classes": len(
                    [r for r in self.risk_assessments if r.risk_level == "high"]
                ),
            },
            "risk_assessments": [
                {
                    "class_name": r.class_name,
                    "risk_level": r.risk_level,
                    "complexity_score": r.complexity_score,
                    "dependent_classes": r.dependent_classes,
                    "risk_factors": r.risk_factors,
                }
                for r in self.risk_assessments[:20]  # Top 20
            ],
            "inheritance_chains": {k: v for k, v in inheritance_chains.items() if len(v) > 3},
            "critical_paths": critical_paths[:10],  # Top 10
            "priority_matrix": priority_matrix,
            "phase_distribution": self._get_phase_distribution(priority_matrix),
            "dependency_statistics": self._get_dependency_statistics(),
        }

        return report

    def _get_phase_distribution(self, priority_matrix: Dict) -> Dict[str, int]:
        """Get class distribution by phase."""
        distribution = defaultdict(int)
        for info in priority_matrix.values():
            distribution[info["suggested_phase"]] += 1
        return dict(distribution)

    def _get_dependency_statistics(self) -> Dict[str, Any]:
        """Get dependency statistics."""
        # In-degree statistics (being depended upon)
        in_degrees = defaultdict(int)
        out_degrees = defaultdict(int)

        for dep in self.all_dependencies:
            in_degrees[dep.target] += 1
            out_degrees[dep.source] += 1

        # Highest in-degree (most depended classes)
        top_depended = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:10]

        # Highest out-degree (classes depending on most others)
        top_depending = sorted(out_degrees.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "most_depended_classes": top_depended,
            "most_depending_classes": top_depending,
            "average_in_degree": sum(in_degrees.values()) / len(in_degrees) if in_degrees else 0,
            "average_out_degree": (
                sum(out_degrees.values()) / len(out_degrees) if out_degrees else 0
            ),
        }

    def save_report(self, report: Dict[str, Any]):
        """Save analysis report."""
        os.makedirs("analysis_results", exist_ok=True)
        filename = (
            f"analysis_results/dependency_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"Dependency analysis report saved to: {filename}")
        return filename

    def print_summary(self, report: Dict[str, Any]):
        """Print analysis summary."""
        print("=" * 70)
        print("Backtrader Class Dependency Analysis Report")
        print("=" * 70)

        summary = report["summary"]
        print(f"Total classes: {summary['total_classes']}")
        print(f"Total dependencies: {summary['total_dependencies']}")
        print(f"  - Inheritance: {summary['inheritance_edges']}")
        print(f"  - Composition: {summary['composition_edges']}")
        print(f"  - Metaclass: {summary['metaclass_edges']}")
        print(f"Classes using metaprogramming: {summary['classes_with_metaprogramming']}")
        print(f"Critical risk classes: {summary['critical_risk_classes']}")
        print(f"High risk classes: {summary['high_risk_classes']}")

        print("\n🚨 Highest Risk Classes (Top 10):")
        print("-" * 50)
        print(f"{'Class Name':<25} {'Risk Level':<10} {'Complexity':<8} {'Depended':<8}")
        print("-" * 50)
        for risk in report["risk_assessments"][:10]:
            print(
                f"{risk['class_name']:<25} {risk['risk_level']:<10} "
                f"{risk['complexity_score']:<8.1f} {risk['dependent_classes']:<8}"
            )

        print("\n📊 Phase Distribution:")
        print("-" * 30)
        for phase, count in report["phase_distribution"].items():
            print(f"{phase}: {count} classes")

        print("\n🔗 Most Depended Classes (Top 5):")
        print("-" * 30)
        for class_name, count in report["dependency_statistics"]["most_depended_classes"][:5]:
            print(f"{class_name}: {count} dependencies")


def main():
    """Main function."""
    print("Starting backtrader project dependency analysis...")

    analyzer = ProjectDependencyAnalyzer()
    analyzer.analyze_project()

    report = analyzer.generate_report()
    analyzer.print_summary(report)
    analyzer.save_report(report)

    print("\nDay 5-7 task completed!")


if __name__ == "__main__":
    # Check if networkx is installed
    try:
        import networkx
    except ImportError:
        print("Please install networkx: pip install networkx")
        sys.exit(1)

    main()
