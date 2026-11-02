import base64, csv, hashlib, importlib, importlib.metadata, importlib.machinery, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
if Path(sys.prefix).resolve() != root or sys.version_info[:3] != (3, 11, 5): raise SystemExit("consumer interpreter mismatch")
expected = {"back-trader-python":"1.4.0", "bt-api-base":"0.15.8", "bt-api-ctp":"2.0.4+iteration41.i9"}
records = {}
for name, version in expected.items():
    dist = importlib.metadata.distribution(name)
    if dist.version != version: raise SystemExit(f"{name} version mismatch: {dist.version}")
    checked = 0
    for rel, digest, size in csv.reader(dist.read_text("RECORD").splitlines()):
        path = Path(dist.locate_file(rel)).resolve(); path.relative_to(root)
        if not path.is_file() or (size and path.stat().st_size != int(size)): raise SystemExit(f"{name} RECORD mismatch: {rel}")
        if digest:
            algorithm, expected_hash = digest.split("=", 1); h = hashlib.new(algorithm)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
            actual = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
            if actual != expected_hash: raise SystemExit(f"{name} RECORD hash mismatch: {rel}")
            checked += 1
    if not checked: raise SystemExit(f"{name} RECORD has no hashed entries")
    records[name] = {"version":dist.version,"hashed_entries_verified":checked}
import backtrader, bt_api_base, bt_api_ctp
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
if not callable(getattr(ExecutionDecisionJournal, "decision_for_key", None)): raise SystemExit("current journal API is missing")
from bt_api_ctp.ctp import _ctp_base
native = importlib.import_module("bt_api_ctp.ctp._ctp")
modules = {"backtrader":Path(backtrader.__file__).resolve(),"bt_api_base":Path(bt_api_base.__file__).resolve(),"bt_api_ctp":Path(bt_api_ctp.__file__).resolve(),"bt_api_ctp.ctp._ctp":Path(native.__file__).resolve()}
for path in modules.values(): path.relative_to(root)
if not any(str(modules["bt_api_ctp.ctp._ctp"]).endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES): raise SystemExit("CTP origin is not a CPython extension")
if not _ctp_base.is_ctp_native_loaded(): raise SystemExit("CTP selected its fallback")
print(json.dumps({"status":"PASS","records":records,"origins":{k:str(v) for k,v in modules.items()},"ctp_native_loaded":True},sort_keys=True))