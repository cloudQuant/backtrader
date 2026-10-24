#!/usr/bin/env python
"""Small installed-wheel smoke for the Iteration 50-A Alpha003 handoff.

Run this file from outside the Backtrader checkout with the frozen Backtrader
wheel installed.  It uses only public Backtrader APIs and an in-memory provider
client.  The ordinary Strategy, Cerebro, BtApiFeed, LiveBarCohort,
LiveFactorSet, BtApiStore, and BtApiBroker remain the installed production
classes.  The read-only profile checks runtime composition and native/build
parity for a small deterministic cohort.  This fixture makes no order calls;
the execution profile remains pending its separately integrated coordinator.
"""

from __future__ import annotations

import argparse
import base64
import csv
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default as email_default_policy
import hashlib
import importlib
from importlib.metadata import Distribution, PackagePath, distribution
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import site
import sys
import sysconfig
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
import zipfile

# This check intentionally runs before importing Backtrader.  The installed
# consumer must not inherit a checkout path that can shadow the wheel.
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("installed fixture requires PYTHONPATH to be unset")

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.stores.btapistore import BtApiStore


_UTC = timezone.utc
_TARGETS = ("IF2611", "IC2611", "IM2611")
_SLOT_COUNT = 12
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_CLOCK_DOMAIN = "iteration50-installed-fixture-v1"
_SESSION_SEMANTICS = "regular-minute-v1"
_DISTRIBUTION_NAME = "back-trader-python"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("installed fixture failed: " + message)


def _record_path(value: str) -> PurePosixPath:
    if type(value) is not str or not value or "\\" in value:
        raise ValueError("wheel RECORD path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ":" in value:
        raise ValueError("wheel RECORD path is not canonical")
    return path


def _allowed_install_roots(install_root: Path) -> Tuple[Path, ...]:
    roots = {Path(install_root).resolve(), Path(sys.prefix).resolve()}
    roots.add(Path(sys.base_prefix).resolve())
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        roots.add(Path(user_site).resolve())
    else:
        roots.update(Path(value).resolve() for value in user_site)
    for scheme in sysconfig.get_scheme_names():
        try:
            paths = sysconfig.get_paths(scheme)
        except (KeyError, TypeError, ValueError):
            continue
        for key in ("purelib", "platlib", "scripts", "data"):
            value = paths.get(key)
            if value:
                roots.add(Path(value).resolve())
    return tuple(sorted(roots, key=lambda path: str(path)))


def _verify_record(
    record_text: str,
    installed: Distribution,
    install_root: Path,
    allowed_roots: Iterable[Path],
) -> Tuple[Dict[str, str], str]:
    """Verify the installed distribution's complete RECORD payload list."""

    if type(record_text) is not str or not record_text:
        raise ValueError("installed distribution has no RECORD")
    root = Path(install_root).resolve()
    safe_roots = tuple(Path(value).resolve() for value in allowed_roots)
    rows: Dict[str, Tuple[str, str]] = {}
    record_paths = []
    for row in csv.reader(io.StringIO(record_text, newline="")):
        if len(row) != 3:
            raise ValueError("wheel RECORD row shape is invalid")
        relative = _record_path(row[0])
        name = relative.as_posix()
        if name in rows:
            raise ValueError("wheel RECORD contains a duplicate path")
        rows[name] = (row[1], row[2])
        if name.endswith(".dist-info/RECORD"):
            record_paths.append(name)
    if len(record_paths) != 1:
        raise ValueError("wheel RECORD must contain one self entry")
    if rows[record_paths[0]] != ("", ""):
        raise ValueError("wheel RECORD self entry must be unhashed")

    verified: Dict[str, str] = {}
    resolved_targets = set()
    record_digest = None
    for name, (hash_field, size_field) in rows.items():
        target = Path(installed.locate_file(PackagePath(name))).resolve(strict=True)
        if target in resolved_targets:
            raise ValueError("wheel RECORD paths resolve to a duplicate file")
        resolved_targets.add(target)
        if name == record_paths[0]:
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError("wheel RECORD file escapes its distribution root") from exc
            record_bytes = target.read_bytes()
            try:
                recorded_text = record_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("installed RECORD is not UTF-8") from exc
            if recorded_text.replace("\r\n", "\n") != record_text.replace("\r\n", "\n"):
                raise ValueError("installed RECORD changed while it was being verified")
            record_digest = hashlib.sha256(record_bytes).hexdigest()
            continue
        if not any(_is_within(target, allowed_root) for allowed_root in safe_roots):
            raise ValueError("wheel RECORD payload escapes recognized install roots")
        if (
            not hash_field.startswith("sha256=")
            or not size_field.isascii()
            or not size_field.isdecimal()
        ):
            raise ValueError("wheel RECORD payload needs SHA-256 and size")
        encoded_digest = hash_field[len("sha256=") :]
        try:
            expected_digest = base64.b64decode(
                encoded_digest + "=" * ((4 - len(encoded_digest) % 4) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, TypeError) as exc:
            raise ValueError("wheel RECORD SHA-256 encoding is invalid") from exc
        if len(expected_digest) != hashlib.sha256().digest_size:
            raise ValueError("wheel RECORD SHA-256 length is invalid")
        if not target.is_file():
            raise ValueError("wheel RECORD payload is missing")
        payload = target.read_bytes()
        actual_digest = hashlib.sha256(payload).digest()
        if actual_digest != expected_digest or len(payload) != int(size_field):
            raise ValueError("installed file differs from wheel RECORD")
        verified[name] = actual_digest.hex()
    if record_digest is None:
        raise ValueError("installed RECORD file could not be resolved")
    return verified, record_digest


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _verified_module_origin(
    module: Any, install_root: Path, record_hashes: Mapping[str, str]
) -> Dict[str, str]:
    origin_value = getattr(module, "__file__", None)
    if type(origin_value) is not str or not origin_value:
        raise ValueError("installed module has no file origin")
    origin = Path(origin_value).resolve()
    root = Path(install_root).resolve()
    try:
        relative = origin.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("module did not load from the installed distribution") from exc
    expected_hash = record_hashes.get(relative)
    if expected_hash is None:
        raise ValueError("module origin is absent from the installed RECORD")
    actual_hash = hashlib.sha256(origin.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("module bytes differ from the installed RECORD")
    return {"path": str(origin), "sha256": actual_hash}


def _canonical_distribution_name(value: str) -> str:
    return "-".join(
        part for part in value.lower().replace("_", "-").replace(".", "-").split("-") if part
    )


def _is_backtrader_package_payload(path: str) -> bool:
    return path.startswith(("backtrader/", "backtrader_runtime/"))


def _verify_installed_package_payloads(
    installed: Distribution,
    install_root: Path,
    record_hashes: Mapping[str, str],
    wheel_payload_hashes: Mapping[str, str],
) -> int:
    """Require every Backtrader wheel package file to match its installed bytes."""

    wheel_paths = {name for name in wheel_payload_hashes if _is_backtrader_package_payload(name)}
    installed_paths = {name for name in record_hashes if _is_backtrader_package_payload(name)}
    if "backtrader/__init__.py" not in wheel_paths:
        raise ValueError("pinned wheel has no Backtrader package payload")
    if wheel_paths != installed_paths:
        raise ValueError("installed Backtrader package payload set differs from the pinned wheel")
    root = Path(install_root).resolve()
    for name in sorted(wheel_paths):
        target = Path(installed.locate_file(PackagePath(name))).resolve(strict=True)
        if not _is_within(target, root):
            raise ValueError("installed Backtrader package payload escapes its distribution root")
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != wheel_payload_hashes[name]:
            raise ValueError("installed Backtrader package payload differs from the pinned wheel")
        if record_hashes.get(name) != actual_hash:
            raise ValueError("installed Backtrader package payload differs from installed RECORD")
    return len(wheel_paths)


def _snapshot_loaded_package_modules(
    install_root: Path,
    record_hashes: Mapping[str, str],
    wheel_payload_hashes: Mapping[str, str],
    previous: Optional[Mapping[str, Tuple[Any, str, str]]] = None,
    modules: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Tuple[Any, str, str]]:
    """Check every loaded package module's identity, origin and bytes."""

    root = Path(install_root).resolve()
    loaded = sys.modules if modules is None else modules
    snapshot: Dict[str, Tuple[Any, str, str]] = {}
    for module_name, module in tuple(loaded.items()):
        if module_name not in ("backtrader", "backtrader_runtime") and not module_name.startswith(
            ("backtrader.", "backtrader_runtime.")
        ):
            continue
        if module is None:
            continue
        origin = _verified_module_origin(module, root, record_hashes)
        path = Path(origin["path"]).resolve()
        relative = path.relative_to(root).as_posix()
        if wheel_payload_hashes.get(relative) != origin["sha256"]:
            raise ValueError("loaded Backtrader module differs from the pinned wheel payload")
        old = None if previous is None else previous.get(module_name)
        current = (module, str(path), origin["sha256"])
        if old is not None and old != current:
            raise ValueError(
                "loaded Backtrader module identity or source changed during the fixture"
            )
        snapshot[module_name] = current
    if previous is not None and not set(previous).issubset(snapshot):
        raise ValueError("a loaded Backtrader module disappeared during the fixture")
    return snapshot


def _verify_wheel_archive(wheel_path: Path, expected_sha256: str) -> Dict[str, Any]:
    """Verify the exact wheel artifact and every payload named by its RECORD."""

    if type(expected_sha256) is not str or len(expected_sha256) != 64:
        raise ValueError("expected wheel SHA-256 must contain 64 lowercase hex characters")
    if any(character not in "0123456789abcdef" for character in expected_sha256):
        raise ValueError("expected wheel SHA-256 must contain 64 lowercase hex characters")
    wheel = Path(wheel_path).resolve(strict=True)
    if not wheel.is_file() or wheel.suffix.lower() != ".whl":
        raise ValueError("wheel input must be an existing .whl file")
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if wheel_digest != expected_sha256:
        raise ValueError("wheel bytes differ from the supplied SHA-256")

    with zipfile.ZipFile(wheel) as archive:
        members: Dict[str, bytes] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            relative = _record_path(name)
            if ".." in relative.parts or name in members:
                raise ValueError("wheel archive contains a duplicate or escaping member")
            members[name] = archive.read(info)
        record_names = [name for name in members if name.endswith(".dist-info/RECORD")]
        metadata_names = [name for name in members if name.endswith(".dist-info/METADATA")]
        wheel_metadata_names = [name for name in members if name.endswith(".dist-info/WHEEL")]
        if len(record_names) != 1 or len(metadata_names) != 1 or len(wheel_metadata_names) != 1:
            raise ValueError("wheel archive must contain one RECORD, METADATA and WHEEL")
        record_name = record_names[0]
        record_bytes = members[record_name]
        try:
            record_text = record_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("wheel archive RECORD is not UTF-8") from exc
        archive_rows: Dict[str, Tuple[str, str]] = {}
        for row in csv.reader(io.StringIO(record_text, newline="")):
            if len(row) != 3:
                raise ValueError("wheel archive RECORD row shape is invalid")
            relative = _record_path(row[0])
            if ".." in relative.parts or relative.as_posix() != row[0]:
                raise ValueError("wheel archive RECORD path is not canonical")
            if row[0] in archive_rows:
                raise ValueError("wheel archive RECORD contains a duplicate path")
            archive_rows[row[0]] = (row[1], row[2])
        if archive_rows.get(record_name) != ("", ""):
            raise ValueError("wheel archive RECORD self entry must be unhashed")
        unrecorded_signatures = {
            name
            for name in members
            if name.endswith((".dist-info/RECORD.jws", ".dist-info/RECORD.p7s"))
        }
        if set(archive_rows) | unrecorded_signatures != set(members):
            raise ValueError("wheel archive members and RECORD entries differ")
        wheel_payload_hashes: Dict[str, str] = {}
        for name, (hash_field, size_field) in archive_rows.items():
            if name == record_name:
                continue
            if (
                not hash_field.startswith("sha256=")
                or not size_field.isascii()
                or not size_field.isdecimal()
            ):
                raise ValueError("wheel archive RECORD payload needs SHA-256 and size")
            encoded = hash_field[len("sha256=") :]
            if not encoded or any(
                not (character.isascii() and (character.isalnum() or character in "-_"))
                for character in encoded
            ):
                raise ValueError("wheel archive RECORD SHA-256 encoding is invalid")
            try:
                expected_digest = base64.b64decode(
                    encoded + "=" * ((4 - len(encoded) % 4) % 4),
                    altchars=b"-_",
                    validate=True,
                )
            except (ValueError, TypeError) as exc:
                raise ValueError("wheel archive RECORD SHA-256 encoding is invalid") from exc
            payload = members[name]
            actual_digest = hashlib.sha256(payload).digest()
            if (
                len(expected_digest) != hashlib.sha256().digest_size
                or actual_digest != expected_digest
                or len(payload) != int(size_field)
            ):
                raise ValueError("wheel archive payload differs from RECORD")
            wheel_payload_hashes[name] = actual_digest.hex()
        metadata = BytesParser(policy=email_default_policy).parsebytes(members[metadata_names[0]])
        distribution_name = metadata.get("Name")
        version = metadata.get("Version")
        if (
            _canonical_distribution_name(distribution_name or "") != _DISTRIBUTION_NAME
            or not version
        ):
            raise ValueError("wheel archive metadata does not identify Backtrader")
        return {
            "path": str(wheel),
            "filename": wheel.name,
            "sha256": wheel_digest,
            "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "record_entries_verified": len(wheel_payload_hashes),
            "name": distribution_name,
            "version": version,
            "payload_hashes": wheel_payload_hashes,
        }


def _verify_installed_distribution(
    wheel_path: Path, expected_wheel_sha256: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Bind production imports to the exact installed and archived wheel files."""

    if os.environ.get("PYTHONPATH"):
        raise ValueError("installed fixture requires PYTHONPATH to be unset")
    wheel_identity = _verify_wheel_archive(wheel_path, expected_wheel_sha256)
    installed = distribution(_DISTRIBUTION_NAME)
    if _canonical_distribution_name(installed.metadata.get("Name", "")) != _DISTRIBUTION_NAME:
        raise ValueError("installed Backtrader distribution name is unexpected")
    if installed.version != bt.__version__:
        raise ValueError("installed distribution and Backtrader versions differ")
    install_root = Path(installed.locate_file("")).resolve()
    record_text = installed.read_text("RECORD")
    if record_text is None:
        raise ValueError("installed Backtrader distribution has no RECORD")
    record_hashes, record_digest = _verify_record(
        record_text,
        installed,
        install_root,
        _allowed_install_roots(install_root),
    )
    if installed.version != wheel_identity["version"]:
        raise ValueError("installed distribution version differs from the pinned wheel")
    installed_package_payloads = _verify_installed_package_payloads(
        installed,
        install_root,
        record_hashes,
        wheel_identity["payload_hashes"],
    )

    alpha003 = get_alpha(3)
    if not isinstance(alpha003, type) or not alpha003.__module__.endswith(".alpha003"):
        raise ValueError("production Alpha003 registry identity changed")
    classes = (
        bt.Cerebro,
        bt.Strategy,
        BtApiBroker,
        BtApiFeed,
        BtApiStore,
        FactorSpec,
        LiveFactorPlan,
        LiveFactorSet,
        LiveBarCohort,
        alpha003,
    )
    module_names = {"backtrader", "backtrader._cerebro.runnext"}
    for cls in classes:
        module_name = getattr(cls, "__module__", None)
        class_name = getattr(cls, "__name__", None)
        if type(module_name) is not str or not module_name or type(class_name) is not str:
            raise ValueError("required production class has no source identity")
        module = importlib.import_module(module_name)
        if getattr(module, class_name, None) is not cls:
            raise ValueError("production class identity differs from its module")
        module_names.add(module_name)

    module_origins = {}
    for module_name in sorted(module_names):
        module = importlib.import_module(module_name)
        origin = _verified_module_origin(module, install_root, record_hashes)
        relative = Path(origin["path"]).resolve().relative_to(install_root).as_posix()
        wheel_hash = wheel_identity["payload_hashes"].get(relative)
        if wheel_hash is None or wheel_hash != origin["sha256"]:
            raise ValueError("loaded production module differs from the pinned wheel payload")
        module_origins[module_name] = origin
    loaded_modules = _snapshot_loaded_package_modules(
        install_root,
        record_hashes,
        wheel_identity["payload_hashes"],
    )
    report = {
        "distribution": _DISTRIBUTION_NAME,
        "version": installed.version,
        "record_sha256": record_digest,
        "record_entries_verified": len(record_hashes),
        "installed_package_payloads_verified": installed_package_payloads,
        "loaded_package_modules_verified": len(loaded_modules),
        "module_origins": module_origins,
        "wheel": {key: value for key, value in wheel_identity.items() if key != "payload_hashes"},
    }
    binding = {
        "install_root": install_root,
        "record_hashes": record_hashes,
        "wheel_payload_hashes": wheel_identity["payload_hashes"],
        "loaded_modules": loaded_modules,
    }
    return report, binding


class _ReplayClock:
    """Deterministic wall and monotonic clocks for the finite synthetic grid."""

    def __init__(self, first_close: datetime) -> None:
        self._now = first_close
        self._monotonic_ns = 1_000_000_000

    def utc_now(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        return self._monotonic_ns

    def wait(self, timeout_seconds: float) -> None:
        seconds = max(0.0, float(timeout_seconds))
        self._now += timedelta(seconds=seconds)
        self._monotonic_ns += max(1, int(seconds * 1_000_000_000))


class _ProviderLeaf:
    """In-memory bt_api_py-shaped leaf; it never opens a network connection."""

    def __init__(self, bars: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        self._bars = {name: deque(dict(row) for row in rows) for name, rows in bars.items()}
        self.connected = False
        self.calls: Counter[str] = Counter()
        self.subscriptions = []

    def connect(self) -> None:
        self.calls["connect"] += 1
        self.connected = True

    def disconnect(self) -> None:
        self.calls["disconnect"] += 1
        self.connected = False

    def get_balance(self) -> Dict[str, float]:
        self.calls["get_balance"] += 1
        return {"cash": 100_000.0, "value": 100_000.0}

    def get_positions(self) -> list:
        self.calls["get_positions"] += 1
        return []

    def fetch_open_orders(self) -> list:
        self.calls["fetch_open_orders"] += 1
        return []

    def subscribe(self, symbol: str) -> None:
        self.calls["subscribe"] += 1
        self.subscriptions.append(symbol)

    def poll_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.calls["poll_bar"] += 1
        queue = self._bars.get(symbol)
        if not queue:
            return None
        return dict(queue.popleft())

    def is_source_exhausted(self, symbol: str) -> bool:
        queue = self._bars.get(symbol)
        return not queue

    def poll_broker_update(self) -> None:
        self.calls["poll_broker_update"] += 1

    def submit_order(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls["submit_order"] += 1
        raise RuntimeError("the installed smoke must not submit orders")

    def cancel_order(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls["cancel_order"] += 1
        raise RuntimeError("the installed smoke must not cancel orders")


def _fixture_bars() -> Tuple[Dict[str, Tuple[Mapping[str, Any], ...]], LiveCohortCalendar]:
    first_close = datetime(2025, 1, 2, 9, 31, tzinfo=_UTC)
    member_ids = {target: "member-" + target for target in _TARGETS}
    slots = []
    bars: Dict[str, list] = {target: [] for target in _TARGETS}

    for index in range(_SLOT_COUNT):
        close_time = first_close + timedelta(minutes=index)
        trading_day = close_time.strftime("%Y%m%d")
        member_sessions = {
            member_ids[target]: LiveCalendarMemberSession(
                trading_day=trading_day,
                session_segment="regular",
            )
            for target in _TARGETS
        }
        slots.append(
            LiveCalendarSlot(
                slot_id="iteration50-slot-%02d" % index,
                bucket_start=close_time - timedelta(minutes=1),
                close_time=close_time,
                trading_day=trading_day,
                session_segment="regular",
                member_sessions=MappingProxyType(member_sessions),
            )
        )

        for asset_index, target in enumerate(_TARGETS):
            open_rank = (asset_index + index) % len(_TARGETS)
            volume_rank = (asset_index + 2 * index) % len(_TARGETS)
            open_price = float(100 + open_rank * 10)
            close_price = open_price + 1.0
            bars[target].append(
                MappingProxyType(
                    {
                        "instrument": target,
                        "symbol": target,
                        "timestamp": close_time.timestamp(),
                        "datetime": close_time,
                        "bucket_start": close_time - timedelta(minutes=1),
                        "bucket_end": close_time,
                        "available_at": close_time,
                        "trading_day": trading_day,
                        "session_segment": "regular",
                        "timezone_id": "UTC",
                        "clock_domain_id": _CLOCK_DOMAIN,
                        "connection_generation": "fixture-generation-1",
                        "bar_sequence": index + 1,
                        "bar_id": "%s-%02d" % (target, index + 1),
                        "open": open_price,
                        "high": close_price + 0.5,
                        "low": open_price - 0.5,
                        "close": close_price,
                        "volume": float(1_000 + volume_rank * 100),
                        "openinterest": 0.0,
                        "present": True,
                        "complete": True,
                        "quality": "GOOD",
                        "quality_flags": (),
                        "source": "iteration50-installed-smoke",
                    }
                )
            )

    calendar = LiveCohortCalendar(
        calendar_id="iteration50-installed-alpha003-v1",
        version="1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id=_CLOCK_DOMAIN,
        session_semantics=_SESSION_SEMANTICS,
        slots=tuple(slots),
    )
    return {target: tuple(rows) for target, rows in bars.items()}, calendar


class _CaptureStrategy(bt.Strategy):
    params = (("cohort", None), ("plan", None))

    def __init__(self) -> None:
        feeds = {data._name: data for data in self.datas}
        self.factor_set = LiveFactorSet.bind(self.p.plan, feeds, cohort=self.p.cohort)
        self.snapshots = []
        self.order_callbacks = 0
        self.next_callbacks = 0

    def notify_order(self, _order: Any) -> None:
        self.order_callbacks += 1

    def nextstart(self) -> None:
        self._capture_complete_batch()

    def next(self) -> None:
        self._capture_complete_batch()

    def _capture_complete_batch(self) -> None:
        batch = self.p.cohort.current_batch()
        _require(batch is not None and batch.status == "COMPLETE", "strategy saw a partial batch")
        _require(
            len({len(data) for data in self.datas}) == 1,
            "ordinary Strategy feeds did not advance on one shared close",
        )
        _require(
            all(
                data.datetime.datetime(0) == batch.close_time.replace(tzinfo=None)
                for data in self.datas
            ),
            "feed line close differs from the cohort close",
        )
        snapshot = self.factor_set.snapshot()
        _require(snapshot.batch_complete, "factor snapshot is not bound to a complete batch")
        _require(snapshot.close_time == batch.close_time, "factor snapshot close changed")
        self.snapshots.append(snapshot)
        self.next_callbacks += 1


def _run_read_only_mode(mode: str) -> Dict[str, Any]:
    bars, calendar = _fixture_bars()
    clock = _ReplayClock(calendar.slots[0].close_time)
    provider = _ProviderLeaf(bars)
    store = BtApiStore(provider="btapi", api=provider, preserve_raw_bars=True)
    broker = store.getbroker(
        market_data_only=True,
        force_refresh_queries=False,
        flatten_on_stop=False,
    )
    _require(isinstance(broker, BtApiBroker), "Store did not create the production BtApiBroker")

    cohort = LiveBarCohort(
        "iteration50-installed-alpha003",
        calendar,
        max_pending_slots=2,
        max_window_bars=_SLOT_COUNT,
        wait_timeout_ns=2_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    cerebro.setbroker(broker)

    feeds = {}
    for target in _TARGETS:
        feed = store.getdata(
            dataname=target,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            qcheck=0.0,
            clock=clock,
        )
        _require(type(feed) is BtApiFeed, "Store did not create the production BtApiFeed")
        feeds[target] = feed
        cerebro.adddata(feed, name=target)
        cohort.register_member(
            "member-" + target,
            feed,
            instrument=target,
            source_ref="store-feed-" + target,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )

    plan = LiveFactorPlan(
        plan_id="iteration50-installed-alpha003-" + mode,
        targets=_TARGETS,
        groups=dict.fromkeys(_TARGETS, "portfolio"),
        factors={
            "alpha003": FactorSpec(
                name="alpha003",
                indicator=get_alpha(3),
                panel_line="factor",
                mode=mode,
                field_bindings={
                    "open": "feed:target:open",
                    "volume": "feed:target:volume",
                },
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=10,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=_SLOT_COUNT,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=0.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(_CaptureStrategy, cohort=cohort, plan=plan)

    strategies = cerebro.run()
    _require(len(strategies) == 1, "Cerebro did not run exactly one ordinary Strategy")
    strategy = strategies[0]
    _require(strategy.next_callbacks > 0, "ordinary Strategy received no complete live batch")
    _require(strategy.snapshots, "ordinary Strategy captured no factor snapshots")
    _require(strategy.order_callbacks == 0, "NOOP strategy unexpectedly received an order callback")
    _require(
        not provider.connected,
        "production broker/store lifecycle did not disconnect fake leaf",
    )
    _require(not store.is_connected, "production Store remained connected after Cerebro stopped")
    _require(set(provider.subscriptions) == set(_TARGETS), "Store subscriptions changed")
    _require(provider.calls["submit_order"] == 0, "the provider leaf observed an order submission")
    _require(provider.calls["cancel_order"] == 0, "the provider leaf observed a cancellation")
    _require(
        sum(len(queue) for queue in provider._bars.values()) == 0,
        "the finite provider fixture left unconsumed bars",
    )

    snapshot = strategy.snapshots[-1]
    _require(snapshot.batch_complete, "final Alpha003 snapshot has no complete batch")
    _require(
        str(getattr(snapshot.readiness, "value", snapshot.readiness)) == "LIVE_READY",
        "final Alpha003 factor graph did not reach LIVE_READY",
    )
    factor = snapshot.factors.get("alpha003")
    _require(factor is not None and factor.mode == mode, "installed Alpha003 mode changed")
    _require(
        set(factor.values) == set(_TARGETS),
        "Alpha003 output target set does not match the selected cohort",
    )
    values = {}
    for target in _TARGETS:
        point = factor.values[target]
        _require(
            point.present and point.complete and point.quality == "GOOD",
            "input receipt degraded",
        )
        _require(
            str(getattr(point.status, "value", point.status)) == "OUTPUT_AVAILABLE",
            "Alpha003 output is unavailable after warmup",
        )
        value = float(point.value)
        _require(math.isfinite(value), "Alpha003 output is not finite")
        values[target] = value
    _require(
        any(abs(value) > 1e-12 for value in values.values()),
        "fixture produced only zero outputs",
    )

    return {
        "mode": mode,
        "readiness": str(getattr(snapshot.readiness, "value", snapshot.readiness)),
        "batch_complete": snapshot.batch_complete,
        "close_time": snapshot.close_time.isoformat(),
        "target_count": len(values),
        "values": values,
        "strategy_callbacks": strategy.next_callbacks,
        "order_callbacks": strategy.order_callbacks,
        "provider_calls": dict(sorted(provider.calls.items())),
        "provider_subscriptions": sorted(provider.subscriptions),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel", required=True, type=Path, help="the exact installed Backtrader wheel"
    )
    parser.add_argument(
        "--wheel-sha256",
        required=True,
        help="the frozen lowercase SHA-256 of --wheel",
    )
    parser.add_argument(
        "--profile",
        choices=("read-only",),
        default="read-only",
        help="select the installed acceptance profile",
    )
    parser.add_argument(
        "--factor-mode",
        choices=("native", "build", "both"),
        default="both",
        help="run one production Alpha003 binding or compare both modes",
    )
    args = parser.parse_args(argv)

    installed_identity, binding = _verify_installed_distribution(args.wheel, args.wheel_sha256)
    requested = ("native", "build") if args.factor_mode == "both" else (args.factor_mode,)
    results = []
    for mode in requested:
        results.append(_run_read_only_mode(mode))
        binding["loaded_modules"] = _snapshot_loaded_package_modules(
            binding["install_root"],
            binding["record_hashes"],
            binding["wheel_payload_hashes"],
            previous=binding["loaded_modules"],
        )
    installed_identity["loaded_package_modules_verified"] = len(binding["loaded_modules"])
    if len(results) == 2:
        native, build = results
        for target in _TARGETS:
            _require(
                math.isclose(
                    native["values"][target], build["values"][target], rel_tol=1e-9, abs_tol=1e-12
                ),
                "native/build Alpha003 outputs differ for " + target,
            )
    print(
        json.dumps(
            {
                "status": "PASS_INSTALLED_WHEEL_PUBLIC_FIXTURE",
                "evidence_level": "INSTALLED_WHEEL_PUBLIC_FIXTURE_ONLY",
                "profile": args.profile,
                "installed_identity": installed_identity,
                "modes": results,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
