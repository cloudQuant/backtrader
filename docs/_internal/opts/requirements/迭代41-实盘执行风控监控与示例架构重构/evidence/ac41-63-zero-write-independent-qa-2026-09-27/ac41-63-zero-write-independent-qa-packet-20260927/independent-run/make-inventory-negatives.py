import copy,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); original=root/'evidence'/'ac41-63'/'live-execution-inventory-candidates.json'; base=json.loads(original.read_text(encoding='utf-8'))
match='examples/007_ctp/live_certification/simnow_penetration/cases/T01_open_order.py'
rows=[r for r in base['writer_candidates'] if r.get('path')==match]
if len(rows)!=1: raise SystemExit('expected one open-order writer row, got '+str(len(rows)))
outdir=root/'evidence'/'qa-negative'; outdir.mkdir(parents=True,exist_ok=True)
aug=copy.deepcopy(base); aug['writer_candidates'].append({'kind':'writer_call_candidate','path':'examples/qa_only/uncovered_submit_writer.py','line':23,'call':'fake_broker.submit','method':'submit','class_name':'SyntheticUnexecutedStrategy','function_name':'next','review_status':'REVIEW_REQUIRED'})
( outdir/'augmented-uncovered-writer.json').write_text(json.dumps(aug,sort_keys=True,indent=2)+'\n',encoding='utf-8')
reduced=copy.deepcopy(base); reduced['writer_candidates']=[r for r in reduced['writer_candidates'] if r.get('path')!=match]; reduced['counts']['writer_candidates']-=len(rows)
( outdir/'deliberately-weakened-inventory.json').write_text(json.dumps(reduced,sort_keys=True,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'baseline_inventory_writer_rows':len(base['writer_candidates']),'target_path':match,'target_rows':rows,'augmented_writer_rows':len(aug['writer_candidates']),'weakened_writer_rows':len(reduced['writer_candidates']),'outputs':[str(outdir/'augmented-uncovered-writer.json'),str(outdir/'deliberately-weakened-inventory.json')]},indent=2))