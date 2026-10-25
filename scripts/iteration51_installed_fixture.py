#!/usr/bin/env python
"""Run the public 028 Alpha003 CLI against an installed Backtrader wheel.

The default profile copies the four public example files to a fresh directory
outside the checkout and runs only dry, research, or local replay.  A separate
``--synthetic-live`` profile runs the actual live CLI with in-memory CTP SDK
leaf modules under the installed Store, Broker, feed, and Cerebro path. The
installed ``btapistore`` CTP factory and its ``RegisteredSimWrapper`` /
``CtpClientWrapper`` composition stay intact. The child binds its causal
virtual UTC scheduler through the copied ``run.py`` function globals and keeps
real monotonic lifecycle bounds. It does not enable live in the offline
allowlist or change the four copied example files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLE = REPOSITORY_ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
PUBLIC_FILES = ("run.py", "entry_tier.py", "alpha003_strategy.py", "config.yaml")
SAFE_MODES = ("dry", "research", "replay")
SYNTHETIC_LIVE_CASES = ("read-only", "write", "write-denied", "tier-escalation")
EXPECTED_STATUSES = {
    "dry": "DRY_VALIDATION_COMPLETE",
    "research": "RESEARCH_COMPLETE",
    "replay": "REPLAY_COMPLETE",
}
RECEIPT_NAME = "iteration51-installed-cli-fixture.json"
_CHILD_MARKER = "ITERATION51_INSTALLED_CHILD="
_LIVE_CHILD_MARKER = "ITERATION51_SYNTHETIC_LIVE_CHILD="


class InstalledFixtureError(RuntimeError):
    """A public installed-wheel CLI check could not prove its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _require_external(path: Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if _is_within(resolved, REPOSITORY_ROOT):
        raise InstalledFixtureError(label + " must be outside the Backtrader checkout")
    return resolved


def copy_public_example(
    source_dir: Path,
    destination: Path,
    *,
    offline_config: Optional[Path] = None,
) -> tuple[Path, Path, dict[str, dict[str, Any]]]:
    """Copy exactly the four public runtime files into a new external folder.

    An optional offline configuration is copied separately as
    ``fixture-config.yaml``; it never replaces the pinned public template.
    """

    source = Path(source_dir).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise InstalledFixtureError("public example source is not a directory")
    target = _require_external(Path(destination), label="example destination")
    if target.exists():
        raise InstalledFixtureError("example destination must not already exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()

    source_files = {name: source / name for name in PUBLIC_FILES}
    for name, source_path in source_files.items():
        if source_path.is_symlink() or not source_path.is_file():
            raise InstalledFixtureError("public example file is missing or not regular: " + name)
    config_source = None
    if offline_config is not None:
        original_config = Path(offline_config).expanduser()
        if original_config.is_symlink():
            raise InstalledFixtureError("offline config must not be a symlink")
        config_source = original_config.resolve(strict=True)
        if (
            not config_source.is_file()
            or config_source.suffix.lower() not in {".yaml", ".yml"}
            or not _is_within(config_source, target.parent)
        ):
            raise InstalledFixtureError(
                "offline config must be a regular YAML fixture inside the external workspace"
            )

    files: dict[str, dict[str, Any]] = {}
    for name, source_path in source_files.items():
        destination_path = target / name
        shutil.copyfile(source_path, destination_path)
        source_hash = _sha256(source_path)
        destination_hash = _sha256(destination_path)
        if source_hash != destination_hash:
            raise InstalledFixtureError("public example copy changed bytes: " + name)
        files[name] = {
            "sha256": source_hash,
            "size_bytes": source_path.stat().st_size,
        }

    config_path = target / "config.yaml"
    if config_source is not None:
        config_path = target / "fixture-config.yaml"
        shutil.copyfile(config_source, config_path)
        files["fixture-config.yaml"] = {
            "sha256": _sha256(config_path),
            "size_bytes": config_path.stat().st_size,
            "role": "caller-supplied-public-offline-config",
        }
    return target, config_path, files


def _config_paths(config: Mapping[str, Any], config_path: Path, workspace: Path, mode: str):
    """Validate offline input/output paths stay inside the isolated workspace."""

    if config.get("mode") == "live":
        raise InstalledFixtureError("live configs are outside this installed fixture")
    output = config.get("output")
    selection = config.get("selection")
    inputs = config.get("inputs")
    if not all(isinstance(value, Mapping) for value in (output, selection, inputs)):
        raise InstalledFixtureError("offline config sections are malformed")
    if output.get("evaluate_with_fincore") is True:
        raise InstalledFixtureError("fincore evaluation is outside this fixture")
    if selection.get("daily_bundles"):
        raise InstalledFixtureError("offline daily rollover is outside this fixture")

    candidates = [
        ("selection.bundle", selection.get("bundle"), True),
        ("inputs.minute_tape", inputs.get("minute_tape"), True),
    ]
    if mode == "replay":
        candidates.extend(
            (
                ("inputs.execution_quotes", inputs.get("execution_quotes"), True),
                ("inputs.instrument_metadata", inputs.get("instrument_metadata"), True),
            )
        )
        candidates.append(("output.decision_tape_path", output.get("decision_tape_path"), False))
    candidates.append(("output.directory", output.get("directory"), False))

    resolved = {}
    for label, value, must_exist in candidates:
        if type(value) is not str or not value or value != value.strip():
            raise InstalledFixtureError(label + " must be explicitly configured")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = config_path.parent / path
        if path.is_symlink():
            raise InstalledFixtureError(label + " must not be a symlink")
        path = path.resolve(strict=False)
        if not _is_within(path, workspace):
            raise InstalledFixtureError(label + " must resolve inside the external workspace")
        if must_exist and (not path.is_file() or path.is_symlink()):
            raise InstalledFixtureError(label + " must name an existing regular fixture file")
        if label == "output.directory" and path.exists():
            raise InstalledFixtureError("offline output directory must be new")
        if label == "output.decision_tape_path" and path.exists():
            raise InstalledFixtureError("decision tape destination must be new")
        resolved[label] = str(path)
    return resolved


def validate_offline_config(config_path: Path, workspace: Path, mode: str) -> dict[str, str]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if mode == "dry":
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise InstalledFixtureError("PyYAML is required to validate an offline config") from exc
    try:
        with Path(config_path).open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise InstalledFixtureError("offline YAML config could not be read") from exc
    if not isinstance(config, Mapping):
        raise InstalledFixtureError("offline YAML config must contain an object")
    return _config_paths(config, config_path, workspace, mode)


_CHILD_CODE = r"""import importlib.util, json, runpy, sys, tempfile
from pathlib import Path
helper_path, wheel_path, wheel_hash, example_dir, config_path, mode, factor_mode, cli_argv_json = sys.argv[1:]
cache = tempfile.TemporaryDirectory(prefix="iteration51-installed-pycache-")
cache_path = Path(cache.name).resolve()
if any(cache_path.iterdir()):
    raise RuntimeError("fixture cache is not fresh")
sys.pycache_prefix = str(cache_path)
spec = importlib.util.spec_from_file_location("iteration50_installed_fixture_reused", helper_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Iteration 50 verifier is unavailable")
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)
installed, binding = helper._verify_installed_distribution(Path(wheel_path), wheel_hash)
before = binding["loaded_modules"]
example = Path(example_dir).resolve(strict=True)
sys.path.insert(0, str(example))
sys.argv = json.loads(cli_argv_json)
exit_code = 0
try:
    runpy.run_path(str(example / "run.py"), run_name="__main__")
except SystemExit as result:
    if result.code is None:
        exit_code = 0
    elif type(result.code) is int:
        exit_code = result.code
    else:
        exit_code = 1
after = helper._snapshot_loaded_package_modules(
    binding["install_root"], binding["record_hashes"], binding["wheel_payload_hashes"],
    previous=before,
)
origins = []
for name, (_module, path, digest) in sorted(after.items()):
    relative = Path(path).resolve().relative_to(binding["install_root"]).as_posix()
    origins.append([name, relative, digest])
print("ITERATION51_INSTALLED_CHILD=" + json.dumps({
    "exit_code": exit_code,
    "distribution": installed["distribution"],
    "version": installed["version"],
    "wheel_sha256": installed["wheel"]["sha256"],
    "record_sha256": installed["record_sha256"],
    "loaded_modules_verified": len(after),
    "module_origins_sha256": __import__("hashlib").sha256(
        json.dumps(origins, separators=(",", ":")).encode("utf-8")
    ).hexdigest(),
    "fresh_bytecode_cache": bool(sys.pycache_prefix == str(cache_path)),
}, sort_keys=True, separators=(",", ":")))
raise SystemExit(exit_code)
"""


_SYNTHETIC_LIVE_CHILD_CODE = r'''import hashlib, importlib.util, json, os, runpy, socket, sys, tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

helper_path, wheel_path, wheel_hash, example_dir, template_path, workspace, case, factor_mode = sys.argv[1:]
cache = tempfile.TemporaryDirectory(prefix="iteration51-installed-pycache-")
cache_path = Path(cache.name).resolve()
if any(cache_path.iterdir()):
    raise RuntimeError("fixture cache is not fresh")
sys.pycache_prefix = str(cache_path)
spec = importlib.util.spec_from_file_location("iteration50_installed_fixture_reused", helper_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Iteration 50 verifier is unavailable")
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)
installed, binding = helper._verify_installed_distribution(Path(wheel_path), wheel_hash)
before = binding["loaded_modules"]
example = Path(example_dir).resolve(strict=True)
template_path = Path(template_path).resolve(strict=True)
workspace = Path(workspace).resolve(strict=True)
repository_root = Path(helper_path).resolve().parents[1]
try:
    workspace.relative_to(repository_root)
except ValueError:
    pass
else:
    raise RuntimeError("synthetic live workspace must be outside the checkout")
if workspace.is_symlink():
    raise RuntimeError("synthetic live workspace must not be a symlink")
import yaml
config = yaml.safe_load(template_path.read_text(encoding="utf-8"))

# Reuse Iteration 50's bounded execution/query provider leaf.  The SDK-facing
# clients below are synthetic modules at the CTP leaf boundary; the installed
# CtpClientWrapper and RegisteredSimWrapper remain in the runtime MRO.
targets = ("M2611", "Y2611", "A2611")
helper._TARGETS = targets
slot_count = 64
source_slot_count = slot_count + 1
utc = timezone.utc
china = timezone(timedelta(hours=8))
created_at = datetime.now(utc)
first_close = created_at.replace(second=0, microsecond=0) + timedelta(minutes=3)
last_close = first_close + timedelta(minutes=slot_count - 1)
source_first_close = first_close - timedelta(minutes=1)
bars, _unused_calendar = helper._fixture_bars(
    slot_count=source_slot_count, varied_stream=True, first_close=source_first_close
)

from backtrader.feeds.futures_main_contract import (
    ExchangeTradingDay,
    FuturesContractRecord,
    MainContractPolicy,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
    select_main_contracts,
)
from backtrader.feeds.futures_selection_io import selection_bundle_to_dict
from backtrader.feeds.futures_sessions import (
    ExchangeSessionCalendar,
    ExpectedRuleEvidence,
    ProductTradingDaySessions,
    SessionWindow,
)

products = tuple(ProductKey("DCE", product_id) for product_id in ("M", "Y", "A"))
instruments = dict(zip(products, targets))
authorized_targets = ("DCE.M", "DCE.A")
trading_day = last_close.astimezone(china).date()
for target_rows in bars.values():
    for target_row in target_rows:
        target_row["trading_day"] = trading_day.isoformat()
        target_row["session_segment"] = "regular"
expiry_day = trading_day + timedelta(days=45)
calendar_days = tuple(
    trading_day + timedelta(days=offset) for offset in range(-2, 47)
)
decision_at = datetime.now(utc)
source_time = decision_at - timedelta(seconds=2)
source_id = "iteration51-synthetic-session-rules"
source = ExpectedRuleEvidence(
    source_id=source_id,
    source_urls=("https://example.invalid/iteration51-synthetic-session-rules",),
    version="fixture-only-v1",
    available_at=source_time,
    retrieved_at=source_time,
    rules_manifest_sha256="a" * 64,
    limitations=("Synthetic local fixture; not exchange-calendar evidence.",),
)
session_start = first_close.astimezone(china) - timedelta(minutes=1)
session_end = last_close.astimezone(china)
session_calendar = ExchangeSessionCalendar(
    exchange_id="DCE",
    calendar_source_id=source_id,
    coverage_start=calendar_days[0],
    coverage_through=calendar_days[-1],
    trading_days=calendar_days,
    product_universe=products,
    product_days=tuple(
        ProductTradingDaySessions(
            product=product,
            trading_day=trading_day,
            source_id=source_id,
            windows=(
                SessionWindow(
                    session_id="regular",
                    session_date=session_start.date(),
                    start=session_start,
                    end=session_end,
                    source_id=source_id,
                ),
            ),
        )
        for product in products
    ),
    sources=(source,),
    complete=True,
    evidence_mode="expected_rule_derived",
)
candidate_ids = {
    product: (instruments[product], product.product_id + "2612") for product in products
}
coverage = tuple(
    ProductRankingCoverage(
        product=product,
        candidate_count=2,
        expected_instrument_ids=candidate_ids[product],
        ranking_instrument_ids=candidate_ids[product],
        candidate_set_complete=True,
        ranking_values_complete=True,
        finalized=True,
        latest_available=True,
        ranking_trading_day=trading_day - timedelta(days=1),
        open_interest_unit="contracts",
        volume_unit="lots",
    )
    for product in products
)
candidates = tuple(
    FuturesContractRecord(
        product=product,
        instrument_id=instrument_id,
        asset_type="future",
        is_trading=True,
        expiry_date=expiry_day + timedelta(days=30 if ordinal else 0),
        open_interest=Decimal("400" if ordinal == 0 else "300") + index,
        volume=Decimal("250" if ordinal == 0 else "200") + index,
    )
    for index, product in enumerate(products)
    for ordinal, instrument_id in enumerate(candidate_ids[product])
)
snapshot_sha = hashlib.sha256(b"iteration51 synthetic ranking fixture").hexdigest()
snapshot = MainContractRankingSnapshot(
    source_id="iteration51-synthetic-main-contracts",
    snapshot_id="iteration51-synthetic-ranking-v1",
    source_sha256=snapshot_sha,
    available_at=source_time,
    retrieved_at=source_time,
    catalog_source_id="iteration51-synthetic-catalog",
    catalog_snapshot_id="iteration51-synthetic-catalog-v1",
    catalog_sha256=hashlib.sha256(b"iteration51 synthetic catalog").hexdigest(),
    catalog_available_at=source_time,
    catalog_retrieved_at=source_time,
    coverage=coverage,
    candidates=candidates,
)
policy = MainContractPolicy(
    policy_id="iteration51-synthetic-prior-day-ranking-v1",
    minimum_trading_days_to_expiry=5,
)
day_row = ExchangeTradingDay("DCE", trading_day)
claim = select_main_contracts(
    snapshot,
    products,
    (day_row,),
    (session_calendar.to_main_contract_calendar(),),
    decision_at=decision_at,
    policy=policy,
)
if claim.status != "READY":
    raise RuntimeError("synthetic main-contract bundle did not produce a ready three-target plan")
case_root = Path(tempfile.mkdtemp(prefix="iteration51-live-case-", dir=str(workspace))).resolve()
bundle_path = case_root / "selection-bundle.json"
config_path = case_root / "runner.yaml"
config["mode"] = "live"
config["entry"]["tier"] = "replay" if case == "tier-escalation" else "live"
config["factor"]["mode"] = factor_mode
config["selection"].update(
    source="bundle", bundle=str(bundle_path), authorized_products=list(authorized_targets),
    daily_bundles=[], max_epochs=1,
)
config["cohort"].update(
    calendar_id=source_id,
    calendar_version="fixture-only-v1",
    epoch_id=1,
    clock_domain_id=helper._CLOCK_DOMAIN,
    timezone_id="UTC",
    session_semantics=helper._SESSION_SEMANTICS,
    max_live_bar_age_seconds=7200,
    max_future_skew_seconds=7200,
    max_window_bars=slot_count + 2,
    wait_timeout_seconds=2.0,
)
config["live"].update(
    store_config_env="BT_SIMNOW_CONFIG_JSON",
    allow_writes=case == "write",
    account_scope="iteration51-synthetic-account",
    strategy_scope="iteration51-alpha003-synthetic",
    logical_run_id="iteration51-" + case,
    journal_path=str(case_root / "live-decisions.sqlite"),
    arm_templates=[],
    ready_timeout_seconds=5.0,
    refresh_timeout_seconds=5.0,
    refresh_overall_timeout_seconds=30.0,
    refresh_interval_seconds=5.0,
    quote_max_age_seconds=7200.0,
    query_max_age_seconds=7200.0,
    shutdown_grace_seconds=2.0,
)
write_risk = {
    "policy_id": "iteration51-synthetic-write-risk-v1",
    "max_hold_eligible_bars": 12,
    "preclose_grace_seconds": 120,
    "run_end_policy": "CLOSE_ALL",
    "quote_max_age_seconds": 7200,
    "max_state_age_seconds": 7200,
    "max_notional_per_position": "100000",
    "max_total_notional": "300000",
    "max_margin_per_position": "10000",
    "max_total_margin": "30000",
    "max_loss_per_position": "10000",
    "max_total_loss": "20000",
    "round_trip_fee_upper_bound_per_contract": "1.00",
    "stop_loss_ticks": 1,
    "max_order_intents_per_grid": 2,
    "max_order_intents_per_run": 20,
}
if case == "write":
    config["risk"].update(write_risk)
    config["live"]["arm_templates"] = [
        {
            "target": "DCE." + product.product_id,
            "md_front": "tcp://180.168.146.187:10211",
            "strategy_identity_sha256": "a" * 64,
            "execution_cycle_id": "iteration51-cycle-" + product.product_id,
            "preflight_sha256": "b" * 64,
        }
        for product in products
        if "DCE." + product.product_id in authorized_targets
    ]
bundle = selection_bundle_to_dict(
    snapshot,
    products,
    (day_row,),
    (session_calendar,),
    decision_at=decision_at,
    policy=policy,
    selection_claim=claim,
)
bundle_bytes = (json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
with bundle_path.open("xb") as handle:
    handle.write(bundle_bytes)
bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
config["output"].update(
    directory=str(case_root / "artifacts"),
    decision_tape_path=str(case_root / "decision-tape.jsonl"),
    decision_tape_max_bytes=5_000_000,
    evaluate_with_fincore=False,
)
config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

# All CTP values below are synthetic placeholders.  The installed Store still
# resolves its ordinary config/environment contract and the unchanged
# CtpClientWrapper factory imports these synthetic SDK leaf modules.
os.environ["BT_SIMNOW_CONFIG_JSON"] = json.dumps({
    "config": {
        "td_address": "tcp://180.168.146.187:10201",
        "md_address": "tcp://180.168.146.187:10211",
        "broker_id": "9999",
        "investor_id": "ITERATION51_SYNTHETIC_ONLY",
        "password": "FIXTURE_ONLY_NOT_A_CREDENTIAL",
        "appid": "simnow_client_test",
        "auth_code": "FIXTURE_ONLY_NOT_A_CREDENTIAL",
        "bar_watermark_ms": 0,
    },
    "api_kwargs": {"fixture_marker": "iteration51-synthetic-ctp-leaf"},
}, sort_keys=True, separators=(",", ":"))
store_environment = json.loads(os.environ["BT_SIMNOW_CONFIG_JSON"])
if (
    set(store_environment) != {"config", "api_kwargs"}
    or set(store_environment["config"]).intersection({"api", "api_cls"})
    or set(store_environment["api_kwargs"]).intersection({"api", "api_cls"})
):
    raise RuntimeError("synthetic Store environment shape is invalid")

fake_state = {
    "trader_clients": [], "md_clients": [], "query_families": [],
    "subscriptions": [], "arm_calls": 0, "disarm_calls": 0,
    "synthetic_leaf_actions": [], "disconnect_calls": 0,
    "trader_stop_calls": 0, "md_stop_calls": 0, "wrapper_mros": [],
    "wrapper_write_flags": [], "wrapper_api_instances": [],
    "synthetic_fill_count": 0, "ctp_order_callback_count": 0,
    "ctp_trade_callback_count": 0,
}
helper._EXECUTION_TRADING_DAY = trading_day.strftime("%Y%m%d")

# Build a causal event schedule.  The first source minute is a warm-up bucket
# that the installed CTP feed intentionally discards as its cumulative-volume
# baseline.  Each later source minute maps one planned cohort slot; one final
# boundary tick closes the last planned minute.
synthetic_events = []
for target in targets:
    cumulative_volume = 0
    for row_index, row in enumerate(bars[target]):
        bucket_start = row["bucket_start"]
        values = (row["open"], row["high"], row["low"], row["close"])
        for tick_index, (offset_seconds, price) in enumerate(
            zip((1, 15, 30, 50), values)
        ):
            cumulative_volume += 1
            event_time = bucket_start + timedelta(seconds=offset_seconds)
            local_time = event_time.astimezone(china)
            payload = {
                "InstrumentID": target,
                "ExchangeID": "DCE",
                "LastPrice": float(price),
                "Volume": cumulative_volume,
                "OpenInterest": 0,
                "TradingDay": trading_day.strftime("%Y%m%d"),
                "ActionDay": local_time.strftime("%Y%m%d"),
                "UpdateTime": local_time.strftime("%H:%M:%S"),
                "UpdateMillisec": 0,
                "BidPrice1": float(price) - 1.0,
                "AskPrice1": float(price) + 1.0,
                "BidVolume1": 5,
                "AskVolume1": 6,
                "Turnover": float(price) * cumulative_volume,
            }
            synthetic_events.append((event_time, target, row_index, tick_index, payload))
    cumulative_volume += 1
    sentinel_time = last_close + timedelta(seconds=1)
    local_time = sentinel_time.astimezone(china)
    synthetic_events.append((
        sentinel_time,
        target,
        source_slot_count,
        0,
        {
            "InstrumentID": target,
            "ExchangeID": "DCE",
            "LastPrice": float(bars[target][-1]["close"]),
            "Volume": cumulative_volume,
            "OpenInterest": 0,
            "TradingDay": trading_day.strftime("%Y%m%d"),
            "ActionDay": local_time.strftime("%Y%m%d"),
            "UpdateTime": local_time.strftime("%H:%M:%S"),
            "UpdateMillisec": 0,
            "BidPrice1": float(bars[target][-1]["close"]) - 1.0,
            "AskPrice1": float(bars[target][-1]["close"]) + 1.0,
            "BidVolume1": 5,
            "AskVolume1": 6,
            "Turnover": float(bars[target][-1]["close"]) * cumulative_volume,
        },
    ))
synthetic_events.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

import threading
import time as _real_time
import types
import heapq

synthetic_callback_events = []
synthetic_callback_sequence = [0]


def _schedule_synthetic_callback(event_time, callback):
    with virtual_scheduler._lock:
        if event_time < virtual_scheduler._now:
            virtual_scheduler._late_callback_schedule_count += 1
            event_time = virtual_scheduler._now
        synthetic_callback_sequence[0] += 1
        heapq.heappush(
            synthetic_callback_events,
            (event_time, synthetic_callback_sequence[0], callback),
        )


class SyntheticVirtualScheduler:
    """Causal UTC scheduler; monotonic lifecycle deadlines stay real."""

    _shared_instance = None
    _runner_clock_constructor_calls = 0
    _last_runner_clock_instance = None

    def __new__(cls):
        if cls._shared_instance is not None:
            cls._runner_clock_constructor_calls += 1
            cls._last_runner_clock_instance = cls._shared_instance
            return cls._shared_instance
        return super().__new__(cls)

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._lock = threading.RLock()
        self._now = created_at
        self._event_index = 0
        self._advance_count = 0
        self._delivered_ticks = 0
        self._callback_delivery_count = 0
        self._late_callback_schedule_count = 0
        self._initialized = True

    def utc_now(self):
        with self._lock:
            return self._now

    def monotonic_ns(self):
        return _real_time.monotonic_ns()

    def _deliver_through(self, target):
        while True:
            next_market = (
                synthetic_events[self._event_index][0]
                if self._event_index < len(synthetic_events)
                else None
            )
            next_callback = (
                synthetic_callback_events[0][0] if synthetic_callback_events else None
            )
            candidates = [
                value for value in (next_market, next_callback) if value is not None
            ]
            if not candidates:
                break
            event_time = min(candidates)
            if event_time > target:
                break
            self._now = event_time
            # At equal virtual UTC, publish market availability before a fill.
            if next_market is not None and next_market == event_time:
                _when, symbol, _row_index, _tick_index, payload = synthetic_events[
                    self._event_index
                ]
                self._event_index += 1
                delivered = False
                for client in tuple(fake_state["md_clients"]):
                    if symbol not in client.subscribed:
                        continue
                    callback = client.on_tick_with_generation
                    if callable(callback):
                        callback(payload, client.connection_generation)
                        delivered = True
                    elif callable(client.on_tick):
                        callback(payload)
                        delivered = True
                if delivered:
                    self._delivered_ticks += 1
                continue
            if next_callback is not None and next_callback == event_time:
                _when, _sequence, callback = heapq.heappop(synthetic_callback_events)
                callback()
                self._callback_delivery_count += 1
                continue
            raise RuntimeError("synthetic scheduler event ordering is inconsistent")

    def _advance(self, timeout_seconds):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("virtual scheduler timeout must be numeric")
        if timeout_seconds < 0:
            raise ValueError("virtual scheduler timeout must be nonnegative")
        with self._lock:
            target = self._now + timedelta(seconds=float(timeout_seconds))
            self._deliver_through(target)
            self._now = target
            self._advance_count += 1

    def wait(self, timeout_seconds):
        self._advance(timeout_seconds)

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        if wait_for_event(0):
            return True
        self._advance(timeout_seconds)
        return False


virtual_scheduler = SyntheticVirtualScheduler()
SyntheticVirtualScheduler._shared_instance = virtual_scheduler


class SyntheticBtApiTime:
    """Virtualize CTP receive-wall time while preserving real monotonic calls."""

    def __getattr__(self, name):
        return getattr(_real_time, name)

    def time(self):
        return virtual_scheduler.utc_now().timestamp()


class SyntheticCtpStruct:
    """Small mutable stand-in for a CTP input struct used at the SDK leaf."""


class SyntheticMdSpi:
    pass


class SyntheticTraderSpi:
    pass


def _sdk_package(name):
    existing = sys.modules.get(name)
    if existing is not None:
        raise RuntimeError("synthetic CTP SDK module unexpectedly preloaded")
    module = types.ModuleType(name)
    module.__package__ = name
    module.__path__ = []
    sys.modules[name] = module
    parent_name, _, child_name = name.rpartition(".")
    if parent_name:
        setattr(sys.modules[parent_name], child_name, module)
    return module


def _sdk_module(name):
    existing = sys.modules.get(name)
    if existing is not None:
        raise RuntimeError("synthetic CTP SDK module unexpectedly preloaded")
    module = types.ModuleType(name)
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    parent_name, _, child_name = name.rpartition(".")
    setattr(sys.modules[parent_name], child_name, module)
    return module


_sdk_package("bt_api_ctp")
_sdk_package("bt_api_ctp.ctp")
_sdk_client_module = _sdk_module("bt_api_ctp.ctp.client")
_sdk_md_module = _sdk_module("bt_api_ctp.ctp.ctp_md_api")
_sdk_structs_module = _sdk_module("bt_api_ctp.ctp.ctp_structs_order")
_sdk_trader_module = _sdk_module("bt_api_ctp.ctp.ctp_trader_api")
_sdk_md_module.CThostFtdcMdSpi = SyntheticMdSpi
_sdk_trader_module.CThostFtdcTraderSpi = SyntheticTraderSpi
_sdk_structs_module.CThostFtdcInputOrderActionField = SyntheticCtpStruct
_sdk_structs_module.CThostFtdcInputOrderField = SyntheticCtpStruct
_sdk_client_module._MdSpi = type("SyntheticSdkMdSpi", (), {})
_sdk_client_module._TraderSpi = type("SyntheticSdkTraderSpi", (), {})


def _wrapper_owner_from_sdk_constructor():
    # The SDK constructor is called directly by CtpClientWrapper.connect(); its
    # immediate Python caller is the real installed wrapper instance.
    caller = sys._getframe(1)
    wrapper = caller.f_locals.get("self")
    if wrapper is None:
        raise RuntimeError("synthetic SDK leaf was not constructed by CtpClientWrapper")
    mro_names = [base.__name__ for base in type(wrapper).__mro__]
    if "CtpClientWrapper" not in mro_names or "RegisteredSimWrapper" not in mro_names:
        raise RuntimeError("installed RegisteredSim/Ctp wrapper composition is missing")
    if not any(existing is wrapper for existing in fake_state["wrapper_api_instances"]):
        fake_state["wrapper_mros"].append(mro_names)
        fake_state["wrapper_write_flags"].append(
            getattr(wrapper, "_registered_sim_allow_writes", None)
        )
        fake_state["wrapper_api_instances"].append(wrapper)


class SyntheticTraderClient(helper._ExecutionProviderLeaf):
    """Iteration 50 provider leaf below the installed CTP wrapper."""

    def __init__(self, **kwargs):
        del kwargs
        _wrapper_owner_from_sdk_constructor()
        super().__init__(bars=bars, slot_count=source_slot_count)
        self.is_read_only_ready = True
        self._req_id = 100
        self.on_login = None
        self.on_order = None
        self.on_trade = None
        self.on_error = None
        fake_state["trader_clients"].append(self)

    def start(self, *, block=False):
        if block is not False:
            raise RuntimeError("synthetic CTP trader start must be nonblocking")
        self.connect()

    def wait_ready(self, timeout=20):
        if timeout <= 0:
            return False
        self.is_ready = True
        self.is_read_only_ready = True
        self.is_trading_ready = True
        return True

    def stop(self):
        fake_state["trader_stop_calls"] += 1
        self.disconnect()
        self.is_ready = False

    def _query_result(self, request_type, family, *, filters=()):
        fake_state["query_families"].append(family)
        return super()._query_result(request_type, family, filters=filters)

    @staticmethod
    def _row(value):
        return types.SimpleNamespace(**dict(value))

    def query_account(self, timeout=5):
        del timeout
        rows = self.query_account_result().records
        return self._row(rows[0]) if rows else None

    def query_positions(self, timeout=5):
        del timeout
        return [self._row(row) for row in self.query_positions_result().records]

    def query_orders(self, timeout=5, **filters):
        del timeout, filters
        return [self._row(row) for row in self.query_orders_result().records]

    def query_trades(self, timeout=5, **filters):
        del timeout, filters
        return [self._row(row) for row in self.query_trades_result().records]

    def query_instrument(self, instrument_id, exchange_id="", timeout=5, **kwargs):
        del kwargs
        result = self.query_instruments_result(
            instrument_id=instrument_id, exchange_id=exchange_id, timeout=timeout
        )
        for row in result.records:
            if row.get("InstrumentID") == instrument_id and (
                not exchange_id or row.get("ExchangeID") == exchange_id
            ):
                return self._row(row)
        return None

    def query_instrument_margin_rate(
        self, instrument_id, exchange_id="", hedge_flag="1", timeout=5, **kwargs
    ):
        del kwargs
        result = self.query_instrument_margin_rate_result(
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            hedge_flag=hedge_flag,
            timeout=timeout,
        )
        return self._row(result.records[0]) if result.records else None

    def query_instrument_commission_rate(self, instrument_id, exchange_id="", timeout=5):
        del timeout
        return types.SimpleNamespace(
            InstrumentID=instrument_id,
            ExchangeID=exchange_id,
            OpenRatioByMoney="0",
            OpenRatioByVolume="0",
            CloseRatioByMoney="0",
            CloseRatioByVolume="0",
            CloseTodayRatioByMoney="0",
            CloseTodayRatioByVolume="0",
        )

    def arm_execution_for_registered_sim(self, **kwargs):
        fake_state["arm_calls"] += 1
        return super().arm_execution_for_registered_sim(**kwargs)

    def disarm_execution_gate(self, capability, reason):
        if capability is None:
            raise RuntimeError("synthetic disarm requires the issued capability")
        fake_state["disarm_calls"] += 1
        self._gate_state = {
            **self._gate_state,
            "managed": True,
            "armed": False,
            "authorized_instruments": [],
            "revocation_reason": str(reason),
        }
        return dict(self._gate_state)

    def submit_order_insert(self, field, request_id, *, execution_capability):
        fake_state["synthetic_leaf_actions"].append({
            "action": "insert",
            "instrument": str(field.InstrumentID),
            "exchange": str(field.ExchangeID),
        })
        result = super().submit_order_insert(
            field, request_id, execution_capability=execution_capability
        )
        order_ref = str(field.OrderRef)
        instrument = str(field.InstrumentID)
        exchange = str(field.ExchangeID)
        quantity = int(field.VolumeTotalOriginal)
        direction_flag = str(field.Direction)
        offset_flag = str(field.CombOffsetFlag)
        price = float(field.LimitPrice)
        side = "buy" if direction_flag == "0" else "sell"
        offset = "open" if offset_flag == "0" else "close"
        self._order_identity[order_ref] = {
            "instrument": instrument,
            "exchange": exchange,
            "side": side,
            "offset": offset,
            "size": quantity,
            "front_id": self._front_id,
            "session_id": self._session_id,
        }

        def _complete_synthetic_fill():
            self.observe_order(
                order_ref, ctp_status="0", filled=quantity, remaining=0
            )
            self.observe_trade_fill(
                order_ref,
                "iteration51-" + order_ref,
                quantity=quantity,
                offset=offset,
                when=virtual_scheduler.utc_now(),
                fee=0.0,
            )
            if callable(self.on_order):
                self.on_order(types.SimpleNamespace(
                    OrderRef=order_ref,
                    OrderSysID="",
                    InstrumentID=instrument,
                    ExchangeID=exchange,
                    OrderStatus="0",
                    OrderSubmitStatus="0",
                    Direction=direction_flag,
                    CombOffsetFlag=offset_flag,
                    LimitPrice=price,
                    VolumeTotalOriginal=quantity,
                    VolumeTraded=quantity,
                    VolumeTotal=0,
                    FrontID=self._front_id,
                    SessionID=self._session_id,
                    UpdateTime=virtual_scheduler.utc_now()
                    .astimezone(china)
                    .strftime("%H:%M:%S"),
                    TradingDay=self._trading_day,
                ))
            if callable(self.on_trade):
                local_time = virtual_scheduler.utc_now().astimezone(china)
                self.on_trade(types.SimpleNamespace(
                    TradeID="iteration51-" + order_ref,
                    OrderRef=order_ref,
                    OrderSysID="",
                    InstrumentID=instrument,
                    ExchangeID=exchange,
                    Direction=direction_flag,
                    OffsetFlag=offset_flag,
                    HedgeFlag="1",
                    Volume=quantity,
                    Price=price,
                    Commission=0.0,
                    TradeDate=local_time.strftime("%Y%m%d"),
                    TradeTime=local_time.strftime("%H:%M:%S.%f"),
                    TradingDay=self._trading_day,
                ))

        _schedule_synthetic_callback(
            virtual_scheduler.utc_now() + timedelta(seconds=1),
            _complete_synthetic_fill,
        )
        return result

    def submit_order_action(self, *args, **kwargs):
        field = args[0] if args else None
        fake_state["synthetic_leaf_actions"].append({
            "action": "cancel",
            "instrument": str(getattr(field, "InstrumentID", "")),
            "exchange": str(getattr(field, "ExchangeID", "")),
        })
        return super().submit_order_action(*args, **kwargs)
    def disconnect(self):
        fake_state["disconnect_calls"] += 1
        return super().disconnect()

class SyntheticMdClient:
    """Synthetic public SDK market-data leaf invoking real CTP callbacks."""

    def __init__(self, **kwargs):
        del kwargs
        _wrapper_owner_from_sdk_constructor()
        self.connection_generation = 1
        self.on_tick = None
        self.on_tick_with_generation = None
        self.on_disconnect = None
        self.on_disconnect_with_generation = None
        self.on_error = None
        self.subscribed = set()
        self.started = False
        fake_state["md_clients"].append(self)

    def start(self, *, block=False):
        if block is not False:
            raise RuntimeError("synthetic CTP market start must be nonblocking")
        self.started = True

    def wait_ready(self, timeout=20):
        return timeout > 0 and self.started

    def subscribe(self, instruments):
        if isinstance(instruments, str):
            instruments = (instruments,)
        for instrument in instruments:
            self.subscribed.add(str(instrument))
            fake_state["subscriptions"].append(str(instrument))

    def stop(self):
        fake_state["md_stop_calls"] += 1
        self.started = False
        return None


_sdk_client_module.MdClient = SyntheticMdClient
_sdk_client_module.TraderClient = SyntheticTraderClient
import backtrader.stores.btapistore as btapistore
original_ctp_factory = btapistore._create_ctp_wrapper_class
original_btapi_time = btapistore.time
btapistore.time = SyntheticBtApiTime()
network_attempts = []
original_socket_connect = socket.socket.connect
original_socket_connect_ex = socket.socket.connect_ex
original_socket_sendto = socket.socket.sendto
original_create_connection = socket.create_connection
def _deny_network(*args, **kwargs):
    network_attempts.append("socket")
    raise RuntimeError("synthetic installed fixture forbids network I/O")
socket.socket.connect = _deny_network
socket.socket.connect_ex = _deny_network
socket.socket.sendto = _deny_network
socket.create_connection = _deny_network
sys.path.insert(0, str(example))
cli_argv = [str(example / "run.py"), "--config", str(config_path), "--mode", "live", "--factor-mode", factor_mode]
if case in {"write", "write-denied"}:
    cli_argv.append("--allow-write")
sys.argv = cli_argv
exit_code = 0
runner_namespace = None
runner_globals = None
runner_clock_original = None
runner_clock_constructor_calls_before = None
cli_stdout = __import__("io").StringIO()
try:
    runner_namespace = runpy.run_path(
        str(example / "run.py"), run_name="iteration51_synthetic_live_cli"
    )
    runner_run = runner_namespace.get("run")
    if not callable(runner_run):
        raise RuntimeError("copied public CLI does not expose its run entry")
    runner_globals = runner_run.__globals__
    runner_file = Path(runner_globals.get("__file__", "")).resolve(strict=True)
    if runner_file != (example / "run.py").resolve(strict=True):
        raise RuntimeError("public CLI run entry is not bound to the copied run.py source")
    runner_clock_original = runner_globals.get("RunnerWallClock")
    if not isinstance(runner_clock_original, type):
        raise RuntimeError("copied public CLI scheduler class is unavailable")
    # runpy returns a namespace snapshot; functions resolve globals through
    # function.__globals__, so patch only that exact copied-source binding.
    runner_globals["RunnerWallClock"] = SyntheticVirtualScheduler
    runner_clock_constructor_calls_before = (
        SyntheticVirtualScheduler._runner_clock_constructor_calls
    )
    from contextlib import redirect_stdout
    with redirect_stdout(cli_stdout):
        exit_code = runner_run()
    if type(exit_code) is not int:
        raise RuntimeError("public CLI returned a non-integer exit code")
except SystemExit as result:
    if result.code is None:
        exit_code = 0
    elif type(result.code) is int:
        exit_code = result.code
    else:
        exit_code = 1
finally:
    socket.socket.connect = original_socket_connect
    socket.socket.connect_ex = original_socket_connect_ex
    socket.socket.sendto = original_socket_sendto
    socket.create_connection = original_create_connection
    btapistore.time = original_btapi_time

raw_cli_stdout = cli_stdout.getvalue()
summary = None
cli_lines = raw_cli_stdout.splitlines()
summary_line_index = None
for line_index in reversed(range(len(cli_lines))):
    line = cli_lines[line_index]
    try:
        candidate = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(candidate, dict):
        summary = candidate
        summary_line_index = line_index
        break
if summary is None:
    raise RuntimeError("actual public CLI did not emit a JSON summary")
summary_line = cli_lines[summary_line_index]
scheduler_clock_labels = []

def _collect_scheduler_clock_labels(value, path=()):
    if isinstance(value, dict):
        if "scheduler_clock" in value:
            scheduler_clock_labels.append({
                "path": ".".join(path).replace(".[", "[") if path else "summary",
                "value": value["scheduler_clock"],
            })
        for key, item in value.items():
            _collect_scheduler_clock_labels(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_scheduler_clock_labels(item, path + ("[{}]".format(index),))

_collect_scheduler_clock_labels(summary)
print(raw_cli_stdout, end="")
if raw_cli_stdout and not raw_cli_stdout.endswith(("\n", "\r")):
    print()

leaf_close_receipt = {
    "trader_client_count": len(fake_state["trader_clients"]),
    "md_client_count": len(fake_state["md_clients"]),
    "trader_stop_calls": fake_state["trader_stop_calls"],
    "trader_disconnect_calls": fake_state["disconnect_calls"],
    "md_stop_calls": fake_state["md_stop_calls"],
    "trader_connected_after_close": [
        bool(client.connected) for client in fake_state["trader_clients"]
    ],
    "trader_ready_after_close": [
        bool(client.is_ready) for client in fake_state["trader_clients"]
    ],
    "md_started_after_close": [
        bool(client.started) for client in fake_state["md_clients"]
    ],
    "wrappers_connected_after_close": [
        bool(getattr(wrapper, "_connected", True))
        for wrapper in fake_state["wrapper_api_instances"]
    ],
}

after = helper._snapshot_loaded_package_modules(
    binding["install_root"], binding["record_hashes"], binding["wheel_payload_hashes"],
    previous=before,
)
origins = []
for name, (_module, path, digest) in sorted(after.items()):
    relative = Path(path).resolve().relative_to(binding["install_root"]).as_posix()
    origins.append([name, relative, digest])
print("ITERATION51_SYNTHETIC_LIVE_CHILD=" + json.dumps({
    "case": case,
    "exit_code": exit_code,
    "cli_argv": cli_argv,
    "distribution": installed["distribution"],
    "version": installed["version"],
    "wheel_sha256": installed["wheel"]["sha256"],
    "record_sha256": installed["record_sha256"],
    "loaded_modules_verified": len(after),
    "module_origins_sha256": hashlib.sha256(
        json.dumps(origins, separators=(",", ":")).encode("utf-8")
    ).hexdigest(),
    "fresh_bytecode_cache": bool(sys.pycache_prefix == str(cache_path)),
    "ctp_wrapper_factory_unchanged": btapistore._create_ctp_wrapper_class is original_ctp_factory,
    "ctp_wrapper_mro_verified": bool(fake_state["wrapper_mros"])
    and all(
        "CtpClientWrapper" in mro and "RegisteredSimWrapper" in mro
        for mro in fake_state["wrapper_mros"]
    ),
    "ctp_wrapper_mros": fake_state["wrapper_mros"],
    "ctp_trader_leaf_instances": len(fake_state["trader_clients"]),
    "ctp_md_leaf_instances": len(fake_state["md_clients"]),
    "store_write_flags": fake_state["wrapper_write_flags"],
    "query_families": sorted(set(fake_state["query_families"])),
    "subscriptions": sorted(fake_state["subscriptions"]),
    "arm_calls": fake_state["arm_calls"],
    "disarm_calls": fake_state["disarm_calls"],
    "disconnect_calls": fake_state["disconnect_calls"],
    "synthetic_leaf_actions": list(fake_state["synthetic_leaf_actions"]),
    "store_environment_shape_valid": True,
    "store_environment_api_kwargs_keys": sorted(store_environment["api_kwargs"]),
    "network_attempts": len(network_attempts),
    "virtual_scheduler": True,
    "virtual_scheduler_advance_count": virtual_scheduler._advance_count,
    "virtual_scheduler_delivered_ticks": virtual_scheduler._delivered_ticks,
    "virtual_scheduler_callback_delivery_count": virtual_scheduler._callback_delivery_count,
    "virtual_scheduler_pending_callbacks": len(synthetic_callback_events),
    "virtual_scheduler_late_callback_schedule_count": (
        virtual_scheduler._late_callback_schedule_count
    ),
    "virtual_scheduler_final_utc": virtual_scheduler.utc_now().isoformat(),
    "virtual_scheduler_monotonic_is_real": True,
    "virtual_scheduler_clock_origin": (
        "copied run.py run.__globals__['RunnerWallClock'] replaced in child; "
        "btapistore.time.time virtualized; monotonic_ns forwarded to host clock"
    ),
    "runner_clock_patch_binding": "run.__globals__['RunnerWallClock']",
    "runner_clock_patch_target_is_function_globals": (
        runner_globals is not None
        and runner_namespace is not None
        and runner_globals is runner_namespace["run"].__globals__
    ),
    "runner_clock_patch_origin": (
        str(Path(runner_globals.get("__file__", "")).resolve())
        if runner_globals is not None else None
    ),
    "runner_clock_constructor_calls": (
        SyntheticVirtualScheduler._runner_clock_constructor_calls
        - (runner_clock_constructor_calls_before or 0)
    ),
    "runner_clock_shared_with_virtual_scheduler": (
        SyntheticVirtualScheduler._last_runner_clock_instance is virtual_scheduler
    ),
    "runner_clock_original_class": (
        runner_clock_original.__name__ if runner_clock_original is not None else None
    ),
    "runner_summary_scheduler_clock_labels": scheduler_clock_labels,
    "runner_summary_scheduler_clock_label_meaning": (
        "production summary default identifier; not the injected runtime clock"
    ),
    "clock_origins": {
        "runner_wall_clock_binding": "copied run.py run.__globals__['RunnerWallClock']",
        "ctp_receive_wall_clock": "backtrader.stores.btapistore.time.time -> synthetic virtual UTC",
        "monotonic_clock": "host time.monotonic_ns forwarded without virtualization",
        "scheduler_shared_state": "RunnerWallClock and CTP leaves share one child-local instance",
    },
    "synthetic_fill_count": fake_state["synthetic_fill_count"],
    "ctp_order_callback_count": fake_state["ctp_order_callback_count"],
    "ctp_trade_callback_count": fake_state["ctp_trade_callback_count"],
    "synthetic_leaf_close_receipt": leaf_close_receipt,
    "synthetic_sdk_modules": [
        "bt_api_ctp", "bt_api_ctp.ctp", "bt_api_ctp.ctp.client",
        "bt_api_ctp.ctp.ctp_md_api", "bt_api_ctp.ctp.ctp_structs_order",
        "bt_api_ctp.ctp.ctp_trader_api",
    ],
    "installed_wrapper_origin": "backtrader.stores.btapistore._create_ctp_wrapper_class",
    "synthetic_sdk_module_origin": "in-memory synthetic leaf modules; no external SDK files",
    "raw_cli_stdout_sha256": hashlib.sha256(raw_cli_stdout.encode("utf-8")).hexdigest(),
    "raw_cli_summary_sha256": hashlib.sha256(summary_line.encode("utf-8")).hexdigest(),
    "authorized_products": list(authorized_targets),
    "selection_bundle_sha256": bundle_sha256,
    "synthetic_only": True,
}, sort_keys=True, separators=(",", ":")))
raise SystemExit(exit_code)
'''


def _sanitized_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONPYCACHEPREFIX",
        "PYTHONDONTWRITEBYTECODE",
        "BT_SIMNOW_CONFIG_JSON",
        "BT_API_TEST_SOURCE_ROOTS",
    ):
        environment.pop(name, None)
    return environment


def _child_command(
    *,
    verifier_path: Path,
    wheel_path: Path,
    wheel_sha256: str,
    example_dir: Path,
    config_path: Path,
    mode: str,
    factor_mode: str,
    python: str = sys.executable,
) -> list[str]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    public_cli_argv = [
        str(Path(example_dir).resolve(strict=True) / "run.py"),
        "--config",
        str(Path(config_path).resolve(strict=True)),
        "--mode",
        mode,
        "--factor-mode",
        factor_mode,
    ]
    return [
        python,
        "-I",
        "-c",
        _CHILD_CODE,
        str(Path(verifier_path).resolve(strict=True)),
        str(Path(wheel_path).resolve(strict=True)),
        wheel_sha256,
        str(Path(example_dir).resolve(strict=True)),
        str(Path(config_path).resolve(strict=True)),
        mode,
        factor_mode,
        json.dumps(public_cli_argv, separators=(",", ":")),
    ]


def _last_json_object(stdout: str) -> dict[str, Any]:
    line = _last_json_object_line(stdout)
    value = json.loads(line)
    if not isinstance(value, dict):
        raise InstalledFixtureError("public CLI JSON result is not an object")
    return value


def _last_json_object_line(stdout: str) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_CHILD_MARKER):
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return line
    raise InstalledFixtureError("public CLI did not emit a JSON result")


def _child_receipt(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(_CHILD_MARKER):
            continue
        try:
            value = json.loads(line[len(_CHILD_MARKER) :])
        except json.JSONDecodeError as exc:
            raise InstalledFixtureError("installed-child receipt is malformed") from exc
        if isinstance(value, dict):
            return value
    raise InstalledFixtureError("installed-child origin receipt is missing")


def _synthetic_live_child_receipt(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(_LIVE_CHILD_MARKER):
            continue
        try:
            value = json.loads(line[len(_LIVE_CHILD_MARKER) :])
        except json.JSONDecodeError as exc:
            raise InstalledFixtureError("synthetic-live child receipt is malformed") from exc
        if isinstance(value, dict):
            return value
    raise InstalledFixtureError("synthetic-live child receipt is missing")


def run_cli_case(
    *,
    example_dir: Path,
    config_path: Path,
    wheel_path: Path,
    wheel_sha256: str,
    mode: str,
    factor_mode: str,
    timeout_seconds: float = 180.0,
    python: str = sys.executable,
) -> dict[str, Any]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    if not Path(example_dir, "run.py").is_file():
        raise InstalledFixtureError("copied public runner is unavailable")
    command = _child_command(
        verifier_path=Path(__file__).with_name("iteration50_installed_fixture.py"),
        wheel_path=wheel_path,
        wheel_sha256=wheel_sha256,
        example_dir=example_dir,
        config_path=config_path,
        mode=mode,
        factor_mode=factor_mode,
        python=python,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(example_dir).resolve()),
            env=_sanitized_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstalledFixtureError("public CLI exceeded its bounded timeout") from exc
    summary = _last_json_object(completed.stdout)
    child = _child_receipt(completed.stdout)
    expected_status = EXPECTED_STATUSES[mode]
    if (
        completed.returncode != 0
        or child.get("exit_code") != completed.returncode
        or summary.get("status") != expected_status
        or child.get("wheel_sha256") != wheel_sha256
        or child.get("loaded_modules_verified", 0) <= 0
        or child.get("fresh_bytecode_cache") is not True
    ):
        raise InstalledFixtureError("public CLI or installed-origin acceptance failed")
    return {
        "mode": mode,
        "factor_mode": factor_mode,
        "cli_argv": [
            str(Path(example_dir).resolve() / "run.py"),
            "--config",
            str(Path(config_path).resolve()),
            "--mode",
            mode,
            "--factor-mode",
            factor_mode,
        ],
        "exit_code": completed.returncode,
        "status": summary["status"],
        "summary": summary,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "installed_child": child,
    }


_SYNTHETIC_LIVE_EXPECTATIONS = {
    "read-only": (0, "LIVE_EPOCH_SEQUENCE_COMPLETE", None, False),
    "write": (0, "LIVE_EPOCH_SEQUENCE_COMPLETE", None, True),
    "write-denied": (2, "BLOCKED", "LIVE_WRITE_GRANT_MISSING_IN_CONFIG", False),
    "tier-escalation": (2, "BLOCKED", "ENTRY_TIER_ESCALATION_DENIED", False),
}


def _synthetic_live_child_command(
    *,
    wheel_path: Path,
    wheel_sha256: str,
    example_dir: Path,
    workspace: Path,
    case: str,
    factor_mode: str,
    python: str = sys.executable,
) -> list[str]:
    if case not in SYNTHETIC_LIVE_CASES:
        raise InstalledFixtureError("synthetic-live case is outside the fixed local set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    return [
        python,
        "-I",
        "-c",
        _SYNTHETIC_LIVE_CHILD_CODE,
        str(Path(__file__).with_name("iteration50_installed_fixture.py").resolve(strict=True)),
        str(Path(wheel_path).resolve(strict=True)),
        wheel_sha256,
        str(Path(example_dir).resolve(strict=True)),
        str((Path(example_dir).resolve(strict=True) / "config.yaml").resolve(strict=True)),
        str(Path(workspace).resolve(strict=True)),
        case,
        factor_mode,
    ]


def run_synthetic_live_case(
    *,
    example_dir: Path,
    workspace: Path,
    wheel_path: Path,
    wheel_sha256: str,
    case: str,
    factor_mode: str = "native",
    timeout_seconds: float = 300.0,
    python: str = sys.executable,
) -> dict[str, Any]:
    """Run one explicit live profile with the installed CTP SDK leaf faked locally."""

    if case not in SYNTHETIC_LIVE_CASES:
        raise InstalledFixtureError("synthetic-live case is outside the fixed local set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    if not (0 < timeout_seconds <= 1800):
        raise InstalledFixtureError(
            "synthetic-live timeout must be finite and at most 1800 seconds"
        )
    example = _require_external(example_dir, label="synthetic-live example")
    if not example.is_dir() or not (example / "run.py").is_file():
        raise InstalledFixtureError("copied public runner is unavailable")
    if not (example / "config.yaml").is_file():
        raise InstalledFixtureError("copied public live config template is unavailable")
    target_workspace = _require_external(workspace, label="synthetic-live workspace")
    target_workspace.mkdir(parents=True, exist_ok=True)
    wheel = Path(wheel_path).expanduser().resolve(strict=True)
    if (
        not wheel.is_file()
        or wheel.suffix.lower() != ".whl"
        or type(wheel_sha256) is not str
        or len(wheel_sha256) != 64
        or any(value not in "0123456789abcdef" for value in wheel_sha256)
        or _sha256(wheel) != wheel_sha256
    ):
        raise InstalledFixtureError("wheel does not match the supplied SHA-256")
    command = _synthetic_live_child_command(
        wheel_path=wheel,
        wheel_sha256=wheel_sha256,
        example_dir=example,
        workspace=target_workspace,
        case=case,
        factor_mode=factor_mode,
        python=python,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(example),
            env=_sanitized_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstalledFixtureError("synthetic-live child exceeded its bounded timeout") from exc
    summary = _last_json_object(completed.stdout)
    summary_line = _last_json_object_line(completed.stdout)
    child = _synthetic_live_child_receipt(completed.stdout)
    if (
        child.get("raw_cli_summary_sha256")
        != hashlib.sha256(summary_line.encode("utf-8")).hexdigest()
    ):
        raise InstalledFixtureError("production CLI summary bytes changed in the fixture")
    expected_exit, expected_status, expected_code, expected_writes = _SYNTHETIC_LIVE_EXPECTATIONS[
        case
    ]
    reported_argv = child.get("cli_argv")
    if (
        type(reported_argv) is not list
        or len(reported_argv) not in {7, 8}
        or reported_argv[0] != str((example / "run.py").resolve())
        or reported_argv[1] != "--config"
    ):
        raise InstalledFixtureError("synthetic-live child command receipt is malformed")
    live_config_path = Path(reported_argv[2]).resolve(strict=False)
    if (
        not _is_within(live_config_path, target_workspace)
        or live_config_path.name != "runner.yaml"
        or live_config_path.is_symlink()
    ):
        raise InstalledFixtureError("synthetic-live config escaped its external workspace")
    cli_argv = [
        str((example / "run.py").resolve()),
        "--config",
        str(live_config_path),
        "--mode",
        "live",
        "--factor-mode",
        factor_mode,
    ]
    if case in {"write", "write-denied"}:
        cli_argv.append("--allow-write")
    common_ok = (
        completed.returncode == expected_exit
        and child.get("exit_code") == expected_exit
        and child.get("case") == case
        and child.get("cli_argv") == cli_argv
        and child.get("wheel_sha256") == wheel_sha256
        and child.get("loaded_modules_verified", 0) > 0
        and child.get("fresh_bytecode_cache") is True
        and child.get("ctp_wrapper_factory_unchanged") is True
        and child.get("network_attempts") == 0
        and child.get("synthetic_only") is True
        and child.get("virtual_scheduler") is True
        and child.get("virtual_scheduler_monotonic_is_real") is True
        and child.get("runner_clock_patch_binding") == "run.__globals__['RunnerWallClock']"
        and child.get("runner_clock_patch_target_is_function_globals") is True
        and child.get("runner_clock_patch_origin") == str((example / "run.py").resolve())
        and child.get("clock_origins")
        == {
            "runner_wall_clock_binding": "copied run.py run.__globals__['RunnerWallClock']",
            "ctp_receive_wall_clock": (
                "backtrader.stores.btapistore.time.time -> synthetic virtual UTC"
            ),
            "monotonic_clock": "host time.monotonic_ns forwarded without virtualization",
            "scheduler_shared_state": (
                "RunnerWallClock and CTP leaves share one child-local instance"
            ),
        }
        and child.get("store_environment_shape_valid") is True
        and child.get("store_environment_api_kwargs_keys") == ["fixture_marker"]
        and type(child.get("selection_bundle_sha256")) is str
        and len(child["selection_bundle_sha256"]) == 64
        and child.get("authorized_products") == ["DCE.M", "DCE.A"]
    )
    if expected_code is None:
        summary_ok = (
            summary.get("status") == expected_status
            and summary.get("mode") == "live"
            and summary.get("cleanup_complete") is True
            and summary.get("epoch_count") == 1
            and summary.get("write_mode") is expected_writes
            and child.get("runner_summary_scheduler_clock_labels")
            == [{"path": "epochs[0]", "value": "host-utc-plus-monotonic"}]
            and child.get("runner_summary_scheduler_clock_label_meaning")
            == ("production summary default identifier; not the injected runtime clock")
            and child.get("ctp_wrapper_mro_verified") is True
            and child.get("ctp_trader_leaf_instances") == 1
            and child.get("ctp_md_leaf_instances") == 1
            and child.get("store_write_flags") == [expected_writes]
            and child.get("runner_clock_constructor_calls") == 1
            and child.get("runner_clock_shared_with_virtual_scheduler") is True
            and child.get("virtual_scheduler_advance_count", 0) > 0
            and child.get("virtual_scheduler_delivered_ticks", 0) > 0
            and child.get("virtual_scheduler_callback_delivery_count", 0)
            == child.get("synthetic_fill_count", 0)
            and child.get("virtual_scheduler_pending_callbacks") == 0
            and child.get("virtual_scheduler_late_callback_schedule_count") == 0
            and child.get("virtual_scheduler_final_utc")
            and child.get("synthetic_leaf_close_receipt")
            == {
                "trader_client_count": 1,
                "md_client_count": 1,
                "trader_stop_calls": 1,
                "trader_disconnect_calls": 1,
                "md_stop_calls": 1,
                "trader_connected_after_close": [False],
                "trader_ready_after_close": [False],
                "md_started_after_close": [False],
                "wrappers_connected_after_close": [False],
            }
        )
        epochs = summary.get("epochs")
        summary_ok = summary_ok and isinstance(epochs, list) and len(epochs) == 1
        if summary_ok:
            epoch = epochs[0]
            summary_ok = (
                epoch.get("status") == "LIVE_RUN_COMPLETE"
                and epoch.get("cleanup_complete") is True
                and set(epoch.get("routes", {})) == {"DCE.M", "DCE.Y", "DCE.A"}
                and epoch.get("selection_source") == "saved_bundle_legacy"
                and epoch.get("scheduler_clock") == "host-utc-plus-monotonic"
                and isinstance(epoch.get("selection_evidence"), Mapping)
                and epoch["selection_evidence"].get("routes")
                == {
                    "DCE.M": "M2611",
                    "DCE.Y": "Y2611",
                    "DCE.A": "A2611",
                }
                and epoch["selection_evidence"].get("authorized_targets") == ["DCE.M", "DCE.A"]
                and isinstance(epoch.get("strategy_order_events"), Mapping)
                and epoch["strategy_order_events"].get("status") == "AVAILABLE"
                and isinstance(epoch["strategy_order_events"].get("events"), list)
                and set(child.get("subscriptions", ())) == {"M2611", "Y2611", "A2611"}
                and {"account", "positions", "orders", "trades"}.issubset(
                    set(child.get("query_families", ()))
                )
            )
        if case == "read-only":
            common_ok = (
                common_ok
                and child.get("synthetic_leaf_actions") == []
                and child.get("synthetic_fill_count") == 0
                and child.get("ctp_order_callback_count") == 0
                and child.get("ctp_trade_callback_count") == 0
            )
        elif case == "write":
            strategy_events = (
                epochs[0].get("strategy_order_events", {}).get("events", [])
                if isinstance(epochs, list) and epochs
                else []
            )
            synthetic_actions = child.get("synthetic_leaf_actions")
            common_ok = (
                common_ok
                and isinstance(synthetic_actions, list)
                and bool(synthetic_actions)
                and any(
                    isinstance(action, Mapping) and action.get("action") == "insert"
                    for action in synthetic_actions
                )
                and all(
                    isinstance(action, Mapping)
                    and action.get("action") in {"insert", "cancel"}
                    and action.get("exchange") == "DCE"
                    and action.get("instrument") in {"M2611", "A2611"}
                    for action in synthetic_actions
                )
                and child.get("arm_calls", 0) > 0
                and child.get("disarm_calls", 0) > 0
                and child.get("synthetic_fill_count", 0) > 0
                and child.get("ctp_order_callback_count", 0) > 0
                and child.get("ctp_trade_callback_count", 0) > 0
                and bool(strategy_events)
                and child.get("virtual_scheduler_callback_delivery_count", 0)
                == child.get("synthetic_fill_count")
            )
    else:
        summary_ok = (
            summary.get("status") == expected_status and summary.get("code") == expected_code
        )
        common_ok = common_ok and child.get("ctp_trader_leaf_instances") == 0
        common_ok = common_ok and child.get("ctp_md_leaf_instances") == 0
        common_ok = common_ok and child.get("synthetic_leaf_actions") == []
        common_ok = common_ok and child.get("runner_clock_constructor_calls") == 0
    if not common_ok or not summary_ok:
        raise InstalledFixtureError("synthetic-live case acceptance failed: " + case)
    return {
        "case": case,
        "factor_mode": factor_mode,
        "exit_code": completed.returncode,
        "status": summary["status"],
        "summary": summary,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "installed_child": child,
        "evidence_level": ("INSTALLED_WHEEL_LOCAL_SYNTHETIC_CTP_SDK_LEAF_VIRTUAL_SCHEDULER_ONLY"),
    }


def run_synthetic_live_matrix(
    *,
    example_dir: Path,
    workspace: Path,
    wheel_path: Path,
    wheel_sha256: str,
    factor_mode: str = "native",
    timeout_seconds: float = 300.0,
    python: str = sys.executable,
) -> list[dict[str, Any]]:
    """Run all fixed read/write admission profiles in separate isolated children."""

    return [
        run_synthetic_live_case(
            example_dir=example_dir,
            workspace=workspace,
            wheel_path=wheel_path,
            wheel_sha256=wheel_sha256,
            case=case,
            factor_mode=factor_mode,
            timeout_seconds=timeout_seconds,
            python=python,
        )
        for case in SYNTHETIC_LIVE_CASES
    ]


_INPUT_FILE_LABELS = (
    "selection.bundle",
    "inputs.minute_tape",
    "inputs.execution_quotes",
    "inputs.instrument_metadata",
)


def _input_evidence(paths: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    evidence = {}
    for label in _INPUT_FILE_LABELS:
        value = paths.get(label)
        if value is None:
            continue
        path = Path(value).resolve(strict=True)
        if not path.is_file() or path.is_symlink():
            raise InstalledFixtureError(label + " is no longer a regular input file")
        evidence[label] = {
            "path": str(path),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
    return evidence


def _write_receipt(workspace: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(workspace) / RECEIPT_NAME
    if path.exists():
        raise InstalledFixtureError("fixture receipt destination already exists")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--example-source", type=Path, default=DEFAULT_EXAMPLE)
    parser.add_argument("--config", type=Path, help="public offline YAML config inside workspace")
    parser.add_argument("--mode", choices=SAFE_MODES)
    parser.add_argument(
        "--synthetic-live",
        action="store_true",
        help=(
            "run four fixed installed live CLI cases with synthetic CTP SDK leaves "
            "and a causal virtual UTC scheduler"
        ),
    )
    parser.add_argument("--factor-mode", choices=("native", "build"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    try:
        if (args.mode is None) == (args.synthetic_live is False):
            raise InstalledFixtureError(
                "select one offline mode or the explicit synthetic-live matrix"
            )
        if args.synthetic_live and args.config is not None:
            raise InstalledFixtureError(
                "synthetic-live matrix uses its generated public fixture config"
            )
        wheel = Path(args.wheel).expanduser().resolve(strict=True)
        if not wheel.is_file() or wheel.suffix.lower() != ".whl":
            raise InstalledFixtureError("wheel must be an existing .whl file")
        wheel_hash = args.wheel_sha256
        if (
            type(wheel_hash) is not str
            or len(wheel_hash) != 64
            or any(value not in "0123456789abcdef" for value in wheel_hash)
            or _sha256(wheel) != wheel_hash
        ):
            raise InstalledFixtureError("wheel does not match the supplied SHA-256")
        if not (0 < args.timeout_seconds <= 1800):
            raise InstalledFixtureError("timeout must be finite and at most 1800 seconds")
        workspace = _require_external(args.workspace, label="workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        config_source = args.config
        if config_source is not None:
            config_source = Path(config_source).expanduser().resolve(strict=True)
            if not _is_within(config_source, workspace):
                raise InstalledFixtureError("offline config must be inside the external workspace")
        copied_dir = workspace / "028_alpha003_simnow_minute"
        copied_dir, config_path, file_pins = copy_public_example(
            args.example_source,
            copied_dir,
            offline_config=config_source,
        )
        if args.synthetic_live:
            result = run_synthetic_live_matrix(
                example_dir=copied_dir,
                workspace=workspace,
                wheel_path=wheel,
                wheel_sha256=wheel_hash,
                factor_mode=args.factor_mode,
                timeout_seconds=args.timeout_seconds,
            )
            receipt = {
                "schema": "backtrader.iteration51.installed_synthetic_live_fixture.v1",
                "status": "PASS_INSTALLED_SYNTHETIC_LIVE_FIXTURE",
                "evidence_level": (
                    "INSTALLED_WHEEL_LOCAL_SYNTHETIC_CTP_SDK_LEAF_VIRTUAL_SCHEDULER_ONLY"
                ),
                "source_files": file_pins,
                "workspace": str(workspace),
                "copied_example": str(copied_dir),
                "wheel": {"path": str(wheel), "sha256": wheel_hash},
                "case_names": [row["case"] for row in result],
                "case_results": result,
            }
        else:
            resolved_inputs = validate_offline_config(config_path, workspace, args.mode)
            input_evidence = _input_evidence(resolved_inputs)
            result = run_cli_case(
                example_dir=copied_dir,
                config_path=config_path,
                wheel_path=wheel,
                wheel_sha256=wheel_hash,
                mode=args.mode,
                factor_mode=args.factor_mode,
                timeout_seconds=args.timeout_seconds,
            )
            if _input_evidence(resolved_inputs) != input_evidence:
                raise InstalledFixtureError("offline fixture inputs changed during the CLI run")
            receipt = {
                "schema": "backtrader.iteration51.installed_cli_fixture.v1",
                "status": "PASS_INSTALLED_PUBLIC_CLI_FIXTURE",
                "evidence_level": "INSTALLED_WHEEL_PUBLIC_CLI_FIXTURE_ONLY",
                "source_files": file_pins,
                "workspace": str(workspace),
                "copied_example": str(copied_dir),
                "config_path": str(config_path),
                "offline_input_evidence": input_evidence,
                "wheel": {"path": str(wheel), "sha256": wheel_hash},
                "command_result": result,
            }
        receipt_path = _write_receipt(workspace, receipt)
        print(
            json.dumps({"status": receipt["status"], "receipt": str(receipt_path)}, sort_keys=True)
        )
        return 0
    except (InstalledFixtureError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
