from __future__ import annotations
import hashlib, json, multiprocessing as mp, os, sys, tempfile
from pathlib import Path
ROOT = Path(r'D:\temp\iteration41-g5-order-authority-independent-qa-20260927')
CAND = ROOT / 'candidate'; sys.path.insert(0, str(CAND / 'src'))
from bt_api_execution import CtpCancelTarget, CtpDispatchReceipt, CtpOrderRefSeedProof, ExecutionScope, SqliteExecutionStore
from bt_api_execution.ctp_identity_authority import CtpActionRefSeedProof, CtpUnifiedOrderActionAuthority
OWNER='qa-multiprocess-owner'; SCOPE_ARGS=('CTP','simulation','g5-multiprocess-account','strategy.g5.multiprocess','20260927')
def scope(): return ExecutionScope(*SCOPE_ARGS)
def runtime(): return 'bt-managed-v1:'+hashlib.sha256(b'qa-runtime').hexdigest()
def order_seed(): return CtpOrderRefSeedProof('20260927','000000000010','000000000012',hashlib.sha256(b'legacy').hexdigest())
def action_seed(): return CtpActionRefSeedProof('20260927',41,hashlib.sha256(b'action-legacy').hexdigest())
def target(ref): return CtpCancelTarget(ref,'SHFE','SYS-QA',11,12)
def request(t): return {'InstrumentID':'rb2710','OrderRef':t.order_ref,'ExchangeID':t.exchange_id,'OrderSysID':t.order_sys_id,'FrontID':t.front_id,'SessionID':t.session_id,'ActionFlag':'0','LimitPrice':0.0,'VolumeChange':0}
def reserve_worker(args):
    path,idx,try_unknown,barrier=args; store=SqliteExecutionStore(path)
    try:
        barrier.wait(timeout=30)
        sc=scope(); auth=CtpUnifiedOrderActionAuthority(store); lease=store.acquire_or_renew_lease(sc,OWNER,ttl_ns=120_000_000_000)
        claim='not-requested'
        if try_unknown:
            value=store.claim_ctp_dispatch_command(sc,'unknown-process-command',writer_lease=lease)
            claim=None if value is None else value.status
        row=auth.reserve_cancel_action_identity(sc,f'multiprocess-{idx}','submit-intent',runtime(),'000000000013',legacy_seed=action_seed(),writer_lease=lease)
        return {'idx':idx,'action_ref':row.native_action_ref,'claim_unknown':claim,'pid':os.getpid()}
    finally: store.close()
def main():
    out=ROOT/'evidence'/'independent-multiprocess-check.json'; out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='g5-cross-process-',dir=str(ROOT)) as td:
        db=Path(td)/'shared.sqlite3'; store=SqliteExecutionStore(db); sc=scope(); auth=CtpUnifiedOrderActionAuthority(store)
        lease=store.acquire_or_renew_lease(sc,OWNER,ttl_ns=120_000_000_000)
        order=auth.reserve_submit_order_identity(sc,order_seed(),'submit-intent',runtime(),writer_lease=lease); assert order.order_ref=='000000000013'
        first=auth.reserve_cancel_action_identity(sc,'preexisting-action','submit-intent',runtime(),order.order_ref,legacy_seed=action_seed(),writer_lease=lease); assert first.native_action_ref==42
        t=target(order.order_ref); command=auth.stage_cancel_command(sc,'preexisting-action','unknown-process-command',request(t),target=t,approval_use_id='qa-approval',approval_digest=hashlib.sha256(b'approval').hexdigest(),session_binding={'generation':1},writer_lease=lease)
        claimed=store.claim_ctp_dispatch_command(sc,command.command_id,writer_lease=lease); assert claimed is not None and claimed.status=='CLAIMED'
        receipt=CtpDispatchReceipt(receipt_type='ctp_dispatch_receipt.v1',command_id=claimed.command_id,account_key=claimed.account_key,scope_key=claimed.scope_key,trading_day=claimed.trading_day,operation=claimed.operation,request_payload_sha256=claimed.request_payload_sha256,reservation_managed_intent_id=claimed.reservation_managed_intent_id,order_ref=claimed.order_ref,cancel_target_order_ref=claimed.cancel_target_order_ref,cancel_target_exchange_id=claimed.cancel_target_exchange_id,cancel_target_order_sys_id=claimed.cancel_target_order_sys_id,cancel_target_front_id=claimed.cancel_target_front_id,cancel_target_session_id=claimed.cancel_target_session_id,approval_use_id=claimed.approval_use_id,approval_digest=claimed.approval_digest,session_binding_sha256=claimed.session_binding_sha256,outcome='UNKNOWN',native_receipt_payload={'synthetic':True})
        assert store.complete_ctp_dispatch_command(sc,receipt,writer_lease=lease).status=='UNKNOWN'; store.close()
        ctx=mp.get_context('spawn')
        with ctx.Manager() as manager:
            barrier=manager.Barrier(8); args=[(str(db),i,i==0,barrier) for i in range(8)]
            with ctx.Pool(processes=8) as pool: rows=pool.map(reserve_worker,args)
        refs=sorted(x['action_ref'] for x in rows); assert refs==list(range(43,51)),refs
        assert len({x['pid'] for x in rows})==8,rows; assert rows[0]['claim_unknown'] is None,rows[0]
        reopened=SqliteExecutionStore(db); auth2=CtpUnifiedOrderActionAuthority(reopened); lease2=reopened.acquire_or_renew_lease(sc,OWNER,ttl_ns=120_000_000_000)
        persisted=[auth2.read_cancel_action_identity(sc,f'multiprocess-{i}') for i in range(8)]
        assert sorted(x.native_action_ref for x in persisted if x)==list(range(43,51))
        assert reopened.read_ctp_dispatch_command(sc,'unknown-process-command').status=='UNKNOWN'
        assert reopened.claim_ctp_dispatch_command(sc,'unknown-process-command',writer_lease=lease2) is None; reopened.close()
        result={'status':'PASS','processes':len(rows),'distinct_worker_pids':sorted({x['pid'] for x in rows}),'unique_action_refs':refs,'unknown_reclaim_from_child':rows[0]['claim_unknown'],'unknown_reclaim_after_parent_reopen':None,'restart_readback_refs':sorted(x.native_action_ref for x in persisted if x),'database':'temporary local SQLite; deleted after run','provider_sdk_network_credentials':'not used'}
        out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__': main()
