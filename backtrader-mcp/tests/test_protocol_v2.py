from __future__ import annotations

import asyncio
import importlib.metadata
from pathlib import Path

import pytest

if not importlib.metadata.version("mcp").startswith("2."):
    pytest.skip("protocol test requires isolated mcp==2.0.0", allow_module_level=True)

from mcp.client import Client

from backtrader_mcp.server import create_server
from backtrader_mcp.settings import Settings


def _create_synthetic_runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    package = runtime / "backtrader"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "__version__ = '1.3.0'\n"
        "class Cerebro: pass\n"
        "class Strategy: pass\n"
        "class GenericCSVData: pass\n"
        "class PandasData: pass\n"
        "class Feeds:\n"
        "    pass\n"
        "feeds = Feeds()\n"
        "feeds.GenericCSVData = GenericCSVData\n"
        "feeds.PandasData = PandasData\n",
        encoding="utf-8",
    )
    return runtime


def test_mcp_v2_typed_surface(tmp_path):
    async def exercise():
        settings = Settings(
            state_root=tmp_path / "state",
            source_roots={},
            target_roots={},
            runtimes={},
        )
        server = create_server(settings)
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "doctor",
                "validate_strategy_spec",
                "refresh_strategy_catalog",
                "apply_strategy_repair",
                "prepare_strategy_changes",
                "apply_strategy_changes",
                "prepare_strategy_run",
                "start_strategy_run",
                "get_run_status",
                "cancel_strategy_run",
                "compare_strategy_runs",
                "render_strategy_report",
            } <= names
            result = await client.call_tool("get_catalog_snapshot", {})
            assert not result.is_error
            prompts = await client.list_prompts()
            assert len(prompts.prompts) == 8
            resources = await client.list_resources()
            resource_uris = {str(resource.uri) for resource in resources.resources}
            assert "backtrader-mcp://strategy/templates" in resource_uris
            assert "backtrader-mcp://strategy/contract" in resource_uris

    asyncio.run(exercise())


def test_mcp_v2_typed_doctor_is_read_only(tmp_path):
    async def exercise():
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        runtime = _create_synthetic_runtime(tmp_path)
        state = tmp_path / "state"
        settings = Settings(
            state_root=state,
            source_roots={"source": source},
            target_roots={"target": target},
            runtimes={"default": runtime},
        )
        server = create_server(settings)
        assert not state.exists(), "constructing the typed server must not initialize state"

        async with Client(server) as client:
            result = await client.call_tool("doctor", {})
            assert not result.is_error

        assert not state.exists(), "typed doctor must not create SQLite, secrets, or recovery state"
        assert not list(runtime.rglob("*.pyc"))
        assert not list(runtime.rglob("__pycache__"))

    asyncio.run(exercise())
