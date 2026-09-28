from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

CANDIDATE = Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r0")
R4_ROOT = Path(r"D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4")
EXPECTED_R4 = "8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8"
EXPECTED_R3 = "417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(root: Path, name: str, expected_sha: str) -> dict:
    manifest_path = root / name
    actual = sha256(manifest_path)
    assert actual == expected_sha, (manifest_path, actual, expected_sha)
    sidecar = root / "manifest.sha256"
    sidecar_sha = sidecar.read_text(encoding="utf-8-sig").strip().split()[0]
    assert sidecar_sha == expected_sha, (sidecar, sidecar_sha, expected_sha)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    for item in manifest["files"]:
        path = root / item["path"]
        actual_file_sha = sha256(path)
        actual_size = path.stat().st_size
        expected_file_sha = item["sha256"]
        expected_size = item.get("size_bytes", item.get("bytes"))
        assert actual_file_sha == expected_file_sha, (path, actual_file_sha, expected_file_sha)
        assert actual_size == expected_size, (path, actual_size, expected_size)
        print(f"VERIFIED {path} {actual_size} {actual_file_sha}")
    print(f"MANIFEST {manifest_path} {actual}")
    return manifest


def ast_nodes(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


r4 = verify_manifest(R4_ROOT, "manifest.json", EXPECTED_R4)
r3_root = CANDIDATE / "upstream-contracts"
r3_manifest_path = r3_root / "r3-r1-manifest.json"
assert sha256(r3_manifest_path) == EXPECTED_R3
assert r3_root.joinpath("r3-r1-manifest.sha256").read_text(encoding="utf-8-sig").strip().split()[0] == EXPECTED_R3
r3 = json.loads(r3_manifest_path.read_text(encoding="utf-8-sig"))
r3_item = next(item for item in r3["files"] if item["path"] == "account_actor_port.py")
r3_module = r3_root / "account_actor_port_r3r1.py"
assert sha256(r3_module) == r3_item["sha256"]
assert sha256(CANDIDATE / "backtrader/stores/ctp_account_actor_port.py") == r4["files"][0]["sha256"]
assert sha256(r3_root / "store_boundary_harness.py") == next(
    item["sha256"] for item in r4["files"] if item["path"] == "store_boundary_harness.py"
)
assert sha256(r3_root / "r4-INTEGRATION_CONTRACT.md") == next(
    item["sha256"] for item in r4["files"] if item["path"] == "INTEGRATION_CONTRACT.md"
)
old_nodes = ast_nodes(r3_module)
new_nodes = ast_nodes(R4_ROOT / "account_actor_port.py")
for name in (
    "classify_store_route",
    "require_account_actor_before_local_client",
    "_collect_config_routes",
    "_collect_symbol_routes",
    "_collect_nested_selector_fields",
    "_selector",
    "_venue",
):
    assert old_nodes[name] == new_nodes[name], name
    print(f"AST-EQUAL {name}")
print("UPSTREAM-CONTRACTS-PASS")
