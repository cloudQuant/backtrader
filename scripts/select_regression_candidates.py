#!/usr/bin/env python3
"""Select ~100 representative regression strategies for migration.

Selection criteria:
1. Skip strategies depending on deleted features/ caches
2. Skip strategies depending on external `back_trader` workspace beyond the hook
3. Diversify by category (target ~5 per category)
4. Prefer smaller data files (faster tests)
5. Prefer simpler strategies (smaller strategy_*.py)
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGRESSION_ROOT = REPO / "tests" / "functional" / "strategies_regression"
DATA_ROOT = REPO / "tests" / "functional" / "datas"
TARGET_PER_CATEGORY = 10000  # effectively no cap — pick everything that's eligible


def find_strategies():
    """Yield (category, strategy_dir) for all leaf strategy dirs."""
    for category_dir in sorted(REGRESSION_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        for strategy_dir in sorted(category_dir.iterdir()):
            if not strategy_dir.is_dir():
                continue
            yield category_dir.name, strategy_dir


def file_size_mb(path: Path) -> float:
    try:
        return path.stat().st_size / 1024 / 1024
    except OSError:
        return 0.0


def evaluate(strategy_dir: Path) -> dict | None:
    """Return a dict of features for the strategy, or None if unsuitable."""
    config_path = strategy_dir / "config.yaml"
    if not config_path.exists():
        return None
    expected_path = strategy_dir / "expected.json"
    if not expected_path.exists():
        return None

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None

    # Walk the entire config to find all "*file*" keys and check whether they
    # reference features/ (deleted) or external paths.
    needs_features = False
    data_files = []

    def visit(node):
        nonlocal needs_features
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    low = k.lower()
                    if "cache" in low or "feature" in low:
                        if "features/" in v:
                            needs_features = True
                            continue
                    if low.endswith("file") or low.endswith("_file"):
                        data_files.append(v)
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(config)

    if needs_features:
        return None

    # Resolve data file paths and check existence
    total_data_mb = 0.0
    missing_data = []
    resolved_paths: list[Path] = []
    for ref in data_files:
        if ref.startswith("../../../datas/"):
            tail = ref.removeprefix("../../../datas/")
            p = DATA_ROOT / tail
        else:
            p = (strategy_dir / ref).resolve()
        if p.exists():
            total_data_mb += file_size_mb(p)
            resolved_paths.append(p)
        else:
            missing_data.append(ref)

    if missing_data:
        return None

    # Strategy file size as proxy for complexity
    strat_files = list(strategy_dir.glob("strategy_*.py"))
    strat_lines = 0
    for sf in strat_files:
        try:
            strat_lines += len(sf.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            pass

    # Read expected to check finite metrics (skip degenerate cases)
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    total_trades = expected.get("total_trades") or expected.get("trade_num") or 0
    final_value = expected.get("final_value")
    if total_trades is None or total_trades <= 0:
        return None  # require trades > 0
    if final_value is None:
        return None
    # Also require buy + sell counts > 0 to filter degenerate cases
    buy_count = expected.get("buy_count") or 0
    sell_count = expected.get("sell_count") or 0
    if buy_count <= 0 and sell_count <= 0:
        return None

    return {
        "category": strategy_dir.parent.name,
        "name": strategy_dir.name,
        "path": strategy_dir,
        "data_mb": total_data_mb,
        "data_files": [str(p.relative_to(REPO)) for p in resolved_paths],
        "strategy_lines": strat_lines,
        "total_trades": total_trades,
        "final_value": final_value,
        # Score: small data + small strategy = good (lower is better)
        "score": total_data_mb * 2 + strat_lines / 100,
    }


def main():
    candidates_by_category: dict[str, list[dict]] = defaultdict(list)
    skipped = {"no_config": 0, "no_expected": 0, "needs_features": 0,
               "missing_data": 0, "zero_trades": 0}

    total = 0
    for category, strat_dir in find_strategies():
        total += 1
        info = evaluate(strat_dir)
        if info is None:
            # Quick re-check to know why
            cfg = strat_dir / "config.yaml"
            exp = strat_dir / "expected.json"
            if not cfg.exists():
                skipped["no_config"] += 1
            elif not exp.exists():
                skipped["no_expected"] += 1
            else:
                # Reason already filtered out
                pass
            continue
        candidates_by_category[info["category"]].append(info)

    print(f"Scanned {total} strategy directories")
    print(f"Skipped: {skipped}")
    print()
    print(f"{'Category':<30s} {'Count':>5s} {'Picked':>6s}")
    print("-" * 50)

    # Pick top-N per category by score (lower = better)
    selected: list[dict] = []
    for category, items in sorted(candidates_by_category.items()):
        items.sort(key=lambda x: x["score"])
        picked = items[:TARGET_PER_CATEGORY]
        selected.extend(picked)
        print(f"{category:<30s} {len(items):>5d} {len(picked):>6d}")

    print("-" * 50)
    print(f"{'TOTAL':<30s} {sum(len(x) for x in candidates_by_category.values()):>5d} {len(selected):>6d}")
    print()

    # Write selection to JSON for later use
    out = REPO / "scripts" / "regression_migration_selection.json"
    out.write_text(
        json.dumps(
            [{
                "category": s["category"],
                "name": s["name"],
                "path": str(s["path"].relative_to(REPO)),
                "data_files": s["data_files"],
                "data_mb": round(s["data_mb"], 2),
                "strategy_lines": s["strategy_lines"],
                "total_trades": s["total_trades"],
                "final_value": s["final_value"],
                "score": round(s["score"], 3),
            } for s in selected],
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Selection written to {out.relative_to(REPO)}")
    print(f"Total selected: {len(selected)}")


if __name__ == "__main__":
    main()
