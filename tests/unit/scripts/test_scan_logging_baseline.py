"""AST fixtures for complete and reproducible logging catalogs."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCANNER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "scan_logging_baseline.py"


@pytest.fixture
def scanner():
    spec = importlib.util.spec_from_file_location("logging_baseline_fixture", SCANNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_known_helpers_have_levels_and_mark_handlers_logged(scanner, tmp_path):
    source = tmp_path / "helpers.py"
    calls = [
        '_safe_log("error", "safe failure")',
        '_safe_log("debug", "fallback")',
        'throttled_warning(logger, "key", "warning")',
        'throttled_error(logger, "key", "error")',
        'logger.warning("ordinary log")',
    ]
    source.write_text(
        "\n".join(f"try:\n    work()\nexcept ValueError:\n    {call}\n" for call in calls)
    )
    excepts, logcalls, prints = scanner.scan_file(str(source))
    assert len(excepts) == 5
    assert all(item["logged"] and item["disposition"] == "logged" for item in excepts)
    assert [item["level"] for item in logcalls] == ["error", "debug", "warning", "error", "warning"]
    assert prints == []


def test_similar_names_unknown_levels_and_unproven_methods_are_not_logs(scanner, tmp_path):
    source = tmp_path / "not_logs.py"
    source.write_text("""try:
    work()
except Exception:
    logger.warning_like("not a supported level")
    other.error("not the known logger")
    _safe_log(level, "dynamic level")
    _safe_log("unknown", "not a supported level")
    self._safe_log("error", "not a helper method present in this package")
    object.throttled_error("not the known function")
    throttled_warning_like("unknown function")
    pass
""")
    excepts, logcalls, _ = scanner.scan_file(str(source))
    assert logcalls == []
    assert excepts[0]["logged"] is False
    assert excepts[0]["disposition"] == "pass"


def test_directory_and_file_order_make_catalogs_reproducible(scanner, tmp_path, monkeypatch):
    package = tmp_path / "package"
    for directory in ("z", "a"):
        (package / directory).mkdir(parents=True)
        for name in ("z.py", "a.py"):
            (package / directory / name).write_text('logger.info("message")\n')

    def deliberately_unordered_walk(root):
        directories = ["z", "a"]
        yield str(root), directories, []
        # os.walk consults its caller-mutable dirs list before descending.
        for directory in directories:
            yield str(Path(root) / directory), [], ["z.py", "a.py"]

    out = tmp_path / "catalog"
    monkeypatch.setattr(scanner, "PACKAGE_ROOT", str(package))
    monkeypatch.setattr(scanner.os, "walk", deliberately_unordered_walk)
    monkeypatch.setattr(sys, "argv", [str(SCANNER_PATH), "--out", str(out)])
    assert scanner.main() == 0
    first = (out / "logger-calls.json").read_bytes()
    assert [item["file"] for item in json.loads(first)] == [
        "package/a/a.py",
        "package/a/z.py",
        "package/z/a.py",
        "package/z/z.py",
    ]
    assert scanner.main() == 0
    assert (out / "logger-calls.json").read_bytes() == first
    assert json.loads((out / "summary.json").read_text())["files_scanned"] == 4


def test_syntax_error_returns_nonzero_without_publishing_partial_catalogs(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "a_valid.py").write_text('logger.error("a known log")\n')
    (package / "z_broken.py").write_text("def broken(:\n")
    out = tmp_path / "catalog"
    program = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("scanner", sys.argv[1])
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
scanner.PACKAGE_ROOT = sys.argv[2]
sys.argv = [sys.argv[1], "--out", sys.argv[3]]
sys.exit(scanner.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(SCANNER_PATH), str(package), str(out)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "SYNTAX ERROR" in result.stderr
    assert "z_broken.py" in result.stderr
    assert not list(out.glob("*.json"))
    assert result.stdout == ""
