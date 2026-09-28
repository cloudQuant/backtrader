import sys
from pathlib import Path
import pytest
repo = Path(r"D:\source_code\backtrader")
qa = Path(r"D:\temp\ac41-63-store-api-identity-r2-p3-independent-qa-20260927")
pkt = Path(r"D:\temp\ac41-63-store-api-identity-r2-20260927")
r4 = Path(r"D:\temp\ac41-63-store-generic-queue-failclose-r4-compat-20260927")
sys.path.insert(0, str(repo))
sys.path.insert(0, str(qa / "overlay"))
import backtrader.stores.btapistore as loaded
print("CANDIDATE_MODULE", loaded.__file__)
paths = [
    str(r4 / "test_btapistore_iteration22.py"),
    str(r4 / "test_btapistore_entry_approval_arm.py"),
    str(r4 / "test_ctp_generic_sdk_queue_failclose.py"),
    str(repo / "tests/unit/stores/test_btapistore.py"),
    str(repo / "tests/unit/stores/test_ctp_managed_projection_bridge.py"),
    str(repo / "tests/unit/stores/test_ctp_i9_managed_dispatch_bridge.py"),
    str(repo / "tests/unit/stores/test_managed_ctp_store_adapter.py"),
    str(repo / "tests/unit/stores/test_managed_execution_store_adapter.py"),
    str(pkt / "candidate/tests/unit/stores/test_btapistore_api_route_identity.py"),
]
raise SystemExit(pytest.main(["-p", "no:asyncio", "-q", "--junitxml", str(qa / "r2-guarded-compat.junit.xml"), *paths]))



