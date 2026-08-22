"""Tests for scripts/ci/classify_pr_risk.py."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.classify_pr_risk import (  # noqa: E402
    classify_risk,
    paths_from_file,
    suggest_area,
    suggest_labels,
    write_github_output,
)

# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------


def test_docs_paths_are_r0():
    assert classify_risk(["docs/source/index.md"]) == "R0"


def test_tests_paths_are_r0():
    assert classify_risk(["tests/unit/test_foo.py"]) == "R0"


def test_markdown_at_root_is_r0():
    assert classify_risk(["README.md", "CONTRIBUTING.md"]) == "R0"


def test_indicator_path_is_r1():
    assert classify_risk(["backtrader/indicators/sma.py"]) == "R1"


def test_unknown_path_defaults_to_r1():
    assert classify_risk(["backtrader/analyzers/sharpe.py"]) == "R1"


def test_cerebro_is_r2():
    assert classify_risk(["backtrader/cerebro.py"]) == "R2"


def test_line_system_is_r2():
    assert classify_risk(["backtrader/lineroot.py", "backtrader/linebuffer.py"]) == "R2"


def test_feeds_and_brokers_are_r2():
    assert classify_risk(["backtrader/feeds/csvgeneric.py"]) == "R2"
    assert classify_risk(["backtrader/brokers/bbroker.py"]) == "R2"


def test_supply_chain_is_r3():
    assert classify_risk(["setup.py", "pyproject.toml", "requirements.txt"]) == "R3"


def test_workflows_are_r3():
    assert classify_risk([".github/workflows/test.yml"]) == "R3"


def test_mixed_paths_take_highest_risk():
    assert classify_risk(["docs/x.md", "backtrader/cerebro.py"]) == "R2"
    assert classify_risk(["docs/x.md", "setup.py"]) == "R3"


def test_windows_path_separators_are_normalized():
    assert classify_risk(["backtrader\\cerebro.py"]) == "R2"


# ---------------------------------------------------------------------------
# Area suggestion
# ---------------------------------------------------------------------------


def test_area_broker():
    assert suggest_area(["backtrader/broker.py"]) == "area:broker"


def test_area_feeds():
    assert suggest_area(["backtrader/feeds/csvgeneric.py"]) == "area:feeds"


def test_area_indicators():
    assert suggest_area(["backtrader/indicators/sma.py"]) == "area:indicators"


def test_area_docs():
    assert suggest_area(["docs/source/index.md"]) == "area:docs"


def test_area_ci():
    assert suggest_area([".github/workflows/test.yml"]) == "area:ci"


def test_area_core_default():
    assert suggest_area(["backtrader/cerebro.py"]) == "area:core"


def test_suggest_labels_contains_risk_and_area():
    labels = suggest_labels(["backtrader/cerebro.py"])
    assert labels["risk"] == "R2"
    assert labels["area"] == "area:core"


def test_paths_file_preserves_one_path_per_line(tmp_path):
    paths_file = tmp_path / "changed-paths.txt"
    paths_file.write_text("docs/source/index.md\nbacktrader/cerebro.py\n", encoding="utf-8")
    assert paths_from_file(paths_file) == ["docs/source/index.md", "backtrader/cerebro.py"]


def test_github_output_contains_only_fixed_classifier_values(tmp_path):
    output = tmp_path / "github-output.txt"
    write_github_output(output, {"risk": "R2", "area": "area:core"})
    assert output.read_text(encoding="utf-8") == "risk=R2\narea=area:core\n"
