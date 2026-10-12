"""Iteration 42 root-manifest source binding against each real legacy loader.

Negative tests build an isolated examples tree from tracked public templates.
The canonical-root case also exercises the real loader against its unchanged
HERE after checking that its public config matches tracked content. No ignored config,
approval credentials, signed receipts, or runtime handlers are used.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_utils.optional_sdk import optional_sdk


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
MANIFEST_PATH = EXAMPLES / "strategy-candidate-manifest.json"

ENTRY_SOURCES = {
    "012_1_midfreq_cross_exchange": (
        "cross_exchange_strategy.py",
        "examples.unified.012_1_midfreq_cross_exchange.legacy_runner",
    ),
    "012_2_event_driven_cross_exchange": (
        "event_driven_strategy.py",
        "examples.unified.012_2_event_driven_cross_exchange.legacy_runner",
    ),
}
REBOUND_FIELDS = frozenset(
    {
        "resolved_example_path",
        "runner_sha256",
        "strategy_sha256",
        "config_sha256",
        "candidate_sha256",
    }
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate_sha256(candidate: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(canonical)


def _tracked_head_config(relative_path: str) -> bytes:
    """Read only a tracked public config blob, never its checkout path."""
    tracked_path = subprocess.check_output(
        ["git", "ls-files", "--error-unmatch", "--", relative_path],
        cwd=ROOT,
        text=True,
    ).strip()
    assert tracked_path == relative_path

    # A stat-only M after restoring LF does not establish a content change.
    # Compare Git content rather than requiring the index stat cache to refresh.
    subprocess.check_call(
        ["git", "diff", "--quiet", "HEAD", "--", relative_path], cwd=ROOT
    )

    return subprocess.check_output(
        ["git", "cat-file", "--filters", f"HEAD:{relative_path}"],
        cwd=ROOT,
    )


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_rebound_tree(tmp_path: Path) -> dict[str, Any]:
    """Mirror the narrow root-manifest rebind in a temporary examples layout."""
    original = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest = copy.deepcopy(original)
    original_rows = {
        row["strategy_id"]: row for row in original["candidates"]
    }
    rows = {
        row["strategy_id"]: row for row in manifest["candidates"]
    }
    assert set(rows) == set(ENTRY_SOURCES)

    temp_examples = tmp_path / "examples"
    temp_manifest_path = temp_examples / "strategy-candidate-manifest.json"
    example_dirs: dict[str, Path] = {}
    source_bytes: dict[str, dict[str, bytes]] = {}

    for strategy_id, (strategy_name, _module_name) in ENTRY_SOURCES.items():
        source_dir = EXAMPLES / "unified" / strategy_id
        entrypoint_name = rows[strategy_id]["entrypoint"]
        assert entrypoint_name == "run.py"

        relative_config = f"examples/unified/{strategy_id}/config.yaml"
        raw = {
            "runner": (source_dir / entrypoint_name).read_bytes(),
            "strategy": (source_dir / strategy_name).read_bytes(),
            "config": _tracked_head_config(relative_config),
        }
        example_dir = temp_examples / "unified" / strategy_id
        example_dir.mkdir(parents=True)
        (example_dir / entrypoint_name).write_bytes(raw["runner"])
        (example_dir / strategy_name).write_bytes(raw["strategy"])
        (example_dir / "config.yaml").write_bytes(raw["config"])

        row = rows[strategy_id]
        row["resolved_example_path"] = f"unified/{strategy_id}"
        row["runner_sha256"] = _sha256(raw["runner"])
        row["strategy_sha256"] = _sha256(raw["strategy"])
        row["config_sha256"] = _sha256(raw["config"])
        row["candidate_sha256"] = _candidate_sha256(row)

        # Verify the actual canonical root manifest, not just a fixture that
        # silently repairs a stale manifest before exercising the loader.
        assert {
            key: original_rows[strategy_id][key] for key in REBOUND_FIELDS
        } == {key: row[key] for key in REBOUND_FIELDS}

        example_dirs[strategy_id] = example_dir
        source_bytes[strategy_id] = raw

    # Rebinding is limited to the five content-addressed path/hash fields.
    for strategy_id, old in original_rows.items():
        new = rows[strategy_id]
        assert {
            key: value for key, value in old.items() if key not in REBOUND_FIELDS
        } == {
            key: value for key, value in new.items() if key not in REBOUND_FIELDS
        }
    assert {
        key: value for key, value in original.items() if key != "candidates"
    } == {
        key: value for key, value in manifest.items() if key != "candidates"
    }

    temp_examples.mkdir(parents=True, exist_ok=True)
    _write_manifest(temp_manifest_path, manifest)
    return {
        "original": original,
        "manifest": manifest,
        "manifest_path": temp_manifest_path,
        "example_dirs": example_dirs,
        "source_bytes": source_bytes,
    }


def _load_actual_runner(strategy_id: str, monkeypatch, tree: dict[str, Any]):
    optional_sdk()
    _strategy_name, module_name = ENTRY_SOURCES[strategy_id]
    runner = importlib.import_module(module_name)
    assert strategy_id == runner.STRATEGY_ID
    monkeypatch.setattr(runner, "HERE", tree["example_dirs"][strategy_id])
    monkeypatch.setattr(runner, "MANIFEST_PATH", tree["manifest_path"])
    return runner


@pytest.fixture
def rebound_tree(tmp_path: Path) -> dict[str, Any]:
    return _build_rebound_tree(tmp_path)


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_canonical_root_manifest_is_source_bound(strategy_id: str) -> None:
    optional_sdk()
    strategy_name, module_name = ENTRY_SOURCES[strategy_id]
    runner = importlib.import_module(module_name)
    expected_dir = (EXAMPLES / "unified" / strategy_id).resolve()
    public_config = _tracked_head_config(
        f"examples/unified/{strategy_id}/config.yaml"
    )
    # Git's declared LF policy must survive a fresh checkout/copy, not merely
    # match a stale CRLF working copy on the acceptance machine.
    public_runner = _tracked_head_config(f"examples/unified/{strategy_id}/run.py")
    public_strategy = _tracked_head_config(
        f"examples/unified/{strategy_id}/{strategy_name}"
    )
    assert expected_dir == runner.HERE
    assert runner.REPO_CANONICAL_MANIFEST.resolve() == MANIFEST_PATH.resolve()
    manifest, candidate, manifest_path = runner.load_candidate(
        manifest_path=runner.REPO_CANONICAL_MANIFEST
    )
    assert manifest_path == MANIFEST_PATH.resolve()
    assert (manifest_path.parent / candidate["resolved_example_path"]).resolve() == expected_dir
    assert candidate["runner_sha256"] == _sha256(public_runner)
    assert candidate["strategy_sha256"] == _sha256(public_strategy)
    assert candidate["config_sha256"] == _sha256(public_config)
    assert candidate["candidate_sha256"] == _candidate_sha256(candidate)
    assert manifest["manifest_status"] == "RESEARCH_REJECTED_OPERATOR_DEMO_SIMULATION_ONLY"
    assert candidate["research_status"] == "RESEARCH_REJECTED"
    assert candidate["demo_approval"]["status"] == "NOT_APPROVED"


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_legacy_loader_rejects_stale_strategy_source(
    strategy_id: str, monkeypatch: pytest.MonkeyPatch, rebound_tree: dict[str, Any]
) -> None:
    runner = _load_actual_runner(strategy_id, monkeypatch, rebound_tree)
    strategy_name, _module_name = ENTRY_SOURCES[strategy_id]
    path = rebound_tree["example_dirs"][strategy_id] / strategy_name
    path.write_bytes(path.read_bytes() + b"\n# stale public strategy fixture\n")
    with pytest.raises(
        runner.RunnerConfigurationError, match="strategy source fingerprint mismatch"
    ):
        runner.load_candidate(manifest_path=rebound_tree["manifest_path"])


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_legacy_loader_accepts_rebound_root_manifest(
    strategy_id: str, monkeypatch: pytest.MonkeyPatch, rebound_tree: dict[str, Any]
) -> None:
    runner = _load_actual_runner(strategy_id, monkeypatch, rebound_tree)

    # Pass the synthetic canonical manifest explicitly: load_candidate's
    # default argument captured the source MANIFEST_PATH when the module loaded.
    loaded_manifest, candidate, loaded_path = runner.load_candidate(
        manifest_path=rebound_tree["manifest_path"]
    )

    expected = rebound_tree["manifest"]
    expected_candidate = next(
        row for row in expected["candidates"] if row["strategy_id"] == strategy_id
    )
    assert loaded_manifest == expected
    assert candidate == expected_candidate
    assert loaded_path == rebound_tree["manifest_path"].resolve()
    assert loaded_path.name == "strategy-candidate-manifest.json"
    assert candidate["resolved_example_path"] == f"unified/{strategy_id}"
    assert candidate["runner_sha256"] == _sha256(
        rebound_tree["source_bytes"][strategy_id]["runner"]
    )
    assert candidate["strategy_sha256"] == _sha256(
        rebound_tree["source_bytes"][strategy_id]["strategy"]
    )
    assert candidate["config_sha256"] == _sha256(
        rebound_tree["source_bytes"][strategy_id]["config"]
    )
    assert candidate["candidate_sha256"] == _candidate_sha256(candidate)

    # The rebind must retain the rejected research and unsigned demo state.
    assert loaded_manifest["manifest_status"] == (
        "RESEARCH_REJECTED_OPERATOR_DEMO_SIMULATION_ONLY"
    )
    assert candidate["research_status"] == "RESEARCH_REJECTED"
    assert candidate["demo_approval"] == {
        "status": "NOT_APPROVED",
        "receipt_path": None,
        "receipt_sha256": None,
    }
    if strategy_id == "012_2_event_driven_cross_exchange":
        assert candidate["hft_label"] == "event_driven"
        assert candidate["hft_gate"]["status"] == "FAIL"
        assert candidate["evidence_level"].endswith("_HFT_FAILED")


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_legacy_loader_rejects_wrong_root_manifest_example_path(
    strategy_id: str, monkeypatch: pytest.MonkeyPatch, rebound_tree: dict[str, Any]
) -> None:
    runner = _load_actual_runner(strategy_id, monkeypatch, rebound_tree)
    altered = copy.deepcopy(rebound_tree["manifest"])
    candidate = next(
        row for row in altered["candidates"] if row["strategy_id"] == strategy_id
    )
    candidate["resolved_example_path"] = strategy_id
    candidate["candidate_sha256"] = _candidate_sha256(candidate)
    _write_manifest(rebound_tree["manifest_path"], altered)

    with pytest.raises(
        runner.RunnerConfigurationError,
        match="manifest resolves to a different example",
    ):
        runner.load_candidate(manifest_path=rebound_tree["manifest_path"])


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_legacy_loader_rejects_stale_runner_source(
    strategy_id: str, monkeypatch: pytest.MonkeyPatch, rebound_tree: dict[str, Any]
) -> None:
    runner = _load_actual_runner(strategy_id, monkeypatch, rebound_tree)
    entrypoint = rebound_tree["example_dirs"][strategy_id] / "run.py"
    entrypoint.write_bytes(entrypoint.read_bytes() + b"\n# stale runner fixture\n")

    candidate = next(
        row
        for row in rebound_tree["manifest"]["candidates"]
        if row["strategy_id"] == strategy_id
    )
    assert candidate["candidate_sha256"] == _candidate_sha256(candidate)

    with pytest.raises(
        runner.RunnerSourceBindingError,
        match="runner source fingerprint mismatch",
    ):
        runner.load_candidate(manifest_path=rebound_tree["manifest_path"])


@pytest.mark.parametrize("strategy_id", tuple(ENTRY_SOURCES))
def test_real_legacy_loader_rejects_stale_candidate_fingerprint(
    strategy_id: str, monkeypatch: pytest.MonkeyPatch, rebound_tree: dict[str, Any]
) -> None:
    runner = _load_actual_runner(strategy_id, monkeypatch, rebound_tree)
    altered = copy.deepcopy(rebound_tree["manifest"])
    candidate = next(
        row for row in altered["candidates"] if row["strategy_id"] == strategy_id
    )
    candidate["candidate_sha256"] = "0" * 64
    assert candidate["candidate_sha256"] != _candidate_sha256(candidate)
    _write_manifest(rebound_tree["manifest_path"], altered)

    with pytest.raises(
        runner.RunnerConfigurationError,
        match="candidate fingerprint does not match manifest content",
    ):
        runner.load_candidate(manifest_path=rebound_tree["manifest_path"])
