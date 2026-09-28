#!/usr/bin/env python3
"""Read-only audit of frozen R10 evidence. Does not launch processes or call APIs."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path, PurePosixPath
EXPECTED = {
    "r10_manifest.json": "da1252e1e25c20530a9cce358c35a1a90f0729dc7f60da85fe2600dd8790f6c3",
    "r10_receipt.json": "deb34cbe0584710fa41f6623f0febcec0a2a2a71c5ff15e0c54f2fbf39c877c7",
    "r10_trials.json": "ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5",
    "r10_trials_initial.json": "32bca66edba15ae73a7cf8777ecafcaabcd346df4326e69c39c49a44ae781040",
}
def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--candidate-root',type=Path,required=True)
    root=ap.parse_args().candidate_root.resolve(strict=True)
    raw={n:(root/n).read_bytes() for n in EXPECTED}
    actual={n:sha(b) for n,b in raw.items()}
    for n,want in EXPECTED.items():
        if actual[n]!=want: raise SystemExit(f'{n} hash mismatch: {actual[n]}')
    manifest=json.loads(raw['r10_manifest.json']); receipt=json.loads(raw['r10_receipt.json'])
    final=json.loads(raw['r10_trials.json']); initial=json.loads(raw['r10_trials_initial.json'])
    if receipt.get('manifest_sha256')!=actual['r10_manifest.json']: raise SystemExit('receipt manifest binding mismatch')
    verified=[]
    for rel,want in manifest.get('payload_sha256',{}).items():
        path=root.joinpath(*PurePosixPath(rel).parts)
        if not path.is_file() or sha(path.read_bytes())!=want: raise SystemExit(f'payload mismatch: {rel}')
        verified.append(rel)
    row=next(x['scenario'] for x in final['scenarios'] if x.get('scenario',{}).get('mode')=='p05')
    first_failed=[x.get('name') for x in initial.get('failed_checks',[])]
    result={
      'classification':'READ_ONLY_AUTHOR_EVIDENCE_ONLY_G1_CLOSED',
      'payload_hashes_verified':len(verified),
      'final_failed_checks':final.get('failed_checks',[]),
      'initial_failed_checks':first_failed,
      'p05':{'budget_ms':row['request_budget_ms'],'deadline_tick_ms':row['deadline_tick_ms'],
             'submit_elapsed_us':row['caller_submit_elapsed_us'],
             'submit_return_before_D':row['caller_submit_return_before_D'],
             'unknown_tick_ms':row['ticket_unknown_tick_ms'],
             'unknown_lateness_ms':row['ticket_unknown_tick_ms']-row['deadline_tick_ms'],
             'pending_io_at_unknown':row['writer_pending_at_unknown'],'completion_error':row['writer_error']},
      'unproven':{'true_CreateProcessW_hang':'NOT_TESTED; Popen wrapper-only',
                  'P14_terminate_query_close':'NOT_TESTED','SCM':'NOT_TESTED',
                  'OS_hard_scheduling_guarantee':'NOT_PROVEN'},
      'sha256':actual,'no_process_or_provider_access':True}
    print(json.dumps(result,indent=2,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
