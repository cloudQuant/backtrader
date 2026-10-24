#!/usr/bin/env python
"""Isolated, public-source slots prototypes for three Backtrader value classes.

This tool never imports or mutates the production classes. It parses their
public source definitions and recompiles independent class copies in child
processes, injecting only __slots__. Child processes run sequentially.
"""
from __future__ import annotations

import argparse
import ast
import collections
import copy
import datetime
import gc
import hashlib
import itertools
import json
import os
import platform
import subprocess
import sys
import time
import tracemalloc
import weakref
from pathlib import Path
from typing import Any

import psutil

CLASS_PATHS = {
    "OrderExecutionBit": "backtrader/order.py",
    "OrderData": "backtrader/order.py",
    "Position": "backtrader/position.py",
}
PROPERTY_BACKING_MAP = {
    "OrderData": {"plimit": "_plimit"},
}
MODE_NAMES = ("baseline", "strict", "hybrid")


def _source_metadata(repo: Path) -> dict[str, Any]:
    by_path: dict[str, str] = {}
    classes: dict[str, dict[str, str]] = {}
    for class_name, relative in CLASS_PATHS.items():
        if relative not in by_path:
            by_path[relative] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
        classes[class_name] = {"path": relative, "sha256": by_path[relative]}
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"git_head": head, "class_sources": classes, "unique_source_hashes": by_path}


def _class_node(repo: Path, class_name: str) -> ast.ClassDef:
    module_path = repo / CLASS_PATHS[class_name]
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one top-level {class_name} in {module_path}; got {len(matches)}")
    node = matches[0]
    if node.bases:
        raise RuntimeError(f"Refusing to prototype inherited class {class_name}: explicit bases found")
    return node


def _target_fields(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        result: list[str] = []
        for item in target.elts:
            result.extend(_target_fields(item))
        return result
    return []


class _WriteCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fields: set[str] = set()
        self.dynamic_writes: list[str] = []
        self.special_accesses: list[str] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.fields.update(_target_fields(target))
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.fields.update(_target_fields(node.target))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.fields.update(_target_fields(node.target))
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.fields.update(_target_fields(node.target))
        self.visit(node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.fields.update(_target_fields(target))

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "setattr" and node.args:
            if isinstance(node.args[0], ast.Name) and node.args[0].id == "self":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    self.fields.add(node.args[1].value)
                else:
                    self.dynamic_writes.append(f"line {node.lineno}: setattr(self, <dynamic-name>, ...)")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr in {"__dict__", "__slots__"}:
            self.special_accesses.append(f"line {node.lineno}: self.{node.attr}")
        self.generic_visit(node)


def _collect_fields(node: ast.ClassDef, class_name: str) -> dict[str, Any]:
    all_writes = _WriteCollector()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_writes.visit(item)

    property_setters: dict[str, str] = {}
    for item in node.body:
        if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Call):
            continue
        if not (isinstance(item.value.func, ast.Name) and item.value.func.id == "property"):
            continue
        if len(item.value.args) < 2 or not isinstance(item.value.args[1], ast.Name):
            continue
        for target in item.targets:
            if isinstance(target, ast.Name):
                property_setters[target.id] = item.value.args[1].id

    property_map = PROPERTY_BACKING_MAP.get(class_name, {})
    resolved: set[str] = set(all_writes.fields)
    audited_mappings: dict[str, dict[str, str]] = {}
    for prop_name, backing_name in property_map.items():
        if prop_name not in property_setters:
            raise RuntimeError(f"Configured property {class_name}.{prop_name} is not declared with property(...)" )
        setter_name = property_setters[prop_name]
        setter = next((item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == setter_name), None)
        if setter is None:
            raise RuntimeError(f"Configured property setter {class_name}.{setter_name} is missing")
        setter_collector = _WriteCollector()
        setter_collector.visit(setter)
        if backing_name not in setter_collector.fields:
            raise RuntimeError(f"Property mapping {class_name}.{prop_name}->{backing_name} is not confirmed by setter source")
        resolved.discard(prop_name)
        resolved.add(backing_name)
        audited_mappings[prop_name] = {"setter": setter_name, "backing_field": backing_name}

    for prop_name, setter_name in property_setters.items():
        if prop_name in all_writes.fields and prop_name not in property_map:
            raise RuntimeError(f"Unmapped property assignment in {class_name}: {prop_name} via {setter_name}")

    return {
        "raw_self_write_fields": sorted(all_writes.fields),
        "property_setters": property_setters,
        "property_write_mappings_manually_confirmed": audited_mappings,
        "slot_fields": sorted(resolved),
        "dynamic_self_writes": all_writes.dynamic_writes,
        "self_dict_or_slots_accesses": all_writes.special_accesses,
        "write_inventory_complete_for_class_source": not all_writes.dynamic_writes,
    }


def _with_slots(node: ast.ClassDef, fields: list[str], mode: str) -> ast.ClassDef:
    cloned = copy.deepcopy(node)
    assert isinstance(cloned, ast.ClassDef)
    slot_entries = list(fields)
    if mode == "hybrid":
        slot_entries.append("__dict__")
    slot_entries.append("__weakref__")
    slots_node = ast.Assign(
        targets=[ast.Name(id="__slots__", ctx=ast.Store())],
        value=ast.Tuple(elts=[ast.Constant(value=item) for item in slot_entries], ctx=ast.Load()),
    )
    # Keep the original class docstring in its required first position.
    insert_at = 1 if cloned.body and isinstance(cloned.body[0], ast.Expr) and isinstance(cloned.body[0].value, ast.Constant) and isinstance(cloned.body[0].value.value, str) else 0
    cloned.body.insert(insert_at, slots_node)
    return ast.fix_missing_locations(cloned)


def _load_class(repo: Path, class_name: str, mode: str, audit: dict[str, Any]) -> type:
    order_classes: list[ast.ClassDef] = []
    namespace: dict[str, Any] = {
        "collections": collections,
        "datetime": datetime,
        "itertools": itertools,
        "copy": copy.copy,
    }
    names = ["OrderExecutionBit"] if class_name == "OrderExecutionBit" else (["OrderExecutionBit", "OrderData"] if class_name == "OrderData" else ["Position"])
    for name in names:
        node = _class_node(repo, name)
        if mode != "baseline":
            node = _with_slots(node, audit[name]["slot_fields"], mode)
        order_classes.append(node)
    module = ast.Module(body=order_classes, type_ignores=[])
    code = compile(ast.fix_missing_locations(module), filename=f"<isolated-{mode}-classes>", mode="exec")
    exec(code, namespace, namespace)
    if class_name == "Position":
        namespace["Position"] = namespace[class_name]
    return namespace[class_name]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, collections.deque):
        return {"type": "collections.deque", "length": len(value)}
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _worker(repo: Path, class_name: str, mode: str, count: int, warmup_count: int, run_info: dict[str, Any]) -> dict[str, Any]:
    audit = {name: _collect_fields(_class_node(repo, name), name) for name in ("OrderExecutionBit", "OrderData", "Position")}
    cls = _load_class(repo, class_name, mode, audit)
    warm = [cls() for _ in range(warmup_count)]
    del warm
    gc.collect()

    process = psutil.Process(os.getpid())
    rss_before = process.memory_info().rss
    tracemalloc.start()
    traced_start, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    started = time.perf_counter()
    objects = [cls() for _ in range(count)]
    elapsed = time.perf_counter() - started
    traced_current, traced_peak = tracemalloc.get_traced_memory()
    retained_bytes = traced_current - traced_start
    tracemalloc.stop()
    rss_after = process.memory_info().rss

    fields = audit[class_name]["slot_fields"]
    sample_indices = sorted({0, count // 2, count - 1})
    field_samples = [
        {"index": idx, "values": {field: _json_value(getattr(objects[idx], field)) for field in fields}}
        for idx in sample_indices
    ]
    weakref_ok = weakref.ref(objects[sample_indices[0]])() is objects[sample_indices[0]]
    if not weakref_ok:
        raise AssertionError(f"Weak references do not work for {class_name}/{mode}")

    # Shell and dict sizes are deliberately sampled only after RSS/tracemalloc.
    shell = objects[sample_indices[0]]
    shell_bytes = sys.getsizeof(shell)
    try:
        instance_dict = shell.__dict__
        dict_present = True
        dict_bytes = sys.getsizeof(instance_dict)
        dict_len_before_extension = len(instance_dict)
        dict_keys_before_extension = sorted(instance_dict)
    except AttributeError:
        dict_present = False
        dict_bytes = None
        dict_len_before_extension = None
        dict_keys_before_extension = None

    extension_obj = objects[sample_indices[-1]]
    extension_attr = "__slots_probe_extension__"
    try:
        setattr(extension_obj, extension_attr, "probe")
        extension_write = "accepted"
        extension_readback = getattr(extension_obj, extension_attr) == "probe"
    except AttributeError:
        extension_write = "rejected"
        extension_readback = False

    deque_payload: dict[str, Any] | None = None
    if class_name == "OrderData":
        payload_target = objects[0]
        if not isinstance(payload_target.exbits, collections.deque):
            raise AssertionError(f"OrderData.exbits lost deque payload in {mode}")
        payload_target.add(dt=1.0, size=1, price=10.0)
        payload_target.markpending()
        pending = payload_target.getpending()
        deque_payload = {
            "attribute_type": type(payload_target.exbits).__name__,
            "payload_length": len(payload_target.exbits),
            "pending_length": len(pending),
            "payload_bit_type": type(payload_target.exbits[0]).__name__ if payload_target.exbits else None,
            "payload_values": {
                "dt": _json_value(payload_target.exbits[0].dt),
                "size": _json_value(payload_target.exbits[0].size),
                "price": _json_value(payload_target.exbits[0].price),
            } if payload_target.exbits else None,
            "preserved": bool(
                type(payload_target.exbits) is collections.deque
                and len(payload_target.exbits) == 1
                and len(pending) == 1
                and type(payload_target.exbits[0]).__name__ == "OrderExecutionBit"
            ),
        }
        if not deque_payload["preserved"]:
            raise AssertionError(f"OrderData deque execution payload contract failed in {mode}")

    return {
        "class": class_name,
        "mode": mode,
        "pid": os.getpid(),
        "count": count,
        "warmup_count": warmup_count,
        "constructor_args": [],
        "construction_seconds_tracemalloc_enabled": elapsed,
        "construction_time_is_performance_gate": False,
        "tracemalloc_retained_bytes": retained_bytes,
        "tracemalloc_peak_bytes": traced_peak - traced_start,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": rss_after - rss_before,
        "rss_before_mib": rss_before / (1024 * 1024),
        "rss_after_mib": rss_after / (1024 * 1024),
        "rss_delta_mib": (rss_after - rss_before) / (1024 * 1024),
        "sample_indices": sample_indices,
        "sampled_field_values": field_samples,
        "weakref_works": weakref_ok,
        "sampled_shallow_shell_bytes_after_sampling": shell_bytes,
        "sampled_dict_present_after_sampling": dict_present,
        "sampled_dict_bytes_after_sampling": dict_bytes,
        "sampled_dict_len_before_extension_probe": dict_len_before_extension,
        "sampled_dict_keys_before_extension_probe": dict_keys_before_extension,
        "extension_attribute_write": extension_write,
        "extension_attribute_readback": extension_readback,
        "orderdata_deque_payload": deque_payload,
        "run_info": run_info,
    }


def _run_parent(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_info = _source_metadata(repo)
    audit = {name: _collect_fields(_class_node(repo, name), name) for name in CLASS_PATHS}
    expected_extension = {"baseline": "accepted", "strict": "rejected", "hybrid": "accepted"}
    results: list[dict[str, Any]] = []
    execution_order: list[dict[str, Any]] = []

    for class_name in CLASS_PATHS:
        for prototype in ("strict", "hybrid"):
            for pair_round in range(1, args.repeats + 1):
                order = ["baseline", prototype] if pair_round % 2 else [prototype, "baseline"]
                pair_results: dict[str, dict[str, Any]] = {}
                for mode in order:
                    command = [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--repo", str(repo),
                        "--class", class_name,
                        "--mode", mode,
                        "--count", str(args.count),
                        "--warmup", str(args.warmup),
                        "--run-info", json.dumps(run_info, separators=(",", ":")),
                    ]
                    completed = subprocess.run(command, capture_output=True, text=True)
                    if completed.returncode:
                        raise RuntimeError(
                            f"Child failed for {class_name}/{mode}/round-{pair_round} "
                            f"(exit {completed.returncode}):\n{completed.stderr}\n{completed.stdout}"
                        )
                    worker_result = json.loads(completed.stdout)
                    worker_result["paired_prototype"] = prototype
                    worker_result["pair_round"] = pair_round
                    pair_results[mode] = worker_result
                    results.append(worker_result)
                    execution_order.append({"class": class_name, "pair": prototype, "round": pair_round, "mode": mode, "pid": worker_result["pid"]})
                baseline = pair_results["baseline"]
                candidate = pair_results[prototype]
                if baseline["sampled_field_values"] != candidate["sampled_field_values"]:
                    raise AssertionError(f"Sampled constructor fields differ: {class_name}/{prototype}/round-{pair_round}")
                if baseline["weakref_works"] is not True or candidate["weakref_works"] is not True:
                    raise AssertionError(f"Weakref parity failed: {class_name}/{prototype}/round-{pair_round}")
                if baseline["extension_attribute_write"] != expected_extension["baseline"]:
                    raise AssertionError(f"Baseline extension attribute behavior unexpected for {class_name}")
                if candidate["extension_attribute_write"] != expected_extension[prototype]:
                    raise AssertionError(f"Extension attribute behavior unexpected for {class_name}/{prototype}")
                if class_name == "OrderData" and baseline["orderdata_deque_payload"] != candidate["orderdata_deque_payload"]:
                    raise AssertionError(f"OrderData deque payload differs for {prototype}/round-{pair_round}")

    if any(info["dynamic_self_writes"] for info in audit.values()):
        raise AssertionError("Dynamic self attribute writes need manual review before prototyping")

    report = {
        "schema_version": 1,
        "title": "Isolated Backtrader object slots diagnostic",
        "repo": str(repo),
        "output_directory": str(output),
        "metadata": {
            "git_head": run_info["git_head"],
            "interpreter": sys.version,
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "source_hashes_by_class": run_info["class_sources"],
            "unique_source_hashes": run_info["unique_source_hashes"],
        },
        "design": {
            "count_per_process": args.count,
            "warmup_objects_per_process": args.warmup,
            "paired_rounds_per_class_and_prototype": args.repeats,
            "modes": list(MODE_NAMES),
            "process_isolation": "one fresh subprocess per class/mode/pair-round; executed sequentially",
            "memory_cap": "not applied; the available command runner exposes no process memory-limit control",
            "tracemalloc_and_rss_sampled_before_any_instance___dict__access": True,
            "shallow_shell_and_dict_sizes_sampled_after_memory_measurement": True,
            "constructor_call": "cls() with all source-defined defaults",
            "copy_serialization_formal_acceptance": "NOT_PERFORMED; outside this diagnostic scope",
            "production_source_modified": False,
        },
        "field_audit": audit,
        "field_counts": {
            name: {
                "regular_slot_fields": len(audit[name]["slot_fields"]),
                "strict_slot_entries_including_weakref": len(audit[name]["slot_fields"]) + 1,
                "hybrid_slot_entries_including_dict_and_weakref": len(audit[name]["slot_fields"]) + 2,
            }
            for name in CLASS_PATHS
        },
        "manual_risk_notes": [
            "Strict slots intentionally reject undeclared extension attributes; this is a layout experiment, not public compatibility acceptance.",
            "Hybrid slots retain an instance __dict__ for arbitrary extension attributes; fixed fields occupy slots and therefore do not appear in vars(instance).",
            "The write inventory covers assignments through self inside each selected class source. External callers, monkey patches, subclasses, and runtime integrations may write additional attributes and were not exhaustively scanned.",
            "Copy, pickle, deepcopy, subclassing, framework integration, GC graph behavior, and production order lifecycle are not formally tested here.",
            "OrderData.plimit assignment is manually mapped to its backing _plimit slot; the source property setter was checked to write _plimit.",
            "Three per-class source hash entries are recorded, but the target classes live in two unique files: backtrader/order.py (two classes) and backtrader/position.py (one class).",
        ],
        "execution_order": execution_order,
        "results": results,
        "result_checks": {
            "all_sampled_fields_match_within_each_pair": True,
            "all_weakrefs_work": all(row["weakref_works"] for row in results),
            "all_orderdata_deque_payloads_preserved": all(
                row["orderdata_deque_payload"]["preserved"]
                for row in results if row["class"] == "OrderData"
            ),
            "strict_extension_attributes_rejected": all(
                row["extension_attribute_write"] == "rejected"
                for row in results if row["mode"] == "strict"
            ),
            "hybrid_extension_attributes_accepted": all(
                row["extension_attribute_write"] == "accepted"
                for row in results if row["mode"] == "hybrid"
            ),
            "hybrid_fixed_fields_stored_outside_dict": all(
                row["sampled_dict_len_before_extension_probe"] == 0
                for row in results if row["mode"] == "hybrid"
            ),
        },
        "status": "DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE",
    }
    report_path = output / "results.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report_path": str(report_path), "script_path": str(Path(__file__).resolve()), "field_counts": report["field_counts"], "status": report["status"], "process_runs": len(results)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path("/Users/yunjinqi/Documents/new_projects/backtrader"))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--class", dest="class_name", choices=tuple(CLASS_PATHS))
    parser.add_argument("--mode", choices=MODE_NAMES)
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--warmup", type=int, default=128)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--run-info", default="{}")
    args = parser.parse_args()

    if args.worker:
        if not args.class_name or not args.mode:
            parser.error("worker mode requires --class and --mode")
        result = _worker(args.repo.resolve(), args.class_name, args.mode, args.count, args.warmup, json.loads(args.run_info))
        print(json.dumps(result, separators=(",", ":")))
        return 0

    if args.count != 100_000 or args.warmup != 128 or args.repeats != 3:
        parser.error("formal diagnostic profile is fixed at count=100000, warmup=128, repeats=3")
    summary = _run_parent(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
