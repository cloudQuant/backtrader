"""Guarded no-CTP-import broad regression runner for the integrated main tree.

Run from any directory with PYTHONPATH set to this receipt's guard directory.
The 16 deselections are exact tests that call optional_sdk("bt_api_ctp.ctp.client").
The two other blocked node IDs in the P3 compatibility attempt are in the
separate R4 temp file and are not selected by this main-tree path list.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if 'sitecustomize' not in sys.modules or not hasattr(sys.modules['sitecustomize'], '_ProviderImportBlocker'):
    raise SystemExit('fake-only import/network guard is not active; set PYTHONPATH to receipt guard')

REPO = Path(r"D:\source_code\backtrader")
if not (REPO / "backtrader" / "stores" / "btapistore.py").is_file():
    raise SystemExit("repository Store source not found")
identity_test = REPO / "tests/unit/stores/test_btapistore_api_route_identity.py"
if not identity_test.is_file():
    raise SystemExit("integrated route identity test is absent; do not count a partial suite")

sys.path.insert(0, str(REPO))
paths = [
    str(REPO / "tests/unit/stores"),
    str(REPO / "tests/unit/runtime"),
    str(REPO / "tests/test_ctp_generic_sdk_queue_failclose.py"),
    str(identity_test),
]

blocked = [
    "tests/unit/stores/test_btapistore.py::test_create_ctp_wrapper_patches_missing_spi_callbacks",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_accepts_dict_snapshots_from_trader_client",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_positions_accept_float_string_ctp_codes",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_positions_use_contract_multiplier_and_exchange_fields",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_polls_order_insert_error_events_with_order_ref",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_order_submit_reject_status_overrides_unknown_order_status",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_trade_callback_accepts_float_string_ctp_codes",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_fetch_open_orders_converts_ctp_rows",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_fetch_open_orders_accepts_float_string_ctp_codes",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_submit_order_rejects_caller_forged_store_capability",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_submit_order_rejects_raw_only_client_before_api_access",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_cancel_rejects_without_raw_action_access[missing-capability]",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_cancel_rejects_without_raw_action_access[caller-forged-capability]",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_submit_order_rejects_non_integer_lots[0]",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_submit_order_rejects_non_integer_lots[1.5]",
    "tests/unit/stores/test_btapistore.py::test_ctp_wrapper_submit_order_rejects_non_integer_lots[bad]",
]
args = ["-p", "no:asyncio", "-q"]
for node_id in blocked:
    args.extend(["--deselect", node_id])
junit_path = Path(os.environ.get("ITER41_GUARDED_JUNIT", str(Path(__file__).parent / "guarded-main-broad.junit.xml")))
args.extend(["--junitxml", str(junit_path), *paths])
print("GUARD_EXPECTED=sitecustomize in PYTHONPATH; see ITER41_GUARD_LOG")
print("DESELECTED_EXPLICIT_CTP_IMPORTS=16")
print("JUNIT", junit_path)
raise SystemExit(pytest.main(args))



