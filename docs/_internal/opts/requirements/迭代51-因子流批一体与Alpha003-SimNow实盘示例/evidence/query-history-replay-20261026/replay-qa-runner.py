"""Focused query/history QA; run only in an idle interval between benchmarks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

repo = Path("D:/source_code/backtrader")
root = Path("D:/temp/i51-replay-clock-focus-20261026-r1")
assert not root.exists(), "Require a fresh QA output directory"
assert Path(
    "D:/temp/i50-formal-27b-native-20261026/completion.json"
).is_file(), "Root must first observe the native benchmark's terminal session"

expected = {
    "examples/unified/028_alpha003_simnow_minute/run.py":
        "dc0319a85e0fe62addbc6b0c0c06a97cc6b33f94a88c50a3764411455872a92c",
    "tests/unit/test_alpha003_simnow_runner.py":
        "e1b3907d0d0b6985e4de4e4e7eb7d98c44bec51e60e24699fff710426afb12a7",
    "backtrader/stores/execution_decision_journal.py":
        "e60e9c1e353ce9dea39c3f6461ce1f9aadbb48308ff45c72c19796cf10dadadf",
    "examples/unified/028_alpha003_simnow_minute/alpha003_strategy.py":
        "b7d65886d10b792af58bf8100a9e94f3da1b1405b2a6d0247315dcaaa8dfa058",
    "backtrader/research/live_cohort.py":
        "69f31733ad0fedc126837f6595b752cf2e2b180471da2352ab98ccb2e825b0d6",
}


def pins():
    result = {}
    for relative in expected:
        raw = (repo / relative).read_bytes()
        result[relative] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return result


pre = pins()
assert {key: row["sha256"] for key, row in pre.items()} == expected
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()
assert head == "fab06cdbb4539c8b00e253a01834727004a3f9b6"
base = (
    "tests/unit/test_alpha003_simnow_runner.py::"
    "test_live_two_epoch_uses_real_three_route_cerebro_and_closes_before_next_bundle"
)
nodes = [base + "[" + suffix + "]" for suffix in (
    "saved-query-history-three-epoch-restart",
    "saved-history-real-live-restart",
    "same-store-query-live",
)] + [
    "tests/unit/test_alpha003_simnow_runner.py::"
    "test_replay_executes_real_cerebro_orders_only_on_causal_later_bars"
]
nodes = ['tests/unit/test_alpha003_simnow_runner.py::' + name for name in (
    'test_replay_clock_deadline_samples_and_partial_waits_do_not_skip_slots',
    'test_replay_executes_real_cerebro_orders_only_on_causal_later_bars',
    'test_replay_rejects_late_quote_for_original_decision_and_tape_detects_tamper',
    'test_real_cerebro_live_strategy_winddown_is_ready_or_times_out',
)]
command = [sys.executable, "-m", "pytest", "-p", "no:asyncio", "-q", "--tb=short",
           "-o", "faulthandler_timeout=45", "--junitxml=" + str(root / "junit.xml"), *nodes]
environment = os.environ.copy()
environment.pop("PYTHONPATH", None)
environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
environment["PYTHONUTF8"] = "1"
root.mkdir()
launch = {"head": head, "python": sys.version, "command": command, "pre": pre,
          "timeout_seconds": 180, "evidence_level": "SOURCE_FAKE_COMPOSITION_ONLY",
          "env": {key: environment.get(key) for key in
                  ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONUTF8", "PYTHONPATH")}}
(root / "launch.json").write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")
started = time.monotonic()
timed_out = False
with (root / "stdout.bin").open("xb") as out, (root / "stderr.bin").open("xb") as err:
    try:
        result = subprocess.run(command, cwd=repo, env=environment, stdout=out, stderr=err,
                                timeout=180)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = 124
post = pins()
receipt = {"exit_code": exit_code, "timed_out": timed_out,
           "seconds": time.monotonic() - started, "pins_unchanged": post == pre, "post": post}
if (root / "junit.xml").is_file():
    receipt["junit_suites"] = [row.attrib for row in ET.parse(root / "junit.xml").getroot().iter("testsuite")]
(root / "completion.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt), flush=True)
assert post == pre, "Source changed during QA"
raise SystemExit(exit_code)
