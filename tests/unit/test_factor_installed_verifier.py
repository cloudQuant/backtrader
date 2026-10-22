"""Focused contracts for the pinned-wheel verifier's file-boundary checks."""

from __future__ import annotations

import ast
import csv
import importlib.util
import inspect
import json
from pathlib import Path
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
