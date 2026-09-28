import sys
from pathlib import Path
import pytest
repo = Path(r"D:\source_code\backtrader")
qa = Path(r"D:\temp\ac41-63-store-api-identity-r2-p3-independent-qa-20260927")
sys.path.insert(0, str(repo))
sys.path.insert(0, str(qa / "overlay"))
import backtrader.stores.btapistore as loaded
print("CANDIDATE_MODULE", loaded.__file__)
raise SystemExit(pytest.main(["--noconftest", "-p", "no:asyncio", "-q", *sys.argv[1:]]))
