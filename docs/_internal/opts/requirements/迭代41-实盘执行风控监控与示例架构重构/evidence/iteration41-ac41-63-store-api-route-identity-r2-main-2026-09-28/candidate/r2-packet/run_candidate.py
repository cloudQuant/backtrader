import sys
from pathlib import Path
import pytest
root = Path(r"D:\source_code\backtrader")
pkg = Path(r"D:\temp\ac41-63-store-api-identity-r2-20260927")
r4 = Path(r"D:\temp\ac41-63-store-generic-queue-failclose-r4-compat-20260927")
sys.path.insert(0, str(root))
sys.path.insert(0, str(pkg / "overlay"))
import backtrader.stores.btapistore as loaded
print("CANDIDATE_MODULE", loaded.__file__)
paths = [
    str(r4 / "test_btapistore_iteration22.py"),
    str(r4 / "test_btapistore_entry_approval_arm.py"),
    str(r4 / "test_ctp_generic_sdk_queue_failclose.py"),
    str(root / "tests/unit/stores/test_btapistore.py"),
    str(root / "tests/unit/stores/test_ctp_managed_projection_bridge.py"),
    str(root / "tests/unit/stores/test_ctp_i9_managed_dispatch_bridge.py"),
    str(root / "tests/unit/stores/test_managed_ctp_store_adapter.py"),
    str(root / "tests/unit/stores/test_managed_execution_store_adapter.py"),
    str(pkg / "candidate/tests/unit/stores/test_btapistore_api_route_identity.py"),
]
args = ["-p", "no:asyncio", "-q", "--junitxml", str(pkg / "focused-junit.xml"), *paths]
raise SystemExit(pytest.main(args))
