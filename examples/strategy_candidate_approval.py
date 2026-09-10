"""Verify a 012 strategy candidate's offline demo-approval receipt.

This module is example admission policy. It is deliberately outside both
Backtrader core and ``bt_api_py``: the private signing key, candidate manifest,
and provenance closure bind a particular strategy release rather than a venue
protocol or general execution session.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urlparse

APPROVAL_ALGORITHM = "Ed25519"
APPROVAL_KEY_ID = "iter21-demo-approval-ed25519-2026-09"
APPROVAL_PUBLIC_KEY_SHA256 = "2563eac8a40505f80903dd2659fe8667cafd3b8d0d5290db6620d4b3293e8f98"
CANONICAL_MANIFEST_RELATIVE_PATH = "examples/strategy-candidate-manifest.json"

# This is deliberately an explicit transitive dependency allowlist. Demo
# approval binds the engine/order/commission path, framework bridge, paper
# execution path, SDK execution/normalization contracts, and the two venue
# plugins used by the examples. Unrelated dirty repository files stay outside
# the approval fingerprint.
RUNTIME_SOURCE_MODULES = (
    ("backtrader.package_api", "backtrader", "backtrader"),
    ("backtrader.cerebro", "backtrader.cerebro", "backtrader"),
    ("backtrader.strategy", "backtrader.strategy", "backtrader"),
    ("backtrader.order", "backtrader.order", "backtrader"),
    ("backtrader.comminfo", "backtrader.comminfo", "backtrader"),
    ("backtrader.parameters", "backtrader.parameters", "backtrader"),
    ("backtrader.metabase", "backtrader.metabase", "backtrader"),
    ("backtrader.lineroot", "backtrader.lineroot", "backtrader"),
    ("backtrader.linebuffer", "backtrader.linebuffer", "backtrader"),
    ("backtrader.lineseries", "backtrader.lineseries", "backtrader"),
    ("backtrader.lineiterator", "backtrader.lineiterator", "backtrader"),
    ("backtrader.dataseries", "backtrader.dataseries", "backtrader"),
    ("backtrader.channel", "backtrader.channel", "backtrader"),
    ("backtrader.trade", "backtrader.trade", "backtrader"),
    ("backtrader.sizer", "backtrader.sizer", "backtrader"),
    ("backtrader.trade_logger", "backtrader.observers.trade_logger", "backtrader"),
    ("backtrader.broker_base", "backtrader.broker", "backtrader"),
    ("backtrader.feed_base", "backtrader.feed", "backtrader"),
    ("backtrader.position", "backtrader.position", "backtrader"),
    ("backtrader.position_modes", "backtrader.position_modes", "backtrader"),
    ("backtrader.events", "backtrader.events", "backtrader"),
    ("backtrader.store", "backtrader.stores.btapistore", "backtrader"),
    ("backtrader.live_store", "backtrader.stores.livestore", "backtrader"),
    ("backtrader.feed", "backtrader.feeds.btapifeed", "backtrader"),
    ("backtrader.live_feed", "backtrader.feeds.livefeed", "backtrader"),
    ("backtrader.broker", "backtrader.brokers.btapibroker", "backtrader"),
    ("backtrader.tickbroker", "backtrader.brokers.tickbroker", "backtrader"),
    ("backtrader.mixbroker", "backtrader.brokers.mixbroker", "backtrader"),
    ("backtrader.hft_package", "backtrader.brokers.hft", "backtrader"),
    ("backtrader.hft_exchange", "backtrader.brokers.hft.exchange", "backtrader"),
    ("backtrader.hft_queue", "backtrader.brokers.hft.queue", "backtrader"),
    ("backtrader.hft_latency", "backtrader.brokers.hft.latency", "backtrader"),
    ("backtrader.hft_matching", "backtrader.brokers.hft.matching_core", "backtrader"),
    ("backtrader.hft_recorder", "backtrader.brokers.hft.recorder", "backtrader"),
    ("backtrader.hft_state", "backtrader.brokers.hft.state", "backtrader"),
    (
        "examples.strategy_candidate_approval",
        "examples.strategy_candidate_approval",
        "backtrader",
    ),
    ("bt_api_py.package_api", "bt_api_py", "bt_api_py"),
    ("bt_api_py.public_api", "bt_api_py.bt_api", "bt_api_py"),
    ("bt_api_py.cross_venue", "bt_api_py.cross_venue", "bt_api_py"),
    ("bt_api_py.execution_session", "bt_api_py._execution_session", "bt_api_py"),
    ("bt_api_py.normalization", "bt_api_py._normalization", "bt_api_py"),
    ("bt_api_py.feed_adapter", "bt_api_py._feed_adapter", "bt_api_py"),
    ("bt_api_py.direct_backend", "bt_api_py._direct_backend", "bt_api_py"),
    ("bt_api_py.operation_backend", "bt_api_py._operation_backend", "bt_api_py"),
    ("bt_api_py.plugin_catalog", "bt_api_py._plugin_catalog", "bt_api_py"),
    ("bt_api_py.contract_models", "bt_api_py._contracts.models", "bt_api_py"),
    ("bt_api_py.contract_errors", "bt_api_py._contracts.errors", "bt_api_py"),
    ("bt_api_py.position_mapper", "bt_api_py._venue_mappers._position", "bt_api_py"),
    ("bt_api_py.okx_mapper", "bt_api_py._venue_mappers.okx", "bt_api_py"),
    ("bt_api_py.binance_mapper", "bt_api_py._venue_mappers.binance", "bt_api_py"),
    ("bt_api_py.balance_manager", "bt_api_py.balance_manager", "bt_api_py"),
    ("bt_api_py.data_downloader", "bt_api_py.data_downloader", "bt_api_py"),
    ("bt_api_base.event_bus", "bt_api_base.event_bus", "bt_api_base"),
    ("bt_api_base.exceptions", "bt_api_base.exceptions", "bt_api_base"),
    ("bt_api_base.logging", "bt_api_base.logging_factory", "bt_api_base"),
    ("bt_api_base.plugin_loader", "bt_api_base.plugins.loader", "bt_api_base"),
    ("bt_api_base.registry", "bt_api_base.registry", "bt_api_base"),
    ("bt_api_base.gateway_registrar", "bt_api_base.gateway.registrar", "bt_api_base"),
    ("bt_api_base.gateway_base", "bt_api_base.gateway.adapters.base", "bt_api_base"),
    (
        "bt_api_base.plugin_adapter",
        "bt_api_base.gateway.adapters.plugin_adapter",
        "bt_api_base",
    ),
    ("bt_api_okx.plugin", "bt_api_okx.plugin", "bt_api_okx"),
    ("bt_api_okx.registration", "bt_api_okx.registry_registration", "bt_api_okx"),
    ("bt_api_okx.environment", "bt_api_okx.environment", "bt_api_okx"),
    ("bt_api_okx.gateway", "bt_api_okx.gateway.adapter", "bt_api_okx"),
    ("bt_api_okx.market_ws", "bt_api_okx.feeds.live_okx.market_wss_base", "bt_api_okx"),
    ("bt_api_okx.request", "bt_api_okx.feeds.live_okx.request_base", "bt_api_okx"),
    ("bt_api_okx.swap", "bt_api_okx.feeds.live_okx.swap", "bt_api_okx"),
    ("bt_api_okx.orderbook", "bt_api_okx.containers.orderbooks.okx_orderbook", "bt_api_okx"),
    ("bt_api_okx.order", "bt_api_okx.containers.orders.okx_order", "bt_api_okx"),
    ("bt_api_binance.plugin", "bt_api_binance.plugin", "bt_api_binance"),
    (
        "bt_api_binance.registration",
        "bt_api_binance.registry_registration",
        "bt_api_binance",
    ),
    ("bt_api_binance.environment", "bt_api_binance.environment", "bt_api_binance"),
    ("bt_api_binance.client", "bt_api_binance.client", "bt_api_binance"),
    ("bt_api_binance.gateway", "bt_api_binance.gateway.adapter", "bt_api_binance"),
    ("bt_api_binance.market_ws", "bt_api_binance.feeds.market_wss_base", "bt_api_binance"),
    ("bt_api_binance.request", "bt_api_binance.feeds.request_base", "bt_api_binance"),
    ("bt_api_binance.execution", "bt_api_binance.feeds.rest_trade", "bt_api_binance"),
    ("bt_api_binance.swap", "bt_api_binance.feeds.swap", "bt_api_binance"),
    ("bt_api_binance.normalization", "bt_api_binance.feeds.normalize", "bt_api_binance"),
    (
        "bt_api_binance.orderbook",
        "bt_api_binance.containers.orderbooks.binance_orderbook",
        "bt_api_binance",
    ),
    ("bt_api_binance.order", "bt_api_binance.containers.orders.binance_order", "bt_api_binance"),
    (
        "bt_api_binance.websocket_adapter",
        "bt_api_binance.websocket.exchange_adapters",
        "bt_api_binance",
    ),
)


def write_private_json_report(path: Path, payload: Mapping[str, Any]) -> Path:
    """Atomically persist a runtime report with owner-only permissions."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GIT_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class DemoApprovalVerificationError(ValueError):
    """Raised when a demo approval receipt cannot be trusted."""


def canonical_json_bytes(value) -> bytes:
    """Return the one canonical JSON representation used for hashes/signatures."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value) -> str:
    """Hash a value using the approval canonical-JSON contract."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def manifest_binding_sha256(manifest: Mapping) -> str:
    """Bind a manifest while excluding only attachable approval pointers.

    ``demo_approval`` is excluded so an offline signer can approve the frozen
    manifest before the receipt path/hash is attached.  All other fields,
    including candidate fingerprints and evidence, remain in the binding.
    """

    if not isinstance(manifest, Mapping):
        raise DemoApprovalVerificationError("manifest must be a JSON object")
    binding = dict(manifest)
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        raise DemoApprovalVerificationError("manifest candidates must be a list")
    bound_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise DemoApprovalVerificationError("manifest candidate must be a JSON object")
        bound_candidates.append(
            {key: value for key, value in candidate.items() if key != "demo_approval"}
        )
    binding["candidates"] = bound_candidates
    return canonical_sha256(binding)


def _file_sha256(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DemoApprovalVerificationError(f"{label} runtime source is unavailable") from exc


def _module_artifact(module_name: str) -> Path:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise DemoApprovalVerificationError(
            f"required runtime module is unavailable: {module_name}"
        ) from exc
    origin = None if spec is None else spec.origin
    if not origin or origin in {"built-in", "frozen"}:
        raise DemoApprovalVerificationError(
            f"required runtime module has no verifiable artifact: {module_name}"
        )
    path = Path(origin).resolve()
    if not path.is_file():
        raise DemoApprovalVerificationError(
            f"required runtime module has no verifiable artifact: {module_name}"
        )
    return path


def _distribution_direct_url(distribution_name: str) -> Mapping:
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise DemoApprovalVerificationError(
            f"required runtime distribution is unavailable: {distribution_name}"
        ) from exc
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return {}
    return _read_json_object(raw.encode("utf-8"), f"{distribution_name} direct_url.json")


def _checkout_contains_distribution_source(root: Path, distribution_name: str) -> bool:
    """Require a matching import package before binding a wheel to a checkout.

    A wheel archive can be stored below any repository's .git directory. Its
    location alone is not evidence that that checkout built the package.
    """

    package = distribution_name.replace("-", "_")
    candidates = (
        root / package / "__init__.py",
        root / "src" / package / "__init__.py",
        root / "bt_api" / distribution_name / package / "__init__.py",
        root / "bt_api" / distribution_name / "src" / package / "__init__.py",
    )
    return any(candidate.is_file() for candidate in candidates)


def _local_distribution_root(distribution_name: str) -> Optional[Path]:
    direct_url = _distribution_direct_url(distribution_name)
    raw_url = direct_url.get("url")
    if not isinstance(raw_url, str):
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme != "file":
        return None
    if parsed.netloc not in {"", "localhost"}:
        return None
    path = Path(unquote(parsed.path)).resolve()
    if path.is_dir():
        return path
    if not path.is_file():
        return None

    archive = direct_url.get("archive_info")
    hashes = archive.get("hashes") if isinstance(archive, Mapping) else None
    expected_sha256 = hashes.get("sha256") if isinstance(hashes, Mapping) else None
    if not isinstance(expected_sha256, str) or _SHA256_RE.fullmatch(expected_sha256) is None:
        legacy_hash = archive.get("hash") if isinstance(archive, Mapping) else None
        expected_sha256 = (
            legacy_hash.removeprefix("sha256=")
            if isinstance(legacy_hash, str) and legacy_hash.startswith("sha256=")
            else None
        )
    if not isinstance(expected_sha256, str) or _SHA256_RE.fullmatch(expected_sha256) is None:
        raise DemoApprovalVerificationError(
            f"{distribution_name} wheel direct_url has no verifiable SHA-256"
        )
    if _file_sha256(path, f"{distribution_name} wheel") != expected_sha256:
        raise DemoApprovalVerificationError(
            f"{distribution_name} wheel direct_url hash does not match the archive"
        )

    # A locally built wheel may live below the checkout's .git directory.  Do
    # not ask Git to treat that directory as a work tree; locate the enclosing
    # checkout explicitly and then validate it through the ordinary Git path.
    for candidate in path.parents:
        if not (candidate / ".git").exists():
            continue
        if _git_root(candidate) == candidate and _checkout_contains_distribution_source(
            candidate, distribution_name
        ):
            return candidate
    return None


def _git_output(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DemoApprovalVerificationError("runtime Git provenance is unavailable") from exc
    value = result.stdout.strip()
    if not value:
        raise DemoApprovalVerificationError("runtime Git provenance is unavailable")
    return value


def _git_root(path: Path) -> Optional[Path]:
    try:
        return Path(_git_output(path, "rev-parse", "--show-toplevel")).resolve()
    except DemoApprovalVerificationError:
        return None


def _git_head_commit(path: Path, label: str) -> str:
    return _git_commit_value(_git_output(path, "rev-parse", "HEAD"), label)


def _git_commit_value(value, label: str) -> str:
    if not isinstance(value, str) or _GIT_COMMIT_RE.fullmatch(value) is None or set(value) == {"0"}:
        raise DemoApprovalVerificationError(f"{label} must be a full lowercase Git commit SHA")
    return value


def _distribution_commit(distribution_name: str, local_root: Optional[Path]) -> str:
    if local_root is not None:
        git_root = _git_root(local_root)
        if git_root is not None:
            return _git_head_commit(git_root, f"{distribution_name} commit")
    direct_url = _distribution_direct_url(distribution_name)
    vcs_info = direct_url.get("vcs_info")
    if isinstance(vcs_info, Mapping):
        return _git_commit_value(vcs_info.get("commit_id"), f"{distribution_name} commit")
    raise DemoApprovalVerificationError(
        f"{distribution_name} installed artifact has no verifiable Git commit"
    )


def _source_artifact(
    module_name: str,
    distribution_name: str,
    runtime_path: Path,
    local_root: Optional[Path],
) -> Path:
    runtime_git_root = _git_root(runtime_path.parent)
    if runtime_git_root is not None:
        return runtime_path
    if local_root is None:
        return runtime_path

    parts = module_name.split(".")
    suffix = Path(*parts)
    candidates = [
        local_root / suffix.with_suffix(".py"),
        local_root / "src" / suffix.with_suffix(".py"),
        local_root / "bt_api" / distribution_name / "src" / suffix.with_suffix(".py"),
    ]
    if runtime_path.name == "__init__.py":
        candidates = [
            local_root.joinpath(*parts) / "__init__.py",
            local_root.joinpath("src", *parts) / "__init__.py",
            local_root.joinpath("bt_api", distribution_name, "src", *parts) / "__init__.py",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise DemoApprovalVerificationError(
        f"{distribution_name} checkout does not contain bound source for {module_name}"
    )


def _validate_runtime_source_provenance(value: Mapping) -> dict:
    provenance = _mapping(value, "runtime_source")
    _exact_fields(
        provenance,
        {
            "schema_version",
            "repository_commits",
            "runtime_files",
            "source_files",
            "fingerprint_sha256",
        },
        "runtime_source",
    )
    if type(provenance.get("schema_version")) is not int or provenance["schema_version"] != 1:
        raise DemoApprovalVerificationError("runtime_source schema_version must be 1")

    commits = _mapping(provenance.get("repository_commits"), "runtime_source.repository_commits")
    _exact_fields(commits, {"backtrader", "bt_api_py"}, "runtime_source.repository_commits")
    commits = {
        "backtrader": _git_commit_value(commits.get("backtrader"), "runtime backtrader commit"),
        "bt_api_py": _git_commit_value(commits.get("bt_api_py"), "runtime bt_api_py commit"),
    }

    expected_labels = {label for label, _module, _distribution in RUNTIME_SOURCE_MODULES}
    files = {}
    for field in ("runtime_files", "source_files"):
        rows = _mapping(provenance.get(field), f"runtime_source.{field}")
        _exact_fields(rows, expected_labels, f"runtime_source.{field}")
        files[field] = {
            label: _sha256(rows.get(label), f"runtime_source.{field}.{label}")
            for label in sorted(expected_labels)
        }

    mismatched = [
        label
        for label in sorted(expected_labels)
        if files["runtime_files"][label] != files["source_files"][label]
    ]
    if mismatched:
        raise DemoApprovalVerificationError(
            "installed runtime does not match bound source: " + ",".join(mismatched)
        )

    normalized = {
        "schema_version": 1,
        "repository_commits": commits,
        "runtime_files": files["runtime_files"],
        "source_files": files["source_files"],
    }
    fingerprint = _sha256(provenance.get("fingerprint_sha256"), "runtime_source.fingerprint_sha256")
    if fingerprint != canonical_sha256(normalized):
        raise DemoApprovalVerificationError("runtime_source fingerprint does not match its content")
    normalized["fingerprint_sha256"] = fingerprint
    return normalized


def collect_runtime_source_provenance() -> dict:
    """Fingerprint the exact framework/SDK artifacts and their local sources.

    Absolute paths are intentionally omitted from the signed contract.  When a
    distribution was installed from a local checkout, both the installed file
    and the corresponding checkout file are hashed so dirty source cannot hide
    behind an older installed copy.
    """

    local_roots = {
        distribution: _local_distribution_root(distribution)
        for distribution in {row[2] for row in RUNTIME_SOURCE_MODULES}
    }
    runtime_files = {}
    source_files = {}
    backtrader_root = None
    runtime_distribution_roots = {}
    for label, module_name, distribution in RUNTIME_SOURCE_MODULES:
        runtime_path = _module_artifact(module_name)
        runtime_files[label] = _file_sha256(runtime_path, label)
        runtime_git_root = _git_root(runtime_path.parent)
        if runtime_git_root is not None:
            previous_root = runtime_distribution_roots.get(distribution)
            if previous_root is not None and previous_root != runtime_git_root:
                raise DemoApprovalVerificationError(
                    f"{distribution} runtime modules resolve to different Git checkouts"
                )
            runtime_distribution_roots[distribution] = runtime_git_root
        source_path = _source_artifact(
            module_name, distribution, runtime_path, local_roots[distribution]
        )
        if distribution == "backtrader":
            backtrader_root = runtime_git_root or local_roots[distribution]
        source_files[label] = _file_sha256(source_path, label)

    if backtrader_root is None:
        raise DemoApprovalVerificationError("backtrader runtime Git provenance is unavailable")
    bt_api_root = runtime_distribution_roots.get("bt_api_py") or local_roots.get("bt_api_py")
    commits = {
        "backtrader": _distribution_commit("backtrader", backtrader_root),
        "bt_api_py": _distribution_commit("bt_api_py", bt_api_root),
    }
    provenance = {
        "schema_version": 1,
        "repository_commits": commits,
        "runtime_files": dict(sorted(runtime_files.items())),
        "source_files": dict(sorted(source_files.items())),
    }
    provenance["fingerprint_sha256"] = canonical_sha256(provenance)
    return _validate_runtime_source_provenance(provenance)


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DemoApprovalVerificationError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_nonfinite_number(value):
    raise DemoApprovalVerificationError(f"non-finite JSON number: {value}")


def _read_json_object(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
    except DemoApprovalVerificationError:
        raise
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise DemoApprovalVerificationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DemoApprovalVerificationError(f"{label} must be a JSON object")
    return value


def _mapping(value, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise DemoApprovalVerificationError(f"{label} must be a JSON object")
    return value


def _exact_fields(value: Mapping, expected, label: str) -> None:
    actual = set(value)
    expected = set(expected)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise DemoApprovalVerificationError(f"{label} fields are invalid ({'; '.join(details)})")


def _sha256(value, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None or value == "0" * 64:
        raise DemoApprovalVerificationError(f"{label} must be a lowercase SHA-256")
    return value


def _positive_decimal_token(value, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DemoApprovalVerificationError(f"{label} must be a canonical decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DemoApprovalVerificationError(f"{label} must be a canonical decimal string") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise DemoApprovalVerificationError(f"{label} must be finite and positive")
    if value != format(parsed.normalize(), "f"):
        raise DemoApprovalVerificationError(f"{label} must be a canonical decimal string")
    return value


def _git_commit(value, label: str) -> str:
    return _git_commit_value(value, label)


def _utc_timestamp(value, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DemoApprovalVerificationError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DemoApprovalVerificationError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise DemoApprovalVerificationError(f"{label} must use UTC")
    return parsed


def _candidate_fingerprint(candidate: Mapping) -> str:
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }
    return canonical_sha256(payload)


def _load_public_key(path: Path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise DemoApprovalVerificationError(
            "Ed25519 approval verification requires cryptography; install backtrader[live]"
        ) from exc

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DemoApprovalVerificationError("demo approval trust root is unavailable") from exc
    try:
        public_key = serialization.load_pem_public_key(raw)
    except (TypeError, ValueError) as exc:
        raise DemoApprovalVerificationError("demo approval trust root is invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise DemoApprovalVerificationError("demo approval trust root is not an Ed25519 key")
    return public_key, raw


def _verify_candidate_evidence(candidate: Mapping) -> dict:
    if candidate.get("research_status") != "PASS":
        raise DemoApprovalVerificationError("demo requires research_status PASS")

    candidate_sha = _sha256(candidate.get("candidate_sha256"), "candidate_sha256")
    if candidate_sha != _candidate_fingerprint(candidate):
        raise DemoApprovalVerificationError("candidate fingerprint does not match manifest content")
    config_sha = _sha256(candidate.get("config_sha256"), "config_sha256")

    commits = _mapping(candidate.get("repository_commits"), "repository_commits")
    _exact_fields(commits, {"backtrader", "bt_api_py"}, "repository_commits")
    normalized_commits = {
        "backtrader": _git_commit(commits.get("backtrader"), "backtrader commit"),
        "bt_api_py": _git_commit(commits.get("bt_api_py"), "bt_api_py commit"),
    }

    oos = _mapping(candidate.get("oos"), "oos")
    if oos.get("status") != "OOS_PASS":
        raise DemoApprovalVerificationError("demo requires oos.status OOS_PASS")
    if oos.get("demo_pair_eligible") is not True:
        raise DemoApprovalVerificationError("demo requires oos.demo_pair_eligible true")
    normalized_oos = {
        "status": "OOS_PASS",
        "data_sha256": _sha256(oos.get("data_sha256"), "oos.data_sha256"),
        "report_sha256": _sha256(oos.get("report_sha256"), "oos.report_sha256"),
    }

    gates = _mapping(candidate.get("admission_gates"), "admission_gates")
    _exact_fields(gates, {"g4", "g5a"}, "admission_gates")
    g4 = _mapping(gates.get("g4"), "admission_gates.g4")
    _exact_fields(g4, {"status", "receipt_sha256"}, "admission_gates.g4")
    if g4.get("status") != "PASS":
        raise DemoApprovalVerificationError("demo requires admission_gates.g4.status PASS")
    normalized_g4 = {
        "status": "PASS",
        "receipt_sha256": _sha256(g4.get("receipt_sha256"), "admission_gates.g4.receipt_sha256"),
    }

    g5a = _mapping(gates.get("g5a"), "admission_gates.g5a")
    _exact_fields(
        g5a,
        {"status", "okx_receipt_sha256", "binance_receipt_sha256"},
        "admission_gates.g5a",
    )
    if g5a.get("status") != "PASS":
        raise DemoApprovalVerificationError("demo requires admission_gates.g5a.status PASS")
    normalized_g5a = {
        "status": "PASS",
        "okx_receipt_sha256": _sha256(
            g5a.get("okx_receipt_sha256"), "admission_gates.g5a.okx_receipt_sha256"
        ),
        "binance_receipt_sha256": _sha256(
            g5a.get("binance_receipt_sha256"),
            "admission_gates.g5a.binance_receipt_sha256",
        ),
    }
    return {
        "candidate_sha256": candidate_sha,
        "candidate_config_sha256": config_sha,
        "repository_commits": normalized_commits,
        "oos": normalized_oos,
        "g4": normalized_g4,
        "g5a": normalized_g5a,
    }


def verify_demo_approval(
    *,
    candidate: Mapping,
    manifest_path: Path,
    canonical_manifest_path: Path,
    trust_root_path: Path,
    expected_strategy_id: str,
    runtime_source: Mapping,
    expected_public_key_sha256: str = APPROVAL_PUBLIC_KEY_SHA256,
    now: Optional[datetime] = None,
) -> dict:
    """Verify a hash-bound, signed approval receipt for one demo candidate."""

    try:
        resolved_manifest = Path(manifest_path).resolve(strict=True)
        canonical_manifest = Path(canonical_manifest_path).resolve(strict=True)
    except OSError as exc:
        raise DemoApprovalVerificationError("canonical demo manifest is unavailable") from exc
    if resolved_manifest != canonical_manifest:
        raise DemoApprovalVerificationError("demo requires the canonical manifest path")

    try:
        manifest_raw = resolved_manifest.read_bytes()
    except OSError as exc:
        raise DemoApprovalVerificationError("canonical demo manifest is unavailable") from exc
    manifest = _read_json_object(manifest_raw, "manifest")
    matches = [
        row
        for row in manifest.get("candidates", [])
        if isinstance(row, Mapping) and row.get("strategy_id") == expected_strategy_id
    ]
    if len(matches) != 1 or dict(matches[0]) != dict(candidate):
        raise DemoApprovalVerificationError("candidate does not match the canonical manifest")
    if candidate.get("strategy_id") != expected_strategy_id:
        raise DemoApprovalVerificationError("approval strategy_id is invalid")

    evidence = _verify_candidate_evidence(candidate)
    runtime_source = _validate_runtime_source_provenance(runtime_source)
    if runtime_source["repository_commits"] != evidence["repository_commits"]:
        raise DemoApprovalVerificationError(
            "candidate repository_commits do not match the actual runtime revisions"
        )
    approval = _mapping(candidate.get("demo_approval"), "demo_approval")
    _exact_fields(approval, {"status", "receipt_path", "receipt_sha256"}, "demo_approval")
    if approval.get("status") != "STRATEGY_APPROVED_FOR_DEMO":
        raise DemoApprovalVerificationError("strategy has no STRATEGY_APPROVED_FOR_DEMO receipt")
    receipt_name = approval.get("receipt_path")
    if not isinstance(receipt_name, str) or not receipt_name.strip():
        raise DemoApprovalVerificationError("demo approval receipt path is missing")
    expected_receipt_sha = _sha256(approval.get("receipt_sha256"), "demo_approval.receipt_sha256")
    receipt_path = (resolved_manifest.parent / receipt_name).resolve()
    if (
        resolved_manifest.parent != receipt_path
        and resolved_manifest.parent not in receipt_path.parents
    ):
        raise DemoApprovalVerificationError("demo approval receipt must stay under examples")
    try:
        receipt_raw = receipt_path.read_bytes()
    except OSError as exc:
        raise DemoApprovalVerificationError("demo approval receipt is unavailable") from exc
    if hashlib.sha256(receipt_raw).hexdigest() != expected_receipt_sha:
        raise DemoApprovalVerificationError("demo approval receipt hash mismatch")
    receipt = _read_json_object(receipt_raw, "demo approval receipt")

    _exact_fields(
        receipt,
        {
            "schema_version",
            "status",
            "environment",
            "strategy_id",
            "candidate_sha256",
            "candidate_config_sha256",
            "repository_commits",
            "runtime_source",
            "constraints",
            "oos",
            "g4",
            "g5a",
            "manifest",
            "issued_at",
            "expires_at",
            "signature",
        },
        "demo approval receipt",
    )
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 3:
        raise DemoApprovalVerificationError("demo approval receipt schema_version must be 3")
    if receipt.get("status") != "STRATEGY_APPROVED_FOR_DEMO":
        raise DemoApprovalVerificationError("demo approval receipt status is invalid")
    if receipt.get("environment") != "demo":
        raise DemoApprovalVerificationError("demo approval receipt environment is invalid")
    if receipt.get("strategy_id") != expected_strategy_id:
        raise DemoApprovalVerificationError("demo approval receipt strategy_id is invalid")
    for field in (
        "candidate_sha256",
        "candidate_config_sha256",
        "repository_commits",
        "oos",
        "g4",
        "g5a",
    ):
        if receipt.get(field) != evidence[field]:
            raise DemoApprovalVerificationError(f"demo approval receipt {field} is not bound")
    receipt_runtime_source = _validate_runtime_source_provenance(receipt.get("runtime_source"))
    if receipt_runtime_source != runtime_source:
        raise DemoApprovalVerificationError(
            "demo approval receipt runtime_source does not match the actual runtime"
        )

    constraints = _mapping(receipt.get("constraints"), "receipt.constraints")
    _exact_fields(
        constraints,
        {
            "maximum_duration_seconds",
            "maximum_order_count",
            "maximum_quantity_base",
        },
        "receipt.constraints",
    )
    maximum_duration = Decimal(
        _positive_decimal_token(
            constraints.get("maximum_duration_seconds"),
            "receipt.constraints.maximum_duration_seconds",
        )
    )
    _positive_decimal_token(
        constraints.get("maximum_quantity_base"),
        "receipt.constraints.maximum_quantity_base",
    )
    maximum_order_count = constraints.get("maximum_order_count")
    if type(maximum_order_count) is not int or maximum_order_count <= 0:
        raise DemoApprovalVerificationError(
            "receipt.constraints.maximum_order_count must be a positive integer"
        )

    manifest_contract = _mapping(receipt.get("manifest"), "receipt.manifest")
    _exact_fields(manifest_contract, {"path", "binding_sha256"}, "receipt.manifest")
    if manifest_contract.get("path") != CANONICAL_MANIFEST_RELATIVE_PATH:
        raise DemoApprovalVerificationError("demo approval receipt manifest path is invalid")
    _sha256(manifest_contract.get("binding_sha256"), "receipt.manifest.binding_sha256")
    if manifest_contract["binding_sha256"] != manifest_binding_sha256(manifest):
        raise DemoApprovalVerificationError("demo approval receipt manifest binding is invalid")

    issued_at = _utc_timestamp(receipt.get("issued_at"), "issued_at")
    expires_at = _utc_timestamp(receipt.get("expires_at"), "expires_at")
    if issued_at >= expires_at:
        raise DemoApprovalVerificationError("demo approval receipt validity window is invalid")
    validity_seconds = Decimal(str((expires_at - issued_at).total_seconds()))
    if maximum_duration > validity_seconds:
        raise DemoApprovalVerificationError("receipt maximum duration exceeds its validity window")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DemoApprovalVerificationError("approval verification clock must be timezone-aware")
    checked_at = checked_at.astimezone(timezone.utc)
    if checked_at < issued_at:
        raise DemoApprovalVerificationError("demo approval receipt is not yet valid")
    if checked_at >= expires_at:
        raise DemoApprovalVerificationError("demo approval receipt is expired")

    signature_contract = _mapping(receipt.get("signature"), "receipt.signature")
    _exact_fields(
        signature_contract,
        {"algorithm", "key_id", "public_key_sha256", "value"},
        "receipt.signature",
    )
    if signature_contract.get("algorithm") != APPROVAL_ALGORITHM:
        raise DemoApprovalVerificationError("demo approval signature algorithm is invalid")
    if signature_contract.get("key_id") != APPROVAL_KEY_ID:
        raise DemoApprovalVerificationError("demo approval signature key_id is invalid")

    expected_public_key_sha256 = _sha256(
        expected_public_key_sha256, "expected approval public key fingerprint"
    )
    public_key, public_key_raw = _load_public_key(Path(trust_root_path))
    public_key_sha = hashlib.sha256(public_key_raw).hexdigest()
    if public_key_sha != expected_public_key_sha256:
        raise DemoApprovalVerificationError("demo approval trust root fingerprint is invalid")
    if signature_contract.get("public_key_sha256") != expected_public_key_sha256:
        raise DemoApprovalVerificationError("demo approval public key fingerprint is invalid")
    signature_value = signature_contract.get("value")
    if not isinstance(signature_value, str) or not signature_value:
        raise DemoApprovalVerificationError("demo approval signature is missing")
    try:
        signature = base64.b64decode(signature_value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise DemoApprovalVerificationError("demo approval signature is not valid base64") from exc
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != signature_value:
        raise DemoApprovalVerificationError("demo approval signature encoding is invalid")

    signed_payload = {key: value for key, value in receipt.items() if key != "signature"}
    try:
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:
        raise DemoApprovalVerificationError(
            "Ed25519 approval verification requires cryptography; install backtrader[live]"
        ) from exc
    try:
        public_key.verify(signature, canonical_json_bytes(signed_payload))
    except InvalidSignature as exc:
        raise DemoApprovalVerificationError("demo approval signature is invalid") from exc
    return receipt


__all__ = [
    "APPROVAL_ALGORITHM",
    "APPROVAL_KEY_ID",
    "APPROVAL_PUBLIC_KEY_SHA256",
    "CANONICAL_MANIFEST_RELATIVE_PATH",
    "DemoApprovalVerificationError",
    "RUNTIME_SOURCE_MODULES",
    "canonical_json_bytes",
    "canonical_sha256",
    "collect_runtime_source_provenance",
    "manifest_binding_sha256",
    "verify_demo_approval",
    "write_private_json_report",
]
