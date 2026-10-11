"""Iteration 43 R7: a copied example folder must still run, or fail closed loudly.

The three-class layout promised that any leaf under ``examples/`` works inside the
repository *and* after being copied elsewhere.  This guard stages each leaf from
``git ls-files -c -o`` (tracked plus added, never ignored), so an ignored private
config can never be carried along, clears ``PYTHONPATH`` so nothing resolves
through the checkout, and runs the leaf's offline entry from inside the copy.

Two outcomes are acceptable and they are asserted differently:

* the leaf runs (exit 0), meaning its code, its own fixtures and its vendored
  helpers all travelled with it; or
* the leaf refuses (non-zero) and its message names the missing input -- external
  big data, a not-installed optional dependency, or a checkout-only fence.

A non-zero exit that does not name what is missing, or a zero exit that produced
nothing, is exactly the "fake success" class this round removed, so it fails here.
002 is excluded: it carries a registered functional defect unrelated to portability.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT = 600

# (leaf, argv, missing-input marker or None when the leaf must run)
COPY_CONTRACT = (
    ("backtest/004_midfreq_demo", ["run.py"], None),
    ("backtest/005_midfreq_arbitrage", ["run.py"], None),
    ("backtest/006_plots", ["example_bokeh_charts.py"], None),
    ("backtest/006_plots", ["example_plotly_charts.py"], None),
    ("backtest/006_plots", ["example_report_generation.py"], None),
    ("backtest/008_dual_side", ["dual_side_basic.py"], None),
    ("backtest/008_dual_side", ["dual_side_hedge.py"], None),
    ("backtest/008_dual_side", ["dual_side_vs_net.py"], None),
    ("backtest/009_trade_logger", ["trade_logger_example.py"], None),
    ("backtest/009_trade_logger", ["trade_logger_heikin_ashi_example.py"], None),
    ("backtest/001_multi_extend_data", ["run.py", "--dry"], "bond_"),
    (
        "backtest/003_hft_notebook_examples",
        ["prepare_data.py", "--skip-download"],
        "bookTicker",
    ),
    ("backtest/011_hft_backtest", ["tick_backtest.py"], "Generate test data"),
    ("backtest/011_hft_backtest", ["orderbook_backtest.py"], "Generate test data"),
    ("backtest/016_self_similarity", ["run.py"], "XAUUSD_M1.csv"),
    ("backtest/017_fnn_embedding", ["run.py"], "XAUUSD_M1.csv"),
    ("unified/012_1_midfreq_cross_exchange", ["run.py", "--dry"], "checkout's backtrader package"),
    ("unified/012_2_event_driven_cross_exchange", ["run.py", "--dry"], None),
    ("unified/013_1_midfreq_cross_arbitrage", ["run.py", "--dry"], None),
    ("unified/013_2_highfreq_calendar_arbitrage", ["run.py", "--dry"], None),
    ("unified/013_3_sa_midfreq_simnow", ["run.py", "--dry"], None),
    ("unified/014_1_ctp_options_lowfreq", ["run.py", "--dry"], None),
    ("unified/014_2_ctp_options_midfreq", ["run.py", "--dry"], None),
    ("unified/015_ctp_options_highfreq", ["run.py", "--dry"], None),
)
LEAVES = tuple(sorted({leaf for leaf, _argv, _marker in COPY_CONTRACT}))

def _case_id(leaf: str, argv: list[str]) -> str:
    entry = argv[0] if argv and not argv[0].startswith("-") else "run.py"
    flags = "".join(part for part in argv if part.startswith("-"))
    return f"{leaf.split('/')[-1]}-{entry.removesuffix('.py')}{('-' + flags.strip('-')) if flags else ''}"


COPYABLE = [pytest.param(leaf, argv, marker, id=_case_id(leaf, argv)) for leaf, argv, marker in COPY_CONTRACT]


def _stage(leaf: str, destination: Path) -> None:
    """Copy one leaf's tracked-plus-added files; ignored content never travels."""

    prefix = f"examples/{leaf}"
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-c", "-o", "--exclude-standard", prefix],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        pytest.skip("git is unavailable in this environment")
    names = [line for line in listing.stdout.splitlines() if line.startswith(prefix + "/")]
    assert names, f"{leaf}: nothing tracked"
    for relative in names:
        target = destination / Path(relative[len(prefix) + 1 :])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


@pytest.fixture(scope="module")
def library_installed() -> bool:
    """Whether ``backtrader`` resolves outside the checkout (the honest baseline)."""

    probe = subprocess.run(
        [sys.executable, "-c", "import backtrader; print(backtrader.__file__)"],
        capture_output=True,
        text=True,
        cwd=str(ROOT.parent),
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    return probe.returncode == 0


@pytest.mark.parametrize("leaf,argv,marker", COPYABLE)
def test_copied_leaf_runs_or_fails_closed(leaf: str, argv: list[str], marker: str | None, tmp_path: Path, library_installed: bool) -> None:
    if not library_installed:
        pytest.skip("backtrader is only importable from the checkout, so portability cannot be judged")
    destination = tmp_path / leaf.replace("/", "__")
    destination.mkdir(parents=True, exist_ok=True)
    _stage(leaf, destination)

    completed = subprocess.run(
        [sys.executable, *argv],
        cwd=destination,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PROBE_TIMEOUT,
        env={**{key: value for key, value in os.environ.items() if key != "PYTHONPATH"}, "PYTHONIOENCODING": "utf-8"},
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    if marker is None:
        assert completed.returncode == 0, f"{leaf} {argv}: exit {completed.returncode}\n{output[-1200:]}"
        assert output.strip(), f"{leaf} {argv}: succeeded with no output at all"
        return

    assert completed.returncode != 0, f"{leaf} {argv} silently succeeded without {marker!r}"
    assert marker in output, f"{leaf} {argv} failed without naming {marker!r}:\n{output[-1200:]}"


@pytest.mark.parametrize("leaf", LEAVES)
def test_no_leaf_carries_an_ignored_file(leaf: str, tmp_path: Path) -> None:
    """The staged copy contains no private config, state or rebuildable output.

    This is the private-input half of the portability contract: a folder that
    travels must not take an operator's credentials with it, and a guard that
    copies ignored paths would quietly validate a tree that cannot be shared.
    """

    destination = tmp_path / leaf.replace("/", "__")
    destination.mkdir(parents=True, exist_ok=True)
    _stage(leaf, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            name = path.name.lower()
            assert name != ".env" and "secrets" not in name, f"{leaf}: staged a secret-bearing file {path.name}"
            assert path.parent.name not in {"__pycache__", "logs", "state"}, f"{leaf}: staged rebuildable state {path}"
