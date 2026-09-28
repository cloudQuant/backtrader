import copy,hashlib,importlib.util,json,sys
from pathlib import Path
repo=Path(r'D:\source_code\backtrader'); scratch=Path(r'D:\temp\ac41-63-writer-rebaseline-independent-qa-20260927\exact-current-base-replay')
script=scratch/'scripts/verify_iteration41_writer_dispositions.py'
spec=importlib.util.spec_from_file_location('qa_candidate_verifier',script); module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
collector=module._load_inventory_collector(); inventory=collector.collect_inventory(repo)
checklist=json.loads((scratch/'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-writer-dispositions.json').read_text(encoding='utf-8'))
probes=[]
def run(label,mutate):
 c=copy.deepcopy(checklist); mutate(c)
 try:
  result=module.validate_disposition_checklist(inventory,c)
  probes.append({'case':label,'status':result['status'],'reason_codes':result['reason_codes'][:10]})
 except Exception as e:
  probes.append({'case':label,'exception':type(e).__name__+': '+str(e)})
run('valid-control',lambda c:None)
run('preservation-key-removed',lambda c:c.pop('baseline_preservation'))
run('preservation-null',lambda c:c.__setitem__('baseline_preservation',None))
run('preservation-wrong-container',lambda c:c.__setitem__('baseline_preservation',[]))
run('previous-445-ids-null',lambda c:c['baseline_preservation'].__setitem__('previous_445_candidate_ids_in_order',None))
run('removed-tombstone-ids-null',lambda c:c['baseline_preservation'].__setitem__('removed_to_historical_tombstones',None))
run('new-g6-ids-null',lambda c:c['baseline_preservation'].__setitem__('new_g6_candidate_ids',None))
run('baseline-389-ids-null',lambda c:c['baseline_preservation'].__setitem__('baseline_candidate_ids_in_order',None))
run('removed-tombstone-ids-wrong-list',lambda c:c['baseline_preservation'].__setitem__('removed_to_historical_tombstones',[{'x':1}]))
run('new-g6-ids-wrong-list',lambda c:c['baseline_preservation'].__setitem__('new_g6_candidate_ids',[{'x':1}]))
out={'current_inventory_counts':inventory['counts'],'candidate_control':probes[0],'malformed_preservation_probes':probes[1:]}
Path(r'D:\temp\ac41-63-writer-rebaseline-independent-qa-20260927\preservation-probes.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print(json.dumps(out,indent=2))
