import hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(r'D:\temp\iteration41-r2c-independent-qa-20260927')
inputs={
 'r2b_main':Path(r'D:\temp\iteration41-r2b-main-unit-store-runtime.xml'),
 'r2c_author':Path(r'D:\temp\iteration41-r2c-unit-store-runtime-final.xml'),
 'r2c_independent_reviewed':ROOT/'stores-runtime-reviewed-r2c.xml',
 'focus44':ROOT/'r2c-route-focus-reviewed.xml',
 'query7':ROOT/'query-reviewed-r2c.xml',
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def parse(p):
 root=ET.parse(p).getroot(); rows=[]
 for tc in root.iter('testcase'):
  failed=any(x.tag in ('failure','error') for x in list(tc))
  skipped=any(x.tag=='skipped' for x in list(tc))
  rows.append({'file':tc.attrib.get('file',''),'classname':tc.attrib.get('classname',''),'name':tc.attrib.get('name',''),'failed':failed,'skipped':skipped})
 return root.attrib,rows
data={k:(p,parse(p)) for k,p in inputs.items()}
def node(r): return r['classname']+'::'+r['name']
def failed(rows): return sorted([node(x) for x in rows if x['failed']])
def counts(rows): return {'cases':len(rows),'passed':sum(not r['failed'] and not r['skipped'] for r in rows),'failed':sum(r['failed'] for r in rows),'skipped':sum(r['skipped'] for r in rows)}
out={'junit_inputs':{},'r2b_vs_reviewed_failure_identity':{},'reviewed_vs_author_node_delta':{},'focus_nodeids':{},'all_258_reviewed_failures':failed(data['r2c_independent_reviewed'][1][1])}
for k,(p,(attrs,rows)) in data.items(): out['junit_inputs'][k]={'path':str(p),'sha256':sha(p),'counts':counts(rows),'suite_attributes':attrs}
bset=set(failed(data['r2b_main'][1][1])); rset=set(failed(data['r2c_independent_reviewed'][1][1])); out['r2b_vs_reviewed_failure_identity']={'baseline_count':len(bset),'reviewed_count':len(rset),'intersection':len(bset&rset),'r2b_only':sorted(bset-rset),'reviewed_only':sorted(rset-bset),'exact_match':bset==rset}
a_nodes={node(r) for r in data['r2c_author'][1][1]}; i_nodes={node(r) for r in data['r2c_independent_reviewed'][1][1]}; out['reviewed_vs_author_node_delta']={'independent_only':sorted(i_nodes-a_nodes),'author_only':sorted(a_nodes-i_nodes)}
out['focus_nodeids']={'route_focus44':[node(r) for r in data['focus44'][1][1]],'query_focus7':[node(r) for r in data['query7'][1][1]]}
(ROOT/'exact-nodeid-comparison-reviewed-r2c.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='all_258_reviewed_failures' and k!='focus_nodeids'},indent=2,ensure_ascii=False))
print('route_focus=',len(out['focus_nodeids']['route_focus44']),'query=',len(out['focus_nodeids']['query_focus7']),'failure_ids=',len(out['all_258_reviewed_failures']))
