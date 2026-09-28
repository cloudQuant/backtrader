from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

EXPECTED_PARENT = Path(r"D:\bt_api_py_codex_i9_integrated_20260926").resolve()
MODULES = (
    "bt_api_py",
    "bt_api_py._normalization",
    "bt_api_py._contracts.models",
)
for module_name in MODULES:
    module = importlib.import_module(module_name)
    origin = Path(module.__file__).resolve()
    try:
        origin.relative_to(EXPECTED_PARENT)
    except ValueError as exc:
        raise SystemExit(
            f"SOURCE_ASSERTION_FAILED {module_name} origin={origin} expected_under={EXPECTED_PARENT}"
        ) from exc
    print(f"SOURCE_ASSERTION_PASS {module_name} origin={origin}")

os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
import pytest

raise SystemExit(
    pytest.main(
        [
            r"D:\bt_api_ctp_i13_g5_manual_candidate_20260926\tests\test_iter22_contracts.py::test_gateway_quote_v2_serialized_payload_reaches_parent_normalizer",
            "-q",
            "--tb=short",
            r"--junitxml=D:\temp\iteration41-sdk-v2-parent-normalizer-20260926.xml",
        ]
    )
)
