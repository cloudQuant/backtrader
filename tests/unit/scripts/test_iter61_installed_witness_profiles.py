"""Offline tests for pinned factor witness profiles and JUnit gates."""

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "iter61_installed_verifier", ROOT / "scripts/verify_factor_research_installed.py"
)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _write(repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _repository(tmp_path, profile):
    repo = tmp_path / profile
    repo.mkdir()
    _git(repo, "init", "--object-format=sha1")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    for path in (*V._installed_test_inputs(profile), V._PAIR_SEMANTICS_HELPER):
        _write(repo, path, b"fixture\n")
    driver = V._INSTALLED_TEST_PATHS[profile]
    if profile == "legacy":
        content = _git(ROOT, "cat-file", "blob", V._DRIVER_PROFILE_BLOBS[profile][0])
    else:
        content = (ROOT / driver).read_bytes()
    _write(repo, driver, content)
    for path in ("setup.py", "pyproject.toml", "README.md", "backtrader/__init__.py"):
        _write(repo, path, b"fixture\n")
    for directory in V._EXAMPLE_DIRS:
        _write(repo, directory + "/example.py", b"fixture\n")
    strategy = (
        "backtrader/research/factor_strategy.py"
        if profile == "legacy"
        else "backtrader/strategies/factor_strategy.py"
    )
    _write(repo, strategy, b"fixture\n")
    for index, path in enumerate(V._pair_test_inputs(profile)):
        if profile == "legacy":
            content = _git(ROOT, "cat-file", "blob", V._PAIR_PROFILE_BLOBS[profile][index])
        else:
            content = (ROOT / path).read_bytes()
        _write(repo, path, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD").decode().strip()


def _commit(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "change")
    return _git(repo, "rev-parse", "HEAD").decode().strip()


@pytest.mark.parametrize("profile", ("legacy", "current"))
def test_profile_selects_pinned_blobs_and_ignores_dirty_worktree(tmp_path, profile):
    repo, commit = _repository(tmp_path, profile)
    selected = V._select_pair_profile(repo, commit)
    assert selected["profile"] == profile
    assert selected["source_commit"] == commit
    inputs = V._pair_test_inputs(profile)
    assert tuple(selected["git_blobs"][path] for path in inputs) == V._PAIR_PROFILE_BLOBS[profile]
    paths = V._archive_paths_for_commit(
        repo, commit, "backtrader", factor_mode_pair=True, pair_profile=profile
    )
    assert all(path in paths for path in inputs)
    other = V._pair_test_inputs("current" if profile == "legacy" else "legacy")[1]
    assert other not in paths
    # A worktree change cannot affect the commit's identity or chosen test input.
    _write(repo, inputs[1], b"dirty, never used\n")
    assert V._select_pair_profile(repo, commit) == selected
    source, _ = V._extract_archive(
        repo,
        commit,
        tmp_path / (profile + "-archive"),
        "backtrader",
        factor_mode_pair=True,
        pair_profile=profile,
    )
    assert (source / inputs[1]).read_bytes() == _git(repo, "show", commit + ":" + inputs[1])
    assert not (source / other).exists()
    with pytest.raises(V.VerificationError, match="differs from pinned"):
        V._extract_archive(
            repo,
            commit,
            tmp_path / (profile + "-wrong"),
            "backtrader",
            factor_mode_pair=True,
            pair_profile="current" if profile == "legacy" else "legacy",
        )


@pytest.mark.parametrize(
    "problem",
    (
        "mixed",
        "partial",
        "unreviewed",
        "missing-common",
        "mixed-strategy",
        "unreviewed-driver",
        "mixed-driver",
    ),
)
def test_profile_rejects_unknown_or_incomplete_git_tree(tmp_path, problem):
    repo, _ = _repository(tmp_path, "legacy")
    if problem == "mixed":
        _write(repo, V._FACTOR_MODE_PAIR_TEST_INPUTS[1], b"other\n")
    elif problem == "partial":
        (repo / V._LEGACY_FACTOR_MODE_PAIR_TEST_INPUTS[1]).unlink()
    elif problem == "unreviewed":
        _write(repo, V._LEGACY_FACTOR_MODE_PAIR_TEST_INPUTS[1], b"different test body\n")
    elif problem == "missing-common":
        (repo / V._TEST_INPUTS[0]).unlink()
    elif problem == "mixed-strategy":
        _write(repo, "backtrader/strategies/factor_strategy.py", b"other\n")
    elif problem == "unreviewed-driver":
        _write(repo, V._INSTALLED_TEST_PATHS["legacy"], b"different driver\n")
    else:
        _write(repo, V._INSTALLED_TEST_PATHS["current"], b"other\n")
    commit = _commit(repo)
    with pytest.raises(V.VerificationError):
        V._select_pair_profile(repo, commit)


@pytest.mark.parametrize("profile", ("legacy", "current"))
def test_alpha101_profile_requires_its_additional_pinned_inputs(tmp_path, profile):
    repo, commit = _repository(tmp_path, profile)
    with pytest.raises(V.VerificationError, match="lacks required inputs"):
        V._select_pair_profile(repo, commit, alpha101_build_pair=True)
    for index, path in enumerate(V._matrix_test_inputs(profile)):
        content = (
            (
                _git(ROOT, "cat-file", "blob", V._DRIVER_PROFILE_BLOBS[profile][1])
                if profile == "legacy"
                else (ROOT / path).read_bytes()
            )
            if index == 0
            else b"fixture\n"
        )
        _write(repo, path, content)
    commit = _commit(repo)
    source = V._select_pair_profile(repo, commit, alpha101_build_pair=True)
    assert set(V._matrix_test_inputs(profile)) <= source["git_blobs"].keys()


@pytest.mark.parametrize("profile", ("legacy", "current"))
def test_default_profile_does_not_require_optional_pair_tests(tmp_path, profile):
    repo, _ = _repository(tmp_path, profile)
    (repo / V._pair_test_inputs(profile)[1]).unlink()
    commit = _commit(repo)
    assert V._select_pair_profile(repo, commit, factor_mode_pair=False)["profile"] == profile
    with pytest.raises(V.VerificationError, match="lacks required inputs"):
        V._select_pair_profile(repo, commit, factor_mode_pair=True)


def test_current_pair_archive_does_not_require_full_alpha_drivers_or_example_data(tmp_path):
    repo, _ = _repository(tmp_path, "current")
    for path in (
        V._INSTALLED_TEST_PATHS["current"],
        V._TEST_INPUTS[0],
        V._PAIR_SEMANTICS_HELPER,
        V._EXAMPLE_DIRS[2] + "/example.py",
    ):
        (repo / path).unlink()
    commit = _commit(repo)
    selected = V._select_pair_profile(repo, commit, factor_mode_pair=True)
    assert selected["profile"] == "current"
    assert V._INSTALLED_TEST_PATHS["current"] not in selected["git_blobs"]
    paths = V._archive_paths_for_commit(repo, commit, "backtrader", factor_mode_pair=True)
    assert V._INSTALLED_TEST_PATHS["current"] not in paths
    assert V._MATRIX_TEST_PATHS["current"] not in paths
    assert V._PAIR_SEMANTICS_HELPER not in paths
    assert V._EXAMPLE_DIRS[2] not in paths
    source, _ = V._extract_archive(
        repo, commit, tmp_path / "archive", "backtrader", factor_mode_pair=True
    )
    external = tmp_path / "external"
    external.mkdir()
    V._copy_external_tests(source, external, factor_mode_pair=True)
    assert (external / V._FACTOR_MODE_PAIR_TEST_INPUTS[1]).is_file()
    assert not (external / V._INSTALLED_TEST_PATHS["current"]).exists()


def test_legacy_and_explicit_alpha_pair_keep_existing_full_archive_inputs():
    for profile, alpha in (("legacy", False), ("current", True)):
        paths = V._archive_paths(
            "backtrader", factor_mode_pair=True, alpha101_build_pair=alpha, pair_profile=profile
        )
        assert V._INSTALLED_TEST_PATHS[profile] in paths
        assert V._PAIR_SEMANTICS_HELPER in paths
        assert all(path in paths for path in V._EXAMPLE_DIRS)
        if alpha:
            assert V._MATRIX_TEST_PATHS[profile] in paths


def test_current_pair_main_returns_before_full_installed_and_example_paths(tmp_path, monkeypatch):
    bt_repo, fin_repo = tmp_path / "bt", tmp_path / "fin"
    for repo in (bt_repo, fin_repo):
        (repo / ".git").mkdir(parents=True)
    wheels = {}
    for name in ("backtrader", "fincore"):
        wheel = tmp_path / (name + ".whl")
        wheel.write_bytes(name.encode())
        wheels[name] = wheel
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(V, "_require_base_python", lambda: None)
    monkeypatch.setattr(V, "_full_commit", lambda repo, value, name: value)
    monkeypatch.setattr(
        V, "_select_pair_profile", lambda *args, **kwargs: {"profile": "current", "git_blobs": {}}
    )
    monkeypatch.setattr(
        V,
        "_build_wheel",
        lambda repo, commit, name, evidence, **kwargs: (repo, wheels[name], "archive"),
    )
    monkeypatch.setattr(V, "_install_root", lambda args, evidence: (install, "target"))
    monkeypatch.setattr(V, "_run", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    monkeypatch.setattr(V, "_verify_wheel_payload", lambda *args: {})
    monkeypatch.setattr(
        V,
        "_verify_imports",
        lambda *args, **kwargs: {
            "versions": {"backtrader": "1", "fincore": "1"},
            "origins": {},
            "factor_strategy": {},
        },
    )
    monkeypatch.setattr(V, "_copy_external_tests", lambda *args, **kwargs: None)
    monkeypatch.setattr(V, "_run_current_factor_pair_tests", lambda *args: {"test_case_count": 16})

    def forbidden(*args, **kwargs):
        raise AssertionError("full Alpha101 or example path was invoked")

    monkeypatch.setattr(V, "_run_installed_tests", forbidden)
    monkeypatch.setattr(V, "_run_025_026", forbidden)
    monkeypatch.setattr(V, "_copy_external_pair_helper", forbidden)
    evidence = tmp_path / "evidence"
    status = V.main(
        [
            "--backtrader-commit",
            "a" * 40,
            "--fincore-commit",
            "b" * 40,
            "--backtrader-repo",
            str(bt_repo),
            "--fincore-repo",
            str(fin_repo),
            "--data-dir",
            str(tmp_path / "missing"),
            "--symbols",
            "1",
            "--evidence-dir",
            str(evidence),
            "--factor-mode-pair",
        ]
    )
    assert status == 0
    summary = json.loads((evidence / "verification-summary.json").read_text())
    assert summary["status"] == "PASS_LOCAL_INSTALLED_FOUR_FORMULA_WITNESSES"
    assert summary["installed_tests"]["test_case_count"] == 16


@pytest.mark.parametrize("profile", ("legacy", "current"))
def test_no_flag_main_runs_default_driver_without_pair_blob_selection(
    tmp_path, monkeypatch, profile
):
    bt_repo, fin_repo = tmp_path / "bt", tmp_path / "fin"
    for repo in (bt_repo, fin_repo):
        (repo / ".git").mkdir(parents=True)
    wheels = {}
    for name in ("backtrader", "fincore"):
        wheel = tmp_path / (name + ".whl")
        wheel.write_bytes(name.encode())
        wheels[name] = wheel
    data = tmp_path / "data/_metadata"
    data.mkdir(parents=True)
    (data / "manifest.json").write_text("{}")
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(V, "_require_base_python", lambda: None)
    monkeypatch.setattr(V, "_full_commit", lambda repo, value, name: value)
    monkeypatch.setattr(V, "_select_default_profile", lambda *args: profile)

    def forbidden(*args, **kwargs):
        raise AssertionError("default path must not select the pinned pair profile")

    monkeypatch.setattr(V, "_select_pair_profile", forbidden)
    monkeypatch.setattr(
        V,
        "_build_wheel",
        lambda repo, commit, name, evidence, **kwargs: (repo, wheels[name], "archive"),
    )
    monkeypatch.setattr(V, "_install_root", lambda args, evidence: (install, "target"))
    monkeypatch.setattr(V, "_run", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    monkeypatch.setattr(V, "_verify_wheel_payload", lambda *args: {})
    monkeypatch.setattr(
        V,
        "_verify_imports",
        lambda *args, **kwargs: {
            "versions": {"backtrader": "1", "fincore": "1"},
            "origins": {},
            "factor_strategy": {},
        },
    )
    monkeypatch.setattr(V, "_copy_external_tests", lambda *args, **kwargs: None)
    selected = []

    def default_tests(*args, **kwargs):
        selected.append(kwargs["pair_profile"])
        return {}

    monkeypatch.setattr(V, "_run_installed_tests", default_tests)
    monkeypatch.setattr(V, "_run_current_factor_pair_tests", forbidden)
    monkeypatch.setattr(
        V, "_copy_examples", lambda *args, **kwargs: {"027_alpha003_panel_acceptance": tmp_path}
    )
    monkeypatch.setattr(V, "_run_025_026", lambda *args, **kwargs: {})
    monkeypatch.setattr(V, "_run_027", lambda *args, **kwargs: {})
    status = V.main(
        [
            "--backtrader-commit",
            "a" * 40,
            "--fincore-commit",
            "b" * 40,
            "--backtrader-repo",
            str(bt_repo),
            "--fincore-repo",
            str(fin_repo),
            "--data-dir",
            str(data.parent),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert status == 0
    assert selected == [profile]


@pytest.mark.parametrize("profile", ("legacy", "current"))
def test_no_flag_archive_selects_driver_by_presence_without_blob_pins(
    tmp_path, monkeypatch, profile
):
    repo, _ = _repository(tmp_path, profile)
    _write(repo, V._INSTALLED_TEST_PATHS[profile], b"unreviewed historical driver\n")
    commit = _commit(repo)

    def forbidden(*args, **kwargs):
        raise AssertionError("default path must not require pair profile selection")

    monkeypatch.setattr(V, "_select_pair_profile", forbidden)
    assert V._select_default_profile(repo, commit) == profile
    source, _ = V._extract_archive(repo, commit, tmp_path / "default-archive", "backtrader")
    assert (
        source / V._INSTALLED_TEST_PATHS[profile]
    ).read_bytes() == b"unreviewed historical driver\n"


@pytest.mark.parametrize("problem", ("missing", "both"))
def test_no_flag_rejects_missing_or_ambiguous_default_drivers(tmp_path, problem):
    repo, _ = _repository(tmp_path, "legacy")
    if problem == "missing":
        (repo / V._INSTALLED_TEST_PATHS["legacy"]).unlink()
    else:
        _write(repo, V._INSTALLED_TEST_PATHS["current"], b"other driver\n")
    commit = _commit(repo)
    with pytest.raises(V.VerificationError, match="exactly one default installed"):
        V._select_default_profile(repo, commit)


def test_current_pair_help_distinguishes_historical_full_reports():
    help_text = " ".join(V._parser().format_help().split())
    assert (
        "four-formula native/build witnesses on both engines for the current profile" in help_text
    )
    assert (
        "historical profiles retain their original reports, panels and CSV reevaluation"
        in help_text
    )


def _synthetic_installed_tree(root):
    files = {
        "backtrader/__init__.py": b"__version__ = '1.0'\n",
        "backtrader/research/__init__.py": b"",
        "backtrader/research/alpha101/__init__.py": b"",
        "backtrader/strategies/__init__.py": b"",
        "backtrader/strategies/factor_strategy.py": b"class FactorStrategy:\n    pass\n",
        "fincore/__init__.py": b"__version__ = '1.0'\n",
        "fincore/factor_analysis/__init__.py": b"",
        "fincore/factor_analysis/research.py": b"",
        "back_trader_python-1.0.dist-info/METADATA": b"Name: back-trader-python\nVersion: 1.0\n",
        "fincore-1.0.dist-info/METADATA": b"Name: fincore\nVersion: 1.0\n",
    }
    for path, content in files.items():
        _write(root, path, content)


@pytest.mark.parametrize(
    "problem",
    ("none", "wrong-class", "wrong-origin", "old-facade", "old-module", "missing-current"),
)
def test_current_installed_import_identity_and_retired_paths(tmp_path, problem):
    install, evidence = tmp_path / "install", tmp_path / "evidence"
    install.mkdir()
    evidence.mkdir()
    _synthetic_installed_tree(install)
    factor = install / "backtrader/strategies/factor_strategy.py"
    if problem == "wrong-class":
        factor.write_text("class FactorStrategy: pass\nFactorStrategy.__module__ = 'wrong'\n")
    elif problem == "wrong-origin":
        outside = tmp_path / "outside.py"
        outside.write_text("class FactorStrategy: pass\n")
        factor.unlink()
        factor.symlink_to(outside)
    elif problem == "old-facade":
        (install / "backtrader/research/__init__.py").write_text("FactorStrategy = object\n")
    elif problem == "old-module":
        _write(
            install,
            "backtrader/research/factor_strategy.py",
            b"raise RuntimeError('must not import')\n",
        )
    elif problem == "missing-current":
        factor.unlink()
    if problem == "none":
        result = V._verify_imports(install, evidence, pair_profile="current")
        witness = result["factor_strategy"]
        assert witness["class_module"] == "backtrader.strategies.factor_strategy"
        assert Path(witness["module_origin"]) == factor.resolve()
        assert result["origins"][witness["class_module"]] == str(factor.resolve())
        assert witness["old_facade_available"] is False and witness["old_module_available"] is False
        assert (
            json.loads((evidence / "installed-origins.json").read_text())["factor_strategy"]
            == witness
        )
    else:
        with pytest.raises(V.VerificationError):
            V._verify_imports(install, evidence, pair_profile="current")


def test_legacy_installed_import_check_does_not_require_current_strategy(tmp_path):
    install, evidence = tmp_path / "install", tmp_path / "evidence"
    install.mkdir()
    evidence.mkdir()
    _synthetic_installed_tree(install)
    (install / "backtrader/strategies/factor_strategy.py").unlink()
    (install / "backtrader/research/__init__.py").write_text("FactorStrategy = object\n")
    _write(install, "backtrader/research/factor_strategy.py", b"# legacy\n")
    result = V._verify_imports(install, evidence, pair_profile="legacy")
    assert "factor_strategy" not in result


@pytest.mark.parametrize("problem", ("none", "additional-parameter", "missing", "skipped", "extra"))
def test_current_pair_runner_selects_exact_nodes_and_rejects_incomplete_xml(
    tmp_path, monkeypatch, problem
):
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.setenv("BT_ALPHA101_NATIVE_IDS", "3")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")

    def fake_run(command, *, cwd, env):
        assert "BT_ALPHA101_NATIVE_IDS" not in env and "PYTEST_ADDOPTS" not in env
        code = command[4]
        assert "test_iter61_factor_formula_oracles.py::test_close_ma_independent_oracle" in code
        assert "test_iter61_factor_formula_oracles.py::test_roc_independent_oracle" in code
        assert "test_iter61_factor_formula_oracles.py::test_kdj_independent_oracle" in code
        assert "test_alpha003_build_matches_native_trace_values_reasons_and_lifecycle" in code
        assert "test_alpha003_degenerate_recovery_missing_bar_nan_trace_and_reason_pair" in code
        assert (
            "test_iter61_alpha101_installed.py" not in code
            and "test_iter61_alpha101_matrix.py" not in code
        )
        root, suite = _report("current")
        if problem == "missing":
            suite.remove(suite[0])
        elif problem == "skipped":
            ET.SubElement(suite[0], "skipped")
        elif problem == "extra":
            ET.SubElement(suite, "testcase", name="unexpected")
        elif problem == "additional-parameter":
            ET.SubElement(
                suite, "testcase", name="test_close_ma_independent_oracle[native-runnext-extra]"
            )
        ET.ElementTree(root).write(command[-1])
        return SimpleNamespace(stdout="synthetic")

    monkeypatch.setattr(V, "_run", fake_run)
    if problem in ("none", "additional-parameter"):
        report = V._run_current_factor_pair_tests(external, tmp_path, tmp_path)
        assert report["test_case_count"] == (17 if problem == "additional-parameter" else 16)
    else:
        with pytest.raises(V.VerificationError):
            V._run_current_factor_pair_tests(external, tmp_path, tmp_path)


def test_migrated_installed_driver_checks_wheel_provenance_and_hash(tmp_path):
    path = ROOT / "tests/integration/test_iter61_alpha101_installed.py"
    spec = importlib.util.spec_from_file_location("iter61_installed_driver", path)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    wheel = tmp_path / "test.whl"
    wheel.write_bytes(b"synthetic wheel content")
    checksum = hashlib.sha256(wheel.read_bytes()).hexdigest()
    item = {
        "source_commit": "a" * 40,
        "version": "1.0",
        "wheel_path": str(wheel),
        "wheel_sha256": checksum,
    }
    manifest = tmp_path / "provenance.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "iteration46-installed-alpha101-provenance-v1",
                "backtrader": item,
                "fincore": item,
            }
        )
    )
    versions = {"backtrader": "1.0", "fincore": "1.0"}
    assert driver._provenance(str(manifest), versions)["backtrader"]["wheel_sha256"] == checksum
    wheel.write_bytes(b"changed")
    with pytest.raises(AssertionError, match="wheel hash differs"):
        driver._provenance(str(manifest), versions)


@pytest.mark.parametrize("outcome", ("pass", "missing", "skipped"))
def test_matrix_junit_requires_full_t320_and_single_class_witness(tmp_path, outcome):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    if outcome != "missing":
        matrix = ET.SubElement(
            suite, "testcase", name="test_alpha101_native_build_pair_graph_matrix[T320]"
        )
        if outcome == "skipped":
            ET.SubElement(matrix, "skipped")
    ET.SubElement(
        suite, "testcase", name="test_mode", classname="tests.unit.test_factor_single_class_modes"
    )
    report = tmp_path / "matrix.xml"
    ET.ElementTree(root).write(report)
    if outcome == "pass":
        assert V._verify_alpha101_build_pair_test_witness(report)["status"] == "PASSED"
    else:
        with pytest.raises(V.VerificationError):
            V._verify_alpha101_build_pair_test_witness(report)


def _report(profile):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    cases = V._LEGACY_PAIR_FORMULA_TEST_CASES if profile == "legacy" else V._PAIR_FORMULA_TEST_CASES
    for formula, names in cases.items():
        for name in names:
            for engine in V._PAIR_ENGINE_MODES:
                modes = (
                    ("native", "build")
                    if profile == "current" and formula != "Alpha003"
                    else (None,)
                )
                for mode in modes:
                    suffix = engine if mode is None else mode + "-" + engine
                    ET.SubElement(suite, "testcase", name=name + "[" + suffix + "]")
    return root, suite


@pytest.mark.parametrize("profile", ("legacy", "current"))
@pytest.mark.parametrize(
    "problem", ("none", "missing", "skipped", "alpha-missing", "alpha-skipped")
)
def test_junit_requires_each_profile_witness(tmp_path, profile, problem):
    root, suite = _report(profile)
    if problem != "none":
        alpha = problem.startswith("alpha")
        name = (
            "test_alpha003_degenerate_recovery_missing_bar_nan_trace_and_reason_pair"
            if alpha
            else (
                V._LEGACY_PAIR_FORMULA_TEST_CASES
                if profile == "legacy"
                else V._PAIR_FORMULA_TEST_CASES
            )["ROC"][0]
        )
        case = next(
            c for c in suite if c.get("name").startswith(name + "[") and "runnext" in c.get("name")
        )
        if problem in ("missing", "alpha-missing"):
            suite.remove(case)
        else:
            ET.SubElement(case, "skipped")
    report = tmp_path / "test.xml"
    ET.ElementTree(root).write(report)
    if problem == "none":
        assert set(V._verify_pair_formula_test_witnesses(report, pair_profile=profile)) == {
            "Alpha003",
            "CloseMA",
            "ROC",
            "KDJ",
        }
    else:
        with pytest.raises(V.VerificationError):
            V._verify_pair_formula_test_witnesses(report, pair_profile=profile)


@pytest.mark.parametrize(
    "tokens",
    (
        "native-build-runnext",
        "native-runnext-runonce",
        "native-native-runnext",
        "native",
        "runnext",
    ),
)
def test_junit_rejects_conflicting_or_missing_mode_engine_tokens(tmp_path, tokens):
    root, suite = _report("current")
    target = next(
        case for case in suite if case.get("name") == "test_roc_independent_oracle[native-runnext]"
    )
    target.set("name", "test_roc_independent_oracle[" + tokens + "]")
    if tokens == "native-build-runnext":
        suite.remove(
            next(
                case
                for case in suite
                if case.get("name") == "test_roc_independent_oracle[build-runnext]"
            )
        )
    report = tmp_path / "bad-mode.xml"
    ET.ElementTree(root).write(report)
    with pytest.raises(V.VerificationError, match="conflicting"):
        V._verify_pair_formula_test_witnesses(report, pair_profile="current")
