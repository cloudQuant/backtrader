from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def test_wheel_contains_contracts_policy_and_legal_files():
    wheel_value = os.environ.get("BACKTRADER_MCP_WHEEL")
    if not wheel_value:
        pytest.skip("set BACKTRADER_MCP_WHEEL to the wheel under acceptance")
    wheel = Path(wheel_value)
    assert wheel.is_file()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for contract in (
            "strategy-spec",
            "dataset-manifest",
            "corpus-manifest",
            "artifact-manifest",
            "validation-report",
            "run-manifest",
            "run-result",
        ):
            assert f"backtrader_mcp/schemas/{contract}.schema.json" in names
        assert "backtrader_mcp/policies/comparison-profile-v1.json" in names
        assert "backtrader_mcp/feed_runtime.py" in names
        snapshot_name = "backtrader_mcp/catalog_snapshot.jsonl"
        assert snapshot_name in names
        snapshot = archive.read(snapshot_name)
        assert (
            hashlib.sha256(snapshot).hexdigest()
            == "30973a10bd434e7935aa5b45577a5d5de0221a58b53a4c00a8124006438c5828"
        )
        assert len(snapshot.splitlines()) == 1156
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "Requires-Dist: mcp<2.1,>=2.0.0" in metadata
        assert "Requires-Dist: pandas<4,>=1.5" in metadata
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        assert any(name.endswith(".dist-info/licenses/NOTICE") for name in names)


def test_clean_wheel_catalog_import_does_not_need_a_sibling_checkout(tmp_path):
    wheel_value = os.environ.get("BACKTRADER_MCP_WHEEL")
    if not wheel_value:
        pytest.skip("set BACKTRADER_MCP_WHEEL to the wheel under acceptance")
    wheel = Path(wheel_value).resolve()
    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    run_root = tmp_path / "outside-repository"
    run_root.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "from pathlib import Path; from tempfile import TemporaryDirectory; "
                "from backtrader_mcp.catalog import CatalogService; "
                "from backtrader_mcp.settings import Settings; "
                "from backtrader_mcp.state import StateStore; "
                "t=TemporaryDirectory(); s=Settings(state_root=Path(t.name)); "
                "s.initialize(); c=CatalogService(s, StateStore(s.state_root)); "
                "print(c.get_snapshot()['extensions']['entry_count'], "
                "c.list_templates()['count'])"
            ),
        ],
        cwd=run_root,
        env={"PYTHONPATH": str(target), "PATH": os.environ.get("PATH", "")},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.stdout.strip() == "1155 14"
