#!/usr/bin/env python3
"""Analyze pytest --durations=0 output to identify slowest tests and files."""
import re
import sys
from collections import defaultdict

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bt_test_durations.log"

# pytest durations format: "<seconds>s <phase>     <test_id>"
LINE_RE = re.compile(r"^(\d+\.\d+)s\s+(\w+)\s+(.+)$")

entries = []
with open(LOG_PATH) as f:
    for line in f:
        line = line.rstrip()
        m = LINE_RE.match(line)
        if not m:
            continue
        secs = float(m.group(1))
        phase = m.group(2)
        test_id = m.group(3)
        entries.append((secs, phase, test_id))

# Aggregate per test (sum of call+setup+teardown)
per_test = defaultdict(float)
per_test_phases = defaultdict(lambda: defaultdict(float))
for secs, phase, tid in entries:
    per_test[tid] += secs
    per_test_phases[tid][phase] += secs

# Aggregate per file
per_file = defaultdict(float)
per_file_count = defaultdict(int)
for tid, total in per_test.items():
    file_path = tid.split("::")[0]
    per_file[file_path] += total
    per_file_count[file_path] += 1

total_recorded = sum(per_test.values())
print(f"Total tests with duration data: {len(per_test)}")
print(f"Total recorded test time: {total_recorded:.2f}s")
print()

# Top 20% by file
files_sorted = sorted(per_file.items(), key=lambda x: -x[1])
total_files = len(files_sorted)
top20pct_files_count = max(1, total_files // 5)

print(f"=== Top 20% slowest test FILES ({top20pct_files_count} of {total_files}) ===")
print(f"{'Rank':>4} {'Time(s)':>8} {'%':>6} {'Tests':>5}  File")
top_files_time = 0
for i, (path, t) in enumerate(files_sorted[:top20pct_files_count], 1):
    pct = t / total_recorded * 100
    top_files_time += t
    print(f"{i:>4} {t:>8.2f} {pct:>5.1f}% {per_file_count[path]:>5}  {path}")
print()
print(f"Top 20% files account for: {top_files_time:.2f}s ({top_files_time/total_recorded*100:.1f}%)")
print()

# Top 20% by individual test
tests_sorted = sorted(per_test.items(), key=lambda x: -x[1])
total_tests = len(tests_sorted)
top20pct_tests_count = max(1, total_tests // 5)

print(f"=== Top 20% slowest test CASES ({top20pct_tests_count} of {total_tests}) — showing top 60 ===")
print(f"{'Rank':>4} {'Time(s)':>8} {'%':>6}  Test")
top_tests_time = 0
for tid, t in tests_sorted[:top20pct_tests_count]:
    top_tests_time += t

for i, (tid, t) in enumerate(tests_sorted[:60], 1):
    pct = t / total_recorded * 100
    print(f"{i:>4} {t:>8.2f} {pct:>5.1f}%  {tid}")
print()
print(f"Top 20% tests ({top20pct_tests_count}) account for: {top_tests_time:.2f}s ({top_tests_time/total_recorded*100:.1f}%)")
