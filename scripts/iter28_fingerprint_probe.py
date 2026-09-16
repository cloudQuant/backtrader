"""AC28-14: source-fingerprint closure over the split execution files.

For each split file (facade + 8 private modules + package init):
  1. mutate a byte in a temp copy of the repo file,
  2. hash the copied runtime/source inputs via the approval module,
  3. assert the mutated file's hash changed and is present in the fingerprint
     inputs,
  4. assert the fingerprint changes and a missing copied file is rejected.

Runs entirely on temporary copies; the active checkout is never mutated.
This restricted hash probe does not verify signed receipts or SDK provenance.
"""

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


def load_module():
    sys.path.insert(0, str(REPO))
    import examples.strategy_candidate_approval as mod

    return mod


def snapshot_inputs(mod, directory):
    """Copy each distinct input once, preserving runtime/source aliasing."""
    copied = {}
    inputs = {}
    for label, module_name, distribution in mod.RUNTIME_SOURCE_MODULES:
        if distribution != "backtrader":
            continue
        runtime = Path(mod._module_artifact(module_name)).resolve()
        source_root = mod._git_root(runtime.parent)
        source = source_root / runtime.relative_to(source_root) if source_root else runtime
        pair = []
        for original in (runtime, source):
            original = original.resolve()
            if original not in copied:
                target = Path(directory) / f"{len(copied)}.py"
                shutil.copyfile(original, target)
                copied[original] = target
            pair.append(copied[original])
        inputs[label] = (runtime, *pair)
    return inputs


def partial_provenance(mod, inputs):
    """Provenance restricted to the backtrader distribution labels.

    The full collector fail-closes without an installed bt_api_py wheel on
    this machine (same early-return as test_cross_exchange_demo_contract).
    The split-file closure properties are verifiable from the backtrader
    labels alone.
    """
    runtime_files = {}
    source_files = {}
    for label, (_original, runtime_path, source_path) in inputs.items():
        runtime_files[label] = mod._file_sha256(runtime_path, label)
        source_files[label] = mod._file_sha256(source_path, label)
    payload = {"runtime_files": runtime_files, "source_files": source_files}
    payload["fingerprint_sha256"] = mod.canonical_sha256(payload)
    return payload


def probe_snapshot(mod, inputs):
    """Mutate only the copied inputs; callers retain the temporary directory."""
    results = {}
    prov_before = partial_provenance(mod, inputs)
    for rel in SPLIT_FILES:
        label = next(
            (label for label, paths in inputs.items() if paths[0] == (REPO / rel).resolve()),
            None,
        )
        if label is None:
            results[rel] = {"status": "FAIL", "reason": "not covered by RUNTIME_SOURCE_MODULES"}
            continue
        targets = {path: path.read_bytes() for path in inputs[label][1:]}
        try:
            for target, original in targets.items():
                target.write_bytes(original + b"\n# iter28 fingerprint probe mutation\n")
            prov_after = partial_provenance(mod, inputs)
            changed = prov_before["runtime_files"][label] != prov_after["runtime_files"][label]
            source_changed = prov_before["source_files"][label] != prov_after["source_files"][label]
            fp_changed = prov_before["fingerprint_sha256"] != prov_after["fingerprint_sha256"]
            inputs[label][1].unlink()
            missing_rejected = False
            try:
                partial_provenance(mod, inputs)
            except mod.DemoApprovalVerificationError:
                missing_rejected = True
            results[rel] = {
                "status": (
                    "PASS"
                    if all((changed, source_changed, fp_changed, missing_rejected))
                    else "FAIL"
                ),
                "label": label,
                "runtime_hash_changed": changed,
                "source_hash_changed": source_changed,
                "fingerprint_changed": fp_changed,
                "missing_file_rejected": missing_rejected,
            }
        finally:
            for target, original in targets.items():
                target.write_bytes(original)

    ok = all(v["status"] == "PASS" for v in results.values())
    prov_restored = partial_provenance(mod, inputs)
    restored_equal = prov_restored["fingerprint_sha256"] == prov_before["fingerprint_sha256"]
    out = {
        "per_file": results,
        "all_pass": ok,
        "restored_equal": restored_equal,
        "scope": "temporary copies of backtrader hash inputs only; SDK provenance and signed receipts are not verified by this probe",
    }
    return out


def main():
    mod = load_module()
    with tempfile.TemporaryDirectory(prefix="iter28-fingerprint-") as directory:
        out = probe_snapshot(mod, snapshot_inputs(mod, directory))
    print(json.dumps(out, indent=1))
    return 0 if out["all_pass"] and out["restored_equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
