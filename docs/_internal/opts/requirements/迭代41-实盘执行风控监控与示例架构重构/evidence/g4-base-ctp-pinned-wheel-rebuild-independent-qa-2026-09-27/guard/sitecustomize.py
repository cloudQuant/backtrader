import json
import os
import sys
from pathlib import Path

_log = Path(os.environ.get("G4_QA_GUARD_LOG", r"D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\logs\guard-default.jsonl"))
_forbidden_roots = ("bt_api_base", "bt_api_ctp", "bt_api_py")

def _record(kind, detail):
    _log.parent.mkdir(parents=True, exist_ok=True)
    with _log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": kind, "detail": str(detail), "pid": os.getpid()}, sort_keys=True) + "\n")

def _audit(event, args):
    if event == "import" and args:
        name = str(args[0])
        root = name.split(".", 1)[0]
        if root in _forbidden_roots or any(part == "_ctp" for part in name.split(".")):
            _record("blocked_sdk_import", name)
            raise ImportError("G4 QA guard blocked SDK/native import: " + name)
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
        _record("blocked_network_event", event)
        raise RuntimeError("G4 QA guard blocked network event: " + event)

sys.addaudithook(_audit)
