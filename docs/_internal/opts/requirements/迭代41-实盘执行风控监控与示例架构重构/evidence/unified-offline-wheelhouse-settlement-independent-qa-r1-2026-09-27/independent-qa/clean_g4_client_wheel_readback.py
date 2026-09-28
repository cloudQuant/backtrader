import hashlib,zipfile,json
from pathlib import Path
root=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
wheel=root/'wheelhouse'/'bt_api_ctp-2.0.4+g4r2.settlement.probe.20260927-cp311-cp311-win_amd64.whl'
with zipfile.ZipFile(wheel) as z:
 raw=z.read('bt_api_ctp/ctp/client.py')
 s=raw.decode('utf-8').splitlines()
 digest=hashlib.sha256(raw).hexdigest()
 def window(start,end):return '\n'.join(f'{i+1}: {s[i]}' for i in range(start-1,end))
 q='\n'.join(s[8020:8051]); e='\n'.join(s[7490:7547])
 result={'wheel_client_sha256':digest,'matches_clean_g4_client_sha256':digest.lower()=='c217be3e064272327535da7edf4b4ed4d587845f03aa11c4669699417c14e6ff','settlement_method_has_filter_binding':'request_filter_field' in q and 'request_intent_filters' in q,'execute_query_reads_native_filter_getters':'_read_native_query_filter_items(' in e and 'request_filter_field' in e and 'request_intent_items' in e,'line_windows':{'settlement_8021_8051':window(8021,8051),'execute_query_7491_7547':window(7491,7547)}}
Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\evidence\clean-g4-client-wheel-readback.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='line_windows'},indent=2))
if not result['matches_clean_g4_client_sha256'] or not result['settlement_method_has_filter_binding'] or not result['execute_query_reads_native_filter_getters']:raise SystemExit(1)
