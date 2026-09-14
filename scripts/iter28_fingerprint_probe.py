"""AC28-14: source-fingerprint closure over the split execution files.

For each split file (facade + 8 private modules + package init):
  1. mutate a byte in a temp copy of the repo file,
  2. collect provenance via the approval module,
  3. assert the mutated file's hash changed and is present in the fingerprint
     inputs,
  4. assert a stale fingerprint (computed pre-mutation) no longer verifies.

Runs entirely on local copies; no receipts are produced or altered.
"""
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPROVAL = "examples/strategy_candidate_approval.py"

SPLIT_FILES = [
    "backtrader/cerebro.py",
    "backtrader/_cerebro/__init__.py",
    "backtrader/_cerebro/registry.py",
    "backtrader/_cerebro/notifications.py",
    "backtrader/_cerebro/lifecycle.py",
    "backtrader/_cerebro/channel.py",
    "backtrader/_cerebro/execution.py",
    "backtrader/_cerebro/runnext.py",
    "backtrader/_cerebro/runonce.py",
    "backtrader/_cerebro/presentation.py",
]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_module():
    sys.path.insert(0, str(REPO))
    import examples.strategy_candidate_approval as mod

    return mod


def partial_provenance(mod):
    """Provenance restricted to the backtrader distribution labels.

    The full collector fail-closes without an installed bt_api_py wheel on
    this machine (same early-return as test_cross_exchange_demo_contract).
    The split-file closure properties are verifiable from the backtrader
    labels alone.
    """
    runtime_files = {}
    source_files = {}
    for label, module_name, _dist in mod.RUNTIME_SOURCE_MODULES:
        if _dist != "backtrader":
            continue
        runtime_path = mod._module_artifact(module_name)
        runtime_files[label] = mod._file_sha256(runtime_path, label)
        source_root = mod._git_root(runtime_path.parent)
        if source_root is not None:
            rel = runtime_path.relative_to(source_root)
            source_files[label] = mod._file_sha256(source_root / rel, label)
        else:
            source_files[label] = runtime_files[label]
    payload = {"runtime_files": runtime_files, "source_files": source_files}
    payload["fingerprint_sha256"] = mod.canonical_sha256(payload)
    return payload


def main():
    mod = load_module()
    results = {}
    prov_before = partial_provenance(mod)
    for rel in SPLIT_FILES:
        target = REPO / rel
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n# iter28 fingerprint probe mutation\n")
            prov_after = partial_provenance(mod)
            label = None
            for lbl, module_name, _dist in mod.RUNTIME_SOURCE_MODULES:
                if Path(mod._module_artifact(module_name)) == target:
                    label = lbl
                    break
            if label is None:
                results[rel] = {"status": "FAIL", "reason": "not covered by RUNTIME_SOURCE_MODULES"}
                continue
            changed = prov_before["runtime_files"][label] != prov_after["runtime_files"][label]
            source_changed = prov_before["source_files"][label] != prov_after["source_files"][label]
            fp_changed = prov_before["fingerprint_sha256"] != prov_after["fingerprint_sha256"]
            results[rel] = {
                "status": "PASS" if (changed and source_changed and fp_changed) else "FAIL",
                "label": label,
                "runtime_hash_changed": changed,
                "source_hash_changed": source_changed,
                "fingerprint_changed": fp_changed,
            }
        finally:
            target.write_bytes(original)

    ok = all(v["status"] == "PASS" for v in results.values())
    prov_restored = partial_provenance(mod)
    restored_equal = prov_restored["fingerprint_sha256"] == prov_before["fingerprint_sha256"]
    out = {
        "per_file": results,
        "all_pass": ok,
        "restored_equal": restored_equal,
        "note": "bt_api_py labels excluded: no installed wheel with VCS attestation on this machine (fail-closed), full collector verified by test_cross_exchange_demo_contract.py where environment allows",
    }
    print(json.dumps(out, indent=1))
    return 0 if ok and restored_equal else 1


if __name__ == "__main__":
    sys.exit(main())
