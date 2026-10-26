from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

OUT = Path(__file__).resolve().parent.parent
EVIDENCE = OUT / "evidence"
FIXTURE = OUT / "fixture-root"
CONSUMER = Path(sys.prefix).resolve()
SITE_PACKAGES = (CONSUMER / "Lib" / "site-packages").resolve()
PIN_PATH = EVIDENCE / "fixture_pins_before.json"
SUMMARY_PATH = EVIDENCE / "focus_summary.json"
NETWORK_EVENTS: list[str] = []


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if not PIN_PATH.is_file():
    raise SystemExit("fixture pin manifest is absent")
pin_doc = json.loads(PIN_PATH.read_text(encoding="utf-8"))
for item in pin_doc["files"]:
    copied = FIXTURE / Path(item["path"])
    if not copied.is_file() or copied.stat().st_size != item["size"]:
        raise SystemExit("fixture size/presence mismatch: " + item["path"])
    if sha256(copied) != item["fixture_sha256"]:
        raise SystemExit("fixture digest mismatch: " + item["path"])
expected_fixture_files = {
    item["path"].replace("\\", "/") for item in pin_doc["files"]
} | {"pytest.ini"}
actual_fixture_files = {
    path.relative_to(FIXTURE).as_posix()
    for path in FIXTURE.rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
}
if actual_fixture_files != expected_fixture_files:
    raise SystemExit("fixture tree contains missing or unpinned files")
if (FIXTURE / "backtrader").exists():
    raise SystemExit("fixture tree would shadow the installed Backtrader package")
if (FIXTURE / ".env").exists() or (FIXTURE / "runtime-ctp-private").exists():
    raise SystemExit("private input path unexpectedly exists in fixture tree")

sys.dont_write_bytecode = True
import backtrader

BT_ROOT = Path(backtrader.__file__).resolve().parent
if not within(BT_ROOT, SITE_PACKAGES):
    raise SystemExit("Backtrader imported outside the isolated consumer site-packages")
if importlib.metadata.version("back-trader-python") != "1.4.0":
    raise SystemExit("unexpected installed Backtrader distribution version")

# Make the only test input root explicit after the installed package is bound.
sys.path.insert(0, str(FIXTURE.resolve()))
repository_root = Path(pin_doc["repository_root"]).resolve()
for entry in sys.path:
    try:
        resolved = Path(entry or os.getcwd()).resolve()
    except OSError:
        continue
    if within(resolved, repository_root):
        raise SystemExit("repository source root unexpectedly present on sys.path")

# Network access is forbidden for this three-case fixture; provider leaves are fakes.
def deny_network(event: str, args: tuple[object, ...]) -> None:
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo"}:
        NETWORK_EVENTS.append(event)
        raise RuntimeError("network access disabled for installed focus: " + event)


sys.addaudithook(deny_network)
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
import pytest


class ResultCounts:
    def __init__(self) -> None:
        self.collected = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.setup_errors = 0

    def pytest_collection_finish(self, session) -> None:
        self.collected = len(session.items)

    def pytest_runtest_logreport(self, report) -> None:
        if report.when == "call":
            if report.passed:
                self.passed += 1
            elif report.failed:
                self.failed += 1
            elif report.skipped:
                self.skipped += 1
        elif report.when == "setup" and report.failed:
            self.setup_errors += 1


runner_node = (
    str(FIXTURE / "tests/unit/test_alpha003_simnow_runner.py")
    + "::test_live_two_epoch_uses_real_three_route_cerebro_and_closes_before_next_bundle"
    + "[saved-query-history-three-epoch-restart]"
)
integration_node = (
    str(FIXTURE / "tests/integration/test_live_alpha003_history_catchup_execution.py")
    + "::test_alpha003_prenext_history_warmup_dispatches_owned_risk_cancel"
)
args = [
    "-q",
    "-ra",
    "-p",
    "no:cacheprovider",
    "--tb=short",
    "--import-mode=importlib",
    "--confcutdir=" + str(FIXTURE),
    "-c",
    str(FIXTURE / "pytest.ini"),
    "--basetemp=" + str(OUT / "basetemp"),
    "--junitxml=" + str(EVIDENCE / "junit.xml"),
    runner_node,
    integration_node,
]
counts = ResultCounts()
started = time.monotonic()
exit_code = int(pytest.main(args, plugins=[counts]))
elapsed = time.monotonic() - started
bad_origins: list[dict[str, str]] = []
backtrader_origins: list[dict[str, str]] = []
for name, module in sorted(sys.modules.items()):
    if name == "backtrader" or name.startswith("backtrader."):
        origin = getattr(module, "__file__", None)
        if origin:
            resolved = Path(origin).resolve()
            backtrader_origins.append({"module": name, "file": str(resolved)})
            if not within(resolved, BT_ROOT):
                bad_origins.append({"module": name, "file": str(resolved)})
summary = {
    "evidence_level": "INSTALLED_BT_CURRENT_EXAMPLE_FOCUSED_FAKE_ONLY",
    "consumer_prefix": str(CONSUMER),
    "backtrader_distribution": "back-trader-python",
    "backtrader_version": importlib.metadata.version("back-trader-python"),
    "backtrader_file": str(Path(backtrader.__file__).resolve()),
    "backtrader_package_root": str(BT_ROOT),
    "fixture_root": str(FIXTURE.resolve()),
    "repository_head": pin_doc["repository_head"],
    "fixture_file_count": len(pin_doc["files"]),
    "pytest_version": pytest.__version__,
    "selected_nodes": [runner_node, integration_node],
    "collected": counts.collected,
    "passed": counts.passed,
    "failed": counts.failed,
    "skipped": counts.skipped,
    "setup_errors": counts.setup_errors,
    "exit_code": exit_code,
    "elapsed_seconds": round(elapsed, 6),
    "backtrader_module_origin_count": len(backtrader_origins),
    "backtrader_module_origins_valid": not bad_origins,
    "bad_backtrader_origins": bad_origins,
    "network_attempts": NETWORK_EVENTS,
}
SUMMARY_PATH.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print("INSTALLED_FOCUS_SUMMARY=" + json.dumps(summary, sort_keys=True, separators=(",", ":")))
if bad_origins or NETWORK_EVENTS or counts.collected != 3 or counts.passed != 3 or counts.failed or counts.skipped or counts.setup_errors:
    exit_code = exit_code or 1
sys.exit(exit_code)
