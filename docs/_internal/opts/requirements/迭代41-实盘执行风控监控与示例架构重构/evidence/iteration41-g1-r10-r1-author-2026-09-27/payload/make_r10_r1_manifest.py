import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PAYLOAD = [
    "r10_custodian.cpp", "r10_custodian.exe", "r10_custodian.obj",
    "r10_sacrificial_popen.py", "run_r10_r1_trials.py", "run_r10_trials_r10_frozen.py",
    "r10_r1_trials_initial.json", "r10_r1_trials.json",
    "r10_build.bat", "r10_build.log", "r10r1_build.bat",
    "r1_first_build_failure.log", "r1_source_compile_failure.log",
    "r1_first_test_failure_late_admission.txt", "r10_r1_trials_failure-late-admission-tick-mismatch.json",
    "R10R1_FINDINGS.md", "r10_r1_final_run.log", "make_r10_r1_manifest.py",
    "R10_BASELINE/r10_custodian.cpp", "R10_BASELINE/r10_trials.json",
    "R10_BASELINE/r10_manifest.json", "R10_BASELINE/r10_receipt.json",
    "R10_BASELINE/R10_FINDINGS.md",
]
trials = json.loads((ROOT / "r10_r1_trials.json").read_text(encoding="utf-8"))
baseline_source = sha(ROOT / "R10_BASELINE/r10_custodian.cpp")
baseline_trials = sha(ROOT / "R10_BASELINE/r10_trials.json")
manifest = {
    "candidate": trials["candidate"],
    "status": trials["status"],
    "payload_sha256": {name: sha(ROOT / name) for name in PAYLOAD},
    "final_trials_sha256": sha(ROOT / "r10_r1_trials.json"),
    "final_source_sha256": sha(ROOT / "r10_custodian.cpp"),
    "final_binary_sha256": sha(ROOT / "r10_custodian.exe"),
    "final_object_sha256": sha(ROOT / "r10_custodian.obj"),
    "r10_frozen_reference": {
        "source_sha256_actual": baseline_source,
        "source_sha256_expected": "4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3",
        "trials_sha256_actual": baseline_trials,
        "trials_sha256_expected": "ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5",
        "both_match": baseline_source == "4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3" and
                      baseline_trials == "ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5",
    },
    "final_check_count": len(trials["checks"]),
    "final_failed_check_count": len(trials["failed_checks"]),
    "interim_trial_note": "r10_r1_trials_initial.json is an earlier interim run without a contemporaneous source hash; final claims are bound to final source and trials hashes below.",
    "decision": trials["decision"],
    "limits": [
        "The test deadline begins at the GO barrier; whole-command hard D is not proven.",
        "P02/P03 true CreateProcessW kernel hangs, P14, higher-custodian failure, and SCM/service lifecycle are not tested.",
        "Injected cancellation failure skips CancelIoEx and is not a real Win32 failure/delayed kernel completion.",
        "Retained cases use external outer-Job termination after recording UNKNOWN; this is fixture teardown, not release proof.",
        "No CTP/provider/SDK/credentials/private config/account/network/default preflight was used; G1 remains closed.",
    ],
    "repository_effect": "An Iteration 41 author-evidence archive is being added; no production/default-route source is changed.",
}
manifest_path = ROOT / "r10_r1_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
manifest_sha = sha(manifest_path)
(ROOT / "r10_r1_manifest.sha256").write_text(f"{manifest_sha}  r10_r1_manifest.json\n", encoding="ascii")
receipt = {
    "manifest": "r10_r1_manifest.json",
    "manifest_sha256": manifest_sha,
    "source_sha256": sha(ROOT / "r10_custodian.cpp"),
    "binary_sha256": sha(ROOT / "r10_custodian.exe"),
    "trials_sha256": sha(ROOT / "r10_r1_trials.json"),
    "findings_sha256": sha(ROOT / "R10R1_FINDINGS.md"),
    "status": trials["status"],
    "checks": len(trials["checks"]),
    "failed_checks": len(trials["failed_checks"]),
    "no_production_or_default_route_changes": True,
    "no_provider_or_credentials": True,
    "decision": trials["decision"],
}
receipt_path = ROOT / "r10_r1_receipt.json"
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(ROOT / "r10_r1_receipt.sha256").write_text(f"{sha(receipt_path)}  r10_r1_receipt.json\n", encoding="ascii")
sum_files = sorted(p for p in ROOT.rglob("*") if p.is_file() and
                   p.name not in {"SHA256SUMS.txt", "SHA256SUMS.sha256"} and
                   p.name not in {"r10_r1_source_initial.cpp", "summarize_tmp.ps1"} and
                   "__pycache__" not in p.parts and ".tmp" not in p.parts)
lines = [f"{sha(p)}  {p.relative_to(ROOT).as_posix()}" for p in sum_files]
sums_path = ROOT / "SHA256SUMS.txt"
sums_path.write_text("\n".join(lines) + "\n", encoding="ascii")
(ROOT / "SHA256SUMS.sha256").write_text(f"{sha(sums_path)}  SHA256SUMS.txt\n", encoding="ascii")
print(json.dumps({
    "manifest_sha256": manifest_sha,
    "receipt_sha256": sha(receipt_path),
    "source_sha256": sha(ROOT / "r10_custodian.cpp"),
    "binary_sha256": sha(ROOT / "r10_custodian.exe"),
    "trials_sha256": sha(ROOT / "r10_r1_trials.json"),
    "findings_sha256": sha(ROOT / "R10R1_FINDINGS.md"),
    "sha256sums_sha256": sha(sums_path),
    "payload_count": len(PAYLOAD),
    "frozen_r10_inputs_match": manifest["r10_frozen_reference"]["both_match"],
}, indent=2))
