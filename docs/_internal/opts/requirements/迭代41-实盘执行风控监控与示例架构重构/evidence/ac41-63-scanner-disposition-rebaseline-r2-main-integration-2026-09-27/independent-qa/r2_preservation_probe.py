from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'full-current-source-replay-r2'
SCRIPT = ROOT / 'scripts' / 'verify_iteration41_writer_dispositions.py'
CHECKLIST = ROOT / 'docs' / '_internal' / 'opts' / 'requirements' / '迭代41-实盘执行风控监控与示例架构重构' / 'evidence' / 'live-execution-writer-dispositions.json'
spec = importlib.util.spec_from_file_location('qa_candidate_verifier', SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
checklist = json.loads(CHECKLIST.read_text(encoding='utf-8'))
collector = module._load_inventory_collector()
inventory = collector.collect_inventory(ROOT)

def check(name, mutate):
    value = copy.deepcopy(checklist)
    mutate(value)
    try:
        result = module.validate_disposition_checklist(inventory, value)
        return {'case': name, 'status': result['status'], 'reason_codes': result['reason_codes']}
    except Exception as exc:
        return {'case': name, 'exception': f'{type(exc).__name__}: {exc}'}

cases = [
    check('valid_control', lambda c: None),
    check('baseline_preservation_missing', lambda c: c.pop('baseline_preservation', None)),
    check('baseline_preservation_null', lambda c: c.__setitem__('baseline_preservation', None)),
    check('preservation_and_history_and_lineage_missing', lambda c: [c.pop(k, None) for k in ('baseline_preservation', 'historical_tombstones', 'tombstone_lineage')]),
    check('lineage_missing', lambda c: c.pop('tombstone_lineage', None)),
    check('baseline_ids_null', lambda c: c['baseline_preservation'].__setitem__('baseline_candidate_ids_in_order', None)),
    check('baseline_ids_object_member', lambda c: c['baseline_preservation'].__setitem__('baseline_candidate_ids_in_order', [{}] + c['baseline_preservation']['baseline_candidate_ids_in_order'][1:])),
    check('previous_ids_null', lambda c: c['baseline_preservation'].__setitem__('previous_445_candidate_ids_in_order', None)),
    check('previous_ids_object_member', lambda c: c['baseline_preservation'].__setitem__('previous_445_candidate_ids_in_order', [{}] + c['baseline_preservation']['previous_445_candidate_ids_in_order'][1:])),
    check('removed_ids_null', lambda c: c['baseline_preservation'].__setitem__('removed_to_historical_tombstones', None)),
    check('removed_ids_object_member', lambda c: c['baseline_preservation'].__setitem__('removed_to_historical_tombstones', [{}] + c['baseline_preservation']['removed_to_historical_tombstones'][1:])),
    check('new_ids_null', lambda c: c['baseline_preservation'].__setitem__('new_g6_candidate_ids', None)),
    check('new_ids_object_member', lambda c: c['baseline_preservation'].__setitem__('new_g6_candidate_ids', [{}] + c['baseline_preservation']['new_g6_candidate_ids'][1:])),
]
summary = {'root': str(ROOT), 'inventory_counts': inventory['counts'], 'candidate_checklist_sha256': hashlib.sha256(CHECKLIST.read_bytes()).hexdigest(), 'cases': cases}
out = Path(__file__).with_name('r2-preservation-probes.json')
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
