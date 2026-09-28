from __future__ import annotations

import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = Path(r"D:\source_code\backtrader")
OUTPUT = ROOT / "evidence" / "source-diff"
OUTPUT.mkdir(parents=True, exist_ok=True)
PAIRS = (
    ("backtrader_runtime/ctp_simnow_td_trading_readiness.py", "backtrader_runtime/ctp_simnow_td_trading_readiness.py", False),
    ("tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py", "tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py", False),
    (None, "backtrader_runtime/ctp_sdk_artifact_binding.py", True),
    (None, "tests/unit/runtime/test_ctp_sdk_artifact_binding.py", True),
)
for baseline_rel, candidate_rel, added in PAIRS:
    candidate = ROOT / candidate_rel
    if added:
        old_text = ""
        old_name = "/dev/null"
    else:
        old_text = (MAIN / baseline_rel).read_text(encoding="utf-8")
        old_name = "main/" + baseline_rel
    new_text = candidate.read_text(encoding="utf-8")
    patch = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=old_name,
        tofile="candidate/" + candidate_rel,
    )
    safe = candidate_rel.replace("/", "_") + ".patch"
    (OUTPUT / safe).write_text("".join(patch), encoding="utf-8", newline="")
print("source diffs written:", len(PAIRS))
