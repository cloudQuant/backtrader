"""Prove the cleanup leaves formulas, numeric operators and independent oracles intact."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True)
parser.add_argument("--tree", required=True)
args = parser.parse_args()
evidence = Path(__file__).resolve().parent


def read(revision, path):
    return subprocess.check_output(["git", "show", revision + ":" + path])


def parsed(revision, path):
    return ast.parse(read(revision, path))


unchanged = {}
paths = ["backtrader/research/alpha101/alpha%03d.py" % number for number in range(1, 102)]
paths += [
    "backtrader/research/alpha101/_helpers.py",
    "backtrader/research/inputs.py",
    "backtrader/research/strict.py",
    "backtrader/research/fincore_adapter.py",
    "backtrader/research/factor_report.py",
]
for directory in ("tests/test_utils", "tests/fixtures/research"):
    paths.extend(
        subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", args.base, directory], text=True
        ).splitlines()
    )
for path in paths:
    baseline, current = read(args.base, path), read(args.tree, path)
    assert baseline == current, path
    unchanged[path] = hashlib.sha256(current).hexdigest()

aliases = {"Rank", "Scale", "RollingStdDev", "Corr", "Cov", "ElementwiseMin", "ElementwiseMax"}


def operator_ast(revision):
    tree = parsed(revision, "backtrader/research/operators.py")
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in aliases | {"__all__"}
                for target in node.targets
            )
        )
    ]
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "_OperatorIndicator":
            node.body = [
                method
                for method in node.body
                if not isinstance(method, ast.FunctionDef) or method.name != "_set_minperiod"
            ]
    return ast.dump(tree)


assert operator_ast(args.base) == operator_ast(args.tree)
adapter_path = "backtrader/research/factor_indicator.py"
adapters = []
for revision in (args.base, args.tree):
    (adapter,) = [
        node
        for node in parsed(revision, adapter_path).body
        if isinstance(node, ast.ClassDef) and node.name == "_FeedInputLine"
    ]
    adapters.append(ast.dump(adapter))
assert adapters[0] == adapters[1]

reference_path = "tests/unit/test_factor_research_representatives.py"
reference_trees = []
for revision in (args.base, args.tree):
    tree = parsed(revision, reference_path)
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.FunctionDef) and node.name == "_node_matrix")
    ]
    reference_trees.append(ast.dump(tree))
assert reference_trees[0] == reference_trees[1]

test_functions = {}
for path, excluded in (
    (
        "tests/unit/test_alpha101_native_l0.py",
        {
            "test_native_registry_is_read_only_and_separates_formula_from_code_identity",
            "test_native_registry_is_read_only_and_matches_independent_declarations",
        },
    ),
    (
        "tests/unit/test_alpha101_native_promotion.py",
        {
            "test_metadata_decorator_is_immutable_and_has_no_registry_side_effect",
            "test_metadata_decorator_canonicalizes_class_attrs_without_registry_side_effect",
            "test_promotion_registry_and_identities_match_the_twenty_reviewed_recipes",
            "test_promotion_registry_and_declarations_match_the_twenty_reviewed_recipes",
        },
    ),
):
    versions = []
    for revision in (args.base, args.tree):
        versions.append(
            {
                node.name: ast.dump(node)
                for node in parsed(revision, path).body
                if isinstance(node, ast.FunctionDef) and node.name not in excluded
            }
        )
    assert versions[0] == versions[1], path
    test_functions[path] = sorted(versions[1])

record = {
    "status": "PASS",
    "baseline": args.base,
    "candidate_tree": args.tree,
    "byte_identical_files": unchanged,
    "formula_file_count": 101,
    "operator_ast_unchanged_except_dead_method_aliases_and_exports": True,
    "feed_input_native_adapter_ast_unchanged": True,
    "representative_test_ast_unchanged_except_real_node_observer": True,
    "unchanged_l0_and_promotion_numerical_helpers_and_test_functions": test_functions,
}
(evidence / "preservation.json").write_text(json.dumps(record, indent=2) + "\n")
print("PASS: 101 formula files, numeric operator AST and independent oracle inputs preserved")
