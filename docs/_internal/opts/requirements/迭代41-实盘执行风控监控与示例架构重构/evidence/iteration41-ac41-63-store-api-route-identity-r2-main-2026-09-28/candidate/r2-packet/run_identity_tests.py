import sys
from pathlib import Path
import pytest
root = Path(r"D:\source_code\backtrader")
pkg = Path(r"D:\temp\ac41-63-store-api-identity-r2-20260927")
sys.path.insert(0, str(root))
sys.path.insert(0, str(pkg / "overlay"))
import backtrader.stores.btapistore as loaded
print("CANDIDATE_MODULE", loaded.__file__)
raise SystemExit(pytest.main(["-p", "no:asyncio", "-q", str(pkg / "candidate/tests/unit/stores/test_btapistore_api_route_identity.py")]))
