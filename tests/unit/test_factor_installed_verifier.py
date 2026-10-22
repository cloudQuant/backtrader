"""Focused contracts for the pinned-wheel verifier's file-boundary checks."""

from __future__ import annotations

import ast
import csv
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_factor_research_installed.py"
_SPEC = importlib.util.spec_from_file_location("factor_installed_verifier", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)


def _write_export(root: Path, *, charts: bool, include_charts: bool = True) -> Path:
    export = root / "evaluation" / "evaluation-1"
    export.mkdir(parents=True)
    tables = {}
    exports = []
    for name in sorted(verifier._EVALUATION_CSVS):
        columns = ["factor", "value"]
        rows = [["alpha1", "1.0"], ["alpha2", "2.0"]]
        with (export / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        tables[Path(name).stem] = {"columns": columns, "rows": len(rows)}
        exports.append(name)
    if charts and include_charts:
        for name in sorted(verifier._EVALUATION_PNGS):
            (export / name).write_bytes(b"\x89PNG\r\n\x1a\nsynthetic chart")
            exports.append(name)
    manifest = {
        "status": "OK",
        "result_fingerprint": "a" * 64,
        "exports": exports,
        "tables": tables,
    }
    (export / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return export


@pytest.mark.parametrize("charts", (False, True))
def test_evaluation_manifest_exports_match_actual_csv_and_chart_files(tmp_path, charts):
    _write_export(tmp_path, charts=charts)

    result = verifier._require_evaluation_export(tmp_path, charts=charts)

    assert result["result_fingerprint"] == "a" * 64
    assert set(result["table_rows"]) == verifier._EVALUATION_CSVS
    assert set(result["table_rows"].values()) == {2}
    assert bool(result["png_files"]) is charts


def test_evaluation_manifest_rejects_declared_row_count_mismatch(tmp_path):
    export = _write_export(tmp_path, charts=False)
    manifest_path = export / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tables"]["ic"]["rows"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(verifier.VerificationError, match="row count differs"):
        verifier._require_evaluation_export(tmp_path, charts=False)


def test_chart_export_rejects_missing_png(tmp_path):
    _write_export(tmp_path, charts=True, include_charts=False)

    with pytest.raises(verifier.VerificationError, match="incomplete or unexpected files"):
        verifier._require_evaluation_export(tmp_path, charts=True)


def test_wheel_rejects_member_omitted_from_record(tmp_path):
    wheel = tmp_path / "synthetic-1.0-py3-none-any.whl"
    record = "synthetic-1.0.dist-info/RECORD"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("synthetic/module.py", "value = 1\n")
        archive.writestr(record, "%s,,\n" % record)

    with pytest.raises(verifier.VerificationError, match="members and RECORD paths differ"):
        verifier._verify_wheel_payload(wheel, tmp_path / "install", tmp_path / "source")


def test_main_wheel_verifier_calls_supply_required_archive_source_argument():
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_verify_wheel_payload"
    ]
    assert len(calls) == 2

    signature = inspect.signature(verifier._verify_wheel_payload)
    source_arguments = set()
    for call in calls:
        assert all(not isinstance(argument, ast.Starred) for argument in call.args)
        assert len(call.args) >= 3
        assert isinstance(call.args[2], ast.Name)
        source_arguments.add(call.args[2].id)
        signature.bind(*([None] * len(call.args)), **{kw.arg: None for kw in call.keywords})
    assert source_arguments == {"bt_source", "fincore_source"}


def test_factor_mode_pair_is_an_opt_in_archive_profile():
    base = verifier._archive_paths("backtrader")
    paired = verifier._archive_paths("backtrader", factor_mode_pair=True)
    build_pair = verifier._archive_paths("backtrader", alpha101_build_pair=True)

    assert paired[: len(base)] == base
    assert set(verifier._FACTOR_MODE_PAIR_TEST_INPUTS).issubset(paired)
    assert verifier._PAIR_SEMANTICS_HELPER in paired
    assert not set(verifier._FACTOR_MODE_PAIR_ARCHIVE_PATHS).intersection(base)
    assert build_pair[: len(base)] == base
    assert set(verifier._FACTOR_MODE_PAIR_ARCHIVE_PATHS).issubset(build_pair)
    assert set(verifier._ALPHA101_BUILD_PAIR_ARCHIVE_PATHS).issubset(build_pair)
    assert not set(verifier._ALPHA101_BUILD_PAIR_ARCHIVE_PATHS).intersection(paired)

    required = [
        "--backtrader-commit",
        "a" * 40,
        "--fincore-commit",
        "b" * 40,
        "--evidence-dir",
        "/tmp/evidence",
    ]
    assert verifier._parser().parse_args(required).factor_mode_pair is False
    assert verifier._parser().parse_args([*required, "--factor-mode-pair"]).factor_mode_pair is True
    assert verifier._parser().parse_args(required).alpha101_build_pair is False
    assert (
        verifier._parser().parse_args([*required, "--alpha101-build-pair"]).alpha101_build_pair
        is True
    )


def test_pair_profile_copies_pinned_tests_helper_and_examples_outside_source_tree(tmp_path):
    source = tmp_path / "archive-source"
    for relative in (*verifier._TEST_INPUTS, *verifier._FACTOR_MODE_PAIR_TEST_INPUTS):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("from_pinned_archive = True\n", encoding="utf-8")
    for relative in verifier._EXAMPLE_DIRS:
        example = source / relative
        example.mkdir(parents=True, exist_ok=True)
        (example / "run.py").write_text("PINNED = True\n", encoding="utf-8")
    helper = source / verifier._PAIR_SEMANTICS_HELPER
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("PINNED_HELPER = True\n", encoding="utf-8")

    external = tmp_path / "evidence" / "external-tests"
    verifier._copy_external_tests(source, external, factor_mode_pair=True)
    copied_helper = verifier._copy_external_pair_helper(source, external)

    for relative in verifier._FACTOR_MODE_PAIR_TEST_INPUTS:
        assert (external / relative).is_file()
    assert copied_helper.read_text(encoding="utf-8") == "PINNED_HELPER = True\n"
    for relative in verifier._EXAMPLE_DIRS:
        copied = external / "examples" / "backtest" / Path(relative).name
        assert (copied / "run.py").is_file()
    assert not (external / "backtrader").exists()


def test_alpha101_build_pair_copies_matrix_and_dependencies_from_archive(tmp_path):
    source = tmp_path / "archive-source"
    for relative in (
        *verifier._TEST_INPUTS,
        *verifier._FACTOR_MODE_PAIR_TEST_INPUTS,
        *verifier._ALPHA101_BUILD_PAIR_TEST_INPUTS,
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("from_pinned_archive = True\n", encoding="utf-8")
    for relative in verifier._EXAMPLE_DIRS:
        example = source / relative
        example.mkdir(parents=True, exist_ok=True)
        (example / "run.py").write_text("PINNED = True\n", encoding="utf-8")
    helper = source / verifier._PAIR_SEMANTICS_HELPER
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("PINNED_HELPER = True\n", encoding="utf-8")

    external = tmp_path / "evidence" / "external-tests"
    verifier._copy_external_tests(source, external, factor_mode_pair=True, alpha101_build_pair=True)
    copied_helper = verifier._copy_external_pair_helper(source, external)

    for relative in (
        *verifier._TEST_INPUTS,
        *verifier._FACTOR_MODE_PAIR_TEST_INPUTS,
        *verifier._ALPHA101_BUILD_PAIR_TEST_INPUTS,
    ):
        assert (external / relative).read_text(encoding="utf-8") == "from_pinned_archive = True\n"
    assert copied_helper.read_text(encoding="utf-8") == "PINNED_HELPER = True\n"
    assert not (external / "backtrader").exists()


def test_installed_pair_profile_runs_complete_unit_files_without_name_filter():
    source = inspect.getsource(verifier._run_installed_tests)

    assert "tests/unit/test_factor_build_expression.py" in source
    assert "tests/unit/test_factor_research_examples.py" in source
    assert "--junitxml" in source
    assert '"-k"' not in source
    assert "'-k'" not in source


def test_build_pair_profile_runs_exact_t320_node_and_clears_subset_environment(
    tmp_path, monkeypatch
):
    external = tmp_path / "external-tests"
    external.mkdir()
    install_root = tmp_path / "installed"
    for package in ("backtrader", "fincore"):
        package_dir = install_root / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("INSTALLED = True\n", encoding="utf-8")
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    record_path = tmp_path / "matrix-record.json"
    record_path.write_text(json.dumps(_valid_alpha101_build_pair_record()), encoding="utf-8")
    (external / "pytest.py").write_text(
        """import json, os, pathlib, sys

def main(args):
    install = pathlib.Path(sys.path[0]).resolve()
    import backtrader, fincore
    assert pathlib.Path(backtrader.__file__).resolve().is_relative_to(install)
    assert pathlib.Path(fincore.__file__).resolve().is_relative_to(install)
    assert not any(arg in ("-k", "--keyword") for arg in args)
    expected_node = "test_alpha101_native_build_pair_graph_matrix[T320]"
    assert any(expected_node in arg for arg in args)
    assert os.environ.get("BT_ALPHA101_NATIVE_IDS") is None
    assert os.environ.get("BT_ALPHA101_NATIVE_BATCHES") is None
    assert os.environ.get("BT_ALPHA101_CUSTOM_SUBSET_MODE") is None
    baseline = pathlib.Path(args[args.index("--basetemp") + 1])
    ids = list(range(1, 102))
    for batch in ("promoted_20", "a", "b", "c", "d", "e"):
        for engine in ("runnext", "runonce"):
            path = baseline / (batch + "-" + engine) / "alpha101-native-installed-acceptance.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "selected_batch": batch,
                "selected_engine_mode": engine,
                "selected_batch_alpha_ids": ids,
                "trace_validation": {"formula_count": len(ids)},
            }))
    representative = baseline / "representative" / "installed-acceptance.json"
    representative.parent.mkdir(parents=True, exist_ok=True)
    representative.write_text("{}")
    junit = pathlib.Path(args[args.index("--junitxml") + 1])
    names = {
        "test_alpha003_degenerate_recovery_missing_bar_nan_trace_and_reason_pair",
        "test_025_close_ma_build_matches_native_and_independent_oracle",
        "test_026_roc_build_matches_native_and_independent_oracle",
        "test_026_kdj_build_matches_native_oracle_and_all_intermediate_lines",
    }
    cases = ["<testsuite>"]
    for name in sorted(names):
        for engine in ("runnext", "runonce"):
            cases.append("<testcase name=%r />" % (name + "[" + engine + "]"))
    cases.append("<testcase name=%r />" % expected_node)
    cases.append("</testsuite>")
    junit.write_text("".join(cases))
    output = pathlib.Path(os.environ["BT_ALPHA101_BUILD_PAIR_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    matrix = pathlib.Path(os.environ["FAKE_ALPHA101_MATRIX_RECORD"])
    (output / "alpha101-build-pair-T320.json").write_bytes(matrix.read_bytes())
    print("fake pytest bootstrap executed under isolated installed imports")
    return 0
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "poison"))
    monkeypatch.setenv("BT_ALPHA101_NATIVE_IDS", "3")
    monkeypatch.setenv("BT_ALPHA101_NATIVE_BATCHES", "a")
    monkeypatch.setenv("BT_ALPHA101_CUSTOM_SUBSET_MODE", "partial")
    monkeypatch.setenv("FAKE_ALPHA101_MATRIX_RECORD", str(record_path))

    report = verifier._run_installed_tests(
        external,
        install_root,
        provenance,
        evidence,
        factor_mode_pair=True,
        alpha101_build_pair=True,
    )

    assert "fake pytest bootstrap executed under isolated installed imports" in (
        evidence / "installed-tests.log"
    ).read_text(encoding="utf-8")
    assert report["alpha101_build_pair_test_witness"]["status"] == "PASSED"
    assert report["alpha101_build_pair_record"]["status"] == "PASS"


def _valid_alpha101_build_pair_record():
    alpha_ids = list(verifier._ALPHA101_IDS)
    assets = list(verifier._ALPHA101_PAIR_ASSETS)

    def panel():
        return {
            "cells": 320 * len(assets),
            "finite_cells": 1000,
            "nan_cells": 320 * len(assets) - 1000,
            "sha256": "d" * 64,
        }

    def graph_pair(with_panel=False):
        pair = {
            "equal": True,
            "node_count_left": 4,
            "node_count_right": 4,
            "matched_node_count": 4,
            "node_value_cells": 4 * 320 * len(assets),
            "node_reason_cells": 4 * 320 * len(assets),
            "node_value_sha256": "a" * 64,
            "node_reason_sha256": "b" * 64,
            "result_output_cells": 320 * len(assets),
            "result_output_sha256": "c" * 64,
            "grid_rows": 320,
            "assets": assets,
        }
        if with_panel:
            pair["factor_panel"] = panel()
        return pair

    engine_runs = []
    for factor_mode in ("native", "build"):
        for engine in verifier._PAIR_ENGINE_MODES:
            engine_runs.append(
                {
                    "factor_mode": factor_mode,
                    "engine": engine,
                    "runonce": engine == "runonce",
                    "alpha_ids": alpha_ids,
                    "factor_classes": {
                        str(alpha_id): verifier._expected_alpha101_class(alpha_id, factor_mode)
                        for alpha_id in alpha_ids
                    },
                    "oracle_pass_count": 101,
                    "finite_witness_count": 101,
                    "lifecycle_pass_count": 101,
                    "broker": {"submit": 0, "cancel": 0},
                    "factor_panel": {
                        "cells": 101 * 320 * len(assets),
                        "finite_cells": 101 * 1000,
                        "nan_cells": 101 * (320 * len(assets) - 1000),
                        "sha256": "e" * 64,
                    },
                }
            )
    per_alpha = {}
    for alpha_id in alpha_ids:
        per_alpha[str(alpha_id)] = {
            "oracle_pass": True,
            "finite_witness": True,
            "lifecycle_pass": True,
            "lookback_h": alpha_id % 100,
            "factor_classes": {
                factor_mode + "/" + engine: verifier._expected_alpha101_class(alpha_id, factor_mode)
                for factor_mode in ("native", "build")
                for engine in verifier._PAIR_ENGINE_MODES
            },
            "same_engine_build_pair": {
                engine: graph_pair(with_panel=True) for engine in verifier._PAIR_ENGINE_MODES
            },
            "cross_engine": {
                factor_mode: graph_pair(with_panel=True) for factor_mode in ("native", "build")
            },
        }
    pairs = [
        pair
        for item in per_alpha.values()
        for pair in (
            *item["same_engine_build_pair"].values(),
            *item["cross_engine"].values(),
        )
    ]
    panels = [
        item["cross_engine"][factor_mode]["factor_panel"]
        for item in per_alpha.values()
        for factor_mode in ("native", "build")
    ]
    return {
        "schema_version": 1,
        "status": "PASS",
        "periods": 320,
        "alpha_ids": alpha_ids,
        "complete_registry_coverage": True,
        "engine_runs": engine_runs,
        "per_alpha": per_alpha,
        "aggregate": {
            "alpha_count": 101,
            "engine_run_count": 4,
            "oracle_pass_count": 404,
            "finite_witness_count": 404,
            "lifecycle_pass_count": 404,
            "same_engine_graph_pair_count": 202,
            "cross_engine_graph_pair_count": 202,
            "node_value_cells": sum(pair["node_value_cells"] for pair in pairs),
            "node_reason_cells": sum(pair["node_reason_cells"] for pair in pairs),
            "result_output_cells": sum(pair["result_output_cells"] for pair in pairs),
            "cross_engine_panel_cells": sum(panel["cells"] for panel in panels),
            "cross_engine_panel_finite_cells": sum(panel["finite_cells"] for panel in panels),
            "cross_engine_panel_nan_cells": sum(panel["nan_cells"] for panel in panels),
            "all_pass": True,
        },
    }


def _write_alpha101_build_pair_record(tmp_path, record):
    evidence = tmp_path / "alpha101-build-pair"
    evidence.mkdir(exist_ok=True)
    path = evidence / verifier._ALPHA101_BUILD_PAIR_RECORD
    path.write_text(json.dumps(record), encoding="utf-8")
    return evidence


def test_alpha101_build_pair_record_requires_full_exact_matrix(tmp_path):
    evidence = _write_alpha101_build_pair_record(tmp_path, _valid_alpha101_build_pair_record())

    summary = verifier._verify_alpha101_build_pair_record(evidence)

    assert summary["periods"] == 320
    assert summary["alpha_ids"] == list(range(1, 102))
    assert summary["engine_runs"] == 4
    assert summary["aggregate"]["same_engine_graph_pair_count"] == 202
    assert summary["aggregate"]["cross_engine_graph_pair_count"] == 202
    assert len(summary["sha256"]) == 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda r: r.update(periods=640), "not the T320 run"),
        (lambda r: r.update(alpha_ids=list(range(1, 101))), "exactly Alpha001-Alpha101"),
        (lambda r: r.update(complete_registry_coverage=False), "complete registry coverage"),
        (lambda r: r["engine_runs"].pop(), "exactly four engine runs"),
        (
            lambda r: r["engine_runs"][0].update(factor_mode="other"),
            "duplicate or unsupported mode/engine",
        ),
        (
            lambda r: r["engine_runs"][0].update(runonce=True),
            "runonce flag does not match",
        ),
        (
            lambda r: r["engine_runs"][0]["factor_classes"].update({"1": "wrong.Class"}),
            "wrong installed class for Alpha1",
        ),
        (
            lambda r: r["per_alpha"].pop("101"),
            "missing or unexpected fields",
        ),
        (
            lambda r: r["per_alpha"]["1"]["same_engine_build_pair"]["runnext"].update(equal=False),
            "graph comparison is not exact",
        ),
        (
            lambda r: r["per_alpha"]["1"]["cross_engine"]["build"].update(node_reason_cells=0),
            "node_reason_cells must be an integer >= 1",
        ),
        (
            lambda r: r["per_alpha"]["1"]["cross_engine"]["native"]["factor_panel"].update(
                sha256=None
            ),
            "lowercase SHA-256 digest",
        ),
        (lambda r: r["aggregate"].update(all_pass=False), "aggregate all_pass does not reconcile"),
    ),
)
def test_alpha101_build_pair_record_rejects_incomplete_or_false_pass(tmp_path, mutate, message):
    record = copy.deepcopy(_valid_alpha101_build_pair_record())
    mutate(record)
    evidence = _write_alpha101_build_pair_record(tmp_path, record)

    with pytest.raises(verifier.VerificationError, match=message):
        verifier._verify_alpha101_build_pair_record(evidence)


@pytest.mark.parametrize("outcome", ("skipped", "failure", "error"))
def test_alpha101_build_pair_junit_witness_rejects_nonpassing_t320(tmp_path, outcome):
    report = tmp_path / "matrix.xml"
    report.write_text(
        '<testsuite><testcase name="test_alpha101_native_build_pair_graph_matrix[T320]">'
        "<%s /></testcase></testsuite>" % outcome,
        encoding="utf-8",
    )

    with pytest.raises(verifier.VerificationError, match="did not pass"):
        verifier._verify_alpha101_build_pair_test_witness(report)


def test_alpha101_build_pair_nonzero_child_exit_cannot_return_a_pass_record(tmp_path, monkeypatch):
    external = tmp_path / "external-tests"
    external.mkdir()
    install_root = tmp_path / "installed"
    install_root.mkdir()
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    def fail_after_matrix_output(_command, *, cwd=None, env=None):
        record_path = Path(env["BT_ALPHA101_BUILD_PAIR_EVIDENCE"])
        record_path.mkdir(parents=True, exist_ok=True)
        (record_path / verifier._ALPHA101_BUILD_PAIR_RECORD).write_text(
            json.dumps(_valid_alpha101_build_pair_record()), encoding="utf-8"
        )
        raise verifier.VerificationError("command failed with exit 7")

    monkeypatch.setattr(verifier, "_run", fail_after_matrix_output)
    with pytest.raises(verifier.VerificationError, match="command failed with exit 7"):
        verifier._run_installed_tests(
            external,
            install_root,
            provenance,
            evidence,
            factor_mode_pair=True,
            alpha101_build_pair=True,
        )

    assert not (evidence / "verification-summary.json").exists()
    assert not (evidence / "installed-tests.log").exists()


def _write_pair_junit(path: Path, *, omitted=(), skipped=(), failed=()):
    root = ["<testsuite>"]
    omitted = set(omitted)
    skipped = set(skipped)
    failed = set(failed)
    for formula, tests in verifier._PAIR_FORMULA_TEST_CASES.items():
        for test_name in tests:
            for engine in verifier._PAIR_ENGINE_MODES:
                name = "%s[%s]" % (test_name, engine)
                if (formula, engine) in omitted:
                    continue
                if (formula, engine) in skipped:
                    root.append('<testcase name="%s"><skipped /></testcase>' % name)
                elif (formula, engine) in failed:
                    root.append('<testcase name="%s"><failure /></testcase>' % name)
                else:
                    root.append('<testcase name="%s" />' % name)
    root.append("</testsuite>")
    path.write_text("".join(root), encoding="utf-8")


def test_pair_formula_witnesses_require_all_four_formulas_and_both_engines(tmp_path):
    report = tmp_path / "tests.xml"
    _write_pair_junit(report)

    witnesses = verifier._verify_pair_formula_test_witnesses(report)

    assert set(witnesses) == {"Alpha003", "CloseMA", "ROC", "KDJ"}
    assert all(
        {item["engine_mode"] for item in formula_witnesses} == {"runnext", "runonce"}
        for formula_witnesses in witnesses.values()
    )


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"omitted": {("Alpha003", "runonce")}}, "omitted required"),
        ({"skipped": {("ROC", "runnext")}}, "did not pass"),
        ({"failed": {("KDJ", "runonce")}}, "did not pass"),
    ),
)
def test_pair_formula_witnesses_reject_missing_skipped_or_failed_cases(tmp_path, options, message):
    report = tmp_path / "tests.xml"
    _write_pair_junit(report, **options)

    with pytest.raises(verifier.VerificationError, match=message):
        verifier._verify_pair_formula_test_witnesses(report)


def test_report_semantics_sidecar_must_match_actual_html(tmp_path):
    html = tmp_path / "factor.html"
    html.write_text("<html>pinned report</html>", encoding="utf-8")
    payload = {"factor": "close_ma", "title": "report"}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    sidecar = {
        "schema_version": "test-report-semantics-v1",
        "reports": [
            {
                "html_path": str(html),
                "html_sha256": hashlib.sha256(html.read_bytes()).hexdigest(),
                "semantic_payload": payload,
                "semantic_digest": digest,
            }
        ],
    }
    (tmp_path / "report_semantics.json").write_text(json.dumps(sidecar), encoding="utf-8")

    assert verifier._require_report_semantics(tmp_path, expected_reports=1)["reports"]
    sidecar["reports"][0]["html_sha256"] = "0" * 64
    (tmp_path / "report_semantics.json").write_text(json.dumps(sidecar), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="HTML hash does not match"):
        verifier._require_report_semantics(tmp_path, expected_reports=1)


def test_example_bootstrap_captures_pinned_helper_and_imports_only_install(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    for package, marker in (("backtrader", "installed-bt"), ("fincore", "installed-fincore")):
        package_dir = install_root / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("ORIGIN = %r\n" % marker, encoding="utf-8")

    external = tmp_path / "external-tests"
    helper = external / "scripts" / "verify_factor_research_pair_semantics.py"
    helper.parent.mkdir(parents=True)
    helper.write_text(
        """from contextlib import contextmanager
import hashlib, json
active = False
@contextmanager
def capture_report_semantics(output_dir):
    global active
    active = True
    try:
        yield
    except BaseException:
        raise
    else:
        output_dir = __import__('pathlib').Path(output_dir)
        report = next(output_dir.glob('*.html'))
        payload = {'captured': True}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        data = {'schema_version': 'test-v1', 'reports': [{'html_path': str(report), 'html_sha256': hashlib.sha256(report.read_bytes()).hexdigest(), 'semantic_payload': payload, 'semantic_digest': digest}]}
        (output_dir / 'report_semantics.json').write_text(json.dumps(data))
def compare_runs(left, right, *, require_reports=False, require_mode_pair=False, require_panel_pair=False):
    return {'strict_equal': True}
""",
        encoding="utf-8",
    )
    example = tmp_path / "external-example"
    example.mkdir()
    (example / "run.py").write_text(
        """import sys
from pathlib import Path
import backtrader, fincore
def main(args):
    helper = sys.modules['factor_research_installed_pair_semantics']
    assert helper.active
    assert backtrader.ORIGIN == 'installed-bt'
    assert fincore.ORIGIN == 'installed-fincore'
    output = Path(args[args.index('--output-dir') + 1])
    output.mkdir(parents=True)
    (output / 'report.html').write_text('<html>installed</html>')
    return 0
""",
        encoding="utf-8",
    )
    poison = tmp_path / "poison-pythonpath"
    (poison / "backtrader").mkdir(parents=True)
    (poison / "backtrader" / "__init__.py").write_text("raise RuntimeError('PYTHONPATH leaked')\n")
    monkeypatch.setenv("PYTHONPATH", str(poison))
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    output = tmp_path / "run-output"

    verifier._run_example(
        example / "run.py",
        example,
        install_root,
        ["--output-dir", str(output)],
        evidence,
        output_dir=output,
        pair_helper=helper,
        external_test_root=external,
        expected_report_count=1,
    )

    assert (output / "report_semantics.json").is_file()

    failed_script = example / "run_failed.py"
    failed_script.write_text(
        (example / "run.py").read_text(encoding="utf-8").replace("return 0", "return 9"),
        encoding="utf-8",
    )
    failed_output = tmp_path / "failed-run-output"
    with pytest.raises(verifier.VerificationError, match="command failed with exit 9"):
        verifier._run_example(
            failed_script,
            example,
            install_root,
            ["--output-dir", str(failed_output)],
            evidence,
            output_dir=failed_output,
            pair_helper=helper,
            external_test_root=external,
            expected_report_count=1,
        )
    assert not (failed_output / "report_semantics.json").exists()


@pytest.mark.parametrize(
    ("mode", "indicator"),
    (
        ("", None),
        ("native", "backtrader.research.alpha101.alpha003.Alpha003Native"),
        ("build", "backtrader.research.alpha101.alpha003.Alpha003Build"),
    ),
)
def test_027_isolated_bootstrap_accepts_legacy_and_propagates_mode_summary(
    tmp_path, mode, indicator
):
    install_root = tmp_path / "installed"
    for package in ("backtrader", "fincore"):
        package_dir = install_root / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("INSTALLED = True\n", encoding="utf-8")

    example = tmp_path / "external-example"
    example.mkdir()
    (example / "run.py").write_text(
        """import json, os
from pathlib import Path
def main(args):
    output = Path(args[args.index('--output-dir') + 1])
    output.mkdir(parents=True)
    report = output / 'factor_report_alpha003.html'
    report.write_text('<html>report</html>')
    summary = {'status': 'COMPLETED', 'symbols': 20, 'dates': 243,
               'report': str(report)}
    if '--factor-mode' in args:
        mode = os.environ.get('FACTOR_MODE_OVERRIDE', args[args.index('--factor-mode') + 1])
        summary.update({'factor_mode': mode, 'factor_calculation': 'RAN',
                        'indicator': 'backtrader.research.alpha101.alpha003.Alpha003'
                                     + mode.title()})
    (output / 'summary.json').write_text(json.dumps(summary))
    return 0
""",
        encoding="utf-8",
    )
    probe = verifier._write_027_probe(tmp_path)
    source = probe.read_text(encoding="utf-8")
    marker = "# This bootstrap/mode-summary section is exercised independently by the unit\n"
    bootstrap = source.split(marker, 1)[0]
    output = tmp_path / ("output-legacy" if not mode else "output-" + mode)

    result = subprocess.run(
        [
            str(verifier.BASE_PYTHON),
            "-I",
            "-c",
            bootstrap,
            str(install_root),
            str(example),
            str(tmp_path / "unused-data"),
            str(output),
            mode,
            "",
        ],
        cwd=tmp_path,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, result.stdout
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    if mode:
        assert summary["factor_mode"] == mode
        assert summary["indicator"] == indicator

        mismatch_output = tmp_path / "output-mode-mismatch"
        env = os.environ.copy()
        env["FACTOR_MODE_OVERRIDE"] = "native" if mode == "build" else "build"
        mismatch = subprocess.run(
            [
                str(verifier.BASE_PYTHON),
                "-I",
                "-c",
                bootstrap,
                str(install_root),
                str(example),
                str(tmp_path / "unused-data"),
                str(mismatch_output),
                mode,
                "",
            ],
            cwd=tmp_path,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert mismatch.returncode != 0
        assert "mode or indicator identity" in mismatch.stdout
    else:
        assert "factor_mode" not in summary
        assert "indicator" not in summary

    tree = ast.parse(source)
    payload_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets)
        and isinstance(node.value, ast.Dict)
    ]
    assert len(payload_assignments) == 1
    payload = payload_assignments[0].value
    payload_values = {key.value: value for key, value in zip(payload.keys, payload.values)}
    for key in ("factor_mode", "indicator"):
        value = payload_values[key]
        assert isinstance(value, ast.Call)
        assert isinstance(value.func, ast.Attribute) and value.func.attr == "get"
        assert isinstance(value.func.value, ast.Name) and value.func.value.id == "summary"
        assert len(value.args) == 1 and isinstance(value.args[0], ast.Constant)
        assert value.args[0].value == key

    namespace = {
        "summary": summary,
        "status": "OK",
        "restored": SimpleNamespace(target_order=("asset",), grid=("date",)),
        "saved_values": [{}],
        "panel_files": {"factors.csv"},
        "result": SimpleNamespace(manifest={"result_fingerprint": "fingerprint"}),
        "table_rows": {},
        "export_dir": tmp_path,
        "evaluation_files": {"ic.csv"},
    }
    payload_module = ast.Module(body=[payload_assignments[0]], type_ignores=[])
    exec(compile(payload_module, str(probe), "exec"), namespace)
    assert namespace["payload"]["factor_mode"] == summary.get("factor_mode")
    assert namespace["payload"]["indicator"] == summary.get("indicator")


def test_comparison_flags_are_required_and_non_equal_result_fails_closed(tmp_path):
    received = {}

    def compare(left, right, **kwargs):
        received.update(kwargs)
        return {"strict_equal": True, "status": "IDENTICAL"}

    helper = SimpleNamespace(compare_runs=compare)
    result = verifier._compare_paired_runs(
        helper,
        tmp_path / "native",
        tmp_path / "build",
        label="formula pair",
        require_reports=True,
        require_mode_pair=True,
        require_panel_pair=True,
    )
    assert result["strict_equal"] is True
    assert received == {
        "require_reports": True,
        "require_mode_pair": True,
        "require_panel_pair": True,
    }

    received.clear()
    verifier._compare_paired_runs(
        helper,
        tmp_path / "native-full",
        tmp_path / "native-csv",
        label="full-to-CSV re-evaluation",
        require_reports=True,
        require_mode_pair=False,
        require_panel_pair=False,
    )
    assert received == {
        "require_reports": True,
        "require_mode_pair": False,
        "require_panel_pair": False,
    }

    helper.compare_runs = lambda *args, **kwargs: {"strict_equal": False, "status": "DIFFERENT"}
    with pytest.raises(verifier.VerificationError, match="was not accepted"):
        verifier._compare_paired_runs(
            helper,
            tmp_path / "native",
            tmp_path / "build",
            label="formula pair",
            require_reports=True,
            require_mode_pair=True,
            require_panel_pair=True,
        )
