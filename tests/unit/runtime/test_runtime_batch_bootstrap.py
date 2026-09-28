"""Acceptance coverage for reviewed multi-runtime bootstrap operations."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Tuple

import pytest

from backtrader_runtime import (
    PRESET_POLICY_VIOLATION,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
    RuntimeSet,
    bootstrap_runtime_config,
    bootstrap_runtime_set,
)
from backtrader_runtime.cli import main
import backtrader_runtime.registry as runtime_registry


def _registry(tmp_path: Path) -> Tuple[RuntimeRegistry, Tuple[Path, Path]]:
    first = tmp_path / "first" / "runtime"
    second = tmp_path / "second" / "runtime"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    first_registration = RegisteredRuntime(
        runtime_dir=first,
        strategy_id="example.first",
        allowed_presets=("replay",),
    )
    second_registration = RegisteredRuntime(
        runtime_dir=second,
        strategy_id="example.second",
        allowed_presets=("local_backtest", "replay"),
    )
    return (
        RuntimeRegistry(
            (first_registration, second_registration),
            runtime_sets=(
                RuntimeSet(
                    name="safe-fixtures",
                    runtime_ids=("example.first", "example.second"),
                ),
            ),
        ),
        (first, second),
    )


def _payload(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue())


def _attempt_parent_swap(parent: Path, old_parent: Path, replacement_runtime: Path) -> str:
    """Try a full parent replacement, including a same-name runtime target."""

    program = """
from pathlib import Path
import sys

parent = Path(sys.argv[1])
old_parent = Path(sys.argv[2])
replacement_runtime = Path(sys.argv[3])
try:
    parent.rename(old_parent)
except OSError:
    print("blocked")
else:
    replacement_runtime.mkdir(parents=True)
    print("replaced")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(parent),
            str(old_parent),
            str(replacement_runtime),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_batch_bootstrap_creates_a_reviewed_runtime_set_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    registry, directories = _registry(tmp_path)

    first = bootstrap_runtime_set("safe-fixtures", registry)

    assert first.status == "bootstrapped"
    assert [item.status for item in first.items] == ["created", "created"]
    assert [item.preset for item in first.items] == ["replay", "local_backtest"]
    assert all((directory / "config.yaml").is_file() for directory in directories)

    second = bootstrap_runtime_set("safe-fixtures", registry)

    assert second.status == "bootstrapped"
    assert [item.status for item in second.items] == ["already_matching", "already_matching"]
    assert all(item.config_digest for item in second.items)


def test_bootstrap_creation_uses_the_same_sealed_descriptor_for_its_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creation must not reopen a pathname after O_EXCL has succeeded."""

    registry, (first, second) = _registry(tmp_path)

    def fail_path_reload(*_args, **_kwargs):
        raise AssertionError("bootstrap must not call load_runtime_config after creation")

    monkeypatch.setattr(runtime_registry, "load_runtime_config", fail_path_reload)

    single = bootstrap_runtime_config(first, registry, "replay")
    assert single.strategy_id == "example.first"

    # The first target is already canonical.  The second target is created in
    # this batch; neither result may be derived from a second pathname load.
    batch = bootstrap_runtime_set("safe-fixtures", registry)
    assert batch.status == "bootstrapped"
    assert [item.status for item in batch.items] == ["already_matching", "created"]
    assert (second / "config.yaml").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory lease coverage")
def test_windows_bootstrap_directory_lease_blocks_parent_replacement_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bootstrap config cannot land under a concurrently swapped parent."""

    registry, (first, _) = _registry(tmp_path)
    original_writer = runtime_registry.write_bootstrap_config
    old_parent = tmp_path / "first-before-bootstrap"
    replacement_attempts = []

    def verify_then_create(path, content, *, directory_fd=None):
        replacement_attempts.append(_attempt_parent_swap(first.parent, old_parent, first))
        return original_writer(path, content, directory_fd=directory_fd)

    monkeypatch.setattr(runtime_registry, "write_bootstrap_config", verify_then_create)

    config = bootstrap_runtime_config(first, registry, "replay")

    assert replacement_attempts == ["blocked"]
    assert config.source_path == first / "config.yaml"
    assert (first / "config.yaml").is_file()
    assert not old_parent.exists()


def test_bootstrap_does_not_report_created_when_postwrite_bytes_are_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-create replacement fails closed instead of reporting its digest."""

    registry, (first, _) = _registry(tmp_path)
    original_writer = runtime_registry.write_bootstrap_config

    def create_then_replace(path, content, *, directory_fd=None):
        result = original_writer(path, content, directory_fd=directory_fd)
        Path(path).write_text("operator replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(runtime_registry, "write_bootstrap_config", create_then_replace)

    with pytest.raises(RuntimeConfigError) as caught:
        bootstrap_runtime_config(first, registry, "replay")

    assert caught.value.reason == "config_identity_changed"


def test_batch_bootstrap_reports_postwrite_replacement_as_creation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch creation cannot relabel a changed descriptor as already matching."""

    registry, _ = _registry(tmp_path)
    original_writer = runtime_registry.write_bootstrap_config

    def create_then_replace(path, content, *, directory_fd=None):
        result = original_writer(path, content, directory_fd=directory_fd)
        Path(path).write_text("operator replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(runtime_registry, "write_bootstrap_config", create_then_replace)

    result = bootstrap_runtime_set("safe-fixtures", registry)

    assert result.status == "partial"
    assert [item.status for item in result.items] == ["creation_failed", "creation_failed"]
    assert [item.reason for item in result.items] == [
        "config_identity_changed",
        "config_identity_changed",
    ]


def test_batch_bootstrap_preflights_every_target_before_writing_any_missing_config(
    tmp_path: Path,
) -> None:
    registry, (first, second) = _registry(tmp_path)
    (first / "config.yaml").write_text("operator-owned configuration\n", encoding="utf-8")

    result = bootstrap_runtime_set("safe-fixtures", registry)

    assert result.status == "preflight_failed"
    assert [item.status for item in result.items] == ["conflict", "not_written"]
    assert result.items[0].reason == "existing_config_differs"
    assert result.items[1].reason == "batch_preflight_failed"
    assert not (second / "config.yaml").exists()


def test_cli_batch_bootstrap_uses_only_a_reviewed_runtime_set_name(tmp_path: Path) -> None:
    registry, directories = _registry(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--runtime-set", "safe-fixtures"],
        registry=registry,
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0
    payload = _payload(stdout)
    assert payload["status"] == "bootstrapped"
    assert payload["runtime_set"] == "safe-fixtures"
    assert [item["status"] for item in payload["items"]] == ["created", "created"]
    assert stderr.getvalue() == ""
    assert all((directory / "config.yaml").is_file() for directory in directories)

    stderr = io.StringIO()
    status = main(
        ["bootstrap", "--runtime-set", "unreviewed-path-list"],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejected = _payload(stderr)
    assert rejected["error_code"] == PRESET_POLICY_VIOLATION
    assert rejected["reason"] == "runtime_set_not_registered"


def test_cli_batch_bootstrap_rejects_user_selected_presets(tmp_path: Path) -> None:
    registry, directories = _registry(tmp_path)
    stderr = io.StringIO()

    status = main(
        ["bootstrap", "--runtime-set", "safe-fixtures", "--preset", "replay"],
        registry=registry,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejected = _payload(stderr)
    assert rejected["error_code"] == PRESET_POLICY_VIOLATION
    assert rejected["reason"] == "batch_bootstrap_preset_not_allowed"
    assert all(not (directory / "config.yaml").exists() for directory in directories)
