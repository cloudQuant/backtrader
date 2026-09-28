import json, pathlib, xml.etree.ElementTree as ET
root=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-independent-qa-20260927')
out={}
for name in ('baseline','candidate'):
    p=root/'independent-evidence'/(name+'.xml')
    suite=ET.parse(str(p)).getroot(); suites=list(suite.iter('testsuite'))
    failures=[]
    for ts in suites:
        for tc in ts.findall('testcase'):
            f=tc.find('failure')
            if f is not None: failures.append({'classname':tc.get('classname'),'name':tc.get('name'),'message':f.get('message')})
    out[name]={'tests':sum(int(s.get('tests','0')) for s in suites),'failures':sum(int(s.get('failures','0')) for s in suites),'errors':sum(int(s.get('errors','0')) for s in suites),'skipped':sum(int(s.get('skipped','0')) for s in suites),'failing_nodes':failures}
print(json.dumps(out,sort_keys=True,indent=2))
