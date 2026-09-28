from __future__ import annotations
import hashlib
import json
from pathlib import Path

src = Path(r"D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4")
qa = Path(r"D:\temp\iteration41-ctp-account-actor-port-independent-qa-20260927")
expected_manifest = "8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8"
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def rel_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

manifest_path = src / "manifest.json"
manifest = json.loads(manifest_path.read_bytes())
frozen_inventory = set(rel_files(src))
payload_paths = {item["path"] for item in manifest["files"]}
metadata_paths = {"manifest.json", "manifest.sha256", "receipt.md", "receipt.sha256"}
assert len(payload_paths) == 9
assert frozen_inventory == payload_paths | metadata_paths
assert sha(manifest_path) == expected_manifest
assert (src / "manifest.sha256").read_text(encoding="ascii").split()[0] == expected_manifest
receipt_sha = "ee5fb7d0d3362a7f4d82bbf03d846c92ae542365b6207c173f799ec498293a4f"
assert sha(src / "receipt.md") == receipt_sha
assert (src / "receipt.sha256").read_text(encoding="ascii").split()[0] == receipt_sha

copied_files = []
for item in manifest["files"]:
    source = src / Path(item["path"])
    copied = qa / Path(item["path"])
    actual = sha(source)
    assert source.stat().st_size == item["size_bytes"]
    assert copied.stat().st_size == item["size_bytes"]
    assert actual == sha(copied) == item["sha256"]
    copied_files.append({"path": item["path"], "size_bytes": item["size_bytes"], "sha256": actual})
for name in metadata_paths:
    assert (src / name).read_bytes() == (qa / "candidate-original-metadata" / name).read_bytes()

baseline = (qa / "baseline-unittest.log").read_text(encoding="utf-8-sig")
expanded = (qa / "independent-unittest.log").read_text(encoding="utf-8-sig")
assert "Ran 34 tests" in baseline and "\nOK" in baseline
assert "Ran 41 tests" in expanded and "\nOK" in expanded
probe = qa / "tests" / "test_independent_actor_port_qa.py"
assert probe.exists()
assert not any("__pycache__" in name for name in rel_files(qa))

review = """# Independent AccountActorPort r4 QA

## Frozen-input verification

- Frozen directory: D:\\temp\\iteration41-ctp-account-actor-port-freeze-20260927-r4
- Expected and observed manifest.json SHA-256: 8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8
- Manifest payload entries: 9/9 present; every byte count and SHA-256 matched.
- Frozen directory inventory: exactly the 9 listed payload files plus the four expected metadata sidecars (manifest.json, manifest.sha256, receipt.md, receipt.sha256); no unlisted payload files.
- Receipt SHA-256: ee5fb7d0d3362a7f4d82bbf03d846c92ae542365b6207c173f799ec498293a4f; sidecar matched.
- The independent test copy and probes are under this directory. The frozen candidate was not modified.

## Independent fake-only verification

Interpreter: CPython 3.11.5. No SDK, account, provider, credentials, network, or native client was used.

- Baseline command: python -B -m unittest discover -s tests -v — 34 passed.
- Expanded command after adding tests/test_independent_actor_port_qa.py in the isolated copy: python -B -m unittest discover -s tests -v — 41 passed.
- Probes cover stale epoch, wrong account, wrong receipt action, same-process duplicate intent, fresh-process replay, unkeyed digest tampering/recomputation, injected-object property non-read, and post-construction route descriptor mutation.

## Findings and disposition

Local fake-boundary result: accepted with limits. The exercised harness rejects stale epoch and wrong-account intent contexts before invoking the actor; rejects wrong-action and tampered-digest receipts without local/native fallback; claims an intent once within a shared ledger instance; and does not read the injected object's trap property before rejecting an ambiguous route.

Two material limitations were reproduced:

1. Cross-process replay: after one process claims an intent, a fresh process with a new FakeLocalActorReplayLedger successfully claims the same intent ID. The ledger is in-memory/process-local, not durable idempotency.
2. Route descriptor TOCTOU: StoreBoundaryHarness constructed with provider=okx and config.exchange_type=OKX caches NON_CTP. Mutating the referenced config dictionary to exchange_type=CTP after construction leaves route_kind NON_CTP, and a later submit enters the legacy route. This isolated fake harness does not reclassify or freeze the route descriptor. It is a candidate harness route-mutation gap; the 34/41 passing tests do not establish dynamic route safety or G6-P.

The command digest is plain deterministic SHA-256 with no secret key. Validation detects a changed digest against the locally expected intent, but an actor/message forger able to change the logical payload can recompute it. The digest is not actor authentication or keyed message integrity. ActorCommandContextV1 and actor_epoch are caller-supplied local bindings and do not prove current account/session authority.

No external trusted actor, durable server-side replay store, account-wide writer fence, common provider snapshot, or production route is established. This QA does not accept G6-S/G7-S or any live/write path.
"""
(qa / "qa-review.md").write_text(review, encoding="utf-8", newline="\n")

receipt = {
    "schema": "iteration41-account-actor-port-independent-qa-receipt.v1",
    "candidate": "ctp-account-actor-port-r4",
    "candidate_directory": str(src),
    "candidate_manifest_sha256": expected_manifest,
    "candidate_receipt_sha256": receipt_sha,
    "frozen_payload_count": len(copied_files),
    "frozen_directory_exact_inventory": True,
    "copied_payload": copied_files,
    "runtime": {"python": "3.11.5", "scope": "offline fake-only"},
    "tests": [
        {"command": "python -B -m unittest discover -s tests -v", "passed": 34, "log": "baseline-unittest.log"},
        {"command": "python -B -m unittest discover -s tests -v", "passed": 41, "log": "independent-unittest.log"}
    ],
    "probes": {
        "stale_epoch": "rejected before fake actor call",
        "wrong_account": "rejected before fake actor call",
        "wrong_action": "receipt rejected; no local/native fallback",
        "same_process_duplicate": "rejected by shared in-memory ledger",
        "cross_process_duplicate": "reproduced accepted by fresh process-local ledger",
        "unkeyed_digest_tamper": "altered digest rejected; plain SHA-256 is recomputable",
        "injected_object_property": "rejected without property read",
        "route_descriptor_mutation": "reproduced: cached non-CTP classification persisted after config mutated to CTP"
    },
    "local_disposition": "ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY",
    "external_actor_or_production_authority": "NOT_ESTABLISHED",
    "no_sdk_account_provider_credentials_network_native": True
}
(qa / "qa-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

evidence_files = []
for path in sorted(qa.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(qa).as_posix()
    if relative in {"qa-evidence-manifest.json", "qa-evidence-manifest.sha256"}:
        continue
    evidence_files.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha(path)})
evidence = {
    "schema": "iteration41-account-actor-port-independent-qa-evidence.v1",
    "candidate_manifest_sha256": expected_manifest,
    "result": "ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY",
    "evidence_files": evidence_files,
}
manifest_out = qa / "qa-evidence-manifest.json"
manifest_out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
manifest_out_hash = sha(manifest_out)
(qa / "qa-evidence-manifest.sha256").write_text(f"{manifest_out_hash}  qa-evidence-manifest.json\n", encoding="ascii", newline="\n")
print(json.dumps({
    "candidate_manifest_sha256": expected_manifest,
    "candidate_payload_files": len(copied_files),
    "frozen_inventory_exact": True,
    "baseline_tests": 34,
    "expanded_tests": 41,
    "independent_probe_count": 7,
    "cross_process_replay": "reproduced",
    "route_descriptor_mutation": "reproduced",
    "qa_evidence_file_count": len(evidence_files),
    "qa_evidence_manifest_sha256": manifest_out_hash,
    "result": "ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY",
}, indent=2))
