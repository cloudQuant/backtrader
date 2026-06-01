import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.test_utils.hft_scenarios import build_hft_comparison_report


def _format_report(report_rows):
    lines = ["# HFT Scenario Comparison", ""]
    for row in report_rows:
        lines.append(f"## {row['name']}")
        lines.append("")
        lines.append(f"- source: {row['source']}")
        lines.append(f"- reference cash: {row['reference']['cash']}")
        lines.append(f"- backtrader cash: {row['backtrader']['cash']}")
        lines.append(f"- reference position: {row['reference']['position']}")
        lines.append(f"- backtrader position: {row['backtrader']['position']}")
        lines.append(f"- trade count: {row['trade_count']}")
        lines.append(f"- matches: {json.dumps(row['matches'], ensure_ascii=False)}")
        lines.append(f"- fills: {json.dumps(row['backtrader']['fills'], ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    report = build_hft_comparison_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print()
    print(_format_report(report))
