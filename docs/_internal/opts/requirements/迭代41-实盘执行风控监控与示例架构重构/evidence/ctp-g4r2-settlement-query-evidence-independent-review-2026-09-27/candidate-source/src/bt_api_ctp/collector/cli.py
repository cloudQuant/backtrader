"""Command-line entry point for CTP tick collection.

Usage:
    python -m bt_api_ctp.collector --config collector.yaml --once --duration 60
    python -m bt_api_ctp.collector --config collector.yaml --check-calendar
    python -m bt_api_ctp.collector --config collector.yaml --validate-shards
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from bt_api_ctp.collector.engine import CollectionConfig, TickCollectionEngine
from bt_api_ctp.collector.health import HealthThresholds
from bt_api_ctp.collector.protocols import DEFAULT_ASSET_TYPES, EXCHANGES
from bt_api_ctp.collector.schedule import (
    TradingCalendar,
    group_index,
    group_length_seconds,
    next_open_group_index,
    seconds_until_close,
    seconds_until_next_open,
)
from bt_api_ctp.collector.shard import ShardConfig, ShardValidationReport
from bt_api_ctp.collector.sink import DEFAULT_COMPACT_SEGMENTS, SinkReport

EXIT_OK = 0
EXIT_SHARD_MISMATCH = 1
EXIT_CONFIG_ERROR = 2
EXIT_NOT_TRADING_DAY = 3
EXIT_COLLECTION_FAILED = 4

_STRATEGIES = ("by_exchange", "by_prefix", "hash_mod")

_logger = logging.getLogger(__name__)


class SessionClosedError(RuntimeError):
    """The requested moment is not inside any trading session."""


def resolve_duration(
    *,
    duration: float | None,
    until_close: bool,
    now: datetime | None = None,
    grace_sec: float = 300.0,
    wait_for_open: bool = False,
) -> float | None:
    """Decide how long this run should collect.

    ``until_close`` makes an externally scheduled run finish by itself at the
    end of the session group it was started in.  With ``wait_for_open`` a run
    started before the open (a scheduler fires at 08:45 for a 09:00 open)
    sleeps through the wait and still covers the whole session.
    """
    if not until_close:
        return duration
    moment = now or datetime.now()
    remaining = seconds_until_close(moment)
    if remaining is not None:
        return remaining + float(grace_sec)
    if not wait_for_open:
        raise SessionClosedError(moment.strftime("%Y-%m-%d %H:%M:%S"))
    wait = seconds_until_next_open(moment)
    group = next_open_group_index(moment)
    if wait is None or group is None:
        raise SessionClosedError(moment.strftime("%Y-%m-%d %H:%M:%S"))
    return wait + group_length_seconds(group) + float(grace_sec)


def load_config(path: Path | str) -> dict[str, Any]:
    """Read a YAML collector config."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("collector config must be a mapping")
    return payload


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return human-readable problems with a collector config."""
    errors: list[str] = []
    if not config.get("data_root"):
        errors.append("data_root is required")

    shard = config.get("shard") or {}
    strategy = shard.get("strategy", "by_exchange")
    if strategy not in _STRATEGIES:
        errors.append(f"unknown shard strategy: {strategy!r}")
    if strategy == "hash_mod":
        total = int(shard.get("total_shards", 1) or 1)
        shard_id = int(shard.get("shard_id", 0) or 0)
        if total < 1:
            errors.append("shard.total_shards must be >= 1")
        elif not 0 <= shard_id < total:
            errors.append("shard.shard_id must satisfy 0 <= shard_id < total_shards")

    overflow = (config.get("buffer") or {}).get("overflow_policy", "drop")
    if overflow not in ("drop", "flush"):
        errors.append(f"unknown buffer.overflow_policy: {overflow!r}")

    # `first` 模式已删除（整改方案 D16）：未知模式必须 fail-closed，
    # 否则写着 `tick_mode: first` 的旧配置会静默按 every 运行。
    tick_mode = str((config.get("logging") or {}).get("tick_mode", "every"))
    if tick_mode not in ("every", "off"):
        errors.append(f"unknown logging.tick_mode: {tick_mode!r} (only 'every' or 'off')")

    # 重连重订阅依赖分批 + 批间限速，参数必须有效（见整改方案 P1-3 契约）。
    subscription = config.get("subscription") or {}
    try:
        batch_size = int(subscription.get("batch_size", 100))
        batch_interval = float(subscription.get("batch_interval_sec", 0.1))
    except (TypeError, ValueError):
        errors.append("subscription.batch_size / batch_interval_sec must be numeric")
    else:
        if batch_size < 1:
            errors.append("subscription.batch_size must be >= 1")
        if batch_interval <= 0:
            errors.append("subscription.batch_interval_sec must be > 0")

    holidays_file = (config.get("calendar") or {}).get("holidays_file")
    if holidays_file and not Path(holidays_file).exists():
        errors.append(f"calendar.holidays_file not found: {holidays_file}")

    health = config.get("health") or {}
    unknown_health = set(health) - {
        "enabled",
        "min_ticks_per_interval",
        "stall_intervals",
        "silent_after_sec",
        "silent_share_alarm",
    }
    if unknown_health:
        errors.append(f"unknown health settings: {sorted(unknown_health)}")
    try:
        if int(health.get("min_ticks_per_interval", 1)) < 0:
            errors.append("health.min_ticks_per_interval must be >= 0")
        if int(health.get("stall_intervals", 2)) < 1:
            errors.append("health.stall_intervals must be >= 1")
        if float(health.get("silent_after_sec", 300.0)) <= 0:
            errors.append("health.silent_after_sec must be > 0")
        share = float(health.get("silent_share_alarm", 0.8))
        if not 0 < share <= 1:
            errors.append("health.silent_share_alarm must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("health thresholds must be numeric")

    # 健康守卫挂在高频心跳上；心跳关掉守卫就永远不会评估。
    heartbeat = float((config.get("buffer") or {}).get("heartbeat_interval_sec", 60.0))
    if health.get("enabled", True) and heartbeat <= 0:
        errors.append("health.enabled requires a positive buffer.heartbeat_interval_sec")

    return errors


def _shard_from_mapping(shard: dict[str, Any] | None, *, default_strategy: str) -> ShardConfig:
    payload = dict(shard or {})
    strategy = payload.pop("strategy", default_strategy)
    return ShardConfig(
        strategy=strategy,
        exchanges=tuple(payload.pop("exchanges", ()) or ()),
        prefixes=tuple(payload.pop("prefixes", ()) or ()),
        shard_id=int(payload.pop("shard_id", 0) or 0),
        total_shards=int(payload.pop("total_shards", 1) or 1),
    )


def build_collection_config(config: dict[str, Any]) -> CollectionConfig:
    """Translate the YAML payload into a ``CollectionConfig``."""
    shard_payload = config.get("shard") or {}
    if shard_payload.get("strategy", "by_exchange") == "by_exchange" and not shard_payload.get(
        "exchanges"
    ):
        # An unconfigured exchange shard means the whole market.
        shard = ShardConfig(strategy="by_exchange", exchanges=EXCHANGES)
    else:
        shard = _shard_from_mapping(shard_payload, default_strategy="by_exchange")

    buffer_payload = config.get("buffer") or {}
    sink_payload = config.get("sink") or {}
    logging_payload = config.get("logging") or {}
    asset_types = tuple(config.get("asset_types") or DEFAULT_ASSET_TYPES)
    health_payload = dict(config.get("health") or {})
    health_enabled = bool(health_payload.pop("enabled", True))

    return CollectionConfig(
        data_root=config["data_root"],
        shard=shard,
        asset_types=asset_types,
        per_instrument_cap=int(buffer_payload.get("per_instrument_cap", 100_000)),
        overflow_policy=str(buffer_payload.get("overflow_policy", "drop")),
        flush_interval_sec=float(buffer_payload.get("flush_interval_sec", 5.0)),
        merge_existing=bool(sink_payload.get("merge_existing", True)),
        gap_threshold_sec=float(sink_payload.get("gap_threshold_sec", 60.0)),
        compact_segment_count=int(sink_payload.get("compact_segments", DEFAULT_COMPACT_SEGMENTS)),
        gap_threshold_factor=float(sink_payload.get("gap_threshold_factor", 10.0)),
        drop_outside_session=bool(sink_payload.get("drop_outside_session", True)),
        heartbeat_interval_sec=float(buffer_payload.get("heartbeat_interval_sec", 60.0)),
        tick_log_interval=int(logging_payload.get("tick_interval", 1000)),
        tick_log_mode=str(logging_payload.get("tick_mode", "every")),
        health_check_enabled=health_enabled,
        health=HealthThresholds(**health_payload),
        calendar=_calendar_from_config(config),
    )


def _calendar_from_config(config: dict[str, Any]) -> TradingCalendar:
    holidays_file = (config.get("calendar") or {}).get("holidays_file")
    if holidays_file:
        return TradingCalendar.from_file(holidays_file)
    return TradingCalendar()


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def build_engine(config: dict[str, Any], *, env: dict[str, str] | None = None):
    """Wire the real CTP provider and subscriber into the engine."""
    from bt_api_ctp.collector_ctp.instrument_provider import CtpInstrumentProvider
    from bt_api_ctp.collector_ctp.subscriber import CtpMdSubscriber
    from bt_api_ctp.ctp.client import MdClient, TraderClient

    environment = dict(os.environ if env is None else env)
    ctp = config.get("ctp") or {}
    subscription = config.get("subscription") or {}

    def field(name: str, env_name: str, default: str = "") -> str:
        return str(ctp.get(name) or environment.get(env_name) or default)

    md_front = field("md_front", "CTP_MD_FRONT")
    td_front = field("td_front", "CTP_TD_FRONT")
    broker_id = field("broker_id", "CTP_BROKER_ID")
    user_id = field("user_id", "CTP_USER_ID")
    password = field("password", "CTP_PASSWORD")

    trader = TraderClient(
        td_front,
        broker_id,
        user_id,
        password,
        app_id=field("app_id", "CTP_APP_ID", "simnow_client_test"),
        auth_code=field("auth_code", "CTP_AUTH_CODE", "0000000000000000"),
    )
    trader.start(block=False)
    login_timeout_sec = float(ctp.get("login_timeout_sec", 30))
    _logger.info("CTP trader login: front=%s broker=%s user=%s", td_front, broker_id, user_id)
    if trader.wait_ready(timeout=login_timeout_sec) is not True:
        trader.stop()
        _logger.error(
            "CTP trader login timeout after %ss (front=%s)", login_timeout_sec, td_front
        )
        raise RuntimeError("ctp_trader_login_timeout")
    _logger.info("CTP trader login OK (front=%s)", td_front)

    md_client = MdClient(md_front, broker_id, user_id, password)
    subscriber = CtpMdSubscriber(
        md_client,
        batch_size=int(subscription.get("batch_size", 100)),
        batch_interval_sec=float(subscription.get("batch_interval_sec", 0.1)),
    )
    collection_config = build_collection_config(config)
    # An exchange shard only needs its own exchanges: querying the whole
    # market per process is slow and can be rate-limited by the counter.
    shard = collection_config.shard
    provider_exchanges = (
        tuple(shard.exchanges)
        if shard.strategy == "by_exchange" and shard.exchanges
        else EXCHANGES
    )
    provider = CtpInstrumentProvider(trader, exchanges=provider_exchanges)
    return TickCollectionEngine(
        provider=provider,
        subscriber=subscriber,
        config=collection_config,
    )


def validate_shard_configs(configs: list[dict[str, Any]]) -> ShardValidationReport:
    """Statically check exchange-level shard assignments across machines."""
    counts: dict[str, int] = {}
    for entry in configs:
        shard = _shard_from_mapping(entry, default_strategy="by_exchange")
        if shard.strategy != "by_exchange":
            continue
        for exchange in shard.exchanges:
            counts[exchange] = counts.get(exchange, 0) + 1

    overlaps = sorted(name for name, count in counts.items() if count > 1)
    unknown = sorted(name for name in counts if name not in EXCHANGES)
    missing = sorted(set(EXCHANGES) - set(counts))
    return ShardValidationReport(
        overlaps=overlaps + unknown,
        missing=missing,
        ok=not overlaps and not missing and not unknown,
    )


def _report_calendar(config: dict[str, Any], day: str) -> int:
    calendar = _calendar_from_config(config)
    is_trading = calendar.is_trading_day(day)
    print(f"date: {day}")
    print(f"trading_day: {is_trading}")
    print(f"night_session: {calendar.has_night_session(day)}")
    return EXIT_OK if is_trading else EXIT_NOT_TRADING_DAY


def _report_shards(config: dict[str, Any]) -> int:
    configs = list(config.get("shard_all") or [])
    if not configs:
        print("shard_all is required for --validate-shards", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    report = validate_shard_configs(configs)
    print(f"ok: {report.ok}")
    print(f"overlaps: {report.overlaps}")
    print(f"missing: {report.missing}")
    return EXIT_OK if report.ok else EXIT_SHARD_MISMATCH


def _install_sigint_handler(stop_event: threading.Event) -> None:
    def handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handler)


def _print_report(report: SinkReport) -> None:
    print(f"trading_day: {report.trading_day or 'none'}")
    print(f"instruments: {len(report.instruments)}")
    print(f"dropped_ticks: {report.dropped_ticks}")
    for entry in report.instruments:
        print(
            f"  {entry.exchange_id}/{entry.instrument_id}: rows={entry.rows} "
            f"first={entry.first_update} last={entry.last_update} gaps={len(entry.gaps)}"
        )


def _configure_logging(
    *,
    verbosity: int = 0,
    quiet: bool = False,
    log_file: Path | None = None,
) -> None:
    """Make collector progress logs visible on the console and in a file.

    The engine reports subscribe/heartbeat/flush/milestone progress through
    ``logging.INFO``; without a configured root logger those records are
    dropped and an unattended run looks frozen until it finally prints the
    report hours later.

    Args:
        verbosity: How many ``-v`` flags were given; any value above zero
            switches the console to ``DEBUG``.
        quiet: When true only warnings and errors are shown.
        log_file: Optional file to mirror every record into.  The parent
            directory is created on demand.
    """
    if quiet:
        level = logging.WARNING
    elif verbosity > 0:
        level = logging.DEBUG
    else:
        level = logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def _resolve_log_file(
    config: dict[str, Any],
    day: str,
    calendar: TradingCalendar,
    *,
    night: bool,
    moment: datetime | None,
) -> Path | None:
    """Return the per-trading-day log file under ``<data_root>/logs``.

    A night run belongs to the next trading day, matching the directory its
    ticks are written to.  The local calendar is only a startup pre-check;
    CTP's ``GetTradingDay()`` stays authoritative for the data paths.
    """
    logging_config = config.get("logging") or {}
    if logging_config.get("file", True) is False:
        return None
    data_root = config.get("data_root")
    if not data_root:
        return None
    log_dir = Path(data_root) / str(logging_config.get("dir", "logs"))
    if night or group_index(moment or datetime.now()) == 1:
        day = calendar.next_trading_day(day)
    return log_dir / f"collector-{day}.log"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bt_api_ctp.collector",
        description="Collect CTP depth-market ticks into Parquet files.",
    )
    parser.add_argument("--config", required=True, help="path to the YAML collector config")
    parser.add_argument("--once", action="store_true", help="run a single collection window")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="collection window length in seconds (default: until SIGINT)",
    )
    parser.add_argument(
        "--until-close",
        action="store_true",
        help="collect until the end of the current trading session, then exit",
    )
    parser.add_argument(
        "--wait-open",
        action="store_true",
        help="with --until-close, wait for the next open when started beforehand",
    )
    parser.add_argument(
        "--night",
        action="store_true",
        help="this run belongs to the night session: require tonight to trade",
    )
    parser.add_argument(
        "--close-grace-sec",
        type=float,
        default=300.0,
        help="extra seconds to keep collecting after the session end (default: 300)",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="override the current time (YYYYMMDDTHH:MM:SS), for scheduling and tests",
    )
    parser.add_argument(
        "--check-calendar",
        action="store_true",
        help="print trading-day and night-session state, then exit",
    )
    parser.add_argument(
        "--validate-shards",
        action="store_true",
        help="check shard_all for overlaps and gaps, then exit",
    )
    parser.add_argument("--date", default=None, help="override the date (YYYYMMDD)")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        dest="verbosity",
        help="log collector progress; repeat (-vv) for debug level",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only log warnings and errors",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.until_close and args.duration is not None:
        print("config error: --until-close conflicts with --duration", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        override_now = datetime.strptime(args.now, "%Y%m%dT%H:%M:%S") if args.now else None
    except ValueError:
        print("config error: --now must look like YYYYMMDDTHH:MM:SS", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    day = args.date or _today()
    if args.check_calendar:
        return _report_calendar(config, day)
    if args.validate_shards:
        return _report_shards(config)

    calendar = _calendar_from_config(config)
    if args.night:
        # A night run starts in the evening of a regular trading day; Sunday
        # evening never trades, and the evening before a holiday break is
        # suspended by the exchanges.
        if not calendar.has_night_session(day):
            print(f"no night session on: {day}", file=sys.stderr)
            return EXIT_NOT_TRADING_DAY
    elif not calendar.is_trading_day(day):
        print(f"not a trading day: {day}", file=sys.stderr)
        return EXIT_NOT_TRADING_DAY

    # Configured here, not at entry: the log file name needs data_root, the
    # startup day and the session group to resolve.
    _configure_logging(
        verbosity=args.verbosity,
        quiet=args.quiet,
        log_file=_resolve_log_file(config, day, calendar, night=args.night, moment=override_now),
    )

    try:
        duration = resolve_duration(
            duration=args.duration,
            until_close=args.until_close,
            now=override_now,
            grace_sec=args.close_grace_sec,
            wait_for_open=args.wait_open,
        )
    except SessionClosedError as exc:
        print(f"not in a trading session: {exc}", file=sys.stderr)
        return EXIT_NOT_TRADING_DAY

    stop_event = threading.Event()
    _install_sigint_handler(stop_event)
    try:
        engine = build_engine(config)
        report = engine.run_once(duration_sec=duration, stop_event=stop_event)
    except Exception as exc:  # 采集链路任一环节失败
        # 同时写日志：无人值守时只有日志文件留存，print 不会进日志。
        _logger.error("collection failed: %s", exc)
        print(f"collection failed: {exc}", file=sys.stderr)
        return EXIT_COLLECTION_FAILED

    _print_report(report)
    return EXIT_OK


__all__ = [
    "EXIT_COLLECTION_FAILED",
    "EXIT_CONFIG_ERROR",
    "EXIT_NOT_TRADING_DAY",
    "EXIT_OK",
    "EXIT_SHARD_MISMATCH",
    "build_collection_config",
    "build_engine",
    "load_config",
    "main",
    "validate_config",
    "validate_shard_configs",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
