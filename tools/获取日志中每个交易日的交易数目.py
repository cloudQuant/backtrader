"""统计 Backtrader 日志中每个交易日的交易数量。

默认会在 ``logs`` 目录中自动查找最新的 ``master`` 与 ``remove-metaprogramming``
日志，并分别输出“日志类型 / 日期 / 交易数目”三列的表格；也支持手动
指定日志文件。
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Iterator, List

TRADE_PATTERN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})T[0-9:.+-]*,\s*open symbol is\s*:\s*(?P<symbol>\S+)",
    re.IGNORECASE,
)


def iter_trade_dates(lines: Iterable[str]) -> Iterator[str]:
    """从日志文本行中解析交易日期。"""

    for line in lines:
        match = TRADE_PATTERN.search(line)
        if match:
            yield match.group("date")


def count_trades_per_day(path: Path) -> Counter[str]:
    """统计单个日志文件的每日交易次数。"""

    trade_counter: Counter[str] = Counter()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for trade_date in iter_trade_dates(handle):
                trade_counter[trade_date] += 1
    except FileNotFoundError as err:
        raise FileNotFoundError(f"日志文件不存在: {path}") from err

    return trade_counter


def guess_log_label(name: str) -> str:
    lowered = name.lower()
    if "master" in lowered:
        return "master"
    if "remove" in lowered and "metaprogramming" in lowered:
        return "remove_metaprogramming"
    return Path(name).stem


def unique_label(label: str, existing: dict[str, Path]) -> str:
    if label not in existing:
        return label

    index = 2
    while f"{label}_{index}" in existing:
        index += 1
    return f"{label}_{index}"


def discover_logs(log_dir: Path) -> dict[str, Path]:
    log_dir = log_dir.resolve()
    if not log_dir.exists():
        raise FileNotFoundError(f"日志目录不存在: {log_dir}")

    candidates = list(log_dir.glob("*.log"))
    if not candidates:
        raise FileNotFoundError(f"日志目录中未找到 .log 文件: {log_dir}")

    def latest_match(keyword: str) -> Path | None:
        matches = [path for path in candidates if keyword in path.name.lower()]
        if not matches:
            return None
        return max(matches, key=lambda path: path.stat().st_mtime)

    master_log = latest_match("master")
    remove_log = latest_match("remove-metaprogramming") or latest_match("remove_metaprogramming")

    missing = []
    if master_log is None:
        missing.append("master")
    if remove_log is None:
        missing.append("remove_metaprogramming")
    if missing:
        raise FileNotFoundError("日志目录中缺少以下日志文件，请手动指定: " + ", ".join(missing))

    return {
        "master": master_log,
        "remove_metaprogramming": remove_log,
    }


def resolve_log_paths(args: argparse.Namespace) -> dict[str, Path]:
    if args.log_files:
        resolved: dict[str, Path] = {}
        for raw_path in args.log_files:
            path = raw_path.resolve()
            label = unique_label(guess_log_label(path.name), resolved)
            resolved[label] = path
        return resolved

    return discover_logs(args.log_dir)


def sort_labels(labels: list[str]) -> list[str]:
    priority = {"master": 0, "remove_metaprogramming": 1}
    return sorted(labels, key=lambda label: (priority.get(label, 99), label))


def print_table(counts_map: dict[str, Counter[str]], sort_by: str) -> None:
    if not counts_map:
        print("未在日志中找到符合格式的交易记录")
        return

    labels = sort_labels(list(counts_map.keys()))

    if len(labels) < 2:
        # 回退到旧格式
        header = f"{'日志类型':<28}{'日期':<12}{'交易数目'}"
        print(header)
        print("-" * len(header))
        for label in labels:
            for date, count in sorted(counts_map[label].items(), key=lambda item: item[0]):
                print(f"{label:<28}{date:<12}{count}")
        return

    all_dates = set()
    for counter in counts_map.values():
        all_dates.update(counter.keys())

    differing_rows: list[tuple[str, dict[str, int]]] = []
    for date in all_dates:
        row_counts = {label: counts_map[label].get(date, 0) for label in labels}
        if len({row_counts[label] for label in labels}) > 1:
            differing_rows.append((date, row_counts))

    if not differing_rows:
        print("两个日志的每日交易数完全一致")
        return

    if sort_by == "date":
        differing_rows.sort(key=lambda item: item[0])
    elif sort_by == "count":
        differing_rows.sort(key=lambda item: (-max(item[1].values()), item[0]))

    headers = ["日期"] + labels
    widths: dict[str, int] = {
        "日期": max(len("日期"), max(len(date) for date, _ in differing_rows))
    }
    for label in labels:
        max_count_len = max(len(str(row_counts[label])) for _, row_counts in differing_rows)
        widths[label] = max(len(label), max_count_len)

    def build_line(values: list[str]) -> str:
        return "  ".join(f"{value:<{widths[header]}}" for value, header in zip(values, headers))

    print(build_line(headers))
    print("  ".join("-" * widths[header] for header in headers))

    for date, row_counts in differing_rows:
        row = [date] + [str(row_counts[label]) for label in labels]
        print(build_line(row))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计 Backtrader 日志中每个交易日的交易次数")
    parser.add_argument(
        "log_files",
        nargs="*",
        type=Path,
        help="需要统计的日志文件，可以同时分析多个文件",
    )
    parser.add_argument(
        "--sort-by",
        choices=("date", "count", "none"),
        default="date",
        help="输出排序方式，默认按日期升序",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="自动查找日志文件时使用的目录，默认值为 ./logs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log_paths = resolve_log_paths(args)
    counts_map: dict[str, Counter[str]] = {}

    for label, path in log_paths.items():
        counts_map[label] = count_trades_per_day(path)

    print_table(counts_map, args.sort_by)


if __name__ == "__main__":
    main()
