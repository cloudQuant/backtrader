import hashlib,json,subprocess,sys,types
from pathlib import Path
R=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_base')
T=Path('/tmp/iter63-r30-primary')
sys.path[:0]=[str(R/'src'),str(R/'tests')]
mode=sys.argv[1];assert mode in ('old','new')
head='f117c0bea16e77bee87451d8c1dbe3ba790f705c'
if mode=='old':
 for name in ('gateway_execution_protocol','gateway_execution_stream_protocol'):
  full='bt_api_base.'+name
  source=subprocess.check_output(['git','-C',str(R),'show',head+':src/bt_api_base/'+name+'.py'])
  module=types.ModuleType(full);module.__file__='<git:'+head+':'+name+'>';sys.modules[full]=module
  exec(compile(source,module.__file__,'exec'),module.__dict__)
from test_gateway_execution_protocol import trade
from test_gateway_execution_stream_protocol import consumer,page
from test_gateway_execution_cancel_attribution import _cancel_fact
from test_gateway_execution_place_attribution import place_fact
trade=trade.__wrapped__();page=page.__wrapped__(trade,consumer.__wrapped__())
result={'facts':[x.to_mapping() for x in (trade,_cancel_fact(trade),place_fact(trade))],
'fact_digests':[x.fact_digest() for x in (trade,_cancel_fact(trade),place_fact(trade))],
'content_digest':trade.trade_content_digest(),'page':page.to_mapping(),'observation':page.events[0].observation.to_mapping()}
encoded=json.dumps(result,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('ascii')
(T/(mode+'-codec.json')).write_bytes(encoded)
print(mode,head,hashlib.sha256(encoded).hexdigest())
