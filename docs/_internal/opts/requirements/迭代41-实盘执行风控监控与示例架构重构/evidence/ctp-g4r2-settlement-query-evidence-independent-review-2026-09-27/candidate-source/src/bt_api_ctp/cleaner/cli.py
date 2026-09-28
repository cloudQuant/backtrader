"""Command-line entry point for CTP data cleaning.

Usage:
    python -m bt_api_ctp.cleaner --config cleaner.yaml run
    python -m bt_api_ctp.cleaner --config cleaner.yaml run --dry-run
    python -m bt_api_ctp.cleaner --config cleaner.yaml pull --day 20260918
    python -m bt_api_ctp.cleaner --config cleaner.yaml merge
    python -m bt_api_ctp.cleaner --config cleaner.yaml kline --backfill
    python -m bt_api_ctp.cleaner --config cleaner.yaml check-hosts

This module is the only place that wires the CTP naming rules and the trading
calendar into the pipeline; the imports are function-local so every framework
module in ``cleaner`` stays venue-agnostic.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from bt_api_ctp.cleaner.config import CleanerConfig, ConfigError, load_config
from bt_api_ctp.cleaner.pipeline import (
    PipelineReport,
    kline_only,
    merge_only,
    pull_only,
    run,
)
from bt_api_ctp.cleaner.pull import create_backend
from bt_api_ctp.cleaner.report import write_report

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_TRANSFER_FAILED = 2
EXIT_NOT_TRADING_DAY = 3
EXIT_CLEAN_FAILED = 4

_logger = logging.getLogger("bt_api_ctp.cleaner")


def _classifier():
    from bt_api_ctp.cleaner_ctp.symbols import classify_contract

    return classify_contract


def _trading_calendar(config: CleanerConfig):
    from bt_api_ctp.collector.schedule import TradingCalendar

    if config.holidays_file is not None:
        return TradingCalendar.from_file(config.holidays_file)
    return TradingCalendar()


def _setup_logging(config: CleanerConfig, *, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.log_to_file:
        config.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.FileHandler(
                config.log_dir / f"cleaner-{datetime.now():%Y%m%d}.log", encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _exit_code(report: PipelineReport) -> int:
    transfer_problem = any(
        host.errors or host.verify_failures for host in report.hosts.values()
    ) or bool(report.reclaim.failed)
    clean_problem = any(day.unreadable for day in report.kline.values())
    if transfer_problem:
        return EXIT_TRANSFER_FAILED
    if clean_problem:
        return EXIT_CLEAN_FAILED
    return EXIT_OK


def _print_summary(report: PipelineReport, report_file) -> None:
    pulled = sum(len(host.days_pulled) for host in report.hosts.values())
    for name, host in report.hosts.items():
        print(
            f"[{name}] ready={len(host.days_ready)} pulled={len(host.days_pulled)} "
            f"incomplete={len(host.days_incomplete)} already_done={len(host.days_already_done)} "
            f"files={host.fetch_files} bytes={host.fetch_bytes}"
        )
    for day, entry in report.merge.items():
        print(
            f"[merge {day}] instruments={entry.instruments} added={entry.added} deduped={entry.deduped}"
        )
    for day, entry in report.kline.items():
        bars = sum(entry.bars_added.values())
        print(f"[kline {day}] instruments={entry.instruments} bars_added={bars}")
    if report.reclaim.decisions:
        print(
            f"[reclaim] planned={report.reclaim.planned} deleted={report.reclaim.deleted} "
            f"dry_run={report.reclaim.dry_run}"
        )
    print(f"[report] {report_file}")
    if pulled == 0 and not report.merge and not report.kline:
        print("[cleaner] 没有需要处理的数据")


def check_hosts(config: CleanerConfig) -> int:
    """Connectivity check for every configured host."""
    all_ok = True
    for host in config.hosts:
        backend = create_backend(host)
        try:
            status = backend.check()
        finally:
            backend.close()
        marker = "ok" if status.ok else "FAIL"
        print(f"{status.name} ({status.backend}): {marker} {status.detail}")
        all_ok = all_ok and status.ok
    return EXIT_OK if all_ok else EXIT_TRANSFER_FAILED


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bt_api_ctp.cleaner", description=__doc__)
    parser.add_argument("--config", required=True, help="path to cleaner.yaml")
    parser.add_argument(
        "--base-dir",
        default=None,
        help="directory relative paths resolve against (default: current directory)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="pull, verify, merge, build K lines, then reclaim")
    p_run.add_argument("--day", default=None, help="restrict to one trading day (YYYYMMDD)")
    p_run.add_argument("--dry-run", action="store_true", help="plan only, change nothing")

    p_pull = sub.add_parser("pull", help="pull and verify only")
    p_pull.add_argument("--day", default=None, help="restrict to one trading day (YYYYMMDD)")
    p_pull.add_argument("--dry-run", action="store_true")

    p_merge = sub.add_parser("merge", help="merge verified days and build missing K lines")
    p_merge.add_argument("--dry-run", action="store_true")

    p_kline = sub.add_parser("kline", help="build K lines")
    p_kline.add_argument("--day", nargs="+", default=None, help="explicit trading days")
    p_kline.add_argument("--backfill", action="store_true", help="rebuild every tick day")
    p_kline.add_argument("--dry-run", action="store_true")

    sub.add_parser("check-hosts", help="check connectivity of every host")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        config = load_config(args.config, base_dir=args.base_dir)
    except ConfigError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    _setup_logging(config, verbose=args.verbose)

    if args.command == "check-hosts":
        return check_hosts(config)

    if args.command in ("run", "pull") and not args.day:
        today = datetime.now().strftime("%Y%m%d")
        if not _trading_calendar(config).is_trading_day(today):
            _logger.info("%s 非交易日，跳过", today)
            print(f"{today} 非交易日，跳过")
            return EXIT_NOT_TRADING_DAY

    try:
        if args.command == "run":
            report = run(config, classifier=_classifier(), only_day=args.day, dry_run=args.dry_run)
        elif args.command == "pull":
            report = pull_only(config, only_day=args.day, dry_run=args.dry_run)
        elif args.command == "merge":
            report = merge_only(config, classifier=_classifier(), dry_run=args.dry_run)
        else:
            report = kline_only(
                config,
                classifier=_classifier(),
                days=args.day,
                backfill=args.backfill,
                dry_run=args.dry_run,
            )
    except RuntimeError as error:
        _logger.error("run refused: %s", error)
        print(f"运行被拒绝: {error}", file=sys.stderr)
        return EXIT_CLEAN_FAILED

    report_file = write_report(report, config.report_dir)
    _print_summary(report, report_file)
    return _exit_code(report)


__all__ = [
    "EXIT_CLEAN_FAILED",
    "EXIT_CONFIG_ERROR",
    "EXIT_NOT_TRADING_DAY",
    "EXIT_OK",
    "EXIT_TRANSFER_FAILED",
    "check_hosts",
    "main",
]
