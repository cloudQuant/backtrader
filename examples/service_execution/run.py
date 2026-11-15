#!/usr/bin/env python
"""Offline-first example: a strategy client routes a limit parent into Execution.

What this entry point proves in ``--dry-run``:

* the strategy-client configuration (``bt_api_py.service_config``) is valid;
* the ``execution_routing`` selection is valid and resolves to one account /
  strategy / domain, one Execution component, one instrument and the configured
  rule list;
* the selected scheduler class and v1 parameters (PASS / SLICE / TWAP) are
  well formed for the *client* side (the Execution service revalidates);
* the explicit Monitor relay selection resolves its trusted outbox scope;
* netting is disabled and the D67-01 calendar requirement is reported.

It starts no service, opens no network connection, reads no credential, creates
no checkpoint, sqlite journal or state directory, and does not read the calendar
directory. ``--live`` performs the same validation plus a bounded TCP
reachability probe and then refuses: this example never reads credentials or
fabricates the trusted wire identity a real parent submission needs.

Exit codes follow the repository example convention: 0 PASS, 1 FAIL,
2 BLOCKED. Every refusal prints one bounded JSON document.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import yaml

RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUN_DIR))

from execution_route_strategy import ExecutionRoutingDemoStrategy  # noqa: E402

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2

PLACEHOLDER_PREFIX = "REPLACE-"
MAX_ITEMS = 8
MAX_TEXT = 160
MAX_SCAN_NODES = 20_000
MAX_PROBES = 8
PROBE_TIMEOUT_SECONDS = 1.0

_TOP_LEVEL_KEYS = frozenset({"example", "client_config", "monitor_relay", "netting", "calendars"})
_MONITOR_SOURCES = frozenset({"projection", "journal", "none"})
_SCHEDULER_CLASSES = frozenset({"PASS", "SLICE", "TWAP"})
_CHILD_PRICES = frozenset({"limit", "passive", "cross"})
_MISSED_POLICIES = frozenset({"DROP", "ROLL_FORWARD"})
# Canonical positive decimal text, mirroring the Execution v1 quantity contract.
_POSITIVE_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z")


class ExampleRefusal(ValueError):
    """A finite, value-free refusal with a stable ``code``."""

    def __init__(self, code, path=None):
        self.code = code
        self.path = path
        super().__init__(code)


class _StrictLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently keeping the last."""


def _construct_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:
            raise yaml.constructor.ConstructorError(
                None, None, "unhashable mapping key", key_node.start_mark
            ) from None
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate mapping key", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _bounded(value):
    text = value if type(value) is str else str(value)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "..."


def _require_dict(value, path):
    if type(value) is not dict:
        raise ExampleRefusal("config_type_invalid", path)
    return value


def _require_exact_keys(value, keys, path):
    _require_dict(value, path)
    if set(value) != set(keys):
        raise ExampleRefusal("config_key_invalid", path)
    return value


def _require_text(value, path):
    if type(value) is not str or not value or value != value.strip():
        raise ExampleRefusal("config_value_invalid", path)
    return _bounded(value)


def _load_config(config_path):
    try:
        text = config_path.read_text(encoding="utf-8")
        raw = yaml.load(text, Loader=_StrictLoader)
    except (OSError, yaml.YAMLError):
        raise ExampleRefusal("config_unavailable") from None
    _require_dict(raw, "$")
    if set(raw) - _TOP_LEVEL_KEYS:
        raise ExampleRefusal("unknown_config_key", "$")
    return raw


def _iter_strings(value):
    """Yield at most ``MAX_SCAN_NODES`` string leaves from a plain YAML tree."""
    stack = [(value, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > MAX_SCAN_NODES or depth > 48:
            return
        if type(node) is str:
            yield node
        elif type(node) is dict:
            stack.extend((item, depth + 1) for item in node.values())
        elif type(node) is list:
            stack.extend((item, depth + 1) for item in node)


def _placeholder_count(raw):
    count = sum(1 for text in _iter_strings(raw) if text.startswith(PLACEHOLDER_PREFIX))
    return count


def _instrument_plain(instrument):
    return {
        "provider": _bounded(instrument.provider),
        "venue": _bounded(instrument.venue),
        "environment": _bounded(instrument.environment),
        "product_type": _bounded(instrument.product_type),
        "instrument_id": _bounded(instrument.instrument_id),
        "native_symbol": _bounded(instrument.native_symbol),
    }


def _scheduler_report(policy):
    """Validate the client-side scheduler selection for one routing rule.

    This mirrors the Execution v1 contract; it is a pre-check, not the
    authority. The service validates class/version/params against its registry
    and the parent/plan facts before dispatching any child.
    """
    klass = policy.algorithm_class
    if klass not in _SCHEDULER_CLASSES:
        raise ExampleRefusal(
            "scheduler_class_unsupported", "execution_routing.rule.algorithm.class"
        )
    version = policy.algorithm_version
    if str(version) != "1":
        raise ExampleRefusal(
            "scheduler_version_unsupported", "execution_routing.rule.algorithm.version"
        )
    params = policy.algorithm_params
    if type(params) is not dict:
        raise ExampleRefusal("scheduler_config_invalid", "execution_routing.rule.algorithm.params")

    if klass == "PASS":
        if params:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params"
            )
        plan = "one child for the whole parent at the parent limit"
    elif klass == "SLICE":
        if set(params) != {"max_child_qty", "child_price", "child_timeout_s"}:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params"
            )
        _positive_decimal_text(params["max_child_qty"], "max_child_qty")
        if params["child_price"] not in _CHILD_PRICES:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params.child_price"
            )
        timeout = params["child_timeout_s"]
        if type(timeout) is not int or isinstance(timeout, bool) or timeout < 1:
            raise ExampleRefusal(
                "scheduler_config_invalid",
                "execution_routing.rule.algorithm.params.child_timeout_s",
            )
        plan = (
            "sequential children of at most {0} {1}; the next child waits for the "
            "previous child's terminal, aligned observation".format(
                _bounded(params["max_child_qty"]), _bounded(policy.rule.quantity_unit or "units")
            )
        )
    else:
        if set(params) != {
            "slices",
            "start_ns",
            "end_ns",
            "child_price",
            "missed_slice_policy",
        }:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params"
            )
        slices = params["slices"]
        start = params["start_ns"]
        end = params["end_ns"]
        if type(slices) is not int or isinstance(slices, bool) or not 1 <= slices <= 4096:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params.slices"
            )
        if (
            type(start) is not int
            or isinstance(start, bool)
            or type(end) is not int
            or isinstance(end, bool)
            or not 0 <= start < end
        ):
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params"
            )
        if params["child_price"] not in _CHILD_PRICES:
            raise ExampleRefusal(
                "scheduler_config_invalid", "execution_routing.rule.algorithm.params.child_price"
            )
        if params["missed_slice_policy"] not in _MISSED_POLICIES:
            raise ExampleRefusal(
                "scheduler_config_invalid",
                "execution_routing.rule.algorithm.params.missed_slice_policy",
            )
        plan = (
            "{0} equal time windows over [{1}, {2}); no default catch-up, missed "
            "slices follow {3}".format(slices, start, end, _bounded(params["missed_slice_policy"]))
        )

    return {
        "class": _bounded(klass),
        "version": 1,
        "params": _bounded_params(params),
        "plan": _bounded(plan),
    }


def _positive_decimal_text(value, name):
    path = "execution_routing.rule.algorithm.params.{0}".format(name)
    if type(value) is not str or len(value) > 128 or _POSITIVE_DECIMAL.fullmatch(value) is None:
        raise ExampleRefusal("scheduler_config_invalid", path)
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ExampleRefusal("scheduler_config_invalid", path) from None
    if not number.is_finite() or number <= 0:
        raise ExampleRefusal("scheduler_config_invalid", path)


def _bounded_params(params):
    result = {}
    for key in sorted(params):
        value = params[key]
        if type(value) is dict:
            result[_bounded(key)] = {
                _bounded(inner): _bounded(inner_value) for inner, inner_value in value.items()
            }
        elif type(value) is list:
            result[_bounded(key)] = [_bounded(item) for item in value[:MAX_ITEMS]]
        else:
            result[_bounded(key)] = _bounded(value)
    return result


def _rule_plain(policy):
    match = {}
    rule = policy.rule
    if rule.instrument is not None:
        match["instrument"] = _instrument_plain(rule.instrument)
    if rule.side is not None:
        match["side"] = _bounded(rule.side)
    if rule.offset is not None:
        match["offset"] = _bounded(rule.offset)
    if rule.order_type is not None:
        match["order_types"] = [_bounded(rule.order_type)]
    if rule.minimum_quantity is not None:
        match["minimum_quantity"] = _bounded(format(rule.minimum_quantity, "f"))
        match["quantity_unit"] = _bounded(rule.quantity_unit)
    return {
        "id": _bounded(policy.rule_id),
        "match": match,
        "scheme": {
            "name": _bounded(policy.scheme_name),
            "version": _bounded(policy.scheme_version),
        },
        "scheduler": _scheduler_report(policy),
        "deadline": _bounded(policy.deadline_at),
        "time_in_force": _bounded(policy.time_in_force),
        "trading_day": _bounded(policy.trading_day),
        "allowed_trading_days": [_bounded(day) for day in policy.allowed_trading_days[:MAX_ITEMS]],
        "allowed_trading_days_truncated": len(policy.allowed_trading_days) > MAX_ITEMS,
        "target_position_ref": (
            _bounded(policy.target_position_ref) if policy.target_position_ref is not None else None
        ),
    }


def _selection_summary(routing):
    instruments = [_instrument_plain(instrument) for instrument in routing.instruments[:MAX_ITEMS]]
    rules = [_rule_plain(policy) for policy in routing.policies[:MAX_ITEMS]]
    return {
        "account_ref": _bounded(routing.account_ref),
        "strategy_ref": _bounded(routing.strategy_ref),
        "execution_domain_ref": _bounded(routing.execution_domain_ref),
        "component": _bounded(routing.component),
        "grant_revision": _bounded(routing.grant_revision),
        "delegation": {
            "delegation_id": _bounded(routing.delegation_id),
            "principal_ref": _bounded(routing.delegation_principal_ref),
        },
        "instruments": instruments,
        "instruments_truncated": len(routing.instruments) > MAX_ITEMS,
        "rules": rules,
        "rules_truncated": len(routing.policies) > MAX_ITEMS,
    }


def _monitor_report(raw, routing):
    from bt_api_py.service_execution_monitor_composition import (
        ServiceExecutionMonitorCompositionError,
        derive_monitor_outbox_scope,
    )

    monitor = _require_dict(raw.get("monitor_relay"), "monitor_relay")
    unknown = set(monitor) - {"source", "scope_ref", "checkpoint_dir"}
    if unknown:
        raise ExampleRefusal("monitor_config_invalid", "monitor_relay")
    source = monitor.get("source")
    if type(source) is not str or source not in _MONITOR_SOURCES:
        raise ExampleRefusal("monitor_source_unsupported", "monitor_relay.source")

    scope_ref = monitor.get("scope_ref")
    checkpoint_dir = monitor.get("checkpoint_dir")
    if source == "none":
        if scope_ref is not None or checkpoint_dir is not None:
            raise ExampleRefusal("monitor_config_invalid", "monitor_relay")
        return {
            "source": "none",
            "status": "disabled: neither relay module is imported or constructed",
            "scope_key": None,
            "outbox_scope": None,
            "checkpoint": "none",
        }

    if type(scope_ref) is not str or not scope_ref or scope_ref != scope_ref.strip():
        raise ExampleRefusal("monitor_config_invalid", "monitor_relay.scope_ref")
    if (
        type(checkpoint_dir) is not str
        or not checkpoint_dir
        or checkpoint_dir != checkpoint_dir.strip()
    ):
        raise ExampleRefusal("monitor_config_invalid", "monitor_relay.checkpoint_dir")
    try:
        scope_key = derive_monitor_outbox_scope(
            source=source,
            execution_domain_ref=routing.execution_domain_ref,
            account_ref=routing.account_ref,
            strategy_ref=routing.strategy_ref,
        )
    except ServiceExecutionMonitorCompositionError as error:
        raise ExampleRefusal("monitor_scope_invalid", "monitor_relay") from error

    return {
        "source": _bounded(source),
        # The journal relay derives its own outbox scope from the trusted
        # journal; the composition deliberately exposes None for that source.
        "outbox_scope": _bounded(scope_key) if source == "projection" else None,
        "scope_key": _bounded(scope_key),
        "scope_ref": _bounded(scope_ref),
        "checkpoint": "configured (not created or read by the dry-run)",
        "status": "selected (not started; host owns start/maintain/poll/stop)",
    }


def _netting_report(raw):
    netting = _require_exact_keys(raw.get("netting"), {"enabled"}, "netting")
    enabled = netting["enabled"]
    if type(enabled) is not bool:
        raise ExampleRefusal("netting_config_invalid", "netting.enabled")
    if enabled:
        # Internal netting is a separate capability with its own account/service
        # contracts and evidence; this example must not imply it is covered.
        raise ExampleRefusal("netting_not_covered_by_example", "netting.enabled")
    return {
        "enabled": False,
        "status": "disabled: independent of routing and scheduling (D65-09)",
    }


def _calendar_report(raw):
    section = raw.get("calendars")
    if section is None:
        return {
            "status": "unconfigured",
            "code": "calendar_root_unconfigured",
            "live_start": "refused (D67-01); dry-run only reports",
        }
    section = _require_exact_keys(section, {"root"}, "calendars")
    root = section["root"]
    if type(root) is not str or not root or root != root.strip():
        return {
            "status": "unconfigured",
            "code": "calendar_root_unconfigured",
            "live_start": "refused (D67-01); dry-run only reports",
        }
    if root == "package_seed":
        return {
            "status": "refused",
            "code": "calendar_package_seed_unsupported",
            "live_start": "refused: this example does not bind the package seed (D67-01)",
        }
    return {
        "status": "configured",
        "root_kind": "external_directory",
        # D67-01: the offline path never reads the directory.
        "read_by_dry_run": False,
        "live_start": "allowed to proceed to the remaining live preconditions",
    }


def _tcp_reachable(endpoint):
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "tcp" or not host or port is None:
        return None
    try:
        connection = socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS)
    except OSError:
        return False
    try:
        connection.close()
    except OSError:
        pass
    return True


def _probe_endpoints(public):
    profiles = public.get("communication", {}).get("profiles", {})
    seen = set()
    checked = 0
    unreachable = 0
    invalid = 0
    for profile in profiles.values():
        endpoint = profile.get("endpoints", {}).get("rpc_connect")
        if not isinstance(endpoint, str) or endpoint in seen:
            continue
        seen.add(endpoint)
        if checked >= MAX_PROBES:
            break
        checked += 1
        reachable = _tcp_reachable(endpoint)
        if reachable is None:
            invalid += 1
        elif not reachable:
            unreachable += 1
    return {"checked": checked, "unreachable": unreachable, "invalid": invalid}


def _flow_steps(monitor, scheduler):
    return [
        "parse clients.execution.settings.options.execution_routing (no I/O)",
        "build the durable routing journal and ExecutionOrderRouter",
        "router.route(intent): persist original identity, submit one limit parent",
        "Execution service schedules the parent as {0}".format(scheduler["class"]),
        "assemble the monitor relay source={0} and poll on its owner thread".format(
            monitor["source"]
        ),
        "router.cancel(intent): cancel by the original request key/digest",
    ]


def _build_summary(config_path, *, live):
    raw = _load_config(config_path)

    example = _require_exact_keys(raw.get("example"), {"name"}, "example")
    example_name = _require_text(example["name"], "example.name")

    try:
        from bt_api_py.execution_routing import ExecutionRoutingError, parse_execution_routing
        from bt_api_py.service_config import ServiceConfigError, parse_client_config
    except ImportError:
        raise ExampleRefusal("sdk_unavailable", "bt_api_py") from None

    client_raw = raw.get("client_config")
    try:
        parsed = parse_client_config(client_raw)
    except ServiceConfigError as error:
        raise ExampleRefusal(error.code, error.path) from None
    except Exception:
        raise ExampleRefusal("client_config_invalid", "client_config") from None

    public = parsed.to_public_dict()
    option = (
        public.get("clients", {})
        .get("execution", {})
        .get("settings", {})
        .get("options", {})
        .get("execution_routing")
    )
    if option is None:
        raise ExampleRefusal(
            "execution_routing_not_selected",
            "client_config.clients.execution.settings.options",
        )
    try:
        routing = parse_execution_routing(option)
    except ExecutionRoutingError as error:
        raise ExampleRefusal(error.code, "execution_routing") from None

    selection = _selection_summary(routing)
    monitor = _monitor_report(raw, routing)
    netting = _netting_report(raw)
    calendar = _calendar_report(raw)
    placeholders = _placeholder_count(raw)
    scheduler = selection["rules"][0]["scheduler"] if selection["rules"] else None
    if scheduler is None:
        raise ExampleRefusal("execution_routing_rule_missing", "execution_routing.rules")

    summary = {
        "status": "PASS",
        "mode": "live-preflight" if live else "dry-run",
        "example": example_name,
        "strategy": {
            "module": "execution_route_strategy",
            "class": ExecutionRoutingDemoStrategy.__name__,
        },
        "sdk": {
            "client_config_fingerprint": parsed.fingerprint(),
            "routing_configuration_id": routing.configuration_id,
            "validated_without_io": True,
        },
        "selection": selection,
        "scheduler": scheduler,
        "monitor_relay": monitor,
        "netting": netting,
        "calendar": calendar,
        "placeholders": {
            "present": placeholders > 0,
            "count": placeholders,
            "live_start": (
                "refused until every REPLACE- value is operator-supplied"
                if placeholders
                else "none detected"
            ),
        },
        "flow": _flow_steps(monitor, scheduler),
    }

    if live:
        if placeholders:
            summary["status"] = "BLOCKED"
            summary["code"] = "example_placeholders_present"
            return summary
        if calendar["status"] != "configured":
            summary["status"] = "BLOCKED"
            summary["code"] = calendar["code"]
            return summary
        probe = _probe_endpoints(public)
        summary["service_probe"] = probe
        if probe["invalid"] or probe["unreachable"]:
            summary["status"] = "BLOCKED"
            summary["code"] = "service_endpoint_unavailable"
            return summary
        # The services are reachable and the configuration is operator-supplied,
        # but this example deliberately stops here: it does not read credentials
        # and does not fabricate the trusted runtime/wire identity.
        summary["status"] = "BLOCKED"
        summary["code"] = "trusted_runtime_and_credentials_required"
        summary["detail"] = (
            "wire the operator's trusted client runtime (identity, transport "
            "factory, credentials) and construct SdkExecutionRoutePort outside "
            "this example; no credential was read"
        )
        return summary

    return summary


def _print_json(value):
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Execution routing / scheduler / monitor-relay example (offline-first)"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="config path (relative to this folder)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate and print, no I/O")
    mode.add_argument(
        "--live",
        action="store_true",
        help="bounded preflight; never reads credentials and always fail-closed here",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.live:
        _print_json(
            {
                "status": "BLOCKED",
                "code": "mode_required",
                "detail": "use --dry-run (offline) or --live (bounded preflight)",
            }
        )
        return EXIT_BLOCKED

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = RUN_DIR / config_path

    try:
        summary = _build_summary(config_path, live=args.live)
    except ExampleRefusal as error:
        _print_json(
            {
                "status": "BLOCKED",
                "mode": "live-preflight" if args.live else "dry-run",
                "code": error.code,
                "path": error.path,
            }
        )
        return EXIT_BLOCKED
    except Exception:
        # Never print an exception message: it may contain operator values.
        _print_json(
            {
                "status": "FAIL",
                "mode": "live-preflight" if args.live else "dry-run",
                "code": "unexpected_failure",
            }
        )
        return EXIT_FAIL

    _print_json(summary)
    return EXIT_PASS if summary["status"] == "PASS" else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
