import copy,json,tempfile
from pathlib import Path
from backtrader.live_state import StrategyStateDir, LiveStateCorrupt
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_pending import inputs,data
from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _v4,_upgrade,_snapshot
with tempfile.TemporaryDirectory(dir='/tmp/iter63-r31-review-pending') as tmp:
 path=Path(tmp)/'strategy';path.mkdir();state=StrategyStateDir.initialize(path)
 binding,_,make=inputs.__wrapped__(state)
 _v4(state,binding);host=_upgrade(state,binding)
 ref_a,snap_a=_snapshot();ref_b,snap_b=_snapshot('key-b');assert ref_a!=ref_b
 host.save_order_intent(make(),local_seq=1,bt_ref=ref_a,snapshot=snap_a)
 before=data(state)
 host.save_order_intent(make(),local_seq=1,bt_ref=ref_a,snapshot=copy.deepcopy(snap_a))
 assert before==data(state)
 duplicate=copy.deepcopy(snap_b);duplicate['state']['orders']['key-b']['ref']=ref_a
 try:host.save_order_intent(make('key-b'),local_seq=2,bt_ref=ref_a,snapshot=duplicate)
 except ValueError as exc:
  assert str(exc)=='GATEWAY_ORDER_SNAPSHOT_REF_CONFLICT';print('duplicate rejected:',str(exc))
 else:raise AssertionError('duplicate accepted')
 assert before==data(state) and host.load_intent('key-b') is None
 print('failed save leaves bytes unchanged; same-key retry unchanged')
 host.save_order_intent(make('key-b'),local_seq=2,bt_ref=ref_b,snapshot=snap_b)
 assert len(host.iter_order_snapshots())==2
 forged=json.loads(data(state));forged['gateway']['intents']['key-b']['bt_ref']=ref_a
 env=forged['gateway']['order_snapshots']['key-b'];env['bt_ref']=ref_a
 env['snapshot']['state']['orders']['key-b']['ref']=ref_a
 with open(state.pending.path,'w',encoding='utf-8') as file:json.dump(forged,file)
 reopened=GatewayPendingHost(state.strategy_dir,state.strategy_uuid,binding)
 try:reopened.iter_order_snapshots()
 except LiveStateCorrupt as exc:print('reopen rejects forged collision:',type(exc).__name__)
 else:raise AssertionError('forged collision accepted')
 print('different refs accepted')
