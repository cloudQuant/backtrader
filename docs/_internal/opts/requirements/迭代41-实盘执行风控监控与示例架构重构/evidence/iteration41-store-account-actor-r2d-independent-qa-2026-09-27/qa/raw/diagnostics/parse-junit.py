import json, pathlib, xml.etree.ElementTree as ET
root=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-independent-qa-20260927')
out={}
for name in ('baseline','candidate'):
    p=root/'independent-evidence'/(name+'.xml')
    tree=ET.parse(str(p)); suite=tree.getroot()
    failures=[]
    for tc in suite.iter('testcase'):
        f=tc.find('failure')
        if f is not None: failures.append({'nodeid':tc.get('classname')+'.'+tc.get('name'),'message':f.get('message'),'text':(f.text or '').splitlines()[:3]})
    out[name]={'tests':int(suite.get('tests','0')),'failures':int(suite.get('failures','0')),'errors':int(suite.get('errors','0')),'skipped':int(suite.get('skipped','0')),'failing_nodes':failures}
print(json.dumps(out,sort_keys=True,indent=2))
