import copy,json,tempfile
from pathlib import Path
from backtrader.live_state import StrategyStateDir
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _v4,_upgrade,_snapshot
from backtrader.live_state.gateway_execution_state import _json_bytes
with tempfile.TemporaryDirectory(dir='/tmp/iter63-r31-review-pending') as tmp:
 p=Path(tmp)/'strategy'; p.mkdir(); state=StrategyStateDir.initialize(p)
 binding,_,make=inputs.__wrapped__(state)
 _v4(state,binding)
 ref,snapshot=_snapshot()
 rawsize=len(_json_bytes(snapshot))
 host=_upgrade(state,binding,max_order_snapshot_bytes=rawsize*3)
 host.save_order_intent(make(),local_seq=1,bt_ref=ref,snapshot=snapshot)
 second=copy.deepcopy(snapshot)
 second['state']['orders']['key-b']=second['state']['orders'].pop('key-a')
 host.save_order_intent(make('key-b'),local_seq=2,bt_ref=ref,snapshot=second)
 snaps=host.iter_order_snapshots()
 print('saved refs:',[(key,v['local_seq'],v['bt_ref']) for key,v in snaps.items()])
 print('size limit:',rawsize*3,'snapshot payload bytes:',sum(len(_json_bytes(v['snapshot'])) for v in snaps.values()),'entire snapshots mapping bytes:',len(_json_bytes(snaps)))
