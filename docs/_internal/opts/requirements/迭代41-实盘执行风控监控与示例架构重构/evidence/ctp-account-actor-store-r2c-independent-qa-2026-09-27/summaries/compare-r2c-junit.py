import json, xml.etree.ElementTree as ET
from pathlib import Path
files={
 'r2b_main':Path(r'D:\temp\iteration41-r2b-main-unit-store-runtime.xml'),
 'r2c_author':Path(r'D:\temp\iteration41-r2c-unit-store-runtime-final.xml'),
 'r2c_independent_mismatched':Path(r'D:\temp\iteration41-r2c-independent-qa-20260927\stores-runtime-source-only.xml'),
 'r2c_independent_reviewed':Path(r'D:\temp\iteration41-r2c-independent-qa-20260927\stores-runtime-reviewed-r2c.xml'),
}
def parse(path):
 root=ET.parse(path).getroot(); out=[]
 for tc in root.iter('testcase'):
  out.append({'file':tc.attrib.get('file',''),'classname':tc.attrib.get('classname',''),'name':tc.attrib.get('name',''),'failed':any(x.tag in ('failure','error') for x in list(tc)),'skipped':any(x.tag=='skipped' for x in list(tc))})
 return root.attrib,out
parsed={k:parse(v) for k,v in files.items() if v.exists()}
def keys(rows): return {(r['classname'],r['name']) for r in rows}
def failed(rows): return {(r['classname'],r['name']) for r in rows if r['failed']}
def status_counts(rows): return {'cases':len(rows),'failed':sum(r['failed'] for r in rows),'skipped':sum(r['skipped'] for r in rows),'passed':sum(not r['failed'] and not r['skipped'] for r in rows)}
summary={k:{'path':str(files[k]),'counts':status_counts(v[1])} for k,v in parsed.items()}
if all(k in parsed for k in ('r2b_main','r2c_author','r2c_independent_reviewed')):
 b=failed(parsed['r2b_main'][1]); a=failed(parsed['r2c_author'][1]); r=failed(parsed['r2c_independent_reviewed'][1])
 bnodes=keys(parsed['r2b_main'][1]); anodes=keys(parsed['r2c_author'][1]); rnodes=keys(parsed['r2c_independent_reviewed'][1])
 summary['r2b_vs_independent_failure_ids']={'r2b_failed':len(b),'reviewed_failed':len(r),'intersection':len(b&r),'r2b_only':sorted(b-r),'reviewed_only':sorted(r-b),'exact_match':b==r}
 summary['all_node_id_deltas']={
  'r2c_author_minus_r2b':sorted(anodes-bnodes),'r2b_minus_r2c_author':sorted(bnodes-anodes),
  'independent_minus_r2c_author':sorted(rnodes-anodes),'r2c_author_minus_independent':sorted(anodes-rnodes),
  'r2c_author_nodes':len(anodes),'independent_nodes':len(rnodes)}
out=Path(r'D:\temp\iteration41-r2c-independent-qa-20260927\failure-set-comparison-reviewed-r2c.json')
out.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
