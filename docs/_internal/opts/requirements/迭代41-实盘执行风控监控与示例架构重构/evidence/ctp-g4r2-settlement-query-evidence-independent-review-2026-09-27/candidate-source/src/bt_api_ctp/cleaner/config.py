"""Load and validate the cleaner configuration (``cleaner.yaml``).

Configuration is *fail-closed*: an unknown key or an unknown backend is an
error rather than a warning.  A typo such as ``delete_remote_after_verifiy``
must not silently leave the safety guard at its default, and a typo in a host
name must not silently drop a shard from the pull list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: Transport backends the pull stage understands.
BACKENDS = ("rsync", "sftp", "local")

#: K-line periods, in minutes, the aggregator can produce (迭代06 FR-5).
SUPPORTED_PERIODS = (1, 5, 15)

_TOP_LEVEL_KEYS = {"tick_root", "kline_root", "pull", "kline", "calendar", "logging"}
_PULL_KEYS = {"delete_remote_after_verify", "staging_root", "hosts"}
_HOST_KEYS = {"name", "backend", "host", "remote_data_root", "port"}
_KLINE_KEYS = {"periods", "include_options"}
_CALENDAR_KEYS = {"holidays_file"}
_LOGGING_KEYS = {"dir", "file"}

_DEFAULT_HOST_PORT = 22


class ConfigError(ValueError):
    """The cleaner configuration is unusable."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class HostConfig:
    """One remote data source (a shard host).

    ``local`` treats ``remote_data_root`` as a local directory, which is what
    tests and one-off migrations use; ``rsync``/``sftp`` reach it over SSH.
    """

    name: str
    backend: str
    host: str = ""
    remote_data_root: str = ""
    port: int = _DEFAULT_HOST_PORT


@dataclass(frozen=True)
class CleanerConfig:
    """Resolved cleaner configuration; every path is absolute."""

    tick_root: Path
    kline_root: Path
    staging_root: Path
    manifest_path: Path
    report_dir: Path
    lock_path: Path
    log_dir: Path
    log_to_file: bool
    delete_remote_after_verify: bool
    hosts: tuple[HostConfig, ...]
    periods: tuple[int, ...]
    include_options: bool
    holidays_file: Path | None


def _unknown_keys(payload: dict[str, Any], allowed: set[str], where: str) -> list[str]:
    return [f"unknown key in {where}: {key!r}" for key in sorted(set(payload) - allowed)]


def _as_mapping(value: Any, where: str) -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        return {}, [f"{where} must be a mapping"]
    return value, []


def validate_config(payload: dict[str, Any]) -> list[str]:
    """Return human-readable problems with a raw cleaner config."""
    problems = _unknown_keys(payload, _TOP_LEVEL_KEYS, "config")

    if not payload.get("tick_root"):
        problems.append("tick_root is required")

    pull, pull_problems = _as_mapping(payload.get("pull"), "pull")
    problems.extend(pull_problems)
    problems.extend(_unknown_keys(pull, _PULL_KEYS, "pull"))

    hosts = pull.get("hosts")
    if not hosts:
        problems.append("pull.hosts must list at least one host")
    elif not isinstance(hosts, list):
        problems.append("pull.hosts must be a list")
    else:
        if "delete_remote_after_verify" in pull and not isinstance(
            pull["delete_remote_after_verify"], bool
        ):
            problems.append("pull.delete_remote_after_verify must be a boolean")
        seen: set[str] = set()
        for index, entry in enumerate(hosts):
            where = f"pull.hosts[{index}]"
            host, host_problems = _as_mapping(entry, where)
            problems.extend(host_problems)
            if host_problems:
                continue
            problems.extend(_unknown_keys(host, _HOST_KEYS, where))
            name = host.get("name")
            if not name:
                problems.append(f"{where}.name is required")
            elif name in seen:
                problems.append(f"duplicate host name: {name!r}")
            else:
                seen.add(str(name))
            backend = host.get("backend")
            if backend not in BACKENDS:
                problems.append(f"{where}.backend must be one of {BACKENDS}")
            if backend in ("rsync", "sftp") and not host.get("host"):
                problems.append(f"{where}.host is required for backend {backend!r}")
            if not host.get("remote_data_root"):
                problems.append(f"{where}.remote_data_root is required")
            port = host.get("port", _DEFAULT_HOST_PORT)
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                problems.append(f"{where}.port must be an integer in 1..65535")

    kline, kline_problems = _as_mapping(payload.get("kline"), "kline")
    problems.extend(kline_problems)
    problems.extend(_unknown_keys(kline, _KLINE_KEYS, "kline"))
    periods = kline.get("periods", list(SUPPORTED_PERIODS))
    if not isinstance(periods, list) or not periods:
        problems.append("kline.periods must be a non-empty list")
    else:
        for period in periods:
            if period not in SUPPORTED_PERIODS:
                problems.append(
                    f"kline.periods contains unsupported period {period!r}; "
                    f"only {SUPPORTED_PERIODS} are supported"
                )
    if "include_options" in kline and not isinstance(kline["include_options"], bool):
        problems.append("kline.include_options must be a boolean")

    calendar, calendar_problems = _as_mapping(payload.get("calendar"), "calendar")
    problems.extend(calendar_problems)
    problems.extend(_unknown_keys(calendar, _CALENDAR_KEYS, "calendar"))

    logging, logging_problems = _as_mapping(payload.get("logging"), "logging")
    problems.extend(logging_problems)
    problems.extend(_unknown_keys(logging, _LOGGING_KEYS, "logging"))

    return problems


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_dir / path


def _overlaps(left: Path, right: Path) -> bool:
    """Whether two local paths are equal or one contains the other."""
    left, right = left.resolve(), right.resolve()
    return left == right or left in right.parents or right in left.parents


def _local_host_conflicts(hosts: tuple[HostConfig, ...], root: Path, tick_root: Path) -> list[str]:
    """Reject a ``local`` host whose tree overlaps the authoritative tick tree.

    Reclaim deletes ``<remote_data_root>/<day>``.  If that path were the
    authoritative tree itself (or an ancestor of it), a correctly configured
    run would delete the data it just merged -- so this must fail at load time,
    not at delete time.
    """
    problems: list[str] = []
    for host in hosts:
        if host.backend != "local":
            continue
        remote = _resolve(root, host.remote_data_root)
        if _overlaps(remote, tick_root):
            problems.append(
                f"host {host.name!r}: local remote_data_root {remote} overlaps tick_root "
                f"{tick_root}; reclaim would delete the authoritative tree"
            )
    return problems


def load_config(path: Path | str, *, base_dir: Path | str | None = None) -> CleanerConfig:
    """Read and validate ``cleaner.yaml``.

    Relative paths resolve against ``base_dir`` (the repository root by
    convention, matching the collector's ``data_root`` handling).
    """
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError([f"cannot read config {config_path}: {error}"]) from error
    payload = yaml.safe_load(raw)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError(["cleaner config must be a mapping"])

    problems = validate_config(payload)
    if problems:
        raise ConfigError(problems)

    root = Path(base_dir) if base_dir is not None else Path.cwd()
    tick_root = _resolve(root, str(payload["tick_root"]))
    kline_root = _resolve(root, str(payload.get("kline_root") or tick_root / "kline"))

    pull = payload.get("pull") or {}
    cleaner_dir = tick_root / "cleaner"
    staging_root = _resolve(root, str(pull.get("staging_root") or cleaner_dir / "staging"))

    kline = payload.get("kline") or {}
    calendar = payload.get("calendar") or {}
    logging_cfg = payload.get("logging") or {}
    holidays = calendar.get("holidays_file") or None

    hosts = tuple(
        HostConfig(
            name=str(entry["name"]),
            backend=str(entry["backend"]),
            host=str(entry.get("host") or ""),
            remote_data_root=str(entry["remote_data_root"]),
            port=int(entry.get("port", _DEFAULT_HOST_PORT)),
        )
        for entry in pull["hosts"]
    )
    conflicts = _local_host_conflicts(hosts, root, tick_root)
    if conflicts:
        raise ConfigError(conflicts)

    return CleanerConfig(
        tick_root=tick_root,
        kline_root=kline_root,
        staging_root=staging_root,
        manifest_path=cleaner_dir / "manifest.json",
        report_dir=cleaner_dir / "reports",
        lock_path=cleaner_dir / "cleaner.lock",
        log_dir=_resolve(root, str(logging_cfg.get("dir") or tick_root / "logs")),
        log_to_file=bool(logging_cfg.get("file", True)),
        delete_remote_after_verify=bool(pull.get("delete_remote_after_verify", True)),
        hosts=hosts,
        periods=tuple(int(period) for period in kline.get("periods", SUPPORTED_PERIODS)),
        include_options=bool(kline.get("include_options", True)),
        holidays_file=_resolve(root, str(holidays)) if holidays else None,
    )


__all__ = [
    "BACKENDS",
    "SUPPORTED_PERIODS",
    "CleanerConfig",
    "ConfigError",
    "HostConfig",
    "load_config",
    "validate_config",
]
