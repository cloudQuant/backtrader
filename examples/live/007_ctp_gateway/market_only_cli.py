"""Small single-strategy CLI for the 007 CTP MarketHub-only observer.

This entry point has no recovery or trading switch. It accepts one strategy,
one bounded duration, and one pre-provisioned resource root. The SDK's fixed
strategy reference is protected by a per-user cross-process lease.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


_MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
_SIBLINGS: dict[str, ModuleType] = {}


def _load_sibling(name: str) -> ModuleType:
    module = _SIBLINGS.get(name)
    if module is not None:
        return module
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_market_only_cli_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MARKET_ONLY_SOURCE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _SIBLINGS[name] = module
    return module


class _OneStrategy(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, "may be supplied exactly once")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    runner = _load_sibling("market_only_runner")
    parser = argparse.ArgumentParser(
        description="Observe one 007 CTP strategy through Gateway MarketHub."
    )
    parser.add_argument(
        "--strategy",
        required=True,
        choices=tuple(runner.STRATEGIES),
        action=_OneStrategy,
        help="one strategy name from the fixed 007 allowlist",
    )
    parser.add_argument(
        "--duration-seconds",
        required=True,
        type=int,
        help=f"finite observation duration (1..{_MAX_DURATION_SECONDS})",
    )
    parser.add_argument(
        "--resource-root",
        required=True,
        help="absolute owner-only generation directory",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    resource_loader: Callable[..., Any] | None = None,
    lease_factory: Callable[[], Any] | None = None,
    runner: Callable[..., Any] | None = None,
    receipt_factory: Callable[..., Any] | None = None,
) -> int:
    """Run one bounded observation; injectable callables are for fake tests."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.duration_seconds <= _MAX_DURATION_SECONDS:
        parser.error("--duration-seconds is outside the finite allowed range")

    resources = _load_sibling("market_only_resources")
    strategy_runner = _load_sibling("market_only_runner")
    resource_loader = resource_loader or resources.load_market_connection
    lease_factory = lease_factory or resources.GlobalMarketIdentityLease
    runner = runner or strategy_runner.run_market_only
    receipt_factory = receipt_factory or resources.MarketOnlyReceiptSink

    lease = None
    try:
        # Acquire the one fixed SDK strategy identity before reading key files.
        # A durable marker from an uncertain prior close blocks this process
        # and every other process using the same user-global state directory.
        lease = lease_factory()
        lease.acquire()
        loaded = resource_loader(args.resource_root)

        resources._secure_windows_directory(
            loaded.resource_root / "strategies-market-only", create=True
        )
        identity = strategy_runner.create_market_only_run_identity(
            loaded.resource_root, bucket="strategies-market-only"
        )
        resources._secure_created_windows_directory(identity.run_root)
        receipt = receipt_factory(
            identity.run_root / "receipt.json",
            generation_id=loaded.generation_id,
            run_id=identity.run_id,
            connection_json_sha256=loaded.connection_json_sha256,
        )
        runner(
            args.strategy,
            connection=loaded.connection,
            run_root=loaded.resource_root,
            run_seconds=args.duration_seconds,
            generation_id=loaded.generation_id,
            run_identity=identity,
            receipt_sink=receipt,
            identity_guard=lease,
        )
        print(f"MARKET_ONLY_COMPLETE strategy={args.strategy} run_id={identity.run_id}")
        return 0
    except Exception as exc:
        code = getattr(exc, "code", None)
        if type(code) is not str or not code.isascii() or not code.replace("_", "").isalnum():
            code = "MARKET_ONLY_FAILED"
        print(code, file=sys.stderr)
        return 2
    finally:
        if lease is not None:
            try:
                lease.release_unstarted()
            except Exception:
                # A held/uncertain lease remains fail-closed. This is only a
                # best-effort release for failures before the active marker.
                pass


if __name__ == "__main__":  # pragma: no cover - exercised by the installed CLI
    raise SystemExit(main())
