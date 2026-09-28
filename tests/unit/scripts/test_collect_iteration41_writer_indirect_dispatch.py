"""Contract tests for static writer method aliases; no example is imported."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "collect_iteration41_writer_inventory.py"


def _collector_module():
    name = "iteration41_writer_alias_inventory_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_finds_injected_broker_method_alias_dispatch(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    fixture_dir = source_root / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "runner.py").write_text(
        "class Runner:\n"
        "    def submit(self, broker, leg, order_kwargs):\n"
        "        method = broker.buy if leg.side == 'buy' else broker.sell\n"
        "        return method(**order_kwargs)\n"
        "\n"
        "    def cancel(self, broker, order_ref):\n"
        "        cancel = getattr(broker, 'cancel_order', None)\n"
        "        return cancel(order_ref)\n"
        "\n"
        "    def sdk_dispatch(self, api, async_name, request):\n"
        "        writer = getattr(api, async_name, None)\n"
        "        return writer(request)\n"
        "\n"
        "class Proxy:\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(self.api, name)\n",
        encoding="utf-8",
    )
    collector = _collector_module()

    report = collector.collect_inventory(source_root, ("fixture",))

    assert report["counts"]["writer_candidates"] == 3
    assert [
        (row["call"], row["method"], row["dynamic_reason"])
        for row in report["writer_candidates"]
    ] == [
        ("method", "buy", "writer_alias_dispatch"),
        ("method", "sell", "writer_alias_dispatch"),
        ("cancel", "cancel_order", "writer_alias_dispatch"),
    ]
    assert [
        (row["call"], row["dynamic_reason"])
        for row in report["dynamic_execution_candidates"]
    ] == [
        ("getattr", "writer_reflection"),
        ("writer", "indirect_callable_alias"),
        ("getattr", "dynamic_attribute_forwarder"),
    ]
