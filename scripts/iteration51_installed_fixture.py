#!/usr/bin/env python
"""Run the public 028 Alpha003 CLI against an installed Backtrader wheel.

The default profile copies the four public example files to a fresh directory
outside the checkout and runs only dry, research, or local replay.  A separate
``--synthetic-live`` profile runs the actual live CLI with in-memory CTP SDK
native/client leaves under the installed Store, Broker, feed, and Cerebro
path. Its official profile selector is the exact public source blob pinned at
``48b476ea90665791c7d2f86935720ce238931520``; this is not a complete installed
CTP wheel. The installed ``btapistore`` CTP factory and its
``RegisteredSimWrapper`` / ``CtpClientWrapper`` composition stay intact. The
child binds its causal virtual UTC scheduler through the copied ``run.py``
function globals and keeps real monotonic lifecycle bounds. Offline profiles
do not require this selector. No profile enables live in the offline
allowlist or changes the four copied example files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
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
SDK_SELECTOR_SOURCE_COMMIT = "48b476ea90665791c7d2f86935720ce238931520"
SDK_SELECTOR_SOURCE_RELATIVE_PATH = "src/bt_api_ctp/ctp_env_selector.py"
SDK_SELECTOR_SOURCE_SIZE_BYTES = 21403
SDK_SELECTOR_SOURCE_SHA256 = "ca8fa2b48293e7c5d79c1a0cfc20fd229879693290b99b56440b84c72cae12c3"
SDK_SELECTOR_MODULE = "bt_api_ctp.ctp_env_selector"
SDK_SELECTOR_PROFILE = "set1_group1"
SDK_SELECTOR_EVIDENCE_LEVEL = "INSTALLED_BT_WHEEL_PUBLIC_SDK_SOURCE_FIXTURE"
SYNTHETIC_WRITE_MAX_ORDER_INTENTS_PER_RUN = 20
_SYNTHETIC_LIVE_CHECK_IDS = frozenset(
    {
        "summary.direct_live_run_shape",
        "summary.selection_profile_and_routes",
        "summary.selection_bundle_path",
        "summary.strategy_order_events",
        "child.summary_scheduler_clock_label",
        "child.query_families",
        "child.subscriptions",
        "child.planned_slot_count",
        "summary.decision_tape_counts",
        "summary.decision_tape_readback",
        "summary.resource_shutdown",
        "child.runtime_source_authorization_clock_or_lifecycle",
        "child.wrapper_scheduler_and_close_receipts",
        "summary.expected_blocked_status_and_code",
    }
)


class InstalledFixtureError(RuntimeError):
    """A public installed-wheel CLI check could not prove its contract."""

    def __init__(self, message: str, *, safe_check_ids: Sequence[str] = ()) -> None:
        super().__init__(message)
        accepted = []
        for check_id in safe_check_ids:
            if (
                type(check_id) is str
                and check_id in _SYNTHETIC_LIVE_CHECK_IDS
                and check_id not in accepted
            ):
                accepted.append(check_id)
        self.safe_check_ids = tuple(accepted)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pinned_sdk_selector_source(path: Path) -> dict[str, Any]:
    """Validate the one public SDK selector source admitted to synthetic live."""

    requested = Path(path).expanduser()
    if any(component.is_symlink() for component in (requested, *requested.parents)):
        raise InstalledFixtureError("SDK selector source must not be a symlink")
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise InstalledFixtureError("pinned SDK selector source is unavailable") from exc
    if _is_within(resolved, REPOSITORY_ROOT):
        raise InstalledFixtureError("SDK selector source must be outside the checkout")
    if not resolved.is_file():
        raise InstalledFixtureError("SDK selector source must be a regular file")
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise InstalledFixtureError("pinned SDK selector source is unavailable") from exc
    if len(payload) != SDK_SELECTOR_SOURCE_SIZE_BYTES:
        raise InstalledFixtureError("SDK selector source does not match the fixed public size")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != SDK_SELECTOR_SOURCE_SHA256:
        raise InstalledFixtureError("SDK selector source does not match the fixed public pin")
    return {
        "source_commit": SDK_SELECTOR_SOURCE_COMMIT,
        "source_path": SDK_SELECTOR_SOURCE_RELATIVE_PATH,
        "path": str(resolved),
        "module": SDK_SELECTOR_MODULE,
        "size_bytes": SDK_SELECTOR_SOURCE_SIZE_BYTES,
        "sha256": SDK_SELECTOR_SOURCE_SHA256,
    }


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


_SYNTHETIC_LIVE_CHILD_CODE = r'''import hashlib, importlib.machinery, importlib.util, json, os, runpy, socket, sys, tempfile, types
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

helper_path, wheel_path, wheel_hash, example_dir, template_path, workspace, selector_source_path, case, factor_mode, slot_count_text = sys.argv[1:]
SDK_SELECTOR_SOURCE_COMMIT = "48b476ea90665791c7d2f86935720ce238931520"
SDK_SELECTOR_SOURCE_RELATIVE_PATH = "src/bt_api_ctp/ctp_env_selector.py"
SDK_SELECTOR_SOURCE_SIZE_BYTES = 21403
SDK_SELECTOR_SOURCE_SHA256 = "ca8fa2b48293e7c5d79c1a0cfc20fd229879693290b99b56440b84c72cae12c3"
SDK_SELECTOR_MODULE = "bt_api_ctp.ctp_env_selector"
SDK_SELECTOR_PROFILE = "set1_group1"
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
requested_selector_path = Path(selector_source_path).expanduser()
if any(
    component.is_symlink()
    for component in (requested_selector_path, *requested_selector_path.parents)
):
    raise RuntimeError("pinned SDK selector source must not be a symlink")
selector_path = requested_selector_path.resolve(strict=True)
try:
    selector_path.relative_to(repository_root)
except ValueError:
    pass
else:
    raise RuntimeError("pinned SDK selector source must be outside the checkout")
if not selector_path.is_file():
    raise RuntimeError("pinned SDK selector source is not a regular file")
selector_source_bytes = selector_path.read_bytes()
selector_source_sha256 = hashlib.sha256(selector_source_bytes).hexdigest()
if (
    len(selector_source_bytes) != SDK_SELECTOR_SOURCE_SIZE_BYTES
    or selector_source_sha256 != SDK_SELECTOR_SOURCE_SHA256
):
    raise RuntimeError("pinned SDK selector source does not match the fixed public pin")
if "bt_api_ctp" in sys.modules or SDK_SELECTOR_MODULE in sys.modules:
    raise RuntimeError("SDK selector package was unexpectedly preloaded")
sdk_package = types.ModuleType("bt_api_ctp")
sdk_package.__package__ = "bt_api_ctp"
sdk_package.__path__ = [str(selector_path.parent)]
sdk_package.__spec__ = importlib.machinery.ModuleSpec(
    "bt_api_ctp", loader=None, is_package=True
)
sdk_package.__spec__.submodule_search_locations = [str(selector_path.parent)]
sys.modules["bt_api_ctp"] = sdk_package
selector_module = types.ModuleType(SDK_SELECTOR_MODULE)
selector_module.__file__ = str(selector_path)
selector_module.__package__ = "bt_api_ctp"
selector_module.__spec__ = importlib.machinery.ModuleSpec(
    SDK_SELECTOR_MODULE, loader=None, origin=str(selector_path)
)
sys.modules[SDK_SELECTOR_MODULE] = selector_module
setattr(sdk_package, "ctp_env_selector", selector_module)
exec(compile(selector_source_bytes, str(selector_path), "exec"), selector_module.__dict__)
selector_td_front, selector_md_front = selector_module.official_simnow_fronts(
    SDK_SELECTOR_PROFILE
)
selector_inferred_profile = selector_module.official_simnow_profile_for_td_front(
    selector_td_front
)
selector_profile_verified = selector_module.verify_official_simnow_profile(
    selector_td_front, selector_md_front, SDK_SELECTOR_PROFILE
)
if selector_inferred_profile != SDK_SELECTOR_PROFILE or selector_profile_verified is not True:
    raise RuntimeError("pinned SDK selector did not verify the fixed synthetic profile")
selector_source_receipt = {
    "source_commit": SDK_SELECTOR_SOURCE_COMMIT,
    "source_path": SDK_SELECTOR_SOURCE_RELATIVE_PATH,
    "path": str(selector_path),
    "module": SDK_SELECTOR_MODULE,
    "module_origin": selector_module.__file__,
    "size_bytes": len(selector_source_bytes),
    "sha256": selector_source_sha256,
    "profile_id": SDK_SELECTOR_PROFILE,
    "official_fronts_lookup": True,
    "td_front_profile_lookup": True,
    "official_profile_verification": True,
}
import yaml
config = yaml.safe_load(template_path.read_text(encoding="utf-8"))

# Reuse Iteration 50's bounded execution/query provider leaf.  The SDK-facing
# clients below are synthetic modules at the CTP leaf boundary; the installed
# CtpClientWrapper and RegisteredSimWrapper remain in the runtime MRO.
targets = ("M2611", "Y2611", "A2611")
helper._TARGETS = targets
slot_count = int(slot_count_text)
if not 30 <= slot_count <= 64:
    raise RuntimeError("synthetic planned slot count is outside the fixture bounds")
source_slot_count = slot_count + 1
utc = timezone.utc
china = timezone(timedelta(hours=8))
created_at = datetime.now(utc)
first_close = created_at.replace(second=0, microsecond=0) + timedelta(minutes=3)
last_close = first_close + timedelta(minutes=slot_count - 1)
source_first_close = first_close - timedelta(minutes=1)
bars, _unused_calendar = helper._fixture_bars(
    slot_count=source_slot_count,
    include_extra_fields=False,
    varied_stream=True,
    first_close=source_first_close,
)
# The shared execution helper intentionally exposes immutable bar rows.  Add
# synthetic session metadata only to fixture-owned mutable copies.
bars = {
    target: [dict(row) for row in target_rows]
    for target, target_rows in bars.items()
}

# Reuse the same synthetic contract metadata exposed by the execution leaf;
# its PriceTick is 1 and its price range is 1..1000.
contract_leaf = object.__new__(helper._ExecutionProviderLeaf)
contract_leaf._provider_available = 100_000.0
contract_rows = contract_leaf._execution_query_rows()
contract_by_target = {
    str(row["InstrumentID"]): row for row in contract_rows["instruments_result"]
}
margin_by_target = {
    str(row["InstrumentID"]): row
    for row in contract_rows["instrument_margin_rate_result"]
}
if set(contract_by_target) != set(targets) or set(margin_by_target) != set(targets):
    raise RuntimeError("synthetic contract metadata does not cover the three targets")
price_tick_by_target = {
    target: Decimal(str(row["PriceTick"])) for target, row in contract_by_target.items()
}
if any(tick <= 0 for tick in price_tick_by_target.values()):
    raise RuntimeError("synthetic contract PriceTick must be positive")
price_scale = Decimal("100")
for target_rows in bars.values():
    for target_row in target_rows:
        for field_name in ("open", "high", "low", "close"):
            target_row[field_name] = float(
                Decimal(str(target_row[field_name])) * price_scale
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
for target, target_rows in bars.items():
    contract = contract_by_target[target]
    lower_limit = Decimal(str(contract["LowerLimitPrice"]))
    upper_limit = Decimal(str(contract["UpperLimitPrice"]))
    for target_row in target_rows:
        if (
            Decimal(str(target_row["low"])) < lower_limit
            or Decimal(str(target_row["high"])) > upper_limit
        ):
            raise RuntimeError("scaled synthetic OHLC exceeds its contract price limits")
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
authorized_contract_notional = Decimal("0")
authorized_contract_margin = Decimal("0")
authorized_instruments = {
    instruments[product]
    for product in products
    if "DCE." + product.product_id in authorized_targets
}
for target in targets:
    if target not in authorized_instruments:
        continue
    contract = contract_by_target[target]
    price_tick = price_tick_by_target[target]
    max_ask_price = max(
        (Decimal(str(row["high"])) / price_tick).quantize(Decimal("1")) * price_tick
        + price_tick
        for row in bars[target]
    )
    max_contract_notional = max_ask_price * Decimal(str(contract["VolumeMultiple"]))
    max_contract_margin = max_contract_notional * Decimal(
        str(margin_by_target[target]["LongMarginRatioByMoney"])
    )
    if (
        max_contract_notional > Decimal(write_risk["max_notional_per_position"])
        or max_contract_margin > Decimal(write_risk["max_margin_per_position"])
    ):
        raise RuntimeError("synthetic contract price exceeds the write-risk per-position budget")
    authorized_contract_notional += max_contract_notional
    authorized_contract_margin += max_contract_margin
if (
    authorized_contract_notional > Decimal(write_risk["max_total_notional"])
    or authorized_contract_margin > Decimal(write_risk["max_total_margin"])
    or authorized_contract_margin > Decimal(str(contract_leaf._provider_available))
):
    raise RuntimeError("synthetic contract prices exceed the total write-risk budget")
if case == "write":
    config["risk"].update(write_risk)
    config["live"]["arm_templates"] = [
        {
            "target": "DCE." + product.product_id,
            "md_front": selector_md_front,
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
        "td_address": selector_td_front,
        "md_address": selector_md_front,
        "ctp_env_profile": SDK_SELECTOR_PROFILE,
        "broker_id": "9999",
        "investor_id": "ITERATION51_SYNTHETIC_ONLY",
        "password": "FIXTURE_ONLY_NOT_A_CREDENTIAL",
        "appid": "simnow_client_test",
        "auth_code": "FIXTURE_ONLY_NOT_A_CREDENTIAL",
        "bar_watermark_ms": 0,
    },
    "api_kwargs": {
        "fixture_marker": "iteration51-synthetic-ctp-leaf",
        "live_tick_provenance": {
            "clock_domain_id": helper._CLOCK_DOMAIN,
            "rules_hash": "a" * 64,
            "session_segment": "regular",
        },
    },
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
    "arm_scope_observations": [], "disarm_scope_observations": [],
    "synthetic_leaf_actions": [], "disconnect_calls": 0,
    "trader_stop_calls": 0, "md_stop_calls": 0, "wrapper_mros": [],
    "wrapper_write_flags": [], "wrapper_api_instances": [],
    "synthetic_fill_count": 0, "ctp_order_callback_count": 0,
    "ctp_trade_callback_count": 0, "ctp_order_callback_associations": [],
    "ctp_trade_callback_associations": [], "ctp_trade_query_associations": [],
}
helper._EXECUTION_TRADING_DAY = trading_day.strftime("%Y%m%d")

# Build a causal event schedule.  The first source minute is a warm-up bucket
# that the installed CTP feed intentionally discards as its cumulative-volume
# baseline.  Each later source minute maps one planned cohort slot; one final
# boundary tick closes the last planned minute.
def _synthetic_quote_fields(target, price, cumulative_volume):
    price_tick = price_tick_by_target[target]
    tick_units = (Decimal(str(price)) / price_tick).quantize(Decimal("1"))
    last_price = tick_units * price_tick
    bid_price = last_price - price_tick
    ask_price = last_price + price_tick
    contract = contract_by_target[target]
    if (
        bid_price < Decimal(str(contract["LowerLimitPrice"]))
        or ask_price > Decimal(str(contract["UpperLimitPrice"]))
    ):
        raise RuntimeError("synthetic quote exceeds its contract price limits")
    return {
        "LastPrice": float(last_price),
        "BidPrice1": float(bid_price),
        "AskPrice1": float(ask_price),
        "Turnover": float(last_price) * cumulative_volume,
    }


def _synthetic_ctp_payload(fields):
    """Build the attribute-backed leaf shape used by native CTP callbacks."""
    if not isinstance(fields, dict):
        raise TypeError("synthetic CTP payload fields must be a dict")
    return types.SimpleNamespace(**fields)


synthetic_events = []
for target in targets:
    cumulative_volume = 0
    for row_index, row in enumerate(bars[target]):
        bucket_start = row["bucket_start"]
        values = (row["open"], row["high"], row["low"], row["close"])
        bar_volume_decimal = Decimal(str(row["volume"]))
        if not bar_volume_decimal.is_finite() or bar_volume_decimal <= 0:
            raise RuntimeError("synthetic source bar volume must be finite and positive")
        bar_volume = int(bar_volume_decimal.to_integral_value())
        if bar_volume < 4:
            raise RuntimeError("synthetic source bar needs positive volume at all four ticks")
        tick_volume_base, tick_volume_remainder = divmod(bar_volume, len(values))
        for tick_index, (offset_seconds, price) in enumerate(
            zip((1, 15, 30, 50), values)
        ):
            tick_volume = tick_volume_base + int(tick_index < tick_volume_remainder)
            cumulative_volume += tick_volume
            event_time = bucket_start + timedelta(seconds=offset_seconds)
            local_time = event_time.astimezone(china)
            payload = {
                "InstrumentID": target,
                "ExchangeID": "DCE",
                **_synthetic_quote_fields(target, price, cumulative_volume),
                "Volume": cumulative_volume,
                "OpenInterest": 0,
                "TradingDay": trading_day.strftime("%Y%m%d"),
                "ActionDay": local_time.strftime("%Y%m%d"),
                "UpdateTime": local_time.strftime("%H:%M:%S"),
                "UpdateMillisec": 0,
                "BidVolume1": 5,
                "AskVolume1": 6,
            }
            synthetic_events.append(
                (
                    event_time,
                    target,
                    row_index,
                    tick_index,
                    _synthetic_ctp_payload(payload),
                )
            )
    cumulative_volume += 1
    sentinel_time = last_close + timedelta(seconds=1)
    local_time = sentinel_time.astimezone(china)
    synthetic_events.append((
        sentinel_time,
        target,
        source_slot_count,
        0,
        _synthetic_ctp_payload({
            "InstrumentID": target,
            "ExchangeID": "DCE",
            **_synthetic_quote_fields(
                target, bars[target][-1]["close"], cumulative_volume
            ),
            "Volume": cumulative_volume,
            "OpenInterest": 0,
            "TradingDay": trading_day.strftime("%Y%m%d"),
            "ActionDay": local_time.strftime("%Y%m%d"),
            "UpdateTime": local_time.strftime("%H:%M:%S"),
            "UpdateMillisec": 0,
            "BidVolume1": 5,
            "AskVolume1": 6,
        }),
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


if sys.modules.get("bt_api_ctp") is not sdk_package:
    raise RuntimeError("pinned SDK selector package binding changed before CTP leaves")
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
    # The synthetic leaf constructor is called by the real installed wrapper's
    # connect() method. Its own frame is one level above this helper; the next
    # frame owns the actual CtpClientWrapper/RegisteredSimWrapper instance.
    leaf_frame = sys._getframe(1)
    wrapper_frame = leaf_frame.f_back
    if wrapper_frame is None or wrapper_frame.f_code.co_name != "connect":
        raise RuntimeError("synthetic SDK leaf was not constructed by CTP connect()")
    wrapper = wrapper_frame.f_locals.get("self")
    if wrapper is None:
        raise RuntimeError("synthetic SDK leaf was not constructed by CtpClientWrapper")
    mro = type(wrapper).__mro__
    mro_names = [base.__name__ for base in mro]
    ctp_wrapper = next((base for base in mro if base.__name__ == "CtpClientWrapper"), None)
    if (
        ctp_wrapper is None
        or ctp_wrapper.connect.__code__ is not wrapper_frame.f_code
        or "RegisteredSimWrapper" not in mro_names
    ):
        raise RuntimeError("installed RegisteredSim/Ctp wrapper composition is missing")
    if not any(existing is wrapper for existing in fake_state["wrapper_api_instances"]):
        fake_state["wrapper_mros"].append(mro_names)
        fake_state["wrapper_write_flags"].append(
            getattr(wrapper, "_registered_sim_allow_writes", None)
        )
        fake_state["wrapper_api_instances"].append(wrapper)
    return wrapper


class SyntheticTraderClient(helper._ExecutionProviderLeaf):
    """Iteration 50 provider leaf below the installed CTP wrapper."""

    def __init__(self, **kwargs):
        del kwargs
        self._fixture_wrapper_owner = _wrapper_owner_from_sdk_constructor()
        super().__init__(bars=bars, slot_count=source_slot_count)
        # Query wall-clock provenance and the runner's decision time must use
        # the same synthetic UTC domain. The provider leaf keeps its default
        # host-UTC behavior for other consumers; monotonic expiry remains real.
        self._query_utc_clock = virtual_scheduler
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

    def _order_row(self, order_ref, *, status, filled, remaining):
        row = super()._order_row(
            order_ref, status=status, filled=filled, remaining=remaining
        )
        identity = self._order_identity[str(order_ref)]
        row["OrderSysID"] = identity["order_sys_id"]
        return row

    def _trade_row(self, order_ref, trade_id, *, quantity, offset, when, fee):
        row = super()._trade_row(
            order_ref,
            trade_id,
            quantity=quantity,
            offset=offset,
            when=when,
            fee=fee,
        )
        identity = self._order_identity[str(order_ref)]
        row["OrderSysID"] = identity["order_sys_id"]
        row["Price"] = str(identity["price"])
        return row

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
        grant = super().arm_execution_for_registered_sim(**kwargs)
        gate_state = grant[1] if isinstance(grant, tuple) and len(grant) == 2 else None
        authorized = (
            gate_state.get("authorized_instruments")
            if isinstance(gate_state, dict)
            else None
        )
        fake_state["arm_scope_observations"].append({
            "requested_instrument_id": str(kwargs.get("instrument_id", "")),
            "authorized_instruments": list(authorized) if isinstance(authorized, list) else None,
        })
        return grant

    def disarm_execution_gate(self, capability, reason):
        if capability is None:
            raise RuntimeError("synthetic disarm requires the issued capability")
        fake_state["disarm_calls"] += 1
        authorized = self._gate_state.get("authorized_instruments")
        fake_state["disarm_scope_observations"].append(
            [str(instrument) for instrument in authorized]
            if isinstance(authorized, list)
            else None
        )
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
            "order_ref": str(field.OrderRef),
            "instrument": str(field.InstrumentID),
            "exchange": str(field.ExchangeID),
        })
        result = super().submit_order_insert(
            field, request_id, execution_capability=execution_capability
        )
        order_ref = str(field.OrderRef)
        instrument = str(field.InstrumentID)
        exchange = str(field.ExchangeID)
        order_sys_id = "iteration51-sys-" + order_ref
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
            "order_sys_id": order_sys_id,
            "price": price,
            "front_id": self._front_id,
            "session_id": self._session_id,
        }

        def _emit_order_status(ctp_status, filled, remaining):
            self.observe_order(
                order_ref, ctp_status=ctp_status, filled=filled, remaining=remaining
            )
            query_order_row = self._provider_order_rows.get(order_ref)
            if not isinstance(query_order_row, dict):
                raise RuntimeError("synthetic order query row was not published")
            if query_order_row.get("OrderSysID") != order_sys_id:
                raise RuntimeError("synthetic CTP order query identity did not match")
            if not callable(self.on_order):
                raise RuntimeError("synthetic CTP trader lacks the production order callback")
            callback_owner = getattr(self.on_order, "__self__", None)
            local_time = virtual_scheduler.utc_now().astimezone(china)
            self.on_order(types.SimpleNamespace(
                OrderRef=order_ref,
                OrderSysID=order_sys_id,
                InstrumentID=instrument,
                ExchangeID=exchange,
                OrderStatus=ctp_status,
                OrderSubmitStatus="3",
                Direction=direction_flag,
                CombOffsetFlag=offset_flag,
                LimitPrice=price,
                VolumeTotalOriginal=quantity,
                VolumeTraded=filled,
                VolumeTotal=remaining,
                FrontID=self._front_id,
                SessionID=self._session_id,
                UpdateTime=local_time.strftime("%H:%M:%S"),
                TradingDay=self._trading_day,
            ))
            pending = (
                callback_owner._pending_orders.get(order_ref)
                if callback_owner is not None
                else None
            )
            pending_by_sys_id = (
                callback_owner._pending_orders_by_sys_id.get(order_sys_id)
                if callback_owner is not None
                else None
            )
            fake_state["ctp_order_callback_associations"].append({
                "order_ref": order_ref,
                "status": ctp_status,
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": query_order_row.get("OrderSysID"),
                "query_order_sys_id_matches": (
                    query_order_row.get("OrderSysID") == order_sys_id
                ),
                "callback_owner_is_wrapper": any(
                    wrapper is callback_owner
                    for wrapper in fake_state["wrapper_api_instances"]
                ),
                "pending_order_present": pending is not None,
                "pending_order_ref_matches": (
                    pending is not None and pending.get("order_ref") == order_ref
                ),
                "system_id_order_ref_matches": (
                    isinstance(pending_by_sys_id, dict)
                    and pending_by_sys_id.get("order_ref") == order_ref
                ),
                "system_id_uses_full_pending_order": (
                    pending is not None and pending_by_sys_id is pending
                ),
            })
            fake_state["ctp_order_callback_count"] += 1

        # The production wrapper observes the CTP accepted state before the
        # later synthetic fill callback, matching the ordinary order lifecycle.
        _emit_order_status("3", 0, quantity)

        def _complete_synthetic_fill():
            _emit_order_status("0", quantity, 0)
            trade_id = "iteration51-" + order_ref
            self.observe_trade_fill(
                order_ref,
                trade_id,
                quantity=quantity,
                offset=offset,
                when=virtual_scheduler.utc_now(),
                fee=0.0,
            )
            query_trade_rows = [
                row for row in self._provider_trade_rows if row.get("TradeID") == trade_id
            ]
            if len(query_trade_rows) != 1:
                raise RuntimeError("synthetic trade query row was not published exactly once")
            query_trade_row = query_trade_rows[0]
            query_price = query_trade_row.get("Price")
            try:
                query_price_decimal = Decimal(str(query_price))
                callback_price_decimal = Decimal(str(price))
                query_price_matches = (
                    query_price_decimal.is_finite()
                    and callback_price_decimal.is_finite()
                    and query_price_decimal == callback_price_decimal
                )
            except (InvalidOperation, TypeError, ValueError):
                query_price_matches = False
            if (
                query_trade_row.get("OrderSysID") != order_sys_id
                or not query_price_matches
            ):
                raise RuntimeError("synthetic CTP trade query identity/economics did not match")
            fake_state["ctp_trade_query_associations"].append({
                "trade_id": trade_id,
                "order_ref": order_ref,
                "callback_order_sys_id": order_sys_id,
                "query_order_sys_id": query_trade_row.get("OrderSysID"),
                "query_order_sys_id_matches": (
                    query_trade_row.get("OrderSysID") == order_sys_id
                ),
                "callback_price": str(price),
                "query_price": query_price,
                "query_price_matches": query_price_matches,
            })
            if not callable(self.on_trade):
                raise RuntimeError("synthetic CTP trader lacks the production trade callback")
            local_time = virtual_scheduler.utc_now().astimezone(china)
            trade_callback = types.SimpleNamespace(
                TradeID=trade_id,
                OrderRef=order_ref,
                OrderSysID=order_sys_id,
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
            )
            self.on_trade(trade_callback)
            fake_state["ctp_trade_callback_associations"].append({
                "trade_id": str(trade_callback.TradeID),
                "order_ref": str(trade_callback.OrderRef),
                "order_sys_id": str(trade_callback.OrderSysID),
                "callback_price": str(trade_callback.Price),
            })
            fake_state["ctp_trade_callback_count"] += 1
            fake_state["synthetic_fill_count"] += 1

        _schedule_synthetic_callback(
            virtual_scheduler.utc_now() + timedelta(seconds=1),
            _complete_synthetic_fill,
        )
        return result

    def submit_order_action(self, *args, **kwargs):
        field = args[0] if args else None
        fake_state["synthetic_leaf_actions"].append({
            "action": "cancel",
            "order_ref": str(getattr(field, "OrderRef", "")),
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
        self._fixture_wrapper_owner = _wrapper_owner_from_sdk_constructor()
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
live_cohort_exception_diagnostics = []
live_cohort_exception_indices = {}
live_cohort_exception_refs = []
previous_system_trace = sys.gettrace()

def _bounded_diagnostic_value(value, depth=0):
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str):
        return value[:256]
    if depth >= 2:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {
            str(key)[:80]: _bounded_diagnostic_value(item, depth + 1)
            for key, item in list(value.items())[:16]
        }
    if isinstance(value, (tuple, list)):
        return [_bounded_diagnostic_value(item, depth + 1) for item in value[:16]]
    return {"type": type(value).__name__}

def _trace_live_cohort_exception(frame, event, arg):
    if event == "call":
        if frame.f_globals.get("__name__") == "backtrader.research.live_cohort":
            return _trace_live_cohort_exception
        return None
    if event == "exception":
        error_type, error, traceback_value = arg
        error_module = getattr(error_type, "__module__", "")
        error_name = getattr(error_type, "__name__", "")
        if error_module == "backtrader.research.live_cohort" and error_name.startswith(
            "LiveCohort"
        ):
            identity = id(error)
            existing_index = live_cohort_exception_indices.get(identity)
            existing_error_is_same = (
                existing_index is not None
                and live_cohort_exception_refs[existing_index] is error
            )
            frames = []
            current = traceback_value
            while current is not None and len(frames) < 32:
                code = current.tb_frame.f_code
                frames.append(
                    {
                        "file": code.co_filename[:320],
                        "function": code.co_name[:160],
                        "line": current.tb_lineno,
                    }
                )
                current = current.tb_next
            if existing_error_is_same:
                prior = live_cohort_exception_diagnostics[existing_index]
                if len(frames) > len(prior["traceback"]):
                    prior["traceback"] = frames
            elif len(live_cohort_exception_diagnostics) < 8:
                try:
                    message = str(error)[:512]
                except Exception:
                    message = "<message-unavailable>"
                report = getattr(error, "report", None)
                live_cohort_exception_indices[identity] = len(
                    live_cohort_exception_diagnostics
                )
                live_cohort_exception_refs.append(error)
                live_cohort_exception_diagnostics.append(
                    {
                        "module": error_module,
                        "type": error_name,
                        "code": _bounded_diagnostic_value(getattr(error, "code", None)),
                        "detail": _bounded_diagnostic_value(getattr(error, "detail", None)),
                        "report": _bounded_diagnostic_value(report),
                        "message": message,
                        "traceback": frames,
                    }
                )
    return _trace_live_cohort_exception

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
    sys.settrace(_trace_live_cohort_exception)
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
    sys.settrace(previous_system_trace)
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
diagnostic_payload = {
    "schema": "backtrader.iteration51.synthetic_live_cohort_diagnostics.v1",
    "capture": "installed live_cohort exception events during copied public CLI run",
    "captured_exception_count": len(live_cohort_exception_diagnostics),
    "exceptions": live_cohort_exception_diagnostics,
    "runner_summary": (
        {
            key: _bounded_diagnostic_value(summary.get(key))
            for key in ("status", "code", "detail", "error_code")
            if key in summary
        }
        if isinstance(summary, dict)
        else None
    ),
}
diagnostic_bytes = json.dumps(
    diagnostic_payload, sort_keys=True, separators=(",", ":")
).encode("utf-8")
diagnostic_path = case_root / "live-cohort-exception-diagnostics.json"
with diagnostic_path.open("xb") as diagnostic_handle:
    diagnostic_handle.write(diagnostic_bytes)
diagnostic_receipt = {
    "path": str(diagnostic_path),
    "size_bytes": len(diagnostic_bytes),
    "sha256": hashlib.sha256(diagnostic_bytes).hexdigest(),
    "captured_exception_count": len(live_cohort_exception_diagnostics),
}
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
    "ctp_trader_leaf_wrapper_matches_registered_instance": (
        len(fake_state["trader_clients"]) == 1
        and len(fake_state["wrapper_api_instances"]) == 1
        and fake_state["trader_clients"][0]._fixture_wrapper_owner
        is fake_state["wrapper_api_instances"][0]
    ),
    "ctp_md_leaf_wrapper_matches_registered_instance": (
        len(fake_state["md_clients"]) == 1
        and len(fake_state["wrapper_api_instances"]) == 1
        and fake_state["md_clients"][0]._fixture_wrapper_owner
        is fake_state["wrapper_api_instances"][0]
    ),
    "store_write_flags": fake_state["wrapper_write_flags"],
    "query_families": sorted(set(fake_state["query_families"])),
    "subscriptions": sorted(fake_state["subscriptions"]),
    "arm_calls": fake_state["arm_calls"],
    "disarm_calls": fake_state["disarm_calls"],
    "arm_scope_observations": fake_state["arm_scope_observations"],
    "disarm_scope_observations": fake_state["disarm_scope_observations"],
    "disconnect_calls": fake_state["disconnect_calls"],
    "synthetic_leaf_actions": list(fake_state["synthetic_leaf_actions"]),
    "store_environment_shape_valid": True,
    "store_environment_api_kwargs_keys": sorted(store_environment["api_kwargs"]),
    "store_live_tick_provenance": store_environment["api_kwargs"]["live_tick_provenance"],
    "live_cohort_exception_diagnostics": diagnostic_receipt,
    "planned_slot_count": slot_count,
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
    "ctp_order_callback_associations": fake_state["ctp_order_callback_associations"],
    "ctp_trade_callback_count": fake_state["ctp_trade_callback_count"],
    "ctp_trade_callback_associations": fake_state["ctp_trade_callback_associations"],
    "ctp_trade_query_associations": fake_state["ctp_trade_query_associations"],
    "max_order_intents_per_run": write_risk["max_order_intents_per_run"],
    "synthetic_leaf_close_receipt": leaf_close_receipt,
    "synthetic_sdk_modules": [
        "bt_api_ctp.ctp", "bt_api_ctp.ctp.client",
        "bt_api_ctp.ctp.ctp_md_api", "bt_api_ctp.ctp.ctp_structs_order",
        "bt_api_ctp.ctp.ctp_trader_api",
    ],
    "installed_wrapper_origin": "backtrader.stores.btapistore._create_ctp_wrapper_class",
    "synthetic_sdk_module_origin": (
        "pinned public selector source plus in-memory native/client leaves; no SDK wheel"
    ),
    "sdk_selector_source": selector_source_receipt,
    "raw_cli_stdout_sha256": hashlib.sha256(raw_cli_stdout.encode("utf-8")).hexdigest(),
    "raw_cli_summary_sha256": hashlib.sha256(summary_line.encode("utf-8")).hexdigest(),
    "authorized_products": list(authorized_targets),
    "sdk_selector_profile_id": SDK_SELECTOR_PROFILE,
    "sdk_selector_profile_verified": selector_profile_verified,
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
        timeout_stdout = exc.stdout if exc.stdout is not None else b""
        timeout_stderr = exc.stderr if exc.stderr is not None else b""
        if isinstance(timeout_stdout, str):
            timeout_stdout = timeout_stdout.encode("utf-8")
        if isinstance(timeout_stderr, str):
            timeout_stderr = timeout_stderr.encode("utf-8")
        if type(timeout_stdout) is not bytes or type(timeout_stderr) is not bytes:
            raise InstalledFixtureError(
                "public CLI timed out with an unsupported partial-output type"
            ) from exc
        timeout_workspace = _require_external(
            Path(example_dir).resolve().parent,
            label="installed CLI timeout workspace",
        )
        timeout_output = _preserve_synthetic_child_output(
            timeout_workspace,
            "iteration51-installed-cli-" + mode + "-" + factor_mode,
            stdout_bytes=timeout_stdout,
            stderr_bytes=timeout_stderr,
            exit_record=b"UNKNOWN_TIMEOUT\n",
            exit_code=None,
            exit_status="unknown_timeout",
        )
        raise InstalledFixtureError(
            "public CLI exceeded its bounded timeout; exit status is unknown; "
            "raw output was preserved at " + timeout_output["stdout_path"]
        ) from exc
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
    "read-only": (0, "LIVE_RUN_COMPLETE", None, False),
    "write": (0, "LIVE_RUN_COMPLETE", None, True),
    "write-denied": (2, "BLOCKED", "LIVE_WRITE_GRANT_MISSING_IN_CONFIG", False),
    "tier-escalation": (2, "BLOCKED", "ENTRY_TIER_ESCALATION_DENIED", False),
}

_SYNTHETIC_QUERY_FAMILIES = [
    "account_result",
    "instrument_margin_rate_result",
    "instruments_result",
    "orders_result",
    "positions_result",
    "trades_result",
]


def _synthetic_live_summary_failure_checks(
    summary: Mapping[str, Any],
    child: Mapping[str, Any],
    *,
    planned_slot_count: int,
    expected_writes: bool,
    expected_selection_path: Path,
) -> list[str]:
    """Return finite names for the installed live summary contracts that failed."""

    failures: list[str] = []
    expected_routes = {"DCE.M": "M2611", "DCE.Y": "Y2611", "DCE.A": "A2611"}
    expected_targets = ["DCE.M", "DCE.A"]

    direct_summary_ok = (
        summary.get("status") == "LIVE_RUN_COMPLETE"
        and summary.get("mode") == "live"
        and type(summary.get("epoch_id")) is int
        and summary.get("epoch_id") > 0
        and "epoch_count" not in summary
        and "epochs" not in summary
        and summary.get("selection_source") == "saved_bundle_legacy"
        and summary.get("scheduler_clock") == "host-utc-plus-monotonic"
        and summary.get("cleanup_complete") is True
        and summary.get("shutdown_status") == "PASS"
        and summary.get("write_mode") is expected_writes
    )
    if not direct_summary_ok:
        failures.append("summary.direct_live_run_shape")

    selection_evidence = summary.get("selection_evidence")
    simnow_profile = summary.get("simnow_profile")
    if not (
        summary.get("routes") == expected_routes
        and isinstance(selection_evidence, Mapping)
        and selection_evidence.get("schema") == "backtrader.alpha003_epoch_selection_evidence.v1"
        and type(selection_evidence.get("epoch_id")) is int
        and selection_evidence.get("epoch_id") == summary.get("epoch_id")
        and selection_evidence.get("selection_source") == "saved_bundle_legacy"
        and selection_evidence.get("routes") == expected_routes
        and selection_evidence.get("authorized_targets") == expected_targets
        and isinstance(simnow_profile, Mapping)
        and dict(simnow_profile)
        == {
            "verified": True,
            "environment": "simnow",
            "profile": SDK_SELECTOR_PROFILE,
        }
    ):
        failures.append("summary.selection_profile_and_routes")
    evidence_path_value = (
        selection_evidence.get("selection_path")
        if isinstance(selection_evidence, Mapping)
        else None
    )
    if type(evidence_path_value) is not str:
        failures.append("summary.selection_bundle_path")
    else:
        try:
            evidence_candidate = Path(evidence_path_value)
            evidence_path = evidence_candidate.resolve(strict=False)
            expected_path = expected_selection_path.resolve(strict=False)
            evidence_path_ok = (
                evidence_candidate.is_absolute()
                and not evidence_candidate.is_symlink()
                and evidence_path == expected_path
                and evidence_path.is_file()
            )
        except (OSError, RuntimeError, ValueError):
            evidence_path_ok = False
        if not evidence_path_ok:
            failures.append("summary.selection_bundle_path")

    strategy_order_events = summary.get("strategy_order_events")
    if not (
        isinstance(strategy_order_events, Mapping)
        and strategy_order_events.get("status") == "AVAILABLE"
        and isinstance(strategy_order_events.get("events"), list)
    ):
        failures.append("summary.strategy_order_events")

    if child.get("runner_summary_scheduler_clock_labels") != [
        {"path": "summary", "value": "host-utc-plus-monotonic"}
    ] or child.get("runner_summary_scheduler_clock_label_meaning") != (
        "production summary default identifier; not the injected runtime clock"
    ):
        failures.append("child.summary_scheduler_clock_label")
    if child.get("query_families") != _SYNTHETIC_QUERY_FAMILIES:
        failures.append("child.query_families")
    if child.get("subscriptions") != ["A2611", "M2611", "Y2611"]:
        failures.append("child.subscriptions")
    if child.get("planned_slot_count") != planned_slot_count:
        failures.append("child.planned_slot_count")

    decision_tape = summary.get("decision_tape")
    readback = summary.get("decision_tape_readback")
    if not isinstance(decision_tape, Mapping):
        failures.append("summary.decision_tape_counts")
        failures.append("summary.decision_tape_readback")
    else:
        tape_record_count = decision_tape.get("record_count")
        tape_bytes = decision_tape.get("bytes")
        tape_max_bytes = decision_tape.get("max_bytes")
        tape_file_id = decision_tape.get("file_id")
        tape_last_reference = decision_tape.get("last_record_reference")
        tape_sha256 = decision_tape.get("sha256")
        counts_ok = (
            type(tape_record_count) is int
            and tape_record_count == planned_slot_count
            and decision_tape.get("closed") is True
            and decision_tape.get("failed") is False
            and type(tape_bytes) is int
            and tape_bytes > 0
            and type(tape_max_bytes) is int
            and tape_max_bytes == 5_000_000
            and tape_bytes <= tape_max_bytes
        )
        if not counts_ok:
            failures.append("summary.decision_tape_counts")
        reference_ok = (
            isinstance(tape_last_reference, Mapping)
            and type(tape_last_reference.get("record_index")) is int
            and tape_last_reference.get("record_index") == planned_slot_count
            and type(tape_file_id) is str
            and bool(tape_file_id)
            and tape_last_reference.get("file_id") == tape_file_id
            and type(tape_last_reference.get("record_id")) is str
            and bool(tape_last_reference.get("record_id"))
            and type(tape_last_reference.get("batch_id")) is str
            and bool(tape_last_reference.get("batch_id"))
            and type(tape_sha256) is str
            and len(tape_sha256) == 64
            and all(char in "0123456789abcdef" for char in tape_sha256)
        )
        readback_ok = (
            isinstance(readback, Mapping)
            and type(readback.get("record_count")) is int
            and readback.get("record_count") == tape_record_count
            and type(readback.get("actual_bytes")) is int
            and readback.get("actual_bytes") == tape_bytes
            and readback.get("file_id") == tape_file_id
            and readback.get("last_record_reference") == tape_last_reference
            and reference_ok
        )
        if not readback_ok:
            failures.append("summary.decision_tape_readback")

    shutdown_rows = summary.get("resource_shutdown")
    shutdown_by_resource: dict[str, Mapping[str, Any]] = {}
    if isinstance(shutdown_rows, list) and all(
        isinstance(row, Mapping) and type(row.get("resource")) is str
        for row in shutdown_rows
    ):
        for row in shutdown_rows:
            resource = row["resource"]
            if resource in shutdown_by_resource:
                shutdown_by_resource = {}
                break
            shutdown_by_resource[resource] = row
    shutdown_ok = (
        set(shutdown_by_resource)
        == {"query_refresh", "decision_tape", "broker", "store", "journal"}
        and shutdown_by_resource["query_refresh"].get("status") == "RETURNED"
        and shutdown_by_resource["query_refresh"].get("started") is True
        and shutdown_by_resource["query_refresh"].get("joined") is True
        and shutdown_by_resource["broker"].get("status")
        == ("PASS" if expected_writes else "OBSERVATION_ONLY")
        and shutdown_by_resource["broker"].get("store_shutdown_state") == "PASS"
        and shutdown_by_resource["store"].get("status") == "CLOSED_BY_BROKER"
        and shutdown_by_resource["store"].get("shutdown_state") == "PASS"
        and shutdown_by_resource["journal"].get("status") == "CLOSED"
    )
    tape_shutdown = shutdown_by_resource.get("decision_tape")
    shutdown_ok = (
        shutdown_ok
        and isinstance(tape_shutdown, Mapping)
        and isinstance(decision_tape, Mapping)
    )
    if shutdown_ok:
        shutdown_ok = (
            tape_shutdown.get("status") == "CLOSED"
            and tape_shutdown.get("record_count") == planned_slot_count
            and tape_shutdown.get("bytes") == decision_tape.get("bytes")
            and tape_shutdown.get("sha256") == decision_tape.get("sha256")
        )
    if not shutdown_ok:
        failures.append("summary.resource_shutdown")

    return failures


def _synthetic_authorization_scope_is_valid(case: str, child: Mapping[str, Any]) -> bool:
    arm_calls = child.get("arm_calls")
    disarm_calls = child.get("disarm_calls")
    arm_observations = child.get("arm_scope_observations")
    disarm_observations = child.get("disarm_scope_observations")
    if (
        type(arm_calls) is not int
        or type(disarm_calls) is not int
        or not isinstance(arm_observations, list)
        or not isinstance(disarm_observations, list)
    ):
        return False
    if case != "write":
        return (
            arm_calls == 0
            and disarm_calls == 0
            and arm_observations == []
            and disarm_observations == []
        )
    if (
        arm_calls <= 0
        or arm_calls != disarm_calls
        or arm_calls != len(arm_observations)
        or disarm_calls != len(disarm_observations)
    ):
        return False
    synthetic_actions = child.get("synthetic_leaf_actions")
    if not isinstance(synthetic_actions, list):
        return False
    insert_targets = []
    for action in synthetic_actions:
        if not isinstance(action, Mapping):
            return False
        if action.get("action") != "insert":
            continue
        target = action.get("instrument")
        if (
            action.get("exchange") != "DCE"
            or not isinstance(target, str)
            or target not in {"M2611", "A2611"}
        ):
            return False
        insert_targets.append(target)
    allowed_targets = {"M2611", "A2611"}
    arm_targets = []
    for observation in arm_observations:
        if (
            not isinstance(observation, Mapping)
            or set(observation) != {"requested_instrument_id", "authorized_instruments"}
        ):
            return False
        target = observation.get("requested_instrument_id")
        if (
            not isinstance(target, str)
            or target not in allowed_targets
            or observation.get("authorized_instruments") != [target]
        ):
            return False
        arm_targets.append(target)
    disarm_targets = []
    for observation in disarm_observations:
        if (
            not isinstance(observation, list)
            or len(observation) != 1
            or not isinstance(observation[0], str)
            or observation[0] not in allowed_targets
        ):
            return False
        disarm_targets.append(observation[0])
    return (
        sorted(arm_targets) == sorted(disarm_targets)
        and sorted(arm_targets) == sorted(insert_targets)
    )


def _synthetic_positive_prices_match(left: Any, right: Any) -> bool:
    try:
        left_price = Decimal(str(left))
        right_price = Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return (
        left_price.is_finite()
        and right_price.is_finite()
        and left_price > 0
        and right_price > 0
        and left_price == right_price
    )


def _synthetic_order_sys_id_provenance_is_valid(child: Mapping[str, Any]) -> bool:
    synthetic_actions = child.get("synthetic_leaf_actions")
    order_associations = child.get("ctp_order_callback_associations")
    trade_callbacks = child.get("ctp_trade_callback_associations")
    trade_queries = child.get("ctp_trade_query_associations")
    order_callback_count = child.get("ctp_order_callback_count")
    trade_callback_count = child.get("ctp_trade_callback_count")
    synthetic_fill_count = child.get("synthetic_fill_count")
    max_order_intents = child.get("max_order_intents_per_run")
    if (
        not isinstance(synthetic_actions, list)
        or not all(
            isinstance(rows, list)
            for rows in (order_associations, trade_callbacks, trade_queries)
        )
        or type(order_callback_count) is not int
        or type(trade_callback_count) is not int
        or type(synthetic_fill_count) is not int
        or type(max_order_intents) is not int
        or max_order_intents != SYNTHETIC_WRITE_MAX_ORDER_INTENTS_PER_RUN
        or len(order_associations) != order_callback_count
        or len(trade_callbacks) != trade_callback_count
        or len(trade_queries) != trade_callback_count
        or trade_callback_count != synthetic_fill_count
    ):
        return False
    order_targets = {}
    insert_refs = []
    for action in synthetic_actions:
        if (
            not isinstance(action, Mapping)
            or not isinstance(action.get("action"), str)
            or action.get("action") not in {"insert", "cancel"}
            or not isinstance(action.get("exchange"), str)
            or action.get("exchange") != "DCE"
            or not isinstance(action.get("instrument"), str)
            or action.get("instrument") not in {"M2611", "A2611"}
        ):
            return False
        order_ref = action.get("order_ref")
        if not isinstance(order_ref, str) or not order_ref:
            return False
        instrument = action["instrument"]
        if action["action"] == "insert":
            if order_ref in order_targets or len(insert_refs) >= max_order_intents:
                return False
            order_targets[order_ref] = (action["exchange"], instrument)
            insert_refs.append(order_ref)
        elif order_targets.get(order_ref) != (action["exchange"], instrument):
            return False

    if not insert_refs:
        return (
            not synthetic_actions
            and not order_associations
            and not trade_callbacks
            and not trade_queries
            and order_callback_count == 0
            and trade_callback_count == 0
            and synthetic_fill_count == 0
        )

    if (
        len(order_associations) != 2 * len(insert_refs)
        or trade_callback_count != len(insert_refs)
        or len(trade_queries) != len(insert_refs)
    ):
        return False
    callback_states = {order_ref: 0 for order_ref in insert_refs}
    for association in order_associations:
        if not isinstance(association, Mapping):
            return False
        order_ref = association.get("order_ref")
        if not isinstance(order_ref, str) or order_ref not in callback_states:
            return False
        state = callback_states.get(order_ref)
        expected_sys_id = "iteration51-sys-" + order_ref
        if state == 0:
            expected = ("3", False, False, False)
        elif state == 1:
            expected = ("0", True, True, True)
        else:
            return False
        status, pending_present, pending_ref_matches, full_pending = expected
        if (
            association.get("status") != status
            or association.get("callback_order_sys_id") != expected_sys_id
            or association.get("query_order_sys_id") != expected_sys_id
            or association.get("query_order_sys_id_matches") is not True
            or association.get("callback_owner_is_wrapper") is not True
            or association.get("pending_order_present") is not pending_present
            or association.get("pending_order_ref_matches") is not pending_ref_matches
            or association.get("system_id_order_ref_matches") is not True
            or association.get("system_id_uses_full_pending_order") is not full_pending
        ):
            return False
        callback_states[order_ref] = state + 1
    if any(state != 2 for state in callback_states.values()):
        return False

    callback_rows = {}
    for association in trade_callbacks:
        if not isinstance(association, Mapping):
            return False
        trade_id = association.get("trade_id")
        order_ref = association.get("order_ref")
        order_sys_id = association.get("order_sys_id")
        if (
            not isinstance(order_ref, str)
            or not order_ref
            or trade_id != "iteration51-" + order_ref
            or order_sys_id != "iteration51-sys-" + order_ref
            or not _synthetic_positive_prices_match(
                association.get("callback_price"), association.get("callback_price")
            )
            or order_ref not in order_targets
            or order_ref in callback_rows
        ):
            return False
        callback_rows[order_ref] = (
            trade_id,
            order_sys_id,
            str(association.get("callback_price")),
        )
    query_rows = {}
    for association in trade_queries:
        if not isinstance(association, Mapping):
            return False
        trade_id = association.get("trade_id")
        order_ref = association.get("order_ref")
        order_sys_id = "iteration51-sys-" + order_ref if isinstance(order_ref, str) else None
        callback_price = association.get("callback_price")
        query_price = association.get("query_price")
        if (
            not isinstance(order_ref, str)
            or not order_ref
            or trade_id != "iteration51-" + order_ref
            or association.get("callback_order_sys_id") != order_sys_id
            or association.get("query_order_sys_id") != order_sys_id
            or association.get("query_order_sys_id_matches") is not True
            or association.get("query_price_matches") is not True
            or not _synthetic_positive_prices_match(callback_price, query_price)
            or order_ref not in order_targets
            or order_ref in query_rows
            or order_ref not in callback_rows
            or not _synthetic_positive_prices_match(
                callback_price, callback_rows.get(order_ref, (None, None, None))[2]
            )
        ):
            return False
        query_rows[order_ref] = (trade_id, order_sys_id, str(callback_price))
    expected_trades = {
        order_ref: ("iteration51-" + order_ref, "iteration51-sys-" + order_ref)
        for order_ref in insert_refs
    }
    return (
        {order_ref: row[:2] for order_ref, row in callback_rows.items()}
        == expected_trades
        and set(query_rows) == set(expected_trades)
        and all(
            query_rows[order_ref][:2] == callback_rows[order_ref][:2]
            for order_ref in expected_trades
        )
    )


def _synthetic_live_child_command(
    *,
    child_script_path: Path,
    wheel_path: Path,
    wheel_sha256: str,
    example_dir: Path,
    workspace: Path,
    selector_source_path: Path,
    case: str,
    factor_mode: str,
    planned_slot_count: int = 64,
    python: str = sys.executable,
) -> list[str]:
    if case not in SYNTHETIC_LIVE_CASES:
        raise InstalledFixtureError("synthetic-live case is outside the fixed local set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    if type(planned_slot_count) is not int or not 30 <= planned_slot_count <= 64:
        raise InstalledFixtureError("synthetic planned slot count is outside the fixture bounds")
    child_script = _require_external(child_script_path, label="synthetic-live child script")
    if not child_script.is_file() or child_script.is_symlink():
        raise InstalledFixtureError("synthetic-live child script is unavailable")
    return [
        python,
        "-I",
        str(child_script.resolve(strict=True)),
        str(Path(__file__).with_name("iteration50_installed_fixture.py").resolve(strict=True)),
        str(Path(wheel_path).resolve(strict=True)),
        wheel_sha256,
        str(Path(example_dir).resolve(strict=True)),
        str((Path(example_dir).resolve(strict=True) / "config.yaml").resolve(strict=True)),
        str(Path(workspace).resolve(strict=True)),
        str(Path(selector_source_path).resolve(strict=True)),
        case,
        factor_mode,
        str(planned_slot_count),
    ]


def _preserve_synthetic_child_output(
    workspace: Path,
    stem: str,
    *,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    exit_record: bytes,
    exit_code: Optional[int],
    exit_status: str,
) -> dict[str, Any]:
    if any(type(payload) is not bytes for payload in (stdout_bytes, stderr_bytes, exit_record)):
        raise InstalledFixtureError("synthetic-live child output must remain raw bytes")
    stdout_path = workspace / (stem + ".stdout.bin")
    stderr_path = workspace / (stem + ".stderr.bin")
    exit_path = workspace / (stem + ".exit.txt")
    for path in (stdout_path, stderr_path, exit_path):
        if path.exists() or path.is_symlink():
            raise InstalledFixtureError("synthetic-live child output destination must be new")
    for path, payload in (
        (stdout_path, stdout_bytes),
        (stderr_path, stderr_bytes),
        (exit_path, exit_record),
    ):
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except OSError as exc:
            raise InstalledFixtureError(
                "synthetic-live child output could not be preserved"
            ) from exc
    return {
        "stdout_path": str(stdout_path),
        "stdout_size_bytes": len(stdout_bytes),
        "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
        "stderr_path": str(stderr_path),
        "stderr_size_bytes": len(stderr_bytes),
        "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
        "exit_path": str(exit_path),
        "exit_code": exit_code,
        "exit_status": exit_status,
    }


def run_synthetic_live_case(
    *,
    example_dir: Path,
    workspace: Path,
    wheel_path: Path,
    wheel_sha256: str,
    selector_source_path: Path,
    case: str,
    factor_mode: str = "native",
    planned_slot_count: int = 64,
    timeout_seconds: float = 300.0,
    python: str = sys.executable,
) -> dict[str, Any]:
    """Run one explicit live profile with the installed CTP SDK leaf faked locally."""

    if case not in SYNTHETIC_LIVE_CASES:
        raise InstalledFixtureError("synthetic-live case is outside the fixed local set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    if type(planned_slot_count) is not int or not 30 <= planned_slot_count <= 64:
        raise InstalledFixtureError("synthetic planned slot count is outside the fixture bounds")
    if not (0 < timeout_seconds <= 1800):
        raise InstalledFixtureError(
            "synthetic-live timeout must be finite and at most 1800 seconds"
        )
    example = _require_external(example_dir, label="synthetic-live example")
    if not example.is_dir() or not (example / "run.py").is_file():
        raise InstalledFixtureError("copied public runner is unavailable")
    if not (example / "config.yaml").is_file():
        raise InstalledFixtureError("copied public live config template is unavailable")
    selector_source = _pinned_sdk_selector_source(selector_source_path)
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
    child_script = target_workspace / (
        "iteration51-synthetic-live-child-" + factor_mode + "-" + case + ".py"
    )
    if child_script.exists() or child_script.is_symlink():
        raise InstalledFixtureError("synthetic-live child script destination must be new")
    child_source = _SYNTHETIC_LIVE_CHILD_CODE.encode("utf-8")
    try:
        with child_script.open("xb") as handle:
            handle.write(child_source)
    except OSError as exc:
        raise InstalledFixtureError(
            "synthetic-live child source could not be materialized"
        ) from exc
    child_script = child_script.resolve(strict=True)
    child_script_sha256 = _sha256(child_script)
    if (
        child_script.stat().st_size != len(child_source)
        or child_script_sha256 != hashlib.sha256(child_source).hexdigest()
    ):
        raise InstalledFixtureError("synthetic-live child source changed during materialization")
    command = _synthetic_live_child_command(
        child_script_path=child_script,
        wheel_path=wheel,
        wheel_sha256=wheel_sha256,
        example_dir=example,
        workspace=target_workspace,
        selector_source_path=Path(selector_source["path"]),
        case=case,
        factor_mode=factor_mode,
        planned_slot_count=planned_slot_count,
        python=python,
    )
    child_log_stem = "iteration51-synthetic-live-child-" + factor_mode + "-" + case
    child_output_paths = (
        target_workspace / (child_log_stem + ".stdout.bin"),
        target_workspace / (child_log_stem + ".stderr.bin"),
        target_workspace / (child_log_stem + ".exit.txt"),
    )
    if any(path.exists() or path.is_symlink() for path in child_output_paths):
        raise InstalledFixtureError("synthetic-live child output destination must be new")
    try:
        completed = subprocess.run(
            command,
            cwd=str(example),
            env=_sanitized_environment(),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_stdout = exc.stdout if exc.stdout is not None else b""
        timeout_stderr = exc.stderr if exc.stderr is not None else b""
        timeout_output = _preserve_synthetic_child_output(
            target_workspace,
            child_log_stem,
            stdout_bytes=timeout_stdout,
            stderr_bytes=timeout_stderr,
            exit_record=b"UNKNOWN_TIMEOUT\n",
            exit_code=None,
            exit_status="unknown_timeout",
        )
        raise InstalledFixtureError(
            "synthetic-live child exceeded its bounded timeout; exit status is unknown; "
            "raw output was preserved at " + timeout_output["stdout_path"]
        ) from exc
    child_stdout_bytes = completed.stdout
    child_stderr_bytes = completed.stderr
    if type(child_stdout_bytes) is not bytes or type(child_stderr_bytes) is not bytes:
        raise InstalledFixtureError("synthetic-live child did not return binary output")
    child_output = _preserve_synthetic_child_output(
        target_workspace,
        child_log_stem,
        stdout_bytes=child_stdout_bytes,
        stderr_bytes=child_stderr_bytes,
        exit_record=(str(completed.returncode) + "\n").encode("ascii"),
        exit_code=completed.returncode,
        exit_status="returned",
    )
    if (
        child_script.stat().st_size != len(child_source)
        or _sha256(child_script) != child_script_sha256
    ):
        raise InstalledFixtureError("synthetic-live child source changed during execution")
    try:
        child_stdout = child_stdout_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstalledFixtureError(
            "synthetic-live child output is not valid UTF-8; raw bytes were preserved"
        ) from exc
    summary = _last_json_object(child_stdout)
    summary_line = _last_json_object_line(child_stdout)
    child = _synthetic_live_child_receipt(child_stdout)
    if (
        child.get("raw_cli_summary_sha256")
        != hashlib.sha256(summary_line.encode("utf-8")).hexdigest()
    ):
        raise InstalledFixtureError("production CLI summary bytes changed in the fixture")
    if _pinned_sdk_selector_source(selector_source_path) != selector_source:
        raise InstalledFixtureError("pinned SDK selector source changed during the child run")
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
    diagnostic_receipt = child.get("live_cohort_exception_diagnostics")
    if not isinstance(diagnostic_receipt, dict):
        raise InstalledFixtureError("live cohort exception diagnostic receipt is missing")
    diagnostic_requested_path = Path(diagnostic_receipt.get("path", ""))
    if diagnostic_requested_path.is_symlink():
        raise InstalledFixtureError("live cohort diagnostic path must not be a symlink")
    diagnostic_path = diagnostic_requested_path.resolve(strict=True)
    expected_diagnostic_path = live_config_path.parent / "live-cohort-exception-diagnostics.json"
    if (
        diagnostic_path != expected_diagnostic_path.resolve(strict=True)
        or diagnostic_path.is_symlink()
        or not _is_within(diagnostic_path, target_workspace)
        or diagnostic_path.stat().st_size > 65536
    ):
        raise InstalledFixtureError("live cohort diagnostic escaped its bounded case workspace")
    diagnostic_bytes = diagnostic_path.read_bytes()
    if (
        diagnostic_receipt.get("size_bytes") != len(diagnostic_bytes)
        or diagnostic_receipt.get("sha256") != hashlib.sha256(diagnostic_bytes).hexdigest()
    ):
        raise InstalledFixtureError("live cohort diagnostic bytes do not match their receipt")
    try:
        diagnostic_document = json.loads(diagnostic_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstalledFixtureError("live cohort diagnostic JSON is malformed") from exc
    if (
        not isinstance(diagnostic_document, dict)
        or diagnostic_document.get("schema")
        != "backtrader.iteration51.synthetic_live_cohort_diagnostics.v1"
        or diagnostic_document.get("capture")
        != "installed live_cohort exception events during copied public CLI run"
        or not isinstance(diagnostic_document.get("exceptions"), list)
        or len(diagnostic_document["exceptions"]) > 8
        or diagnostic_document.get("captured_exception_count")
        != len(diagnostic_document["exceptions"])
        or diagnostic_receipt.get("captured_exception_count")
        != diagnostic_document.get("captured_exception_count")
    ):
        raise InstalledFixtureError("live cohort diagnostic schema or count is invalid")
    common_ok = (
        completed.returncode == expected_exit
        and child.get("exit_code") == expected_exit
        and child.get("case") == case
        and child.get("cli_argv") == cli_argv
        and child.get("wheel_sha256") == wheel_sha256
        and child.get("sdk_selector_source")
        == {
            **selector_source,
            "module_origin": selector_source["path"],
            "profile_id": SDK_SELECTOR_PROFILE,
            "official_fronts_lookup": True,
            "td_front_profile_lookup": True,
            "official_profile_verification": True,
        }
        and child.get("sdk_selector_profile_id") == SDK_SELECTOR_PROFILE
        and child.get("sdk_selector_profile_verified") is True
        and child.get("loaded_modules_verified", 0) > 0
        and child.get("fresh_bytecode_cache") is True
        and child.get("ctp_wrapper_factory_unchanged") is True
        and _synthetic_authorization_scope_is_valid(case, child)
        and _synthetic_order_sys_id_provenance_is_valid(child)
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
        and child.get("store_environment_api_kwargs_keys")
        == ["fixture_marker", "live_tick_provenance"]
        and child.get("store_live_tick_provenance")
        == {
            "clock_domain_id": "iteration50-installed-fixture-v1",
            "rules_hash": "a" * 64,
            "session_segment": "regular",
        }
        and diagnostic_document.get("captured_exception_count") == 0
        and child.get("planned_slot_count") == planned_slot_count
        and type(child.get("selection_bundle_sha256")) is str
        and len(child["selection_bundle_sha256"]) == 64
        and child.get("authorized_products") == ["DCE.M", "DCE.A"]
    )
    if expected_code is None:
        common_ok = (
            common_ok
            and child.get("ctp_trader_leaf_wrapper_matches_registered_instance") is True
            and child.get("ctp_md_leaf_wrapper_matches_registered_instance") is True
        )
        summary_failures = _synthetic_live_summary_failure_checks(
            summary,
            child,
            planned_slot_count=planned_slot_count,
            expected_writes=expected_writes,
            expected_selection_path=live_config_path.parent / "selection-bundle.json",
        )
        success_runtime_ok = (
            child.get("ctp_wrapper_mro_verified") is True
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
        summary_ok = not summary_failures and success_runtime_ok
        if case == "read-only":
            common_ok = (
                common_ok
                and child.get("synthetic_leaf_actions") == []
                and child.get("synthetic_fill_count") == 0
                and child.get("ctp_order_callback_count") == 0
                and child.get("ctp_order_callback_associations") == []
                and child.get("ctp_trade_callback_count") == 0
            )
        elif case == "write":
            strategy_events = (
                summary.get("strategy_order_events", {}).get("events", [])
                if isinstance(summary.get("strategy_order_events"), Mapping)
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
        common_ok = (
            common_ok
            and child.get("ctp_trader_leaf_wrapper_matches_registered_instance") is False
            and child.get("ctp_md_leaf_wrapper_matches_registered_instance") is False
        )
        summary_ok = (
            summary.get("status") == expected_status and summary.get("code") == expected_code
        )
        common_ok = common_ok and child.get("ctp_trader_leaf_instances") == 0
        common_ok = common_ok and child.get("ctp_md_leaf_instances") == 0
        common_ok = common_ok and child.get("synthetic_leaf_actions") == []
        common_ok = common_ok and child.get("runner_clock_constructor_calls") == 0
    if not common_ok or not summary_ok:
        failed_checks = []
        if not common_ok:
            failed_checks.append("child.runtime_source_authorization_clock_or_lifecycle")
        if expected_code is None:
            failed_checks.extend(summary_failures)
            if not success_runtime_ok:
                failed_checks.append("child.wrapper_scheduler_and_close_receipts")
        elif not summary_ok:
            failed_checks.append("summary.expected_blocked_status_and_code")
        raise InstalledFixtureError(
            "synthetic-live case acceptance failed: "
            + case
            + "; failed_checks="
            + ",".join(failed_checks),
            safe_check_ids=failed_checks,
        )
    return {
        "case": case,
        "factor_mode": factor_mode,
        "planned_slot_count": planned_slot_count,
        "acceptance_status": (
            "SYNTHETIC_64_SLOT_CASE_ACCEPTED"
            if planned_slot_count == 64
            else "SYNTHETIC_DIAGNOSTIC_ONLY"
        ),
        "formal_64_slot_acceptance": planned_slot_count == 64,
        "exit_code": completed.returncode,
        "status": summary["status"],
        "summary": summary,
        "stdout_sha256": hashlib.sha256(child_stdout_bytes).hexdigest(),
        "stderr_sha256": hashlib.sha256(child_stderr_bytes).hexdigest(),
        "child_process_output": child_output,
        "child_launcher": {
            "path": str(child_script),
            "size_bytes": len(child_source),
            "sha256": child_script_sha256,
        },
        "installed_child": child,
        "live_cohort_exception_diagnostics": {
            "path": str(diagnostic_path),
            "size_bytes": len(diagnostic_bytes),
            "sha256": hashlib.sha256(diagnostic_bytes).hexdigest(),
            "captured_exception_count": diagnostic_document["captured_exception_count"],
        },
        "sdk_selector_source": selector_source,
        "evidence_level": (
            SDK_SELECTOR_EVIDENCE_LEVEL
            if planned_slot_count == 64
            else "SYNTHETIC_DIAGNOSTIC_ONLY"
        ),
    }


def run_synthetic_live_matrix(
    *,
    example_dir: Path,
    workspace: Path,
    wheel_path: Path,
    wheel_sha256: str,
    selector_source_path: Path,
    factor_mode: str = "native",
    timeout_seconds: float = 300.0,
    python: str = sys.executable,
) -> list[dict[str, Any]]:
    """Run all fixed read/write admission profiles in separate isolated children."""

    results = [
        run_synthetic_live_case(
            example_dir=example_dir,
            workspace=workspace,
            wheel_path=wheel_path,
            wheel_sha256=wheel_sha256,
            selector_source_path=selector_source_path,
            case=case,
            factor_mode=factor_mode,
            planned_slot_count=64,
            timeout_seconds=timeout_seconds,
            python=python,
        )
        for case in SYNTHETIC_LIVE_CASES
    ]
    if any(
        not isinstance(result, Mapping)
        or result.get("planned_slot_count") != 64
        or result.get("formal_64_slot_acceptance") is not True
        or result.get("acceptance_status") != "SYNTHETIC_64_SLOT_CASE_ACCEPTED"
        for result in results
    ):
        raise InstalledFixtureError("synthetic-live matrix did not preserve the fixed 64-slot gate")
    return results


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
    parser.add_argument(
        "--sdk-selector-source",
        type=Path,
        help="external source file matching the fixed public bt_api_ctp selector pin",
    )
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
        selector_source = None
        if args.synthetic_live:
            if args.sdk_selector_source is None:
                raise InstalledFixtureError(
                    "synthetic-live requires the externally pinned SDK selector source"
                )
            selector_source = _pinned_sdk_selector_source(args.sdk_selector_source)
        elif args.sdk_selector_source is not None:
            raise InstalledFixtureError(
                "SDK selector source is only used by the synthetic-live matrix"
            )
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
                selector_source_path=Path(selector_source["path"]),
                factor_mode=args.factor_mode,
                timeout_seconds=args.timeout_seconds,
            )
            receipt = {
                "schema": "backtrader.iteration51.installed_synthetic_live_fixture.v1",
                "status": "PASS_INSTALLED_SYNTHETIC_LIVE_FIXTURE",
                "evidence_level": SDK_SELECTOR_EVIDENCE_LEVEL,
                "sdk_selector_source": selector_source,
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
        blocked = {"status": "BLOCKED", "error_type": type(exc).__name__}
        if type(exc) is InstalledFixtureError and exc.safe_check_ids:
            blocked["failed_checks"] = list(exc.safe_check_ids)
        print(json.dumps(blocked, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
