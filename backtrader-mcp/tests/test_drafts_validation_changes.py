from __future__ import annotations

import pytest

from backtrader_mcp.contracts import ARCHETYPES, SCAFFOLD_PROFILES
from backtrader_mcp.errors import Conflict, Forbidden
from backtrader_mcp.validation import validate_sources

from conftest import canonical_spec


def test_all_fourteen_scaffolds_are_canonical_and_validate(registered_dataset):
    service, dataset = registered_dataset
    for archetype in ARCHETYPES:
        for profile in SCAFFOLD_PROFILES:
            draft = service.create_strategy_draft(
                canonical_spec(dataset["dataset_id"], archetype, profile)
            )
            assert draft["strategy_spec"]["spec_version"] == "strategy-spec-v1"
            assert draft["strategy_spec"]["archetype"] == archetype
            assert draft["artifact_manifest"]["schema_version"] == "artifact-manifest-v1"
            validation = service.validate_strategy_draft(draft["draft_id"], draft["revision"])
            assert validation["report"]["status"] == "passed", validation["report"]
            assert validation["report"]["schema_version"] == "validation-report-v1"


def test_validator_is_object_class_specific_and_blocks_execution():
    report = validate_sources({"objects.py": """
import backtrader as bt

class Direct(bt.Strategy):
    def __init__(self):
        self.signal = bt.indicators.SMA(self.data.close)

class Cooperative(bt.Indicator):
    lines = ("value",)
    def __init__(self):
        self.lines.value = self.data
"""})
    assert any(
        item["class_name"] == "Direct" and item["category"] == "strategy"
        for item in report["evidence"]["classifications"]
    )
    assert any(item["code"] == "missing_cooperative_super" for item in report["diagnostics"])
    dangerous = validate_sources({"bad.py": "exec('print(1)')\n"})
    assert dangerous["status"] == "failed"
    assert dangerous["diagnostics"][0]["code"] == "blocked_call"


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "run.py",
            "from backtrader_mcp.worker import subprocess\n"
            "subprocess.run(['sh', '-c', 'echo escaped'])\n",
        ),
        (
            "run.py",
            "import os as harmless\nharmless.execlp('sh', 'sh', '-c', 'echo escaped')\n",
        ),
        ("run.py", "from os import system\nsystem('echo escaped')\n"),
        ("run.py", "from pathlib import Path\nlist(Path('.').iterdir())\n"),
        ("run.py", "import os\nprint(os.environ['PATH'])\n"),
        ("run.py", "import backtrader as bt\nprint(bt._os.listdir('.'))\n"),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "result_path = Path('../escaped')\nresult_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "result_path += 'escaped'\nresult_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "result_path: object = object()\nresult_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "(result_path := object())\nresult_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "for result_path in [object()]:\n"
            "    pass\n"
            "result_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\n" "os.environ['BACKTRADER_MCP_DATASETS_JSON'] = '{}'\n",
        ),
        (
            "run.py",
            "import os\n"
            "environment = os.environ\n"
            "environment.update({'BACKTRADER_MCP_DATASETS_JSON': '{}'})\n",
        ),
        (
            "run.py",
            "import os\n"
            "environment = os.environ\n"
            "environment |= {'BACKTRADER_MCP_DATASETS_JSON': '{}'}\n",
        ),
        (
            "run.py",
            "import os\n" "os.environ._data[b'BACKTRADER_MCP_DATASETS_JSON'] = b'{}'\n",
        ),
        (
            "run.py",
            "import os\n"
            "environment = os.environ\n"
            "reader = environment.get\n"
            "print(reader('PATH'))\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "escaped = result_path.with_name('escaped.json')\n"
            "writer = escaped.write_text\n"
            "writer('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "writer = (result_path / 'escaped').write_text\n"
            "writer('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "try:\n"
            "    raise ValueError()\n"
            "except ValueError as result_path:\n"
            "    pass\n"
            "result_path.write_text('escaped')\n",
        ),
        (
            "run.py",
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "match object():\n"
            "    case result_path:\n"
            "        pass\n"
            "result_path.write_text('escaped')\n",
        ),
        ("strategy.py", "getattr(__builtins__, 'eval')('1 + 1')\n"),
        ("strategy.py", "open('escaped.txt', 'w').write('escaped')\n"),
    ],
)
def test_validator_rejects_import_alias_and_dynamic_execution_escapes(path, source):
    report = validate_sources({path: source})
    assert report["status"] == "failed"
    assert any(
        diagnostic["code"].startswith("blocked_") or diagnostic["code"] == "path_traversal"
        for diagnostic in report["diagnostics"]
    )


def test_validator_allows_only_an_unmodified_fixed_result_path():
    source = (
        "import json\nimport os\nfrom pathlib import Path\n"
        "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
        "result_path.write_text(json.dumps({'ok': True}), encoding='utf-8')\n"
    )
    report = validate_sources({"run.py": source})
    assert report["status"] == "passed", report["diagnostics"]


@pytest.mark.parametrize(
    "source",
    [
        (
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "writer = result_path.write_text\n"
            "writer('escaped', encoding='utf-8')\n"
        ),
        "runner = eval\nrunner(\"open('escaped', 'w')\")\n",
        (
            "import os\nfrom pathlib import Path\n"
            "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
            "def emit():\n"
            "    result_path.write_text('escaped', encoding='utf-8')\n"
            "result_path = object()\n"
            "emit()\n"
        ),
    ],
)
def test_validator_rejects_detached_or_late_bound_capabilities(source):
    report = validate_sources({"run.py": source})

    assert report["status"] == "failed"
    assert any(
        diagnostic["code"] in {"blocked_call", "blocked_filesystem"}
        for diagnostic in report["diagnostics"]
    )


def test_validator_allows_stable_result_path_in_ordinary_safe_scaffolding():
    source = (
        "import json\nimport os\nfrom pathlib import Path\n"
        "def payload():\n"
        "    return json.dumps({'ok': True})\n"
        "def emit():\n"
        "    result_path.write_text(payload(), encoding='utf-8')\n"
        "result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
        "emit()\n"
    )

    report = validate_sources({"run.py": source})

    assert report["status"] == "passed", report["diagnostics"]


def test_validator_does_not_leak_result_path_capability_from_dormant_function():
    source = (
        "import os\nfrom pathlib import Path\n"
        "result_path = Path.home() / 'escaped.json'\n"
        "def dormant():\n"
        "    result_path = Path(os.environ['BACKTRADER_MCP_RESULT'])\n"
        "result_path.write_text('escaped', encoding='utf-8')\n"
    )

    report = validate_sources({"run.py": source})

    assert report["status"] == "failed"
    codes = {diagnostic["code"] for diagnostic in report["diagnostics"]}
    assert "blocked_path" in codes
    assert "blocked_filesystem" in codes


def test_validator_does_not_leak_path_import_alias_from_dormant_function():
    source = (
        "import os\n"
        "def dormant():\n"
        "    from pathlib import Path as ResultPath\n"
        "result_path = ResultPath(os.environ['BACKTRADER_MCP_RESULT'])\n"
        "result_path.write_text('escaped', encoding='utf-8')\n"
    )

    report = validate_sources({"run.py": source})

    assert report["status"] == "failed"
    assert any(diagnostic["code"] == "blocked_filesystem" for diagnostic in report["diagnostics"])


@pytest.mark.parametrize(
    "factory",
    [
        "Path.home()",
        "Path.cwd()",
        "Path()",
        "Path('relative-result.json')",
        "pathlib.Path.home()",
    ],
)
def test_validator_blocks_all_non_worker_path_factories(factory):
    imports = "import pathlib\n" if factory.startswith("pathlib.") else "from pathlib import Path\n"
    report = validate_sources({"run.py": f"{imports}result_path = {factory}\n"})

    assert report["status"] == "failed"
    assert any(diagnostic["code"] == "blocked_path" for diagnostic in report["diagnostics"])


def test_repair_invalidates_old_validation_token(registered_dataset):
    service, dataset = registered_dataset
    draft = service.create_strategy_draft(
        canonical_spec(dataset["dataset_id"], "single_data_indicator")
    )
    current = service.get_strategy_draft(draft["draft_id"])
    path = "strategy.py"
    original = current["files"][path]
    broken = original + "\nexec('bad')\n"
    updated = service.update_strategy_draft(
        draft["draft_id"],
        path,
        broken,
        current["revision"],
        current["manifest"][path],
    )
    validation = service.validate_strategy_draft(draft["draft_id"], updated["revision"])
    assert validation["report"]["status"] == "failed"
    repaired = service.apply_strategy_repair(
        draft["draft_id"],
        validation["validation_id"],
        path,
        original,
        updated["revision"],
        updated["manifest"][path],
        "repair-1",
    )
    assert repaired["prior_validation_invalidated"] is True
    with pytest.raises(Conflict):
        service.drafts.verify_validation(draft["draft_id"], validation["validation_token"])


def test_prepare_local_approval_apply_and_idempotency(registered_dataset):
    service, dataset = registered_dataset
    draft = service.create_strategy_draft(
        canonical_spec(dataset["dataset_id"], "single_data_indicator")
    )
    validation = service.validate_strategy_draft(draft["draft_id"], draft["revision"])
    prepared = service.prepare_strategy_changes(
        draft["draft_id"],
        validation["validation_token"],
        "strategies",
        "managed",
        {},
        "prepare-1",
    )
    with pytest.raises(Conflict):
        service.apply_strategy_changes(
            prepared["change_set_id"],
            prepared["change_token"],
            "approval_missing",
            "apply-missing",
        )
    approval = service.changes.approve_change(prepared["change_set_id"], prepared["change_token"])
    applied = service.apply_strategy_changes(
        prepared["change_set_id"],
        prepared["change_token"],
        approval["approval_id"],
        "apply-1",
    )
    replay = service.apply_strategy_changes(
        prepared["change_set_id"],
        prepared["change_token"],
        approval["approval_id"],
        "apply-1",
    )
    assert replay == applied
    assert (service.settings.target_roots["strategies"] / "managed" / "strategy.py").is_file()
    forged = prepared["change_token"][:-1] + ("A" if prepared["change_token"][-1] != "A" else "B")
    with pytest.raises(Forbidden):
        service.changes.approve_change(prepared["change_set_id"], forged)


def test_source_attached_catalog_refresh_and_staleness(service_env):
    service, _, target = service_env
    source = target / "source_strategy.py"
    source.write_text(
        "import backtrader as bt\n\nclass Attached(bt.Strategy):\n    def next(self):\n        pass\n"
    )
    snapshot = service.refresh_strategy_catalog("strategies")
    assert len(snapshot["entries"]) == 1
    entry = snapshot["entries"][0]
    inspected = service.inspect_strategy(
        entry["id"], entry["metadata"]["source_record"]["source_sha256"]
    )
    assert inspected["status"] == "ready"
    source.write_text(source.read_text() + "\n# changed\n")
    assert service.inspect_strategy(entry["id"])["status"] == "stale"
    assert service.list_strategy_templates()["count"] == 14
