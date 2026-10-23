"""Strict native/build operator-graph pairing contracts."""

from __future__ import annotations

from array import array
import copy
import json
from types import SimpleNamespace

import pytest

from backtrader.research.alpha101 import get_alpha
from backtrader.research import operators
from backtrader.research.operators import (
    CrossSectionalScale,
    IndNeutralize,
    Multiply,
    Subtract,
)
from tests.integration.test_alpha101_native_matrix import (
    BUILD_PAIR_EVIDENCE_ENV,
    _write_pair_evidence,
)
from tests.test_utils.alpha101_native_harness import make_positive_fixture, run_native_batch
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs


@pytest.fixture
def alpha003_pair():
    frames = make_positive_fixture(320)
    native = run_native_batch(
        frames,
        (3,),
        runonce=False,
        factor_mode="native",
        alpha_classes={3: get_alpha(3)},
    )
    build = run_native_batch(
        frames,
        (3,),
        runonce=False,
        factor_mode="build",
        alpha_classes={3: get_alpha(3)},
    )
    return native.factor_instances["alpha3"], build.factor_instances["alpha3"]


def test_alpha003_native_build_graph_matches_every_node(alpha003_pair):
    native, build = alpha003_pair
    report = compare_factor_graphs(native, build, 3)

    assert report["equal"], report["failures"]
    assert report["node_count_left"] == report["node_count_right"] == 14
    assert report["matched_node_count"] == 14
    assert report["node_value_cells"] == report["node_reason_cells"] == 24 * 320
    assert report["assets"] == ["asset-%d" % index for index in range(6)]


@pytest.mark.parametrize("damage", ("value", "reason", "asset", "duplicate", "empty", "marker"))
def test_alpha003_graph_pair_rejects_corruption(alpha003_pair, damage):
    native, build = alpha003_pair

    if damage == "value":
        line = build._nodes["negate_0"].lines.value
        line.array[-1] += 0.125
    elif damage == "reason":
        line = build._nodes["correlation10_0"].lines.reason
        line.array[-1] += 1.0
    elif damage == "asset":
        target = build.target_datas[-1]
        build._factor_runtime["asset_by_data_id"][id(target)] = "renamed-target"
    elif damage == "duplicate":
        build._nodes["extra-diagnostic-label"] = build._nodes["negate_0"]
    elif damage == "empty":
        build._nodes.clear()
    else:
        node = build._nodes["correlation10_0"]
        node._operand_args[0]._factor_research_target = object()

    report = compare_factor_graphs(native, build, 3)

    assert not report["equal"]
    assert report["failures"]


def _clone_with_reason(node, target, reason_delta):
    clone = copy.copy(node)
    values = array("d", (float(value) for value in node.lines.value.array))
    reasons = array("d", (float(value) for value in node.lines.reason.array))
    reasons[-1] += reason_delta
    value_line = SimpleNamespace(array=values, _factor_research_target=target)
    value_line._factor_research_reason_line = SimpleNamespace(array=reasons)
    clone.lines = SimpleNamespace(value=value_line, reason=value_line._factor_research_reason_line)
    return clone


def test_duplicate_ast_nodes_pair_by_value_and_reason_not_insertion_order(alpha003_pair):
    native, build = alpha003_pair
    target_native = native.target_datas[0]
    target_build = build.target_datas[0]
    base_native = native._nodes.pop("negate_0")
    base_build = build._nodes.pop("negate_0")
    first_native = _clone_with_reason(base_native, target_native, 0.0)
    second_native = _clone_with_reason(base_native, target_native, 1.0)
    first_build = _clone_with_reason(base_build, target_build, 0.0)
    second_build = _clone_with_reason(base_build, target_build, 1.0)
    native._nodes["native-copy-a"] = first_native
    native._nodes["native-copy-b"] = second_native
    build._nodes["build-copy-b"] = second_build
    build._nodes["build-copy-a"] = first_build

    report = compare_factor_graphs(native, build, 3)

    assert report["equal"], report["failures"]
    assert report["node_count_left"] == report["node_count_right"] == 15


def test_alpha028_scale_parameter_is_part_of_panel_graph_identity():
    frames = make_positive_fixture(320)
    native = run_native_batch(
        frames,
        (28,),
        runonce=False,
        factor_mode="native",
        alpha_classes={28: get_alpha(28)},
    ).factor_instances["alpha28"]
    build = run_native_batch(
        frames,
        (28,),
        runonce=False,
        factor_mode="build",
        alpha_classes={28: get_alpha(28)},
    ).factor_instances["alpha28"]

    assert compare_factor_graphs(native, build, 28)["equal"]
    scale = next(node for node in build._nodes.values() if isinstance(node, CrossSectionalScale))
    scale.p.a = 2.0

    report = compare_factor_graphs(native, build, 28)

    assert not report["equal"]
    assert any("node multiplicity" in failure for failure in report["failures"])


def test_alpha100_indneutralize_classification_input_is_part_of_panel_graph_identity():
    frames = make_positive_fixture(320)
    native = run_native_batch(
        frames,
        (100,),
        runonce=False,
        factor_mode="native",
        alpha_classes={100: get_alpha(100)},
    ).factor_instances["alpha100"]
    build = run_native_batch(
        frames,
        (100,),
        runonce=False,
        factor_mode="build",
        alpha_classes={100: get_alpha(100)},
    ).factor_instances["alpha100"]

    assert compare_factor_graphs(native, build, 100)["equal"]
    neutralize = next(node for node in build._nodes.values() if isinstance(node, IndNeutralize))
    neutralize._groups = (build._field_line_cache["close"][0],) + neutralize._groups[1:]

    report = compare_factor_graphs(native, build, 100)

    assert not report["equal"]
    assert any("node multiplicity" in failure for failure in report["failures"])


def _run_alpha_instance(frames, alpha_id, mode, runonce):
    strategy = run_native_batch(
        frames,
        (alpha_id,),
        runonce=runonce,
        factor_mode=mode,
        alpha_classes={alpha_id: get_alpha(alpha_id)},
    )
    return strategy.factor_instances["alpha%d" % alpha_id]


def _constant_only_subtracts(factor):
    result = []
    for node in factor._nodes.values():
        if not isinstance(node, Subtract):
            continue
        operands = tuple(getattr(node, "_operand_args", ()))
        if operands and not any(operators._is_line_operand(value) for value in operands):
            result.append(node)
    return result


def _line_owner(line):
    return getattr(getattr(line, "_owner", None), "_owner_ref", None)


@pytest.mark.parametrize("alpha_id", (59, 82), ids=lambda value: "alpha%d" % value)
def test_alpha59_alpha82_constant_nodes_pair_for_both_engines(alpha_id):
    frames = make_positive_fixture(320)
    expected_assets = sorted(frames)

    for runonce in (False, True):
        native = _run_alpha_instance(frames, alpha_id, "native", runonce)
        build = _run_alpha_instance(frames, alpha_id, "build", runonce)
        report = compare_factor_graphs(native, build, alpha_id)

        assert report["equal"], report["failures"]
        assert report["node_count_left"] == report["node_count_right"]
        constant_records = [
            row for row in report["matched_nodes"] if row["operator_type"].endswith(".Subtract")
        ]
        assert len(constant_records) == len(expected_assets)
        assert all(row["ast"][0] == "number" for row in constant_records)
        assert sorted(tuple(row["target_assets"]) for row in constant_records) == [
            (asset,) for asset in expected_assets
        ]


@pytest.mark.parametrize("alpha_id", (59, 82), ids=lambda value: "alpha%d" % value)
def test_alpha59_alpha82_constant_nodes_require_correct_reachable_ownership(alpha_id):
    frames = make_positive_fixture(320)
    native = _run_alpha_instance(frames, alpha_id, "native", False)
    build = _run_alpha_instance(frames, alpha_id, "build", False)
    assert compare_factor_graphs(native, build, alpha_id)["equal"]

    constants = _constant_only_subtracts(native)
    assert len(constants) == len(native.target_datas)
    constant_ids = {id(node) for node in constants}
    consumer = None
    operand_index = None
    for node in native._nodes.values():
        if not isinstance(node, Multiply):
            continue
        for index, operand in enumerate(node._operand_args):
            if id(_line_owner(operand)) in constant_ids:
                consumer = node
                operand_index = index
                break
        if consumer is not None:
            break
    assert consumer is not None and operand_index is not None

    original_operands = consumer._operand_args
    used_constant = _line_owner(original_operands[operand_index])
    wrong_constant = next(node for node in constants if node is not used_constant)
    corrupted_operands = list(original_operands)
    corrupted_operands[operand_index] = wrong_constant.lines.value
    consumer._operand_args = tuple(corrupted_operands)

    wrong_owner_report = compare_factor_graphs(native, build, alpha_id)

    assert not wrong_owner_report["equal"]
    assert any(
        "ambiguous or missing consumer asset identity" in failure
        for failure in wrong_owner_report["failures"]
    )

    consumer._operand_args = original_operands
    native._nodes = {key: node for key, node in native._nodes.items() if node is not constants[0]}

    missing_node_report = compare_factor_graphs(native, build, alpha_id)

    assert not missing_node_report["equal"]
    assert any(
        "reachable constant-only operator node" in failure
        and "absent from factor._nodes" in failure
        for failure in missing_node_report["failures"]
    )


def test_alpha082_panel_inputs_keep_their_asset_column_identity():
    frames = make_positive_fixture(320)
    native = _run_alpha_instance(frames, 82, "native", False)
    build = _run_alpha_instance(frames, 82, "build", False)
    assert compare_factor_graphs(native, build, 82)["equal"]

    panel = next(
        node for node in native._nodes.values() if isinstance(node, operators._PanelOperator)
    )
    original_values = panel._values
    corrupted_values = list(original_values)
    corrupted_values[0], corrupted_values[1] = corrupted_values[1], corrupted_values[0]
    panel._values = tuple(corrupted_values)

    report = compare_factor_graphs(native, build, 82)

    assert not report["equal"]
    assert any("bound to another target" in failure for failure in report["failures"])


def test_partial_selection_cannot_write_pass_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv(BUILD_PAIR_EVIDENCE_ENV, str(tmp_path))
    record = {
        "status": "PASS",
        "complete_registry_coverage": False,
        "aggregate": {"all_pass": True},
    }

    with pytest.raises(AssertionError, match="partial Alpha101 selection"):
        _write_pair_evidence(320, record)

    evidence_path = tmp_path / "alpha101-build-pair-T320.json"
    assert not evidence_path.exists()

    record["status"] = "INCOMPLETE"
    record["aggregate"]["all_pass"] = False
    _write_pair_evidence(320, record)

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == record
