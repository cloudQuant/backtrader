"""Iteration 43: copied examples run, fail closed, and cover every public entry.

Copies are staged from Git-tracked and non-ignored added files, never ignored
private config. Strict acceptance additionally requires Git and the current
Backtrader version from an external site-packages installation. The checked-in
entrypoint inventory classifies every tracked Python main guard as a copy
command, frozen dry evidence, or an explicitly deferred entrypoint.
"""

from __future__ import annotations

import ast
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT = 600
INSTALL_PROBE = (
    "import importlib.util, importlib.metadata, json; "
    "spec = importlib.util.find_spec('backtrader'); "
    "print(json.dumps({'origin': spec.origin if spec else None, "
    "'version': importlib.metadata.version('backtrader')}))"
)
STRICT_COPY_ACCEPTANCE = os.environ.get("BT_I43_COPY_STRICT") == "1"
ENTRYPOINT_INVENTORY = Path(__file__).with_name(
    "iteration43_example_entrypoint_coverage.json"
)
EXPECTED_CASE_ROOTS = {
    "examples/live/000_live_certification/binance_penetration/cases",
    "examples/live/000_live_certification/okx_penetration/cases",
    "examples/live/000_live_certification/simnow_penetration/cases",
}
EXPECTED_CASES_PER_SUITE = 33
OPTIONAL16_DRY_SCRIPTS = {
    "examples/live/000_live_certification/optional16/gateway_capability_check.py",
    "examples/live/000_live_certification/optional16/gateway_server.py",
    "examples/live/000_live_certification/optional16/run_matrix.py",
}
UNCOMMITTED_PUBLIC_CONFIGS = {
    "examples/backtest/018_sma_crossover/config.yaml",
}

# (leaf, argv, missing-input marker or None when the leaf must run)
COPY_CONTRACT = (
    ("backtest/018_sma_crossover", ["run.py"], None),
    (
        "backtest/019_bollinger_band_doge",
        ["bollinger_band_strategy_train.py"],
        "DOGEUSDT_15m_20200710_20260126.csv",
    ),
    (
        "backtest/019_bollinger_band_doge",
        ["bollinger_band_strategy_test.py"],
        "DOGEUSDT_15m_20200710_20260126.csv",
    ),
    (
        "backtest/002_hft_alignment_demo",
        ["run_backtrader.py", "--strategy", "plain_grid", "--max-decisions", "500"],
        None,
    ),
    ("backtest/004_midfreq_demo", ["run.py"], None),
    ("backtest/005_midfreq_arbitrage", ["run.py"], None),
    ("backtest/006_plots", ["example_bokeh_charts.py"], None),
    ("backtest/006_plots", ["example_plotly_charts.py"], None),
    ("backtest/006_plots", ["example_report_generation.py"], None),
    (
        "backtest/006_plots",
        ["plot_plotly_example.py", "--output", "output/plotly_example.html"],
        None,
    ),
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

OUTPUT_ARTIFACTS = {
    ("backtest/006_plots", "example_bokeh_charts.py"): (
        "output/bokeh_chart.html",
        "output/backend_bokeh_dispatch.html",
    ),
    ("backtest/006_plots", "example_plotly_charts.py"): (
        "output/plotly_chart.html",
    ),
    ("backtest/006_plots", "example_report_generation.py"): (
        "output/backtest_report.html",
        "output/backtest_report.json",
    ),
    ("backtest/006_plots", "plot_plotly_example.py"): (
        "output/plotly_example.html",
    ),
}

def _case_id(leaf: str, argv: list[str]) -> str:
    entry = argv[0] if argv and not argv[0].startswith("-") else "run.py"
    flags = "".join(part for part in argv if part.startswith("-"))
    suffix = f"-{flags.strip('-')}" if flags else ""
    return f"{leaf.split('/')[-1]}-{entry.removesuffix('.py')}{suffix}"


COPYABLE = [
    pytest.param(leaf, argv, marker, id=_case_id(leaf, argv))
    for leaf, argv, marker in COPY_CONTRACT
]


def _missing_prerequisite(reason: str, strict: bool | None = None) -> None:
    """Skip ordinary local runs; make the same condition fail strict acceptance."""

    strict_mode = STRICT_COPY_ACCEPTANCE if strict is None else strict
    if strict_mode:
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def _child_environment(output_root: Path | None = None) -> dict[str, str]:
    """Pass process/runtime variables only, never ambient trading configuration."""

    allowed = (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
        "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION", "NUMBER_OF_PROCESSORS", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
        "CONDA_EXE", "CONDA_PYTHON_EXE", "CONDA_SHLVL", "_CONDA_ROOT", "_CONDA_EXE",
        "CONDA_PROMPT_MODIFIER",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MPLBACKEND"] = "Agg"
    if output_root is not None:
        mpl_config = output_root / ".mplconfig"
        mpl_config.mkdir(parents=True, exist_ok=True)
        env["MPLCONFIGDIR"] = str(mpl_config)
    return env


def _repo_version() -> str:
    """Read the checked-out version literal without importing the local package."""

    version_file = ROOT / "backtrader" / "version.py"
    tree = ast.parse(version_file.read_text(encoding="utf-8-sig"), filename=str(version_file))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str), "backtrader/version.py __version__ must be a string"
            return value
    raise AssertionError("backtrader/version.py has no literal __version__ assignment")


def _external_site_origin(origin_text: str) -> bool:
    origin = Path(origin_text).resolve()
    try:
        origin.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        return False
    return any(part.casefold() in {"site-packages", "dist-packages"} for part in origin.parts)


def _installation_problem(origin: object, version: object) -> str | None:
    if not isinstance(origin, str) or not _external_site_origin(origin):
        return f"backtrader origin must be external site-packages, got {origin!r}"
    expected_version = _repo_version()
    if version != expected_version:
        return (
            f"installed backtrader version {version!r} does not match repository "
            f"{expected_version!r}"
        )
    return None


def _is_main_guard(test: ast.expr) -> bool:
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
    ):
        return False
    left_is_name = isinstance(test.left, ast.Name) and test.left.id == "__name__"
    right_is_name = (
        len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Name)
        and test.comparators[0].id == "__name__"
    )
    left_is_main = isinstance(test.left, ast.Constant) and test.left.value == "__main__"
    right_is_main = (
        len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )
    return (left_is_name and right_is_main) or (right_is_name and left_is_main)


def _tracked_main_entrypoints() -> set[str]:
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "examples"],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        _missing_prerequisite("git ls-files is required to discover tracked example entrypoints")
    discovered: set[str] = set()
    for relative in listing.stdout.split("\0"):
        if not relative.endswith(".py"):
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        if any(
            isinstance(node, ast.If) and _is_main_guard(node.test)
            for node in ast.walk(tree)
        ):
            discovered.add(Path(relative).as_posix())
    return discovered


def _entrypoint_classes() -> tuple[set[str], set[str]]:
    inventory = json.loads(ENTRYPOINT_INVENTORY.read_text(encoding="utf-8"))
    assert inventory["schema_version"] == 1
    assert inventory["acceptance_status"] == "classification_only_not_run_evidence"

    frozen = inventory["frozen_dry_evidence"]
    suites = frozen["case_suites"]
    assert {suite["cases_root"] for suite in suites} == EXPECTED_CASE_ROOTS
    case_ids = frozen["case_ids"]
    assert len(case_ids) == EXPECTED_CASES_PER_SUITE
    assert len(set(case_ids)) == len(case_ids)
    assert len(suites) == len(EXPECTED_CASE_ROOTS)
    for suite in suites:
        evidence_ref = suite["evidence_ref"]
        assert evidence_ref and (ROOT / evidence_ref).is_file(), (
            f"frozen case evidence document is unavailable: {evidence_ref}"
        )
        assert suite["evidence_note"]

    frozen_paths = {
        f"{suite['cases_root']}/{case_id}/run.py"
        for suite in suites
        for case_id in case_ids
    }
    optional_paths = set(frozen["optional16_scripts"])
    assert optional_paths == OPTIONAL16_DRY_SCRIPTS
    optional_evidence = frozen["optional16_evidence_ref"]
    assert optional_evidence["path"] and (ROOT / optional_evidence["path"]).is_file()
    assert optional_evidence["note"]
    frozen_paths.update(optional_paths)

    deferred_rows = inventory["deferred_entrypoints"]
    deferred_paths = [row["path"] for row in deferred_rows]
    assert len(deferred_paths) == len(set(deferred_paths)), (
        "duplicate deferred entrypoint classification"
    )
    assert all(row["category"] and row["reason"] for row in deferred_rows)
    return frozen_paths, set(deferred_paths)


def test_every_tracked_main_entrypoint_is_classified() -> None:
    discovered = _tracked_main_entrypoints()
    copy_paths = {f"examples/{leaf}/{argv[0]}" for leaf, argv, _marker in COPY_CONTRACT}
    for relative in copy_paths - discovered:
        path = ROOT / relative
        assert path.is_file(), f"copy contract entrypoint is missing: {relative}"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        assert any(
            isinstance(node, ast.If) and _is_main_guard(node.test)
            for node in ast.walk(tree)
        ), f"copy contract path is not an executable entrypoint: {relative}"
        discovered.add(relative)
    frozen_paths, deferred_paths = _entrypoint_classes()

    classes = (copy_paths, frozen_paths, deferred_paths)
    for index, current in enumerate(classes):
        for other in classes[index + 1 :]:
            assert current.isdisjoint(other), "an entrypoint is assigned to multiple classes"

    classified = set().union(*classes)
    assert frozen_paths <= discovered, (
        f"frozen dry entrypoints disappeared from the tracked AST set: "
        f"{sorted(frozen_paths - discovered)}"
    )
    assert deferred_paths <= discovered, (
        f"deferred entrypoints disappeared from the tracked AST set: "
        f"{sorted(deferred_paths - discovered)}"
    )
    assert copy_paths <= discovered, (
        f"copy commands are not tracked main entrypoints: {sorted(copy_paths - discovered)}"
    )
    assert discovered == classified, (
        f"unclassified tracked entrypoints: {sorted(discovered - classified)}; "
        f"stale classifications: {sorted(classified - discovered)}"
    )


def test_installation_probe_rejects_checkout_origin_and_wrong_version(tmp_path: Path) -> None:
    expected_version = _repo_version()
    local_origin = str(ROOT / "backtrader" / "__init__.py")
    external_origin = str(
        tmp_path.joinpath("venv", "Lib", "site-packages", "backtrader", "__init__.py")
    )

    local_problem = _installation_problem(local_origin, expected_version)
    version_problem = _installation_problem(external_origin, "1.3.0")
    assert local_problem is not None and "origin" in local_problem
    assert version_problem is not None and "version" in version_problem
    assert _installation_problem(external_origin, expected_version) is None


def test_strict_prerequisite_failure_is_not_a_skip() -> None:
    with pytest.raises(pytest.fail.Exception, match="Git is required"):
        _missing_prerequisite("Git is required for strict copy acceptance", strict=True)


def _assert_copy_artifacts(leaf: str, argv: list[str], destination: Path) -> None:
    for relative in OUTPUT_ARTIFACTS.get((leaf, argv[0]), ()):
        artifact = destination / relative
        assert artifact.is_file(), f"{leaf} {argv}: expected artifact was not created: {relative}"
        assert artifact.stat().st_size > 0, f"{leaf} {argv}: empty artifact: {relative}"
        if relative.endswith(".json"):
            json.loads(artifact.read_text(encoding="utf-8"))


def _assert_002_result(completed: subprocess.CompletedProcess[str], leaf: str) -> None:
    if leaf != "backtest/002_hft_alignment_demo":
        return
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    assert {"balance", "position", "num_trades", "fills"} <= payload.keys()
    assert math.isfinite(float(payload["balance"]))
    assert math.isfinite(float(payload["position"]))
    assert type(payload["num_trades"]) is int and payload["num_trades"] > 0
    assert isinstance(payload["fills"], list)
    assert payload["num_trades"] == len(payload["fills"])
    assert payload["num_trades"] == 62, "plain_grid fixture should produce its documented 62 fills"
    for fill in payload["fills"]:
        assert isinstance(fill, dict)
        assert {"side", "price", "size"} <= fill.keys()
        assert fill["side"] in {"buy", "sell"}
        assert math.isfinite(float(fill["price"]))
        assert math.isfinite(float(fill["size"]))
        assert float(fill["price"]) > 0.0
        assert float(fill["size"]) > 0.0


def _stage(leaf: str, destination: Path) -> None:
    """Copy one leaf's tracked-plus-added files; ignored content never travels."""

    prefix = f"examples/{leaf}"
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-c", "-o", "--exclude-standard", prefix],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        _missing_prerequisite("git is required to stage isolated copies of the example leaf")
    names = [line for line in listing.stdout.splitlines() if line.startswith(prefix + "/")]
    assert names, f"{leaf}: nothing tracked"
    for relative in names:
        basename = Path(relative).name.casefold()
        if basename == ".env" or "secret" in basename:
            pytest.fail(f"refusing to stage a private-input path: {relative}", pytrace=False)
        target = destination / Path(relative[len(prefix) + 1 :])
        target.parent.mkdir(parents=True, exist_ok=True)
        if basename == "config.yaml":
            tracked = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "--", relative],
                capture_output=True,
                text=True,
            )
            if tracked.returncode == 0:
                template = subprocess.run(
                    ["git", "-C", str(ROOT), "show", f"HEAD:{relative}"],
                    capture_output=True,
                )
                assert template.returncode == 0, (
                    f"{relative}: committed public config template is unavailable"
                )
                contents = template.stdout
            else:
                assert relative in UNCOMMITTED_PUBLIC_CONFIGS, (
                    f"{relative}: add a reviewed public config path before copy-out staging"
                )
                contents = (ROOT / relative).read_bytes()
        else:
            contents = (ROOT / relative).read_bytes()
        target.write_bytes(contents)


@pytest.fixture(scope="module")
def library_installed() -> dict[str, str]:
    """Verify external package origin/version, or skip ordinary local runs."""

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            INSTALL_PROBE,
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT.parent),
        env=_child_environment(),
        encoding="utf-8",
        timeout=60,
    )
    if probe.returncode != 0:
        _missing_prerequisite(
            "backtrader cannot be imported by the selected interpreter; "
            "strict copy acceptance requires an installed package"
        )
    try:
        result = json.loads(probe.stdout)
        origin = result["origin"]
        version = result["version"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        _missing_prerequisite(f"installed backtrader probe returned invalid metadata: {exc}")
        raise AssertionError("unreachable")

    problem = _installation_problem(origin, version)
    if problem:
        _missing_prerequisite(problem)
        raise AssertionError("unreachable")
    return {"origin": origin, "version": version}


@pytest.mark.parametrize("leaf,argv,marker", COPYABLE)
def test_copied_leaf_runs_or_fails_closed(
    leaf: str,
    argv: list[str],
    marker: str | None,
    tmp_path: Path,
    library_installed: dict[str, str],
) -> None:
    assert library_installed["version"] == _repo_version()
    assert _external_site_origin(library_installed["origin"])
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
        env=_child_environment(destination),
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    if marker is None:
        assert completed.returncode == 0, (
            f"{leaf} {argv}: exit {completed.returncode}\n{output[-1200:]}"
        )
        assert output.strip(), f"{leaf} {argv}: succeeded with no output at all"
        _assert_002_result(completed, leaf)
        _assert_copy_artifacts(leaf, argv, destination)
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
            assert name != ".env" and "secret" not in name, (
                f"{leaf}: staged a secret-bearing file {path.name}"
            )
            assert path.parent.name not in {"__pycache__", "logs", "state"}, (
                f"{leaf}: staged rebuildable state {path}"
            )
