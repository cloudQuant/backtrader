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
node = str(r4 / "test_btapistore_iteration22.py") + "::test_recovery_exit_generic_ctp_enqueue_rejects_and_aborts_before_native_write"
raise SystemExit(pytest.main(["-p", "no:asyncio", "-q", node]))
