#!/usr/bin/env python
"""Installed-wheel fixtures for the Iteration 50 live-factor handoff.

Run this file from outside the Backtrader checkout with the frozen Backtrader
wheel installed.  The launcher restarts the profile under Python ``-I`` from
a fresh external working directory and removes import-affecting ambient
environment variables before importing Backtrader.  It uses only public APIs
and an in-memory provider client.  The ordinary Strategy, Cerebro, BtApiFeed,
LiveBarCohort, LiveFactorSet, BtApiStore, and BtApiBroker remain installed
production classes.  ``read-only`` checks Alpha003; ``alpha101-stream`` pairs
all registered factors' native/build outputs on one finite live stream;
``execution`` drives a finite synthetic registered-simulation route through
the ordinary Broker and durable decision journal. Provider and query calls are
synthetic leaves; this profile is not account or exchange acceptance.
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
from importlib.util import source_from_cache
from importlib.metadata import Distribution, PackagePath, distribution
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import site
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from types import SimpleNamespace
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
import zipfile

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_AMBIENT_IMPORT_ENVIRONMENT = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONUSERBASE",
    "PYTHONPYCACHEPREFIX",
    "PYTHONDONTWRITEBYTECODE",
    "BT_API_TEST_SOURCE_ROOTS",
    "BACKTRADER_USE_INSTALLED",
)
_PARENT_CLEARED_ENVIRONMENT_MARKER = "ITERATION50_PARENT_CLEARED_ENVIRONMENT"


def _ambient_import_environment_names(environment: Mapping[str, str]) -> Tuple[str, ...]:
    explicit = set(_AMBIENT_IMPORT_ENVIRONMENT)
    return tuple(
        sorted(explicit.union(name for name in environment if name.upper().startswith("PYTHON")))
    )


def _sanitized_environment() -> Dict[str, str]:
    environment = os.environ.copy()
    names = _ambient_import_environment_names(environment)
    cleared = [name for name in names if name in environment]
    for name in names:
        environment.pop(name, None)
    environment[_PARENT_CLEARED_ENVIRONMENT_MARKER] = json.dumps(cleared, separators=(",", ":"))
    return environment


def _isolated_arguments(arguments: Sequence[str]) -> list:
    """Resolve only path-bearing CLI input before changing to the external cwd."""

    resolved = list(arguments)
    for index, argument in enumerate(resolved):
        if argument == "--wheel" and index + 1 < len(resolved):
            resolved[index + 1] = str((Path.cwd() / resolved[index + 1]).resolve())
        elif argument.startswith("--wheel="):
            value = argument.split("=", 1)[1]
            resolved[index] = "--wheel=" + str((Path.cwd() / value).resolve())
    return resolved


def _run_isolated_entry(arguments: Sequence[str]) -> int:
    """Restart this public fixture under ``-I`` from a fresh external cwd."""

    with tempfile.TemporaryDirectory(prefix="iteration50-installed-external-") as directory:
        external_cwd = Path(directory).resolve()
        try:
            external_cwd.relative_to(_REPOSITORY_ROOT)
        except ValueError:
            pass
        else:
            raise RuntimeError("installed fixture temporary directory is inside the checkout")
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            *_isolated_arguments(arguments),
        ]
        environment = _sanitized_environment()
        for name in ("TMP", "TEMP", "TMPDIR"):
            environment[name] = str(external_cwd)
        completed = subprocess.run(
            command,
            cwd=str(external_cwd),
            env=environment,
            check=False,
        )
        return int(completed.returncode)


def _is_direct_script_invocation() -> bool:
    """Distinguish a real interpreter script launch from the source QA runpy tests."""

    script_path = Path(__file__).resolve()
    original_arguments = getattr(sys, "orig_argv", ())
    for argument in original_arguments[1:]:
        if argument == "-c" or argument == "-m":
            return False
        if argument.startswith("-"):
            continue
        try:
            if Path(argument).resolve() == script_path:
                return True
        except (OSError, ValueError):
            continue
    return False


def _cwd_is_inside_checkout() -> bool:
    try:
        Path.cwd().resolve().relative_to(_REPOSITORY_ROOT)
    except ValueError:
        return False
    return True


def _clear_isolated_environment() -> Dict[str, Any]:
    """Remove import-affecting environment before the first installed import."""

    encoded_parent_keys = os.environ.pop(_PARENT_CLEARED_ENVIRONMENT_MARKER, "[]")
    try:
        parent_cleared = json.loads(encoded_parent_keys)
    except json.JSONDecodeError as exc:
        raise RuntimeError("isolated launcher environment receipt is malformed") from exc
    explicit_names = set(_AMBIENT_IMPORT_ENVIRONMENT)
    if not isinstance(parent_cleared, list) or any(
        not isinstance(name, str)
        or (name not in explicit_names and not name.upper().startswith("PYTHON"))
        for name in parent_cleared
    ):
        raise RuntimeError("isolated launcher environment receipt is invalid")

    names = _ambient_import_environment_names(os.environ)
    present = [name for name in names if name in os.environ]
    for name in names:
        os.environ.pop(name, None)
    if any(name.upper().startswith("PYTHON") for name in os.environ):
        raise RuntimeError("installed fixture requires Python environment overrides to be unset")
    try:
        Path.cwd().resolve().relative_to(_REPOSITORY_ROOT)
    except ValueError:
        external_cwd = True
    else:
        external_cwd = False
    return {
        "python_isolated": bool(sys.flags.isolated),
        "external_working_directory": external_cwd,
        "parent_cleared_environment_names": tuple(parent_cleared),
        "child_cleared_environment_names": tuple(present),
        "ambient_import_environment_unset": all(
            name not in os.environ for name in _AMBIENT_IMPORT_ENVIRONMENT
        ),
    }


_ISOLATED_BYTECODE_CACHE = None
_ISOLATED_BYTECODE_CACHE_PREFIX = None


def _configure_isolated_bytecode_cache() -> None:
    """Keep pre-existing timestamp-valid caches out of this fixture process."""

    global _ISOLATED_BYTECODE_CACHE, _ISOLATED_BYTECODE_CACHE_PREFIX

    if any(name == "backtrader" or name.startswith("backtrader.") for name in sys.modules):
        raise RuntimeError(
            "installed fixture requires Backtrader to be unloaded before cache setup"
        )
    cache = tempfile.TemporaryDirectory(prefix="iteration50-installed-pycache-")
    cache_prefix = Path(cache.name).resolve()
    if any(cache_prefix.iterdir()):
        cache.cleanup()
        raise RuntimeError("installed fixture requires a fresh bytecode cache directory")
    sys.pycache_prefix = str(cache_prefix)
    _ISOLATED_BYTECODE_CACHE = cache
    _ISOLATED_BYTECODE_CACHE_PREFIX = str(cache_prefix)


# A fresh process is the supported installed-fixture entry point. Configure
# its cache before any Backtrader import so an existing site-packages __pycache__
# cannot supply timestamp-valid bytecode.
_EXECUTION_ENVIRONMENT = None
if __name__ == "__main__" and _is_direct_script_invocation():
    if not sys.flags.isolated or _cwd_is_inside_checkout():
        raise SystemExit(_run_isolated_entry(sys.argv[1:]))
    _EXECUTION_ENVIRONMENT = _clear_isolated_environment()
    _configure_isolated_bytecode_cache()
elif __name__ == "__main__":
    _configure_isolated_bytecode_cache()

import backtrader as bt  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.research import (  # noqa: E402
    FactorSpec,
    FieldPITPolicy,
    LiveFactorPlan,
    LiveFactorSet,
)
from backtrader.research.alpha101 import get_alpha  # noqa: E402
from backtrader.research.live_cohort import (  # noqa: E402
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveFieldContract,
    LiveFieldObservation,
)
from backtrader.stores.btapistore import BtApiStore  # noqa: E402


_UTC = timezone.utc
_TARGETS = ("IF2611", "IC2611", "IM2611")
_SLOT_COUNT = 12
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_EXTRA_FIELDS = ("vwap", "cap", "sector", "industry", "subindustry", "dollar_volume")
_FIELD_PIT_UNITS = {
    "open": "USD/share",
    "high": "USD/share",
    "low": "USD/share",
    "close": "USD/share",
    "volume": "share",
    "vwap": "USD/share",
    "cap": "USD",
    "sector": "fixture-code:sector-v1",
    "industry": "fixture-code:industry-v1",
    "subindustry": "fixture-code:subindustry-v1",
    "dollar_volume": "USD",
}
_FIELD_PIT_MAX_AGE_SECONDS = 60.0
_ALPHA101_SLOT_COUNT = 320
_CLOCK_DOMAIN = "iteration50-installed-fixture-v1"
_SESSION_SEMANTICS = "regular-minute-v1"
_DISTRIBUTION_NAME = "back-trader-python"
_ALPHA101_REL_TOL = 1e-10
_ALPHA101_ABS_TOL = 1e-12
_ALPHA101_EXTRA_WITNESS_FACTORS = {
    "vwap": 5,
    "cap": 56,
    "sector": 58,
    "industry": 59,
    "subindustry": 48,
    "dollar_volume": 7,
}
_ALPHA101_REQUIRED_OUTPUT_WITNESS_IDS = (3, 5, 7, 48, 56, 58, 59)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("installed fixture failed: " + message)


def _validate_order_execution_fill(
    order,
    *,
    label: str,
    expected_size: float,
    expected_price: float,
    expected_commission: float,
    expected_pnl: float,
    expected_opened: float,
    expected_closed: float,
    expected_opened_commission: float,
    expected_closed_commission: float,
) -> Dict[str, Any]:
    """Gate Broker aggregate execution against all of its actual execution bits."""
    executed = order.executed
    bits = tuple(executed.exbits)
    _require(bits, label + " has no Broker execution bits")

    fields = (
        "size",
        "price",
        "comm",
        "opened",
        "closed",
        "openedcomm",
        "closedcomm",
        "pnl",
    )
    bit_rows = []
    for bit in bits:
        row = {name: float(getattr(bit, name)) for name in fields}
        _require(
            all(math.isfinite(value) for value in row.values()),
            label + " has a non-finite Broker execution bit",
        )
        bit_rows.append(row)

    signed_size = sum(row["size"] for row in bit_rows)
    filled_quantity = sum(abs(row["size"]) for row in bit_rows)
    _require(filled_quantity > 0.0, label + " has zero aggregate execution quantity")
    weighted_price = sum(abs(row["size"]) * row["price"] for row in bit_rows) / filled_quantity
    commission = sum(row["comm"] for row in bit_rows)
    opened = sum(row["opened"] for row in bit_rows)
    closed = sum(row["closed"] for row in bit_rows)
    opened_commission = sum(row["openedcomm"] for row in bit_rows)
    closed_commission = sum(row["closedcomm"] for row in bit_rows)
    pnl = sum(row["pnl"] for row in bit_rows)
    projection = {
        "size": signed_size,
        "price": weighted_price,
        "commission": commission,
        "opened": opened,
        "closed": closed,
        "opened_commission": opened_commission,
        "closed_commission": closed_commission,
        "pnl": pnl,
        "bits": bit_rows,
    }
    actual_totals = {
        "size": float(executed.size),
        "price": float(executed.price),
        "commission": float(executed.comm),
    }
    for name in ("size", "price", "commission"):
        _require(
            math.isfinite(actual_totals[name])
            and math.isclose(actual_totals[name], projection[name], rel_tol=0.0, abs_tol=1e-12),
            "%s aggregate %s differs from its execution bits: %r vs %r"
            % (label, name, actual_totals[name], projection[name]),
        )

    expected = {
        "size": expected_size,
        "price": expected_price,
        "commission": expected_commission,
        "pnl": expected_pnl,
        "opened": expected_opened,
        "closed": expected_closed,
        "opened_commission": expected_opened_commission,
        "closed_commission": expected_closed_commission,
    }
    for name, expected_value in expected.items():
        _require(
            math.isclose(projection[name], expected_value, rel_tol=0.0, abs_tol=1e-12),
            "%s Broker %s differs from provider fill: %r != %r"
            % (label, name, projection[name], expected_value),
        )
    return projection


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
) -> Tuple[Dict[str, str], str, int]:
    """Verify hashed RECORD payloads and narrowly mapped generated bytecode."""

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
    generated_pyc_sources = []
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
        if not hash_field and not size_field:
            if target.suffix != ".pyc" or not target.is_file():
                raise ValueError("unhashed installed RECORD entry is not a generated pyc")
            relative = _record_path(name)
            if ".." in relative.parts:
                raise ValueError("generated bytecode cache path uses parent traversal")
            lexical_target = Path(os.path.abspath(root.joinpath(*relative.parts)))
            if not _is_within(lexical_target, root) or target != lexical_target:
                raise ValueError("generated bytecode cache path is not a direct installed file")
            try:
                target.relative_to(root)
                source_path = Path(source_from_cache(str(target))).resolve(strict=True)
                source_name = source_path.relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise ValueError(
                    "generated bytecode cache does not map to an installed source"
                ) from exc
            if source_path.suffix != ".py" or not source_path.is_file():
                raise ValueError("generated bytecode cache source is not a Python file")
            generated_pyc_sources.append(source_name)
            continue
        if not hash_field or not size_field:
            raise ValueError("wheel RECORD payload needs both SHA-256 and size")
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
    for source_name in generated_pyc_sources:
        if source_name not in verified:
            raise ValueError("generated bytecode cache has no verified installed source")
    return verified, record_digest, len(generated_pyc_sources)


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
    record_hashes, record_digest, generated_pyc_count = _verify_record(
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
        "generated_pyc_auxiliaries_not_wheel_payload": generated_pyc_count,
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


def _alpha101_source_ref(instrument: str, field_name: str) -> str:
    return "iteration50-synthetic:%s:%s:v1" % (instrument, field_name)


def _validate_alpha101_field_provenance(
    provenance: Mapping[str, Mapping[str, Any]], expected_evaluation_points: int
) -> None:
    """Require real production provenance rows in the bounded stream summary."""

    _require(
        set(provenance) == set(_FIELD_PIT_UNITS),
        "field provenance summary does not cover every factor input field",
    )
    expected_sources = {
        field_name: sorted(_alpha101_source_ref(target, field_name) for target in _TARGETS)
        for field_name in _FIELD_PIT_UNITS
    }
    for field_name, expected_unit in _FIELD_PIT_UNITS.items():
        stats = provenance[field_name]
        _require(
            stats["row_count"] >= expected_evaluation_points
            and stats["pit_qualified_rows"] >= expected_evaluation_points
            and stats["unit_counts"] == {expected_unit: stats["row_count"]}
            and stats["source_refs"] == expected_sources[field_name]
            and all(
                stats[key]
                for key in (
                    "first_effective_at",
                    "last_effective_at",
                    "first_available_at",
                    "last_available_at",
                    "first_valid_until",
                    "last_valid_until",
                    "first_evaluated_at",
                    "last_evaluated_at",
                )
            ),
            "field provenance summary lacks source, unit, or PIT time witnesses: " + field_name,
        )


def _fixture_bars(
    slot_count: int = _SLOT_COUNT,
    *,
    include_extra_fields: bool = False,
    varied_stream: bool = False,
    first_close: Optional[datetime] = None,
) -> Tuple[Dict[str, Tuple[Mapping[str, Any], ...]], LiveCohortCalendar]:
    first_close = first_close or datetime(2025, 1, 2, 9, 31, tzinfo=_UTC)
    member_ids = {target: "member-" + target for target in _TARGETS}
    slots = []
    bars: Dict[str, list] = {target: [] for target in _TARGETS}

    for index in range(slot_count):
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
            if varied_stream:
                phase = index + 1
                wave = math.sin(phase * (0.071 + asset_index * 0.009)) + 0.37 * math.cos(
                    phase * (0.037 + asset_index * 0.006)
                )
                open_price = 82.0 + asset_index * 13.0 + phase * 0.021 + wave * 2.2
                move = (
                    math.sin(phase * (0.113 + asset_index * 0.017)) * 0.72
                    + math.cos(phase * (0.053 + asset_index * 0.011)) * 0.19
                )
                close_price = open_price + move
                high_price = (
                    max(open_price, close_price)
                    + 0.31
                    + abs(math.sin(phase * 0.17 + asset_index)) * 0.22
                )
                low_price = (
                    min(open_price, close_price)
                    - 0.29
                    - abs(math.cos(phase * 0.13 + asset_index)) * 0.18
                )
                volume = (
                    1_500.0
                    + asset_index * 211.0
                    + (phase * 37 + asset_index * 83) % 997
                    + 91.0 * math.sin(phase * 0.083 + asset_index)
                )
            else:
                open_rank = (asset_index + index) % len(_TARGETS)
                volume_rank = (asset_index + 2 * index) % len(_TARGETS)
                open_price = float(100 + open_rank * 10)
                close_price = open_price + 1.0
                high_price = close_price + 0.5
                low_price = open_price - 0.5
                volume = float(1_000 + volume_rank * 100)

            row = {
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
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "openinterest": 0.0,
                "present": True,
                "complete": True,
                "quality": "GOOD",
                "quality_flags": (),
                "source": (
                    "iteration50-installed-alpha101-stream"
                    if varied_stream
                    else "iteration50-installed-smoke"
                ),
            }
            if include_extra_fields:
                row.update(
                    {
                        "vwap": (
                            (open_price + high_price + low_price + close_price) / 4.0
                            + 0.173
                            + asset_index * 0.031
                            + index * 0.002
                        ),
                        "cap": 1_000_000.0 + asset_index * 72_000.0 + index * 1_237.0,
                        "sector": float(asset_index % 3),
                        "industry": float(10 + asset_index % 5),
                        "subindustry": float(100 + asset_index % 7),
                        "dollar_volume": (
                            25_000.0
                            + asset_index * 3_700.0
                            + index * 29.0
                            + 1_900.0 * math.sin((index + 1) * 0.101 + asset_index)
                        ),
                    }
                )
                row["field_observations"] = MappingProxyType(
                    {
                        field_name: LiveFieldObservation(
                            source_ref=_alpha101_source_ref(target, field_name),
                            unit=unit,
                            effective_at=close_time - timedelta(seconds=1),
                            available_at=close_time,
                            revision="%s-%s-%d" % (target, field_name, index + 1),
                            valid_until=close_time + timedelta(minutes=5),
                        )
                        for field_name, unit in _FIELD_PIT_UNITS.items()
                    }
                )
            bars[target].append(MappingProxyType(row))

    calendar = LiveCohortCalendar(
        calendar_id=(
            "iteration50-installed-alpha101-v1"
            if include_extra_fields
            else "iteration50-installed-alpha003-v1"
        ),
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


def _alpha101_field_bindings(indicator: type) -> Dict[str, Any]:
    """Map production formula aliases to fixed feed lines or ADV derivations."""

    bindings = {}
    for alias in tuple(getattr(indicator, "formula_fields", ())):
        if alias == "dollar_volume":
            bindings[alias] = "feed:target:dollar_volume"
        elif alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": int(alias[3:]),
            }
        else:
            bindings[alias] = "feed:target:%s" % alias
    return bindings


def _alpha101_field_policies(indicator: type) -> Dict[str, FieldPITPolicy]:
    """Give each declared source alias an explicit fixture-local unit/age policy."""

    policies = {}
    for alias in tuple(getattr(indicator, "formula_fields", ())):
        unit = "USD" if alias.startswith("adv") and alias[3:].isdigit() else _FIELD_PIT_UNITS[alias]
        policies[alias] = FieldPITPolicy(unit=unit, max_age_seconds=_FIELD_PIT_MAX_AGE_SECONDS)
    return policies


def _alpha101_factor_specs() -> Dict[str, Any]:
    """Build the installed registry's complete paired native/build selection."""

    factors = {}
    for alpha_id in range(1, 102):
        indicator = get_alpha(alpha_id)
        for mode in ("native", "build"):
            name = "alpha%d_%s" % (alpha_id, mode)
            factors[name] = FactorSpec(
                name=name,
                indicator=indicator,
                panel_line="factor",
                mode=mode,
                field_bindings=_alpha101_field_bindings(indicator),
                field_policies=_alpha101_field_policies(indicator),
            )
    return factors


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _float_token(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "+inf" if value > 0 else "-inf"
    return value.hex()


def _same_stream_value(left: float, right: float) -> bool:
    if math.isnan(left) or math.isnan(right):
        return math.isnan(left) and math.isnan(right)
    if math.isinf(left) or math.isinf(right):
        return False
    return abs(left - right) <= _ALPHA101_ABS_TOL + _ALPHA101_REL_TOL * abs(right)


def _validate_alpha101_stream_witnesses(
    factor_pairs: Mapping[str, Mapping[str, Any]],
    extra_fields: Mapping[str, Mapping[str, Any]],
    expected_points: int,
    expected_evaluation_points: int,
) -> None:
    """Fail closed when the stream has no qualified factor/field witnesses."""

    for alpha_id in _ALPHA101_REQUIRED_OUTPUT_WITNESS_IDS:
        stats = factor_pairs.get(str(alpha_id))
        _require(stats is not None, "missing required Alpha%d output witness" % alpha_id)
        _require(
            stats["output_available_witnesses"] > 0 and stats["finite_witnesses"] > 0,
            "Alpha%d has no finite OUTPUT_AVAILABLE witness" % alpha_id,
        )
        _require(
            stats["evaluation_available_finite_witnesses"] > 0,
            "Alpha%d has no evaluation OUTPUT_AVAILABLE witness" % alpha_id,
        )
        _require(
            stats["pit_qualified_evaluation_points"] == expected_evaluation_points,
            "Alpha%d lacks complete PIT-qualified evaluation witnesses" % alpha_id,
        )

    for field_name, alpha_id in _ALPHA101_EXTRA_WITNESS_FACTORS.items():
        stats = extra_fields.get(field_name)
        _require(stats is not None, "missing extra-field witness record: " + field_name)
        expected_sources = sorted(_alpha101_source_ref(target, field_name) for target in _TARGETS)
        _require(
            stats["values_checked"] == expected_points
            and stats["finite_witnesses"] == expected_points,
            "extra field lacks a finite streamed witness for every member: " + field_name,
        )
        _require(
            stats["pit_qualified_witnesses"] == expected_evaluation_points
            and stats["unit"] == _FIELD_PIT_UNITS[field_name]
            and stats["source_refs"] == expected_sources
            and all(
                stats[key]
                for key in (
                    "first_effective_at",
                    "last_effective_at",
                    "first_available_at",
                    "last_available_at",
                    "first_valid_until",
                    "last_valid_until",
                    "first_evaluated_at",
                    "last_evaluated_at",
                )
            ),
            "extra field lacks PIT provenance witnesses: " + field_name,
        )
        factor_stats = factor_pairs.get(str(alpha_id), {})
        _require(
            factor_stats.get("output_available_witnesses", 0) > 0,
            "extra field representative Alpha%d has no available output" % alpha_id,
        )
        if field_name in {"vwap", "dollar_volume"}:
            _require(
                stats["distinct_from_ohlc_witnesses"] == expected_points,
                "extra field is not independent on every fixture row: " + field_name,
            )


def _counter_add_bounded(counter: Counter, value: Any, limit: int = 32) -> None:
    key = _enum_text(value)
    if len(key) > 128:
        key = key[:128]
    if key in counter or len(counter) < limit:
        counter[key] += 1
    else:
        counter["<other>"] += 1


class _CaptureStrategy(bt.Strategy):
    params = (
        ("cohort", None),
        ("plan", None),
        ("profile", "alpha003"),
        ("alpha_ids", ()),
        ("warmup_required_bars", 0),
        ("first_evaluation_close_time", None),
    )

    def __init__(self) -> None:
        feeds = {data._name: data for data in self.datas}
        self.factor_set = LiveFactorSet.bind(self.p.plan, feeds, cohort=self.p.cohort)
        self.snapshots = []
        self.last_snapshot = None
        self.order_callbacks = 0
        self.next_callbacks = 0
        self._alpha_ids = tuple(self.p.alpha_ids)
        self._alpha101_first_close_time = None
        self._alpha101_last_close_time = None
        self._alpha101_first_available_at = None
        self._alpha101_last_available_at = None
        self._alpha101_first_evaluation_close_time = None
        self._alpha101_first_live_ready_close_time = None
        self._alpha101_evaluation_batches = 0
        self._alpha101_digest = hashlib.sha256()
        self._alpha101_readiness_counts = Counter()
        self._alpha101_factor_stats = {
            alpha_id: {
                "compared_points": 0,
                "finite_witnesses": 0,
                "available_finite_witnesses": 0,
                "output_available_witnesses": 0,
                "evaluation_available_finite_witnesses": 0,
                "pit_qualified_evaluation_points": 0,
                "first_finite_close_time": None,
                "first_output_available_close_time": None,
                "max_abs_diff": 0.0,
                "status_counts": Counter(),
                "reason_counts": Counter(),
            }
            for alpha_id in self._alpha_ids
        }
        self._extra_field_stats = {
            field: {
                "values_checked": 0,
                "finite_witnesses": 0,
                "minimum": None,
                "maximum": None,
                "distinct_from_ohlc_witnesses": 0,
                "pit_qualified_witnesses": 0,
                "unit": _FIELD_PIT_UNITS[field],
                "source_refs": set(),
                "first_effective_at": None,
                "last_effective_at": None,
                "first_available_at": None,
                "last_available_at": None,
                "first_valid_until": None,
                "last_valid_until": None,
                "first_evaluated_at": None,
                "last_evaluated_at": None,
            }
            for field in _EXTRA_FIELDS
        }
        self._alpha101_provenance_stats = {
            field: {
                "row_count": 0,
                "pit_qualified_rows": 0,
                "status_counts": Counter(),
                "unit_counts": Counter(),
                "source_refs": set(),
                "first_effective_at": None,
                "last_effective_at": None,
                "first_available_at": None,
                "last_available_at": None,
                "first_valid_until": None,
                "last_valid_until": None,
                "first_evaluated_at": None,
                "last_evaluated_at": None,
            }
            for field in _FIELD_PIT_UNITS
        }

    def prenext(self) -> None:
        if self.p.profile == "alpha101-stream":
            self._capture_complete_batch()

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
        feed_closes = {data._name: data.datetime.datetime(0).isoformat() for data in self.datas}
        expected_close = batch.close_time.replace(tzinfo=None)
        _require(
            all(data.datetime.datetime(0) == expected_close for data in self.datas),
            "feed line closes %r differ from cohort close %s"
            % (feed_closes, expected_close.isoformat()),
        )
        snapshot = self.factor_set.snapshot()
        _require(snapshot.batch_complete, "factor snapshot is not bound to a complete batch")
        _require(snapshot.close_time == batch.close_time, "factor snapshot close changed")
        if self.p.profile == "alpha101-stream":
            _require(
                snapshot.available_at == batch.available_at,
                "factor snapshot availability differs from the complete cohort batch",
            )
        self.last_snapshot = snapshot
        self.next_callbacks += 1
        if self.p.profile == "alpha101-stream":
            self._capture_alpha101_stream(snapshot)
        else:
            self.snapshots.append(snapshot)

    def _capture_alpha101_stream(self, snapshot: Any) -> None:
        _require(self._alpha_ids, "full Alpha101 profile has no selected factor IDs")
        _require(
            type(self.p.warmup_required_bars) is int and self.p.warmup_required_bars > 0,
            "full Alpha101 profile has no finite warmup boundary",
        )
        expected_names = {
            "alpha%d_%s" % (alpha_id, mode)
            for alpha_id in self._alpha_ids
            for mode in ("native", "build")
        }
        _require(
            set(snapshot.factors) == expected_names,
            "full Alpha101 snapshot differs from its native/build factor set",
        )
        self._alpha101_readiness_counts[_enum_text(snapshot.readiness)] += 1
        close_text = snapshot.close_time.isoformat()
        available_text = snapshot.available_at.isoformat()
        if self._alpha101_first_close_time is None:
            self._alpha101_first_close_time = close_text
            self._alpha101_first_available_at = available_text
        self._alpha101_last_close_time = close_text
        self._alpha101_last_available_at = available_text
        if _enum_text(snapshot.readiness) == "LIVE_READY" and (
            self._alpha101_first_live_ready_close_time is None
        ):
            self._alpha101_first_live_ready_close_time = close_text
        evaluation_active = self.next_callbacks >= self.p.warmup_required_bars
        if evaluation_active:
            self._alpha101_evaluation_batches += 1
        if self.next_callbacks == self.p.warmup_required_bars:
            self._alpha101_first_evaluation_close_time = close_text
            _require(
                snapshot.close_time == self.p.first_evaluation_close_time,
                "observed warmup/evaluation boundary differs from the finite calendar",
            )
        payload = [
            close_text,
            available_text,
            _enum_text(snapshot.readiness),
            list(snapshot.readiness_reasons),
        ]

        for field in _EXTRA_FIELDS:
            stats = self._extra_field_stats[field]
            for feed in self.datas:
                value = float(getattr(feed, field)[0])
                _require(math.isfinite(value), "installed extra feed line is not finite: " + field)
                stats["values_checked"] += 1
                stats["finite_witnesses"] += 1
                stats["minimum"] = (
                    value if stats["minimum"] is None else min(stats["minimum"], value)
                )
                stats["maximum"] = (
                    value if stats["maximum"] is None else max(stats["maximum"], value)
                )
                if field == "vwap":
                    ohlc_average = sum(float(getattr(feed, name)[0]) for name in _FIELDS[:4]) / 4.0
                    if value != ohlc_average:
                        stats["distinct_from_ohlc_witnesses"] += 1
                elif field == "dollar_volume":
                    derived = float(feed.vwap[0]) * float(feed.volume[0])
                    if not math.isclose(value, derived, rel_tol=1e-9, abs_tol=1e-9):
                        stats["distinct_from_ohlc_witnesses"] += 1

        for alpha_id in self._alpha_ids:
            native_name = "alpha%d_native" % alpha_id
            build_name = "alpha%d_build" % alpha_id
            native = snapshot.factors[native_name]
            build = snapshot.factors[build_name]
            _require(
                native.mode == "native" and build.mode == "build", "factor mode binding changed"
            )
            _require(
                native.pit_policy_complete is True and build.pit_policy_complete is True,
                "factor is missing a declared field PIT policy",
            )
            _require(
                native.pit_qualified == build.pit_qualified,
                "native/build PIT qualification differs",
            )
            if evaluation_active:
                _require(
                    native.pit_qualified is True,
                    "factor source fields are not PIT-qualified after its full history window",
                )
            stats = self._alpha101_factor_stats[alpha_id]
            pair_payload = [alpha_id]
            if evaluation_active and native.pit_qualified:
                stats["pit_qualified_evaluation_points"] += len(_TARGETS)
            for target in _TARGETS:
                left = native.values[target]
                right = build.values[target]
                left_status = _enum_text(left.status)
                right_status = _enum_text(right.status)
                _require(left_status == right_status, "native/build output status differs")
                _require(left.reason == right.reason, "native/build output reason differs")
                _require(
                    (left.present, left.complete, _enum_text(left.quality))
                    == (right.present, right.complete, _enum_text(right.quality)),
                    "native/build output receipt state differs",
                )
                _require(
                    (
                        left.source_role,
                        left.member_id,
                        left.source_ref,
                        left.sequence,
                        left.generation,
                    )
                    == (
                        right.source_role,
                        right.member_id,
                        right.source_ref,
                        right.sequence,
                        right.generation,
                    ),
                    "native/build source receipt identity differs",
                )
                _require(
                    left.field_provenance == right.field_provenance,
                    "native/build field provenance differs",
                )
                left_value = float(left.value)
                right_value = float(right.value)
                _require(
                    _same_stream_value(left_value, right_value),
                    "native/build value exceeds the installed parity tolerance",
                )
                if math.isfinite(left_value) and math.isfinite(right_value):
                    stats["finite_witnesses"] += 1
                    if stats["first_finite_close_time"] is None:
                        stats["first_finite_close_time"] = close_text
                    stats["max_abs_diff"] = max(
                        stats["max_abs_diff"], abs(left_value - right_value)
                    )
                if left_status == "OUTPUT_AVAILABLE":
                    _require(
                        math.isfinite(left_value) and math.isfinite(right_value),
                        "OUTPUT_AVAILABLE factor output is not finite",
                    )
                    stats["output_available_witnesses"] += 1
                    stats["available_finite_witnesses"] += 1
                    if evaluation_active:
                        stats["evaluation_available_finite_witnesses"] += 1
                    if stats["first_output_available_close_time"] is None:
                        stats["first_output_available_close_time"] = close_text
                stats["compared_points"] += 1
                stats["status_counts"][left_status] += 1
                if left.reason is not None:
                    _counter_add_bounded(stats["reason_counts"], left.reason)
                else:
                    stats["reason_counts"]["<none>"] += 1
                pair_payload.append(
                    [
                        target,
                        left_status,
                        _enum_text(left.reason) if left.reason is not None else None,
                        _float_token(left_value),
                        _float_token(right_value),
                        left.present,
                        left.complete,
                        _enum_text(left.quality),
                        left.member_id,
                        left.sequence,
                        _enum_text(left.generation),
                    ]
                )
            provenance_output = native.values[_TARGETS[0]]
            _require(
                set(provenance_output.field_provenance) == set(native.inputs),
                "factor input provenance aliases differ from the bound field set",
            )
            for alias, rows in provenance_output.field_provenance.items():
                _require(
                    len(rows) == len(_TARGETS),
                    "factor provenance omitted a live cohort member",
                )
                for row in rows:
                    field_name = row.line_name
                    _require(
                        field_name in _FIELD_PIT_UNITS,
                        "factor provenance refers to a field without a fixture unit",
                    )
                    expected_unit = (
                        "USD"
                        if alias.startswith("adv") and alias[3:].isdigit()
                        else _FIELD_PIT_UNITS[field_name]
                    )
                    _require(
                        row.unit == expected_unit and bool(row.source_ref),
                        "factor provenance lacks the declared source unit",
                    )
                    _require(
                        row.source_ref == _alpha101_source_ref(row.feed_name, field_name),
                        "factor provenance source differs from the synthetic adapter contract",
                    )
                    _require(
                        row.delivery_mode == "independent"
                        and row.effective_at is not None
                        and row.available_at is not None
                        and row.valid_until is not None
                        and row.evaluated_at is not None
                        and row.revision is not None,
                        "factor provenance omits its PIT observation fields",
                    )
                    _require(
                        row.effective_at <= snapshot.close_time
                        and row.available_at <= snapshot.available_at
                        and row.valid_until >= snapshot.close_time
                        and row.evaluated_at == snapshot.close_time
                        and (snapshot.close_time - row.effective_at).total_seconds()
                        <= _FIELD_PIT_MAX_AGE_SECONDS,
                        "factor field observation falls outside its PIT policy boundary",
                    )
                    if evaluation_active:
                        _require(
                            row.status == "PIT_QUALIFIED",
                            "field provenance is not PIT-qualified at evaluation time",
                        )
                    else:
                        _require(
                            row.status in {"WINDOW_UNQUALIFIED", "PIT_QUALIFIED"},
                            "factor provenance has an unrecognized prewarm state",
                        )
                    provenance_stats = self._alpha101_provenance_stats[field_name]
                    provenance_stats["row_count"] += 1
                    provenance_stats["status_counts"][row.status] += 1
                    provenance_stats["unit_counts"][row.unit] += 1
                    if row.status == "PIT_QUALIFIED":
                        provenance_stats["pit_qualified_rows"] += 1
                    if len(provenance_stats["source_refs"]) < len(_TARGETS):
                        provenance_stats["source_refs"].add(row.source_ref)
                    for name, timestamp in (
                        ("effective_at", row.effective_at),
                        ("available_at", row.available_at),
                        ("valid_until", row.valid_until),
                        ("evaluated_at", row.evaluated_at),
                    ):
                        first_key = "first_" + name
                        last_key = "last_" + name
                        if provenance_stats[first_key] is None:
                            provenance_stats[first_key] = timestamp.isoformat()
                        provenance_stats[last_key] = timestamp.isoformat()

                    if (
                        alpha_id == _ALPHA101_EXTRA_WITNESS_FACTORS.get(field_name)
                        and alias == field_name
                    ):
                        extra_stats = self._extra_field_stats[field_name]
                        if len(extra_stats["source_refs"]) < len(_TARGETS):
                            extra_stats["source_refs"].add(row.source_ref)
                        for name, timestamp in (
                            ("effective_at", row.effective_at),
                            ("available_at", row.available_at),
                            ("valid_until", row.valid_until),
                            ("evaluated_at", row.evaluated_at),
                        ):
                            first_key = "first_" + name
                            last_key = "last_" + name
                            if extra_stats[first_key] is None:
                                extra_stats[first_key] = timestamp.isoformat()
                            extra_stats[last_key] = timestamp.isoformat()
                        if evaluation_active and row.status == "PIT_QUALIFIED":
                            extra_stats["pit_qualified_witnesses"] += 1
            payload.append(pair_payload)

        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._alpha101_digest.update(encoded.encode("utf-8"))
        self._alpha101_digest.update(b"\n")

    def alpha101_stream_report(self) -> Dict[str, Any]:
        _require(
            self.p.profile == "alpha101-stream", "Alpha101 report requested for another profile"
        )
        return {
            "stream_callbacks": self.next_callbacks,
            "same_stream_pair_sha256": self._alpha101_digest.hexdigest(),
            "global_readiness_counts": dict(sorted(self._alpha101_readiness_counts.items())),
            "stream_boundaries": {
                "first_close_time": self._alpha101_first_close_time,
                "last_close_time": self._alpha101_last_close_time,
                "first_available_at": self._alpha101_first_available_at,
                "last_available_at": self._alpha101_last_available_at,
            },
            "evaluation_boundary": {
                "configured_warmup_min_bars": self.p.plan.warmup_min_bars,
                "graph_required_bars": self.p.warmup_required_bars,
                "observed_first_evaluation_close_time": self._alpha101_first_evaluation_close_time,
                "first_live_ready_close_time": self._alpha101_first_live_ready_close_time,
                "evaluation_batches": self._alpha101_evaluation_batches,
            },
            "factor_count": len(self._alpha101_factor_stats),
            "factor_pairs": {
                str(alpha_id): {
                    "compared_points": stats["compared_points"],
                    "finite_witnesses": stats["finite_witnesses"],
                    "available_finite_witnesses": stats["available_finite_witnesses"],
                    "output_available_witnesses": stats["output_available_witnesses"],
                    "evaluation_available_finite_witnesses": stats[
                        "evaluation_available_finite_witnesses"
                    ],
                    "pit_qualified_evaluation_points": stats["pit_qualified_evaluation_points"],
                    "first_finite_close_time": stats["first_finite_close_time"],
                    "first_output_available_close_time": stats["first_output_available_close_time"],
                    "max_abs_diff": stats["max_abs_diff"],
                    "status_counts": dict(sorted(stats["status_counts"].items())),
                    "reason_counts": dict(sorted(stats["reason_counts"].items())),
                }
                for alpha_id, stats in self._alpha101_factor_stats.items()
            },
            "extra_field_witnesses": {
                field: {
                    **{name: value for name, value in stats.items() if name != "source_refs"},
                    "source_refs": sorted(stats["source_refs"]),
                    "pit_qualified_witnesses": stats["pit_qualified_witnesses"],
                }
                for field, stats in self._extra_field_stats.items()
            },
            "field_provenance": {
                field: {
                    "row_count": stats["row_count"],
                    "pit_qualified_rows": stats["pit_qualified_rows"],
                    "status_counts": dict(sorted(stats["status_counts"].items())),
                    "unit_counts": dict(sorted(stats["unit_counts"].items())),
                    "source_refs": sorted(stats["source_refs"]),
                    "first_effective_at": stats["first_effective_at"],
                    "last_effective_at": stats["last_effective_at"],
                    "first_available_at": stats["first_available_at"],
                    "last_available_at": stats["last_available_at"],
                    "first_valid_until": stats["first_valid_until"],
                    "last_valid_until": stats["last_valid_until"],
                    "first_evaluated_at": stats["first_evaluated_at"],
                    "last_evaluated_at": stats["last_evaluated_at"],
                }
                for field, stats in self._alpha101_provenance_stats.items()
            },
            "synthetic_field_contracts_only": True,
        }


def _run_live_mode(mode: str, *, profile: str = "alpha003") -> Dict[str, Any]:
    is_alpha101 = profile == "alpha101-stream"
    _require(profile in {"alpha003", "alpha101-stream"}, "unknown installed stream profile")
    slot_count = _ALPHA101_SLOT_COUNT if is_alpha101 else _SLOT_COUNT
    alpha_ids = tuple(range(1, 102)) if is_alpha101 else ()
    bars, calendar = _fixture_bars(
        slot_count,
        include_extra_fields=is_alpha101,
        varied_stream=is_alpha101,
    )
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
        "iteration50-installed-alpha101" if is_alpha101 else "iteration50-installed-alpha003",
        calendar,
        max_pending_slots=2,
        max_window_bars=slot_count,
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
        declared_fields = _FIELDS + (_EXTRA_FIELDS if is_alpha101 else ())
        cohort.register_member(
            "member-" + target,
            feed,
            instrument=target,
            source_ref="store-feed-" + target,
            line_fields=declared_fields,
            raw_fields=declared_fields,
            numeric_fields=declared_fields,
            field_contracts=(
                {
                    field_name: LiveFieldContract(
                        source_ref=_alpha101_source_ref(target, field_name),
                        unit=unit,
                        delivery_mode="independent",
                    )
                    for field_name, unit in _FIELD_PIT_UNITS.items()
                }
                if is_alpha101
                else None
            ),
        )

    if is_alpha101:
        factors = _alpha101_factor_specs()
        warmup_min_bars = 30
        graph_required_bars = max(int(spec.lookback_h) + 1 for spec in factors.values())
        warmup_required_bars = max(warmup_min_bars, graph_required_bars)
        _require(
            warmup_required_bars <= slot_count,
            "finite fixture calendar does not cover the Alpha101 evaluation boundary",
        )
        first_evaluation_close_time = calendar.slots[warmup_required_bars - 1].close_time
        plan_id = "iteration50-installed-alpha101-native-build"
    else:
        factors = {
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
        }
        warmup_min_bars = 10
        warmup_required_bars = 0
        first_evaluation_close_time = None
        plan_id = "iteration50-installed-alpha003-" + mode

    plan = LiveFactorPlan(
        plan_id=plan_id,
        targets=_TARGETS,
        groups=dict.fromkeys(_TARGETS, "portfolio"),
        factors=factors,
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=warmup_min_bars,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=slot_count,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=0.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _CaptureStrategy,
        cohort=cohort,
        plan=plan,
        profile=profile,
        alpha_ids=alpha_ids,
        warmup_required_bars=warmup_required_bars,
        first_evaluation_close_time=first_evaluation_close_time,
    )

    strategies = cerebro.run()
    _require(len(strategies) == 1, "Cerebro did not run exactly one ordinary Strategy")
    strategy = strategies[0]
    _require(strategy.next_callbacks > 0, "ordinary Strategy received no complete live batch")
    _require(
        strategy.last_snapshot is not None,
        "ordinary Strategy captured no complete factor snapshot",
    )
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

    snapshot = strategy.last_snapshot
    _require(snapshot.batch_complete, "final Alpha003 snapshot has no complete batch")
    if is_alpha101:
        _require(
            strategy.next_callbacks == slot_count,
            "full Alpha101 profile did not capture every complete streamed batch",
        )
        summary = strategy.alpha101_stream_report()
        expected_points = strategy.next_callbacks * len(_TARGETS)
        expected_evaluation_batches = slot_count - warmup_required_bars + 1
        expected_evaluation_points = expected_evaluation_batches * len(_TARGETS)
        _require(
            summary["factor_count"] == 101,
            "installed profile omitted an Alpha101 factor pair",
        )
        _require(
            summary["stream_boundaries"]
            == {
                "first_close_time": calendar.slots[0].close_time.isoformat(),
                "last_close_time": calendar.slots[-1].close_time.isoformat(),
                "first_available_at": calendar.slots[0].close_time.isoformat(),
                "last_available_at": calendar.slots[-1].close_time.isoformat(),
            },
            "stream summary does not cover the finite calendar boundaries",
        )
        _require(
            summary["evaluation_boundary"]["observed_first_evaluation_close_time"]
            == first_evaluation_close_time.isoformat()
            and summary["evaluation_boundary"]["evaluation_batches"] == expected_evaluation_batches,
            "stream summary does not prove the exact warmup/evaluation boundary",
        )
        _require(
            summary["evaluation_boundary"]["first_live_ready_close_time"] is not None,
            "no LIVE_READY witness occurred in the finite stream",
        )
        for alpha_id, stats in summary["factor_pairs"].items():
            _require(
                stats["compared_points"] == expected_points,
                "native/build comparison omitted streamed targets for Alpha%d" % int(alpha_id),
            )
            _require(
                stats["pit_qualified_evaluation_points"] == expected_evaluation_points,
                "Alpha%d lacks complete PIT-qualified evaluation points" % int(alpha_id),
            )
        for field, stats in summary["extra_field_witnesses"].items():
            _require(
                stats["values_checked"] == expected_points,
                "extra field was not checked on every live target batch: " + field,
            )
        _validate_alpha101_stream_witnesses(
            summary["factor_pairs"],
            summary["extra_field_witnesses"],
            expected_points,
            expected_evaluation_points,
        )
        _validate_alpha101_field_provenance(summary["field_provenance"], expected_evaluation_points)
        _require(
            summary["extra_field_witnesses"]["vwap"]["distinct_from_ohlc_witnesses"]
            == expected_points,
            "VWAP fixture was not independent of OHLC on every row",
        )
        _require(
            summary["extra_field_witnesses"]["dollar_volume"]["distinct_from_ohlc_witnesses"]
            == expected_points,
            "dollar-volume fixture was not independent of VWAP times volume",
        )
        return {
            "mode": "native-build-paired",
            "batch_complete": snapshot.batch_complete,
            "close_time": snapshot.close_time.isoformat(),
            "target_count": len(_TARGETS),
            "factor_count": summary["factor_count"],
            "order_callbacks": strategy.order_callbacks,
            "provider_calls": dict(sorted(provider.calls.items())),
            "provider_subscriptions": sorted(provider.subscriptions),
            "stream": summary,
        }

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


def _run_read_only_mode(mode: str) -> Dict[str, Any]:
    return _run_live_mode(mode, profile="alpha003")


def _run_alpha101_stream_profile() -> Dict[str, Any]:
    return _run_live_mode("native-build-paired", profile="alpha101-stream")


_EXECUTION_SCOPE = "iteration50-alpha003-installed"
_EXECUTION_ACCOUNT = "fixture-account-scope"
_EXECUTION_TRADING_DAY = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
_EXECUTION_STARTING_AVAILABLE = 100_000.0


class _ExecutionProviderLeaf:
    """Bounded synthetic CTP leaf composed under the production wrapper."""

    def __init__(self, *, bars, slot_count, **kwargs):
        del kwargs
        self._bars = {name: tuple(rows) for name, rows in bars.items()}
        self._slot_count = int(slot_count)
        self._bar_counts = Counter()
        self._bar_condition = threading.Condition()
        self._allowed_index = self._slot_count - 1
        self._factor_ready = False
        self._source_stopped = False
        self._ticks = {}
        self._provider_commission = 0.0
        self._provider_available = _EXECUTION_STARTING_AVAILABLE
        self._query_rows = self._execution_query_rows()
        self._query_issuer = object()
        self._request_id = 0
        self._update_queue = deque()
        self._order_identity = {}
        self._provider_order_rows = {}
        self._provider_trade_rows = []
        self._provider_position_quantities = Counter()
        self._provider_events = []
        self._native_order_ref = 500
        self._native_request_id = 100
        self.native_calls = []
        self.connected = False
        self.subscriptions = []
        self.trader_client = self
        self.is_ready = True
        self.is_trading_ready = True
        self._connection_generation = 1
        self._stream_revision = 0
        self._stream_stale = True
        self._stream_stale_reason = "ctp_front_disconnected"
        self._ever_connected = False
        self._account_fingerprint = _EXECUTION_ACCOUNT
        self._trading_day = _EXECUTION_TRADING_DAY
        self._front_id = 4
        self._session_id = 7
        self._gate_state = {
            "managed": False,
            "armed": False,
            "instrument": None,
            "authorized_instruments": [],
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "scope_version": "ctp-contract-bundle-v1",
            "proof_sha256": "c" * 64,
            "environment_profile": "fixture_only",
            "revocation_reason": None,
        }

    def _execution_query_rows(self):
        return {
            "account_result": [{"Available": str(self._provider_available), "CurrMargin": "0"}],
            "positions_result": [],
            "orders_result": [],
            "trades_result": [],
            "instruments_result": [
                {
                    "InstrumentID": target,
                    "ExchangeID": "DCE",
                    "IsTrading": 1,
                    "VolumeMultiple": 10,
                    "PriceTick": 1,
                    "LowerLimitPrice": 1,
                    "UpperLimitPrice": 1000,
                }
                for target in _TARGETS
            ],
            "instrument_margin_rate_result": [
                {
                    "InstrumentID": target,
                    "ExchangeID": "DCE",
                    "HedgeFlag": "1",
                    "LongMarginRatioByMoney": "0.1",
                    "LongMarginRatioByVolume": "0",
                    "ShortMarginRatioByMoney": "0.1",
                    "ShortMarginRatioByVolume": "0",
                }
                for target in _TARGETS
            ],
        }

    def connect(self):
        if self._ever_connected:
            self._connection_generation += 1
            self._stream_revision += 1
        self.connected = True
        self._ever_connected = True
        self._stream_stale = False
        self._stream_stale_reason = ""

    def disconnect(self):
        if self.connected:
            self._stream_revision += 1
        self.connected = False
        self._stream_stale = True
        self._stream_stale_reason = "ctp_front_disconnected"
        self.stop_bar_source()

    def _get_live_ctp_stream_health(self):
        """Expose the synthetic leaf's bounded generation-aware stream state."""
        return {
            "generation_callbacks_supported": True,
            "source_generation": self._connection_generation,
            "source_revision": self._stream_revision,
            "stale": self._stream_stale,
            "stale_reason": self._stream_stale_reason,
            "stale_tick_drop_count": 0,
            "stale_tick_drop_reason": "",
            "symbols": tuple(sorted(self._bars)),
        }

    def subscribe(self, symbol):
        self.subscriptions.append(symbol)

    def get_balance(self):
        row = self._query_rows["account_result"][0]
        available = float(row["Available"])
        return {"cash": available, "value": available}

    def get_positions(self):
        result = []
        for row in self._query_rows.get("positions_result", ()):
            quantity = float(row.get("Position", 0) or 0)
            if quantity <= 0:
                continue
            side = "long" if str(row.get("PosiDirection")) == "2" else "short"
            result.append(
                {
                    "instrument": row.get("InstrumentID"),
                    "symbol": row.get("InstrumentID"),
                    "exchange_id": row.get("ExchangeID"),
                    "direction": side,
                    "size": quantity if side == "long" else -quantity,
                    "volume": quantity,
                    "price": 100.0,
                    "avg_price": 100.0,
                }
            )
        return result

    def fetch_open_orders(self):
        return []

    def is_source_exhausted(self, symbol):
        return self._bar_counts[symbol] >= self._slot_count

    def poll_bar(self, symbol):
        with self._bar_condition:
            index = self._bar_counts[symbol]
            if index >= self._slot_count:
                return None
            deadline = time.monotonic() + 30.0
            while index > self._allowed_index and not self._source_stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("synthetic bar gate timed out")
                self._bar_condition.wait(remaining)
            if self._source_stopped:
                return None
            self._bar_counts[symbol] += 1
            return dict(self._bars[symbol][index])

    def freeze_after_factor_ready(self):
        with self._bar_condition:
            if not self._factor_ready:
                self._factor_ready = True
                consumed = min(self._bar_counts.values(), default=0)
                self._allowed_index = consumed - 1
                self._bar_condition.notify_all()

    def advance_one_bar(self):
        with self._bar_condition:
            self._allowed_index += 1
            self._bar_condition.notify_all()

    def finish_bar_source(self):
        with self._bar_condition:
            self._allowed_index = self._slot_count - 1
            self._bar_condition.notify_all()

    def stop_bar_source(self):
        with self._bar_condition:
            self._source_stopped = True
            self._bar_condition.notify_all()

    def poll_tick(self, symbol):
        return self._ticks.pop(symbol, None)

    def publish_tick(self, symbol, sequence, event_time):
        from backtrader.events import TickEvent

        received_at = datetime.now(_UTC)
        event_time = min(event_time, received_at)
        tick = TickEvent(
            timestamp=event_time.timestamp(),
            symbol=symbol,
            exchange="DCE",
            price=100.0,
            volume=1.0,
            bid_price=99.0,
            ask_price=101.0,
            bid_volume=5.0,
            ask_volume=6.0,
            exchange_time=event_time.timestamp(),
            received_wall_time=received_at.timestamp(),
            sequence=sequence,
            snapshot_or_delta="snapshot",
            continuity_status="continuous",
            stale=False,
            source="fixture-ctp-provider-leaf",
            event_id="iteration50-execution-%s-%d" % (symbol, sequence),
            coalesced_count=1,
        )
        tick.instrument_id = symbol
        tick.exchange_id = "DCE"
        tick.trading_day = self._trading_day
        tick.connection_generation = self._connection_generation
        tick.stream_generation = self._connection_generation
        tick.ingest_seq = sequence
        self._ticks[symbol] = tick

    def get_query_session_scope(self):
        return SimpleNamespace(
            issuer=self._query_issuer,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            trading_day=self._trading_day,
            read_only_ready=True,
        )

    def get_session_state(self):
        return {
            "account_fingerprint": self._account_fingerprint,
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "trading_ready": self.is_trading_ready,
            "front_id": self._front_id,
            "session_id": self._session_id,
        }

    def get_execution_gate_state(self):
        return dict(self._gate_state)

    def arm_execution_for_registered_sim(self, *, instrument_id, **kwargs):
        del kwargs
        self._gate_state = {
            "managed": True,
            "armed": True,
            "instrument": instrument_id,
            "authorized_instruments": [instrument_id],
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "scope_version": "ctp-contract-bundle-v1",
            "proof_sha256": "c" * 64,
            "environment_profile": "fixture_only",
            "revocation_reason": None,
        }
        return object(), dict(self._gate_state)

    def next_order_ref(self):
        self._native_order_ref += 1
        return str(self._native_order_ref)

    def _next_request(self):
        self._native_request_id += 1
        return self._native_request_id

    def submit_order_insert(self, field, request_id, *, execution_capability):
        _require(execution_capability is not None, "native insert lacked wrapper capability")
        self.native_calls.append(
            ("insert", field.InstrumentID, field.ExchangeID, field.OrderRef, request_id)
        )
        return 0

    def submit_order_action(self, field, request_id, *, execution_capability):
        _require(execution_capability is not None, "native cancel lacked wrapper capability")
        self.native_calls.append(
            ("cancel", field.InstrumentID, field.ExchangeID, field.OrderRef, request_id)
        )
        return 0

    def _query_result(self, request_type, family, *, filters=()):
        self._request_id += 1
        started = datetime.now(_UTC)
        mono_started = time.monotonic()
        rows = self._query_rows.get(family, [])
        if family == "instrument_margin_rate_result":
            instrument = filters.get("instrument_id")
            exchange = filters.get("exchange_id")
            rows = [
                row
                for row in rows
                if row.get("InstrumentID") == instrument and row.get("ExchangeID") == exchange
            ]
        rows = [dict(row) for row in rows]
        completed = datetime.now(_UTC)
        mono_completed = time.monotonic()
        digest = hashlib.sha256(
            json.dumps(
                rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        source = SimpleNamespace(
            issuer=self._query_issuer,
            request_type=request_type,
            request_id=self._request_id,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            trading_day=self._trading_day,
            started_at_utc=started,
            completed_at_utc=completed,
            started_monotonic=mono_started,
            completed_monotonic=mono_completed,
            trusted_expires_monotonic=mono_completed + 30.0,
            records_sha256=digest,
            explicit_request_filters=tuple(filters.get("source_filters", ())),
        )
        return SimpleNamespace(
            request_type=request_type,
            request_id=self._request_id,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            started_at_utc=started,
            completed_at_utc=completed,
            is_last_seen=True,
            error_code=None,
            error_message="",
            timed_out=False,
            complete=True,
            records=tuple(rows),
            late_callback_count=0,
            unsupported=False,
            submit_code=0,
            query_source=source,
        )

    def _query(self, request_type, family, **filters):
        source_filters = ("HedgeFlag",) if family == "instrument_margin_rate_result" else ()
        return self._query_result(
            request_type,
            family,
            filters={**filters, "source_filters": source_filters},
        )

    def query_account_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("account", "account_result", **filters)

    def query_positions_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("positions", "positions_result", **filters)

    def query_orders_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("orders", "orders_result", **filters)

    def query_trades_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("trades", "trades_result", **filters)

    def query_instruments_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("instruments", "instruments_result", **filters)

    def query_instrument_margin_rate_result(self, *, timeout=5.0, **filters):
        del timeout
        return self._query("margin_rate", "instrument_margin_rate_result", **filters)

    def _register_order(self, payload):
        instrument = payload.get("instrument_id") or payload.get("symbol")
        order_ref = str(payload.get("order_ref") or self.reserve_registered_sim_order_ref())
        request_id = self._next_request()
        field = SimpleNamespace(
            InstrumentID=instrument,
            ExchangeID=payload["exchange_id"],
            OrderRef=order_ref,
            RequestID=request_id,
            FrontID=self._front_id,
            SessionID=self._session_id,
            OrderSysID="",
        )
        self._send_native_order_insert(field, request_id)
        self._order_identity[order_ref] = {
            "instrument": instrument,
            "exchange": payload["exchange_id"],
            "side": str(payload["side"]).lower(),
            "offset": str(payload.get("offset") or "open").lower(),
            "size": abs(int(payload["size"])),
            "front_id": self._front_id,
            "session_id": self._session_id,
        }
        self._provider_order_rows[order_ref] = self._order_row(
            order_ref, status="3", filled=0, remaining=abs(int(payload["size"]))
        )
        self._query_rows["orders_result"] = list(self._provider_order_rows.values())
        return {
            "status": "accepted",
            "id": order_ref,
            "order_ref": order_ref,
            "front_id": self._front_id,
            "session_id": self._session_id,
            "exchange_id": payload["exchange_id"],
        }

    def submit_order(self, payload):
        return self._register_order(payload)

    def cancel_order(self, order_ref, dataname=None):
        del dataname
        identity = self._order_identity[str(order_ref)]
        request_id = self._next_request()
        field = SimpleNamespace(
            InstrumentID=identity["instrument"],
            ExchangeID=identity["exchange"],
            OrderRef=str(order_ref),
            OrderSysID="",
            FrontID=identity["front_id"],
            SessionID=identity["session_id"],
            RequestID=request_id,
        )
        self._send_native_order_action(field, request_id)
        return {
            "status": "accepted",
            "id": str(order_ref),
            "order_ref": str(order_ref),
            "front_id": identity["front_id"],
            "session_id": identity["session_id"],
            "exchange_id": identity["exchange"],
        }

    def _order_row(self, order_ref, *, status, filled, remaining):
        identity = self._order_identity[str(order_ref)]
        side = identity["side"]
        return {
            "OrderRef": str(order_ref),
            "InstrumentID": identity["instrument"],
            "ExchangeID": identity["exchange"],
            "OrderStatus": status,
            "Direction": "0" if side == "buy" else "1",
            "CombOffsetFlag": "0" if identity["offset"] == "open" else "1",
            "VolumeTotalOriginal": str(identity["size"]),
            "VolumeTraded": str(filled),
            "VolumeTotal": str(remaining),
            "FrontID": identity["front_id"],
            "SessionID": identity["session_id"],
            "TradingDay": self._trading_day,
        }

    def _trade_row(self, order_ref, trade_id, *, quantity, offset, when, fee):
        identity = self._order_identity[str(order_ref)]
        local_time = when.astimezone(timezone(timedelta(hours=8)))
        return {
            "TradeID": trade_id,
            "OrderRef": str(order_ref),
            "InstrumentID": identity["instrument"],
            "ExchangeID": identity["exchange"],
            "Direction": "0" if identity["side"] == "buy" else "1",
            "OffsetFlag": "0" if offset == "open" else "1",
            "HedgeFlag": "1",
            "Volume": str(quantity),
            "Price": "100",
            "Commission": str(fee),
            "TradeDate": local_time.strftime("%Y%m%d"),
            "TradeTime": local_time.strftime("%H:%M:%S.%f"),
            "TradingDay": self._trading_day,
        }

    def _position_row(self, instrument, exchange, *, quantity):
        side = "2" if quantity > 0 else "3"
        quantity = abs(int(quantity))
        return {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "PosiDirection": side,
            "HedgeFlag": "1",
            "PositionDate": "1",
            "TradingDay": self._trading_day,
            "Position": str(quantity),
            "TodayPosition": str(quantity),
            "YdPosition": "0",
            "LongFrozen": "0",
            "ShortFrozen": "0",
            "CombLongFrozen": "0",
            "CombShortFrozen": "0",
            "StrikeFrozen": "0",
            "AbandonFrozen": "0",
            "LongFrozenAmount": "0",
            "ShortFrozenAmount": "0",
            "FrozenMargin": "0",
            "FrozenCash": "0",
            "FrozenCommission": "0",
            "StrikeFrozenAmount": "0",
            "YdStrikeFrozen": "0",
        }

    def observe_order(self, order_ref, *, ctp_status, filled, remaining):
        identity = self._order_identity[str(order_ref)]
        ctp_status = str(ctp_status)
        filled = int(filled)
        remaining = int(remaining)
        if filled < 0 or remaining < 0 or filled + remaining != identity["size"]:
            raise ValueError("synthetic CTP order volumes are inconsistent")
        normalized_status = {
            "0": "completed",
            "1": "partial",
            "3": "accepted",
            "5": "canceled",
        }.get(ctp_status)
        if normalized_status is None:
            raise ValueError("unsupported synthetic CTP order status")
        if (
            (ctp_status == "0" and remaining != 0)
            or (ctp_status == "1" and (filled == 0 or remaining == 0))
            or (ctp_status == "3" and (filled != 0 or remaining == 0))
            or (ctp_status == "5" and remaining == 0)
        ):
            raise ValueError("synthetic CTP order status and volumes are inconsistent")
        details = self._order_row(
            order_ref,
            status=ctp_status,
            filled=filled,
            remaining=remaining,
        )
        self._provider_order_rows[str(order_ref)] = details
        self._query_rows["orders_result"] = list(self._provider_order_rows.values())
        self._provider_events.append(
            {
                "kind": "order",
                "order_ref": str(order_ref),
                "ctp_status": ctp_status,
                "normalized_status": normalized_status,
                "filled": filled,
                "remaining": remaining,
            }
        )
        self._update_queue.append(
            {
                "kind": "order",
                "order_ref": str(order_ref),
                "data_name": identity["instrument"],
                "instrument": identity["instrument"],
                "exchange_id": identity["exchange"],
                "front_id": identity["front_id"],
                "session_id": identity["session_id"],
                "status": normalized_status,
                "side": identity["side"],
                "offset": identity["offset"],
                "price": 100.0,
                "size": identity["size"],
                "filled": filled,
                "remaining": remaining,
                "details": details,
            }
        )

    def observe_trade_fill(self, order_ref, trade_id, *, quantity, offset, when, fee):
        identity = self._order_identity[str(order_ref)]
        quantity = int(quantity)
        fee = float(fee)
        if quantity <= 0 or offset != identity["offset"] or not math.isfinite(fee):
            raise ValueError("synthetic CTP trade fields do not match the order")
        details = self._trade_row(
            order_ref, trade_id, quantity=quantity, offset=offset, when=when, fee=fee
        )
        self._provider_trade_rows.append(details)
        self._query_rows["trades_result"] = list(self._provider_trade_rows)
        self._provider_commission += fee
        self._provider_available = _EXECUTION_STARTING_AVAILABLE - self._provider_commission
        self._query_rows["account_result"] = [
            {"Available": str(self._provider_available), "CurrMargin": "0"}
        ]
        self._provider_events.append(
            {
                "kind": "trade",
                "trade_id": str(trade_id),
                "order_ref": str(order_ref),
                "quantity": quantity,
                "offset": offset,
                "fee": fee,
            }
        )
        position_key = (identity["instrument"], identity["exchange"])
        position_delta = quantity if identity["side"] == "buy" else -quantity
        self._provider_position_quantities[position_key] += position_delta
        self._query_rows["positions_result"] = [
            self._position_row(instrument, exchange, quantity=net)
            for (instrument, exchange), net in sorted(self._provider_position_quantities.items())
            if net
        ]
        self._update_queue.append(
            {
                "kind": "trade",
                "trade_id": trade_id,
                "order_ref": str(order_ref),
                "data_name": identity["instrument"],
                "instrument": identity["instrument"],
                "exchange_id": identity["exchange"],
                "side": identity["side"],
                "offset": offset,
                "price": 100.0,
                "size": quantity,
                "fee": fee,
                "timestamp": when.isoformat(),
                "details": details,
            }
        )

    def poll_broker_update(self):
        return self._update_queue.popleft() if self._update_queue else None


class _ExecutionStrategy(_CaptureStrategy):
    params = (
        _CaptureStrategy.params._gettuple()
        if hasattr(_CaptureStrategy.params, "_gettuple")
        else _CaptureStrategy.params
    ) + (("execution_state", None),)

    def start(self):
        self.p.execution_state["started"].set()

    def nextstart(self):
        self._execution_next()

    def next(self):
        self._execution_next()

    def notify_order(self, order):
        super().notify_order(order)
        state = self.p.execution_state
        status = order.getstatusname()
        state["order_notifications"].append(
            {
                "status": status,
                "executed_size": float(order.executed.size or 0.0),
                "executed_price": float(order.executed.price or 0.0),
                "executed_commission": float(order.executed.comm or 0.0),
                "cancel_acknowledged": bool(order.info.get("cancel_acknowledged", False)),
            }
        )
        if status == "Partial":
            state["partial_notification"].set()
        if order.info.get("cancel_acknowledged") is True:
            state["cancel_ack_notification"].set()
        if status == "Canceled":
            state["terminal_cancel_notification"].set()
        if status == "Completed" and order.info.get("factor_position_effect") == "CLOSE":
            state["close_completed_notification"].set()

    def notify_trade(self, trade):
        self.p.execution_state["trade_notifications"].append(
            {
                "just_opened": bool(trade.justopened),
                "closed": bool(trade.isclosed),
                "size": float(trade.size or 0.0),
                "pnlcomm": float(trade.pnlcomm or 0.0),
            }
        )
        if trade.isclosed:
            self.p.execution_state["closed_trade_notification"].set()

    def _execution_next(self):
        from backtrader.order import Order
        from backtrader.stores.execution_decision_journal import (
            ExecutionDecisionKey,
            ExecutionIntentKey,
        )

        self._capture_complete_batch()
        state = self.p.execution_state
        state["last_snapshot"] = self.last_snapshot
        if self.last_snapshot is not None and not state["factor_ready"].is_set():
            factor = self.last_snapshot.factors.get("alpha003")
            if (
                str(getattr(self.last_snapshot.readiness, "value", self.last_snapshot.readiness))
                == "LIVE_READY"
                and factor is not None
                and all(math.isfinite(float(point.value)) for point in factor.values.values())
                and any(abs(float(point.value)) > 1e-12 for point in factor.values.values())
            ):
                state["api"].freeze_after_factor_ready()
                state["factor_ready"].set()

        command = state.get("command")
        if not command or command == state.get("consumed_command"):
            return
        state["consumed_command"] = command
        coordinator = state["coordinator"]
        snapshot = self.last_snapshot
        batch = state["cohort"].current_batch()
        if command == "OPEN":
            _require(snapshot is not None and batch is not None, "OPEN has no live cohort snapshot")
            factor = snapshot.factors.get("alpha003")
            _require(factor is not None, "OPEN has no production Alpha003 output")
            available = [
                (target, point)
                for target, point in factor.values.items()
                if point.status == "OUTPUT_AVAILABLE" and math.isfinite(float(point.value))
            ]
            _require(available, "OPEN has no finite Alpha003 route output")
            target, point = max(available, key=lambda item: abs(float(item[1].value)))
            side = "BUY" if float(point.value) >= 0.0 else "SELL"
            data = next(data for data in self.datas if data._name == target)
            facts = state["open_facts"]
            economics = {
                "instrument": target,
                "exchange": "DCE",
                "side": side,
                "position_effect": "OPEN",
                "quantity": "2",
                "limit_price": "100",
                "offset": "open",
                "factor_stop_price": "95" if side == "BUY" else "105",
                "risk_policy_id": "alpha003-installed-fixture-v1",
                "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "200"},
                "entry_grid_ordinal": 1,
                "batch_id": batch.batch_id,
                "price": "100",
            }
            key = ExecutionDecisionKey(
                account_scope=_EXECUTION_ACCOUNT,
                strategy_scope=_EXECUTION_SCOPE,
                logical_run_id=state["logical_run_id"],
                cohort_id=batch.cohort_id,
                close_time=batch.close_time.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_GRID",
            )
            intent = ExecutionIntentKey(
                action="SUBMIT",
                instrument=target,
                side=side,
                position_effect="OPEN",
                leg=0,
            )
            with coordinator.decision_scope(
                owner=self,
                key=key,
                economic_payload={"intent_economics": (economics,)},
                intent_keys=(intent,),
                batch=batch,
                snapshot=snapshot,
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=1,
            ) as decision:
                state["open_order"] = (
                    self.buy(
                        data=data,
                        size=2,
                        price=100,
                        exectype=Order.Limit,
                        instrument_id=target,
                        exchange_id="DCE",
                        factor_position_effect="OPEN",
                        factor_strategy_scope=_EXECUTION_SCOPE,
                        offset="open",
                    )
                    if side == "BUY"
                    else self.sell(
                        data=data,
                        size=2,
                        price=100,
                        exectype=Order.Limit,
                        instrument_id=target,
                        exchange_id="DCE",
                        factor_position_effect="OPEN",
                        factor_strategy_scope=_EXECUTION_SCOPE,
                        offset="open",
                    )
                )
            state["selected_target"] = target
            state["open_side"] = side
            state["decision_ids"].append(decision.decision_id)
            state["open_sent"].set()
        elif command == "PARTIAL_CHECK":
            order = state["open_order"]
            _require(order is not None and order.alive(), "partial order is not still alive")
            _require(abs(float(order.executed.size)) == 1.0, "partial fill quantity changed")
            state["partial_bar"].set()
        elif command == "CANCEL":
            order = state["open_order"]
            facts = state["cancel_facts"]
            _require(order is not None and facts.order_cancel_ready, "cancel facts are not ready")
            key = _risk_key(facts, state["logical_run_id"])
            intent = ExecutionIntentKey(
                action="CANCEL",
                instrument=state["selected_target"],
                side=state["open_side"],
                position_effect="OPEN",
                leg=0,
            )
            economics = {
                "instrument": state["selected_target"],
                "exchange": "DCE",
                "side": state["open_side"],
                "position_effect": "OPEN",
                "owner_intent_id": order.info.get("factor_intent_id"),
                "reason": "installed fixture partial remainder cancel",
            }
            with coordinator.risk_decision_scope(
                owner=self,
                key=key,
                economic_payload={"intent_economics": (economics,)},
                intent_keys=(intent,),
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=1,
            ) as decision:
                self.cancel(order)
            cancel_intent_id = order.info.get("factor_cancel_intent_id")
            _require(cancel_intent_id, "ordinary Broker cancel has no durable cancel intent")
            state["cancel_intent_id"] = cancel_intent_id
            state["decision_ids"].append(decision.decision_id)
            state["cancel_sent"].set()
        elif command == "CANCEL_ACK_CHECK":
            order = state["open_order"]
            _require(order is not None and order.alive(), "cancel acknowledgement ended order")
            _require(order.info.get("cancel_acknowledged") is True, "cancel ACK was not observed")
            state["cancel_ack_bar"].set()
        elif command == "TERMINAL_CANCEL_CHECK":
            order = state["open_order"]
            _require(
                order is not None and order.status == Order.Canceled, "terminal cancel missing"
            )
            _require(not order.alive(), "terminal canceled order remains alive")
            state["terminal_cancel_bar"].set()
        elif command == "CLOSE":
            order = state["open_order"]
            facts = state["close_facts"]
            _require(facts.risk_reduction_ready, "close risk facts are not ready")
            side = "SELL" if state["open_side"] == "BUY" else "BUY"
            data = next(data for data in self.datas if data._name == state["selected_target"])
            owner_intent_id = order.info.get("factor_intent_id")
            economics = {
                "instrument": state["selected_target"],
                "exchange": "DCE",
                "side": side,
                "position_effect": "CLOSE",
                "quantity": "1",
                "limit_price": "100",
                "offset": "close",
                "owner_intent_id": owner_intent_id,
                "owner_position_effect": "OPEN",
                "owner_side": state["open_side"],
                "entry_grid_ordinal": 1,
            }
            intent = ExecutionIntentKey(
                action="SUBMIT",
                instrument=state["selected_target"],
                side=side,
                position_effect="CLOSE",
                leg=0,
            )
            with coordinator.risk_decision_scope(
                owner=self,
                key=_risk_key(facts, state["logical_run_id"]),
                economic_payload={"intent_economics": (economics,)},
                intent_keys=(intent,),
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=0,
            ) as decision:
                state["close_order"] = (
                    self.buy(
                        data=data,
                        size=1,
                        price=100,
                        exectype=Order.Limit,
                        instrument_id=state["selected_target"],
                        exchange_id="DCE",
                        factor_position_effect="CLOSE",
                        factor_strategy_scope=_EXECUTION_SCOPE,
                        factor_owner_side=state["open_side"],
                        factor_owner_position_effect="OPEN",
                        offset="close",
                    )
                    if side == "BUY"
                    else self.sell(
                        data=data,
                        size=1,
                        price=100,
                        exectype=Order.Limit,
                        instrument_id=state["selected_target"],
                        exchange_id="DCE",
                        factor_position_effect="CLOSE",
                        factor_strategy_scope=_EXECUTION_SCOPE,
                        factor_owner_side=state["open_side"],
                        factor_owner_position_effect="OPEN",
                        offset="close",
                    )
                )
            state["decision_ids"].append(decision.decision_id)
            state["close_sent"].set()
        elif command == "CLOSE_CHECK":
            order = state["close_order"]
            _require(
                order is not None and order.status == Order.Completed, "close fill not completed"
            )
            position = self.broker.execution_position_snapshot(order.data)
            _require(position.quantity == 0, "actual Broker position is not flat after close")
            state["close_bar"].set()


def _risk_key(facts, logical_run_id):
    from backtrader.stores.execution_decision_journal import ExecutionDecisionKey

    return ExecutionDecisionKey(
        account_scope=_EXECUTION_ACCOUNT,
        strategy_scope=_EXECUTION_SCOPE,
        logical_run_id=logical_run_id,
        cohort_id="iteration50-execution-risk-cohort",
        close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_RISK_REDUCTION",
    )


def _wait_execution_event(state, name, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not state[name].wait(min(0.05, max(0.0, deadline - time.monotonic()))):
        error = state.get("error")
        if error is not None:
            raise RuntimeError(
                "installed execution engine failed: " + type(error).__name__
            ) from error
        if time.monotonic() >= deadline:
            api = state.get("api")
            progress = (
                {
                    "bars": dict(api._bar_counts),
                    "allowed_index": api._allowed_index,
                    "source_stopped": api._source_stopped,
                    "snapshot": _execution_snapshot_diagnostic(state.get("last_snapshot")),
                }
                if api is not None
                else {}
            )
            raise RuntimeError(
                "installed execution profile timed out at %s; progress=%r" % (name, progress)
            )


def _execution_snapshot_diagnostic(snapshot):
    if snapshot is None:
        return None
    factors = {}
    for name, factor in snapshot.factors.items():
        factors[name] = {
            target: {
                "status": str(getattr(point.status, "value", point.status)),
                "reason": str(getattr(point.reason, "value", point.reason)),
                "value_finite": math.isfinite(float(point.value)),
            }
            for target, point in factor.values.items()
        }
    return {
        "readiness": str(getattr(snapshot.readiness, "value", snapshot.readiness)),
        "close_time": snapshot.close_time.isoformat(),
        "factors": factors,
    }


def _refresh_execution_facts(store, broker, targets, api, sequence, coordinator):
    from backtrader.stores.factor_execution_facts import (
        project_factor_execution_facts,
        refresh_factor_execution_queries,
    )

    receipt = refresh_factor_execution_queries(
        store,
        targets=targets,
        timeout=4.0,
        overall_timeout=20.0,
    )
    _require(
        not receipt.blockers and not receipt.pending_families, "execution source query incomplete"
    )
    for target in targets:
        api.publish_tick(target.instrument, sequence, receipt.completed_at)
        consumed = store.poll_tick(target.instrument)
        _require(consumed is not None, "registered Store did not consume a synthetic tick")
        _require(consumed.source == "ctp-native-live", "Store-owned tick source was not stamped")
    now = datetime.now(_UTC)
    facts = project_factor_execution_facts(
        store,
        broker,
        targets=targets,
        account_scope=_EXECUTION_ACCOUNT,
        strategy_scope=_EXECUTION_SCOPE,
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=30),
        query_set=receipt.query_set,
    )
    return receipt, facts


def _run_execution_mode(mode: str) -> Dict[str, Any]:
    from backtrader.stores.execution_decision_journal import (
        ExecutionDecisionJournal,
    )
    from backtrader.stores.factor_execution import FactorExecutionCoordinator
    from backtrader.stores.factor_execution_facts import FactorExecutionTarget
    from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper

    class ExecutionApi(RegisteredSimWrapper, _ExecutionProviderLeaf):
        pass

    _require(mode in {"native", "build"}, "execution profile requires one Alpha003 mode")
    slot_count = 24
    now = datetime.now(_UTC).replace(second=0, microsecond=0)
    first_close = now - timedelta(minutes=slot_count - 1)
    bars, calendar = _fixture_bars(
        slot_count,
        varied_stream=False,
        first_close=first_close,
    )
    clock = _ReplayClock(calendar.slots[0].close_time)
    api = ExecutionApi(
        registered_sim_allow_writes=True,
        bars=bars,
        slot_count=slot_count,
    )
    api.live_tick_provenance = {"source": "fixture-ctp-provider-leaf"}
    store = RegisteredSimStore(
        allow_writes=True,
        provider="ctp",
        backend="direct",
        api=api,
        live_tick_provenance={"source": "fixture-ctp-provider-leaf"},
        preserve_raw_bars=True,
    )
    broker = store.getbroker(
        cash=100_000.0,
        market_data_only=False,
        validation_enabled=False,
        cash_check_enabled=False,
        force_refresh_queries=False,
        position_sync_policy="startup",
        flatten_on_stop=False,
        contract_metadata={
            target: {"instrument_id": target, "exchange_id": "DCE"} for target in _TARGETS
        },
    )
    cohort = LiveBarCohort(
        "iteration50-installed-execution-" + mode,
        calendar,
        max_pending_slots=2,
        max_window_bars=slot_count,
        wait_timeout_ns=2_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    cerebro.setbroker(broker)
    feeds = {}
    targets = []
    for index, target in enumerate(_TARGETS):
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
        _require(type(feed) is BtApiFeed, "execution Store did not create exact BtApiFeed")
        feeds[target] = feed
        cerebro.adddata(feed, name=target)
        declared = _FIELDS
        cohort.register_member(
            "member-" + target,
            feed,
            instrument=target,
            source_ref="store-feed-" + target,
            line_fields=declared,
            raw_fields=declared,
            numeric_fields=declared,
        )
        targets.append(FactorExecutionTarget("asset-%d" % index, target, "DCE", feed))

    plan = LiveFactorPlan(
        plan_id="iteration50-installed-execution-alpha003-" + mode,
        targets=_TARGETS,
        groups=dict.fromkeys(_TARGETS, "portfolio"),
        factors={
            "alpha003": FactorSpec(
                name="alpha003",
                indicator=get_alpha(3),
                panel_line="factor",
                mode=mode,
                field_bindings={"open": "feed:target:open", "volume": "feed:target:volume"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=10,
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=slot_count,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=0.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    journal_dir = tempfile.TemporaryDirectory(prefix="iteration50-execution-journal-")
    journal_path = str(Path(journal_dir.name) / "decisions.sqlite3")
    journal_limits = {
        "max_pending_intents": 128,
        "max_pending_callbacks": 64,
        "max_payload_bytes": 65_536,
        "max_decision_records": 16,
        "settlement_decision_reserve_records": 8,
        "max_decision_bytes": 65_536,
        "settlement_decision_reserve_bytes": 32_768,
    }
    journal = ExecutionDecisionJournal(journal_path, **journal_limits)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_EXECUTION_ACCOUNT,
        strategy_scope=_EXECUTION_SCOPE,
        logical_run_id="iteration50-installed-execution-" + mode,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=4,
    )
    state = {
        name: threading.Event()
        for name in (
            "started",
            "factor_ready",
            "open_sent",
            "partial_notification",
            "partial_bar",
            "cancel_sent",
            "cancel_ack_notification",
            "cancel_ack_bar",
            "terminal_cancel_notification",
            "terminal_cancel_bar",
            "close_sent",
            "close_completed_notification",
            "closed_trade_notification",
            "close_bar",
            "engine_done",
        )
    }
    state.update(
        {
            "api": api,
            "coordinator": coordinator,
            "cohort": cohort,
            "logical_run_id": "iteration50-installed-execution-" + mode,
            "command": None,
            "consumed_command": None,
            "open_facts": None,
            "cancel_facts": None,
            "close_facts": None,
            "open_order": None,
            "close_order": None,
            "selected_target": None,
            "open_side": None,
            "decision_ids": [],
            "order_notifications": [],
            "trade_notifications": [],
            "error": None,
            "result": None,
            "last_snapshot": None,
        }
    )
    cerebro.addstrategy(
        _ExecutionStrategy,
        cohort=cohort,
        plan=plan,
        profile="alpha003",
        alpha_ids=(),
        warmup_required_bars=0,
        first_evaluation_close_time=None,
        execution_state=state,
    )

    def run_engine():
        try:
            state["result"] = cerebro.run(runonce=False, preload=False)
        except BaseException as error:
            state["error"] = error
            api.stop_bar_source()
        finally:
            state["engine_done"].set()

    engine = threading.Thread(target=run_engine, name="iteration50-installed-execution")
    engine.start()
    receipts = []
    try:
        _wait_execution_event(state, "started")
        _wait_execution_event(state, "factor_ready")
        initial_receipt, initial_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 1, coordinator
        )
        templates = {
            (target, "DCE"): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": hashlib.sha256(
                    ("iteration50-installed:" + target).encode("utf-8")
                ).hexdigest(),
                "execution_cycle_id": "cycle-" + target,
                "preflight_sha256": "b" * 64,
            }
            for target in _TARGETS
        }
        store.registered_sim_configure_arm_templates(templates)
        initial_receipt, initial_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 2, coordinator
        )
        receipts.append(initial_receipt)
        _require(
            initial_facts.open_risk_ready,
            "armed execution facts are not open-risk ready: " + ",".join(initial_facts.blockers),
        )
        state["open_facts"] = initial_facts
        state["command"] = "OPEN"
        api.advance_one_bar()
        _wait_execution_event(state, "open_sent")

        opening = state["open_order"]
        _require(opening is not None and opening.alive(), "opening order was not accepted")
        order_ref = str(opening.info.get("external_order_ref") or "")
        _require(
            order_ref in api._order_identity,
            "opening order has no provider identity: order=%r provider_refs=%r"
            % (dict(opening.info), tuple(api._order_identity)),
        )
        open_when = datetime.now(_UTC)
        api.observe_trade_fill(
            order_ref,
            "iteration50-open-fill-1",
            quantity=1,
            offset="open",
            when=open_when,
            fee=1.25,
        )
        api.observe_order(order_ref, ctp_status="1", filled=1, remaining=1)
        state["command"] = "PARTIAL_CHECK"
        api.advance_one_bar()
        _wait_execution_event(state, "partial_bar")
        _require(
            state["partial_notification"].is_set(), "Broker omitted partial order notification"
        )
        _require(
            abs(float(opening.executed.size)) == 1.0
            and math.isfinite(float(opening.executed.comm)),
            "Broker partial fill economics are not finite",
        )

        partial_receipt, cancel_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 3, coordinator
        )
        receipts.append(partial_receipt)
        coordinator.reconcile_trade_observations(cancel_facts)
        partial_receipt, cancel_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 4, coordinator
        )
        receipts.append(partial_receipt)
        coordinator.reconcile_trade_observations(cancel_facts)
        _require(cancel_facts.order_cancel_ready, "partial-order cancellation facts are not ready")
        state["cancel_facts"] = cancel_facts
        state["command"] = "CANCEL"
        api.advance_one_bar()
        _wait_execution_event(state, "cancel_sent")
        _require(opening.alive(), "cancel acknowledgement incorrectly terminated order")
        _require(opening.info.get("cancel_acknowledged") is True, "native cancel ACK is absent")
        _require(
            any(item[0] == "cancel" for item in api.native_calls),
            "ordinary Broker cancel did not reach the registered native wrapper",
        )

        state["command"] = "CANCEL_ACK_CHECK"
        api.advance_one_bar()
        _wait_execution_event(state, "cancel_ack_bar")
        _require(opening.alive(), "order ended before a separate terminal callback")
        api.observe_order(order_ref, ctp_status="5", filled=1, remaining=1)
        state["command"] = "TERMINAL_CANCEL_CHECK"
        api.advance_one_bar()
        _wait_execution_event(state, "terminal_cancel_bar")
        _require(
            state["terminal_cancel_notification"].is_set(),
            "Broker omitted terminal cancel notification",
        )

        terminal_receipt, terminal_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 5, coordinator
        )
        receipts.append(terminal_receipt)
        coordinator.reconcile_trade_observations(terminal_facts)
        terminal_result = coordinator.reconcile_terminal_order_observations(
            terminal_facts,
            refresh_receipt=terminal_receipt,
        )
        _require(
            terminal_result.items
            and all(item.status == "RESOLVED" for item in terminal_result.items),
            "terminal CTP order observation was not reconciled",
        )
        close_receipt, close_facts = _refresh_execution_facts(
            store, broker, tuple(targets), api, 6, coordinator
        )
        receipts.append(close_receipt)
        coordinator.reconcile_trade_observations(close_facts)
        _require(close_facts.risk_reduction_ready, "close risk facts are not ready")
        state["close_facts"] = close_facts
        state["command"] = "CLOSE"
        api.advance_one_bar()
        _wait_execution_event(state, "close_sent")

        close_order = state["close_order"]
        _require(close_order is not None and close_order.alive(), "close order was not dispatched")
        close_ref = str(close_order.info.get("external_order_ref") or "")
        _require(close_ref in api._order_identity, "close order has no provider identity")
        close_when = datetime.now(_UTC)
        api.observe_trade_fill(
            close_ref,
            "iteration50-close-fill-1",
            quantity=1,
            offset="close",
            when=close_when,
            fee=0.75,
        )
        api.observe_order(close_ref, ctp_status="0", filled=1, remaining=0)
        state["command"] = "CLOSE_CHECK"
        api.advance_one_bar()
        _wait_execution_event(state, "close_bar")
        _require(
            state["close_completed_notification"].is_set(), "Broker omitted close notification"
        )
        _require(
            state["closed_trade_notification"].is_set(), "Broker omitted closed Trade notification"
        )

        settlement_queries = {
            "account": api.query_account_result(),
            "orders": api.query_orders_result(),
            "trades": api.query_trades_result(),
            "positions": api.query_positions_result(),
        }
        _require(
            all(
                result.complete and result.error_code is None
                for result in settlement_queries.values()
            ),
            "provider settlement query did not complete",
        )

        api.finish_bar_source()
        _wait_execution_event(state, "engine_done")
        engine.join(timeout=5.0)
        _require(not engine.is_alive(), "ordinary Cerebro execution thread did not stop")
        if state["error"] is not None:
            raise RuntimeError(
                "ordinary Cerebro execution failed: " + type(state["error"]).__name__
            ) from state["error"]
        _require(
            len(state["result"]) == 1, "ordinary Cerebro returned an unexpected Strategy count"
        )
        strategy = state["result"][0]
        _require(
            strategy.last_snapshot is not None, "execution Strategy captured no factor snapshot"
        )
        _require(
            len(state["decision_ids"]) == 3, "expected OPEN/CANCEL/CLOSE decisions were not durable"
        )
        _require(len(api.native_calls) == 3, "unexpected registered native insert/cancel count")
        _require(
            broker.execution_position_snapshot(close_order.data).quantity == 0,
            "final ordinary Broker position is not flat",
        )

        open_signed_size = 1.0 if state["open_side"] == "BUY" else -1.0
        close_signed_size = -open_signed_size
        open_fill = _validate_order_execution_fill(
            opening,
            label="OPEN",
            expected_size=open_signed_size,
            expected_price=100.0,
            expected_commission=1.25,
            expected_pnl=0.0,
            expected_opened=open_signed_size,
            expected_closed=0.0,
            expected_opened_commission=1.25,
            expected_closed_commission=0.0,
        )
        close_fill = _validate_order_execution_fill(
            close_order,
            label="CLOSE",
            expected_size=close_signed_size,
            expected_price=100.0,
            expected_commission=0.75,
            expected_pnl=0.0,
            expected_opened=0.0,
            expected_closed=close_signed_size,
            expected_opened_commission=0.0,
            expected_closed_commission=0.75,
        )

        trade_notifications = state["trade_notifications"]
        opened_trades = [row for row in trade_notifications if row["just_opened"]]
        closed_trades = [row for row in trade_notifications if row["closed"]]
        _require(len(opened_trades) == 1, "Broker did not emit exactly one opened Trade")
        _require(len(closed_trades) == 1, "Broker did not emit exactly one closed Trade")
        _require(
            math.isclose(opened_trades[0]["size"], open_signed_size, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(opened_trades[0]["pnlcomm"], -1.25, rel_tol=0.0, abs_tol=1e-12),
            "opened Trade does not match the Broker OPEN fill and fee",
        )
        _require(
            math.isclose(closed_trades[0]["size"], 0.0, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(closed_trades[0]["pnlcomm"], -2.0, rel_tol=0.0, abs_tol=1e-12),
            "closed Trade net PnL does not match both provider commissions",
        )

        account_rows = tuple(settlement_queries["account"].records)
        trade_rows = tuple(settlement_queries["trades"].records)
        order_rows = tuple(settlement_queries["orders"].records)
        position_rows = tuple(settlement_queries["positions"].records)
        expected_available = (
            _EXECUTION_STARTING_AVAILABLE - open_fill["commission"] - close_fill["commission"]
        )
        _require(len(account_rows) == 1, "provider account query returned an unexpected row count")
        provider_available = float(account_rows[0]["Available"])
        broker_balance_projection = api.get_balance()
        _require(
            math.isclose(provider_available, expected_available, rel_tol=0.0, abs_tol=1e-9)
            and math.isclose(
                float(broker_balance_projection["cash"]),
                provider_available,
                rel_tol=0.0,
                abs_tol=1e-9,
            ),
            "provider Available does not reflect the Broker fill commissions",
        )
        _require(
            math.isclose(
                float(broker_balance_projection["value"]),
                provider_available,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and float(account_rows[0]["CurrMargin"]) == 0.0,
            "synthetic account query and balance projection differ",
        )
        _require(
            len(trade_rows) == 2,
            "provider trade query does not contain both actual Broker fill references",
        )
        trade_rows_by_order = {str(row["OrderRef"]): row for row in trade_rows}
        _require(
            set(trade_rows_by_order) == {order_ref, close_ref},
            "provider trade query order references differ from the Broker orders",
        )
        for ref, expected_fee, expected_offset, expected_direction in (
            (
                order_ref,
                open_fill["commission"],
                "0",
                "0" if state["open_side"] == "BUY" else "1",
            ),
            (
                close_ref,
                close_fill["commission"],
                "1",
                "1" if state["open_side"] == "BUY" else "0",
            ),
        ):
            row = trade_rows_by_order[ref]
            _require(
                int(row["Volume"]) == 1
                and math.isclose(float(row["Price"]), 100.0, rel_tol=0.0, abs_tol=1e-12)
                and math.isclose(float(row["Commission"]), expected_fee, rel_tol=0.0, abs_tol=1e-12)
                and row["OffsetFlag"] == expected_offset
                and row["Direction"] == expected_direction,
                "provider trade query differs from actual Broker execution bits for %s" % ref,
            )
        order_rows_by_ref = {str(row["OrderRef"]): row for row in order_rows}
        _require(
            set(order_rows_by_ref) == {order_ref, close_ref}
            and order_rows_by_ref[order_ref]["OrderStatus"] == "5"
            and int(order_rows_by_ref[order_ref]["VolumeTraded"]) == 1
            and int(order_rows_by_ref[order_ref]["VolumeTotal"]) == 1
            and order_rows_by_ref[close_ref]["OrderStatus"] == "0"
            and int(order_rows_by_ref[close_ref]["VolumeTraded"]) == 1
            and int(order_rows_by_ref[close_ref]["VolumeTotal"]) == 0,
            "provider order query differs from the observed Broker lifecycle",
        )
        _require(not position_rows, "provider position query did not return the settled flat book")
        _require(not api.connected and not store.is_connected, "Store/API did not close normally")
        _require(
            set(api.subscriptions) == set(_TARGETS),
            "production Store did not subscribe the complete Alpha003 cohort",
        )
        decision_rows = [journal.decision(decision_id) for decision_id in state["decision_ids"]]
        _require(all(row is not None for row in decision_rows), "journal lost a decision row")
        intent_ids = [
            opening.info["factor_intent_id"],
            state["cancel_intent_id"],
            close_order.info["factor_intent_id"],
        ]
        journal_snapshot = journal.decision_capacity_snapshot()
        journal.close()
        reopened = ExecutionDecisionJournal(journal_path, **journal_limits)
        try:
            replayed = [reopened.decision(decision_id) for decision_id in state["decision_ids"]]
            intent_rows = [reopened.intent(intent_id) for intent_id in intent_ids]
            _require(all(row is not None for row in replayed), "journal reopen lost decisions")
            _require(
                all(row is not None and row.state == "KNOWN" for row in intent_rows),
                "journal reopen lost known intents",
            )
            _require(
                intent_rows[1].key.action == "CANCEL"
                and intent_rows[1].owner_intent_id == intent_rows[0].intent_id,
                "durable cancel intent lost its opening-order owner link",
            )
            reopened_snapshot = reopened.decision_capacity_snapshot()
        finally:
            reopened.close()
        point = strategy.last_snapshot.factors["alpha003"].values[state["selected_target"]]
        _require(math.isfinite(float(point.value)), "selected Alpha003 output is not finite")
        return {
            "mode": mode,
            "evidence_level": "INSTALLED_SYNTHETIC_REGISTERED_SIM_EXECUTION_FIXTURE_ONLY",
            "ordinary_cerebro": True,
            "exact_feed_type": type(feeds[_TARGETS[0]]).__name__,
            "factor": {
                "name": "alpha003",
                "mode": mode,
                "selected_instrument": state["selected_target"],
                "selected_side": state["open_side"],
                "selected_value": float(point.value),
                "readiness": str(
                    getattr(
                        strategy.last_snapshot.readiness, "value", strategy.last_snapshot.readiness
                    )
                ),
                "close_time": strategy.last_snapshot.close_time.isoformat(),
            },
            "provider_dispatches": [list(item) for item in api.native_calls],
            "provider_observations": {
                "events": list(api._provider_events),
                "orders": [
                    {
                        "order_ref": row["OrderRef"],
                        "ctp_status": row["OrderStatus"],
                        "filled": int(row["VolumeTraded"]),
                        "remaining": int(row["VolumeTotal"]),
                    }
                    for row in order_rows
                ],
                "trades": [
                    {
                        "trade_id": row["TradeID"],
                        "order_ref": row["OrderRef"],
                        "quantity": int(row["Volume"]),
                        "price": float(row["Price"]),
                        "commission": float(row["Commission"]),
                    }
                    for row in trade_rows
                ],
                "positions": [
                    {
                        "instrument": row["InstrumentID"],
                        "direction": row["PosiDirection"],
                        "quantity": int(row["Position"]),
                    }
                    for row in position_rows
                ],
                "account": {
                    "available": provider_available,
                    "current_margin": float(account_rows[0]["CurrMargin"]),
                    "starting_available": _EXECUTION_STARTING_AVAILABLE,
                    "cumulative_commission": open_fill["commission"] + close_fill["commission"],
                    "projection": broker_balance_projection,
                    "model": "synthetic fee-only balance; margin and realized/unrealized PnL are not modeled",
                },
            },
            "order_notifications": state["order_notifications"],
            "trade_notifications": state["trade_notifications"],
            "orders": {
                "open": {
                    "intent_id": opening.info.get("factor_intent_id"),
                    "cancel_intent_id": state["cancel_intent_id"],
                    "final_status": opening.getstatusname(),
                    "filled_size": float(opening.executed.size),
                    "filled_price": float(opening.executed.price),
                    "fee": float(opening.executed.comm),
                    "execution_projection": open_fill,
                    "cancel_acknowledged": opening.info.get("cancel_acknowledged") is True,
                },
                "close": {
                    "intent_id": close_order.info.get("factor_intent_id"),
                    "final_status": close_order.getstatusname(),
                    "filled_size": float(close_order.executed.size),
                    "filled_price": float(close_order.executed.price),
                    "fee": float(close_order.executed.comm),
                    "execution_projection": close_fill,
                },
            },
            "final_position": str(broker.execution_position_snapshot(close_order.data).quantity),
            "journal": {
                "decision_count": len(replayed),
                "intent_count": len(intent_rows),
                "intent_actions": [row.key.action for row in intent_rows],
                "cancel_owner_intent_id": intent_rows[1].owner_intent_id,
                "capacity_before_close": {
                    name: getattr(journal_snapshot, name)
                    for name in (
                        "base_record_count",
                        "base_record_limit",
                        "settlement_record_count",
                        "settlement_record_limit",
                        "base_payload_bytes",
                        "base_payload_byte_limit",
                        "database_bytes",
                        "wal_bytes",
                        "physical_bytes",
                    )
                },
                "capacity_after_reopen": {
                    name: getattr(reopened_snapshot, name)
                    for name in (
                        "base_record_count",
                        "base_record_limit",
                        "settlement_record_count",
                        "settlement_record_limit",
                        "base_payload_bytes",
                        "base_payload_byte_limit",
                        "database_bytes",
                        "wal_bytes",
                        "physical_bytes",
                    )
                },
            },
            "query_refreshes": len(receipts),
            "store_disconnected": not api.connected and not store.is_connected,
            "provider_calls_are_fixture_only": True,
        }
    finally:
        api.stop_bar_source()
        if engine.is_alive():
            engine.join(timeout=5.0)
        if journal._connection is not None:
            journal.close()
        journal_dir.cleanup()


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
        choices=("read-only", "alpha101-stream", "execution"),
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
    if args.profile == "alpha101-stream" and args.factor_mode != "both":
        parser.error("alpha101-stream requires --factor-mode both for same-stream comparison")
    if not sys.flags.isolated:
        raise RuntimeError("installed profile must run under the isolated Python -I child")

    installed_identity, binding = _verify_installed_distribution(args.wheel, args.wheel_sha256)
    if args.profile == "alpha101-stream":
        results = [_run_alpha101_stream_profile()]
        binding["loaded_modules"] = _snapshot_loaded_package_modules(
            binding["install_root"],
            binding["record_hashes"],
            binding["wheel_payload_hashes"],
            previous=binding["loaded_modules"],
        )
    elif args.profile == "execution":
        requested = ("native", "build") if args.factor_mode == "both" else (args.factor_mode,)
        results = []
        for mode in requested:
            results.append(_run_execution_mode(mode))
            binding["loaded_modules"] = _snapshot_loaded_package_modules(
                binding["install_root"],
                binding["record_hashes"],
                binding["wheel_payload_hashes"],
                previous=binding["loaded_modules"],
            )
    else:
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
    if args.profile == "read-only" and len(results) == 2:
        native, build = results
        for target in _TARGETS:
            _require(
                math.isclose(
                    native["values"][target], build["values"][target], rel_tol=1e-9, abs_tol=1e-12
                ),
                "native/build Alpha003 outputs differ for " + target,
            )
    if args.profile == "execution" and len(results) == 2:
        native, build = results
        _require(
            native["factor"]["selected_instrument"] == build["factor"]["selected_instrument"]
            and native["factor"]["selected_side"] == build["factor"]["selected_side"]
            and math.isclose(
                native["factor"]["selected_value"],
                build["factor"]["selected_value"],
                rel_tol=1e-9,
                abs_tol=1e-12,
            ),
            "execution native/build Alpha003 route outputs differ",
        )
    print(
        json.dumps(
            {
                "status": "PASS_INSTALLED_WHEEL_PUBLIC_FIXTURE",
                "evidence_level": "INSTALLED_WHEEL_PUBLIC_FIXTURE_ONLY",
                "profile": args.profile,
                "execution_environment": _EXECUTION_ENVIRONMENT,
                "isolated_bytecode_cache": {
                    "fresh_isolated_cache_before_backtrader_import": (
                        _ISOLATED_BYTECODE_CACHE_PREFIX is not None
                    ),
                },
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
