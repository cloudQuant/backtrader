"""Check exact test-ID coverage across the preserved and rescheduled runs."""

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def passed_cases(path, *, allow_interrupted_item=False):
    passed = set()
    interrupted = []
    tree = ET.parse(path).getroot()
    suites = list(tree.iter("testsuite"))
    assert len(suites) == 1
    counters = {
        key: int(suites[0].attrib[key]) for key in ("tests", "failures", "errors", "skipped")
    }
    assert not any(counters[key] for key in ("failures", "errors", "skipped"))
    for case in tree.findall(".//testcase"):
        if "classname" not in case.attrib or "name" not in case.attrib:
            assert allow_interrupted_item and not list(case), case.attrib
            interrupted.append(dict(case.attrib))
            continue
        nodeid = case.attrib["classname"].replace(".", "/") + ".py::" + case.attrib["name"]
        assert not any(
            case.find(tag) is not None for tag in ("failure", "error", "skipped")
        ), nodeid
        assert nodeid not in passed, nodeid
        passed.add(nodeid)
    assert counters["tests"] == len(passed)
    return passed, interrupted, counters


root = Path(__file__).resolve().parent
plan = json.loads((root / "source-coverage-plan.json").read_text())
expected = set(plan["expected_nodeids"])
assert len(expected) == plan["expected_count"] == 298
collection_path = root / "source-collection.txt"
collected = [
    line.strip()
    for line in collection_path.read_text().splitlines()
    if line.startswith("tests/") and "::" in line
]
assert collected == plan["expected_nodeids"]
assert "298 tests collected" in collection_path.read_text()
assert plan["initial_exit_code"] == 2
assert plan["initial_status"] == "INTENTIONALLY_INTERRUPTED_TO_RESCHEDULE_PENDING_CASES"
initial_path = root / "source-native-initial.xml"
remainder_path = root / "source-native-remainder.xml"
initial, interrupted, initial_counters = passed_cases(initial_path, allow_interrupted_item=True)
remainder, remainder_interrupted, remainder_counters = passed_cases(remainder_path)
process = json.loads((root / "source-native-remainder-process.json").read_text())
assert process["exit_code"] == 0
assert len(initial) == plan["initial_passed_count"] == 292
assert interrupted == plan["interrupted_harness_items"]
assert len(interrupted) == 1
assert initial == set(plan["initial_passed_nodeids"])
assert remainder == set(plan["remaining_nodeids"])
assert len(remainder) == 6 and not remainder_interrupted
assert initial.isdisjoint(remainder)
completed = initial | remainder
missing = sorted(expected - completed)
unexpected = sorted(completed - expected)
assert not missing and not unexpected


def digest(values):
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


record = {
    "status": "PASS",
    "expected_count": len(expected),
    "completed_count": len(completed),
    "initial_passed_count": len(initial),
    "remainder_passed_count": len(remainder),
    "initial_run_status": plan["initial_status"],
    "initial_exit_code": 2,
    "initial_unnamed_interrupted_items_excluded": interrupted,
    "remainder_exit_code": process["exit_code"],
    "initial_junit_counters": initial_counters,
    "remainder_junit_counters": remainder_counters,
    "failures": initial_counters["failures"] + remainder_counters["failures"],
    "errors": initial_counters["errors"] + remainder_counters["errors"],
    "skipped": initial_counters["skipped"] + remainder_counters["skipped"],
    "missing_nodeids": missing,
    "unexpected_nodeids": unexpected,
    "duplicate_passed_nodeids": sorted(initial & remainder),
    "expected_nodeids_sha256": digest(expected),
    "completed_nodeids_sha256": digest(completed),
    "raw_collection_sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
    "junit_sha256": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (initial_path, remainder_path)
    },
}
(root / "source-coverage.json").write_text(json.dumps(record, indent=2) + "\n")
print("PASS: all 298 collected test IDs completed; no missing or repeated passed cases")
