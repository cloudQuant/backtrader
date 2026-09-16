"""Astra independent MF-T1 oracle consumers, explicitly synthetic; no SDK grants.
Expected boundaries are frozen contract/root values, not author-test output.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from dataclasses import replace,fields
import atexit,copy,json,threading
import pytest,yaml
import backtrader as bt
from execution_timing import *
from ctp_options_midfreq_strategy import CTPOptionsMidFrequencyStrategy,ConfigurationError,validate_config

O=Path(__file__).resolve().parent;R=O.parent/'source';EX=R/'examples/014_2_ctp_options_midfreq';NS=10**9
BASE=datetime(2026,9,11,9,30,tzinfo=timezone.utc)
CASES=[];TRACES=[];PRODUCT_NEGATIVE=[];PRODUCT_NEGATIVE_CONTRACTS=json.loads((O/'product_negative_contracts.json').read_text())['contracts']
def save():
 """Persist collected cases, engine traces, and product-negative contracts as JSON files."""
 with (O/'mf-cases.json').open('x') as f:json.dump(CASES,f,indent=2,default=str)
 with (O/'mf-engine-traces.json').open('x') as f:json.dump(TRACES,f,indent=2,default=str)
 with (O/'mf-product-negative-contracts.json').open('x') as f:json.dump(PRODUCT_NEGATIVE,f,indent=2,default=str)
atexit.register(save)
def ck(name,contracts,expected,observed):
 """Record and assert one frozen-contract comparison case."""
 ok=expected==observed
 CASES.append(dict(id=name,contracts=contracts,expected=expected,observed=observed,pass_=ok))
 assert ok, json.dumps({'id':name,'expected':expected,'observed':observed},default=str)
def env(error=0):
 """Build a synthetic scope identity and its matching clock mapping."""
 s=ScopeIdentity('candidate','basket','synthetic-account','20260911','day',7,'rules','synthetic-domain','mapping','astra-synthetic-scope',True)
 m=ClockMapping('mapping',BASE,0,s.clock_domain,s.generation,'astra-synthetic-mapping',error,10**15,s.rules_hash,True)
 return s,m
def clock(s,m,n,**kw):
 """Build a synthetic trusted clock observation at monotonic time n."""
 # Python datetime stores microseconds; nanosecond residual is explicitly bounded.
 k=dict(monotonic_ns=n,wall_utc=BASE+timedelta(microseconds=(n-m.anchor_monotonic_ns)//1000),clock_domain=s.clock_domain,mapping=m,scope=s,source='astra-synthetic-clock',trusted=True,synthetic=True);k.update(kw)
 return ClockObservation(**k)
def facts(s,**kw):
 """Build synthetic execution facts defaulting to a trusted idle scope."""
 k=dict(scope=s,source='astra-synthetic-facts',source_kind='synthetic',trusted=True,reported_phase='IDLE',first_leg_intent_ns=None,first_basket_intent_ns=None,cancel_intent_ns=None,earliest_exposure_lower_ns=None,latest_complete_fill_upper_ns=None,complete_basket=False,authoritative_flat_verified=True,possible_exposure_qty=0,confirmed_qty=0,event_ids=(),collection_version='v1',expiry_ns=10**15)
 k.update(kw);return ExecutionFacts(**k)
def active(s,**kw):
 """Build synthetic execution facts for an active leg-pending basket."""
 k=dict(reported_phase='LEG_PENDING',authoritative_flat_verified=False,possible_exposure_qty=3);k.update(kw);return facts(s,**k)
def complete(s,exposure=61*NS,fill=64*NS,**kw):
 """Build synthetic execution facts for a completed exposed basket."""
 k=dict(reported_phase='EXPOSED',authoritative_flat_verified=False,possible_exposure_qty=3,confirmed_qty=3,complete_basket=True,earliest_exposure_lower_ns=exposure,latest_complete_fill_upper_ns=fill);k.update(kw);return facts(s,**k)
def minute(s,end=120*NS,**kw):
 """Build a synthetic minute input whose bucket ends at the given nanosecond."""
 k=dict(minute_id='m'+str(end),bucket_start_ns=end-60*NS,bucket_end_ns=end,scope=s,bar_ids=tuple(f'{end}-{x}' for x in 'FCP'),quote_cutoffs=tuple((x,i+1) for i,x in enumerate('FCP')),direction='conversion',max_quantity=1,invocation_id='A'+str(end),next_boundary_ns=end+60*NS,decision_deadline_ns=end+30*NS,entry_candidate=True,z_score=.5,legal_barrier=True)
 k.update(kw);return MinuteInput(**k)
def exact(s,n):
 """Build an aligned mapping and clock observation that land exactly on nanosecond n."""
 _,m=env();m=replace(m,anchor_monotonic_ns=n%1000);return m,clock(s,m,n)
def exact_project(s,f,n,mi=None):
 """Project facts through the exact clock at nanosecond n, optionally with a minute input."""
 m,c=exact(s,n);return projector(s,m).project(f,c,minute=mi)
def projector(s,m,**kw):
 """Build a timing projector bound to the given scope and mapping."""
 return TimingProjector(scope=s,mapping=m,policy=TimingPolicy(30,**kw))
def evt(id='e',kind='fill',leg='F',quantity=1,n=1*NS,terminal=True,source='astra-synthetic-event',**kw):
 """Build one synthetic execution event."""
 k=dict(event_id=id,kind=kind,leg=leg,quantity=quantity,occurred_lower_ns=n,occurred_upper_ns=n,received_ns=n,terminal=terminal,source=source);k.update(kw);return ExecutionEvent(**k)
def rejection(contract_id,f):
 """Assert the frozen negative contract's expected exception or projection outcome."""
 expected=PRODUCT_NEGATIVE_CONTRACTS[contract_id]['expected']
 if expected['kind']=='exception':
  expected_type={'TimingContractError':TimingContractError,'ConfigurationError':ConfigurationError}[expected['exception_class']]
  try:
   f()
  except expected_type as error:
   # Exact product type/code/message: a different ValueError is a test failure.
   assert type(error) is expected_type
   observed=dict(kind='exception',code=getattr(error,'code',None),exception_class=type(error).__name__,message=str(error),normal_exit_allowed=None,risk_action=None,token_is_none=None)
  else:raise AssertionError(f'{contract_id} did not reject')
 else:
  r=f()
  observed=dict(kind='projection',code=r.reason,exception_class=None,message=None,normal_exit_allowed=r.normal_exit_allowed,risk_action=r.risk_action,token_is_none=r.token is None)
 assert observed==expected, json.dumps(dict(id=contract_id,expected=expected,observed=observed),sort_keys=True)
 PRODUCT_NEGATIVE.append(dict(id=contract_id,expected=expected,observed=observed,pass_=True))
 return True

def test_root01_leg():
 s,m=env(999);f=active(s,first_leg_intent_ns=100*NS)
 out=[exact_project(s,f,n).deadlines['leg'] for n in (105*NS-1,105*NS,105*NS+1)]
 ck('ROOT-MFT1-01',['C02'],{'expired':[False,True,True],'deadlines':[105*NS]*3},{'expired':[r.expired for r in out],'deadlines':[r.deadline_ns for r in out]})
def test_root02_basket():
 s,m=env(999);f=active(s,first_basket_intent_ns=100*NS)
 out=[exact_project(s,f,n).deadlines['basket'] for n in (115*NS-1,115*NS,115*NS+1)]
 ck('ROOT-MFT1-02',['C02'],[False,True,True],[r.expired for r in out])
def test_root03_cancel():
 s,m=env(999);f=active(s,cancel_intent_ns=105*NS)
 out=[exact_project(s,f,n).deadlines['cancel'] for n in (110*NS-1,110*NS,110*NS+1)]
 ck('ROOT-MFT1-03',['C02'],{'expired':[False,True,True],'deadline':[110*NS]*3},{'expired':[r.expired for r in out],'deadline':[r.deadline_ns for r in out]})
def test_root04_recovery():
 s,m=env(999);f=active(s,risk_event_origin_ns=115*NS)
 out=[exact_project(s,f,n) for n in (175*NS-1,175*NS,175*NS+1)]
 ck('ROOT-MFT1-04',['C02','C03'],{'expired':[False,True,True],'deadline':[175*NS]*3,'handover':[False,True,True]},{'expired':[r.deadlines['recovery'].expired for r in out],'deadline':[r.deadlines['recovery'].deadline_ns for r in out],'handover':[r.risk_action=='HANDOVER' for r in out]})
def test_root05_delayed_basket():
 s,m=env();f=active(s,first_leg_intent_ns=10*NS,first_basket_intent_ns=0,events=(evt(n=2*NS),))
 r=projector(s,m).project(f,clock(s,m,16*NS))
 ck('ROOT-MFT1-05',['C02'],[15*NS,15*NS,75*NS],[r.deadlines['basket'].deadline_ns,r.deadlines['recovery'].origin_ns,r.deadlines['recovery'].deadline_ns])
def test_root06_leg_ack():
 s,m=env();f=active(s,first_leg_intent_ns=0,cancel_intent_ns=5*NS,unknown=True,events=(evt(kind='ACK',quantity=0,n=4900000000,terminal=False),))
 r=projector(s,m).project(f,clock(s,m,10*NS))
 ck('ROOT-MFT1-06',['C02','C03'],[5*NS,10*NS,65*NS,True,3],[r.deadlines['leg'].deadline_ns,r.deadlines['cancel'].deadline_ns,r.deadlines['recovery'].deadline_ns,r.possible_exposure_unknown,f.possible_exposure_qty])
def test_root07_earliest_risk():
 s,m=env();f=active(s,first_basket_intent_ns=0,risk_event_origin_ns=3*NS,cancel_intent_ns=20*NS)
 r=projector(s,m).project(f,clock(s,m,21*NS))
 ck('ROOT-MFT1-07',['C02'],[3*NS,63*NS,25*NS],[r.deadlines['recovery'].origin_ns,r.deadlines['recovery'].deadline_ns,r.deadlines['cancel'].deadline_ns])

class SequenceProvider:
 def __init__(self,s,m,sequence):self.scope=s;self.mapping=m;self.sequence=sequence;self.current=None;self.reads=[];self.next_calls=0;self.idle_calls=0
 def next_minute(self):self.next_calls+=1;self.reads.append(('next_minute',threading.get_ident()));return self.current['minute']
 def execution_facts(self):self.reads.append(('facts',threading.get_ident()));return self.current['facts']
 def clock_for_next(self):return clock(self.scope,self.mapping,self.current['n'])
 def clock_for_idle(self):self.idle_calls+=1;return clock(self.scope,self.mapping,self.current['n'])
class SequenceFeed(bt.feed.DataBase):
 params=(('qcheck',0.0),)
 def __init__(self,provider):super().__init__();self.pv=provider;self.index=0;self.none_returns=0
 def islive(self):return True
 def haslivedata(self):return True
 def _load(self):
  if self.index>=len(self.pv.sequence):return False
  e=self.pv.sequence[self.index];self.index+=1;self.pv.current=e
  if e['type']=='idle':self.none_returns+=1;return None
  self.lines.datetime[0]=bt.date2num(BASE+timedelta(microseconds=e['n']//1000))
  for line in (self.lines.open,self.lines.high,self.lines.low,self.lines.close):line[0]=100.
  self.lines.volume[0]=1.;self.lines.openinterest[0]=0.;return True

def engine(name,s,m,sequence):
 """Run the real strategy over a synthetic sequence feed and record its trace."""
 provider=SequenceProvider(s,m,sequence);feed=SequenceFeed(provider)
 c=bt.Cerebro(stdstats=False);c.adddata(feed);cfg=yaml.safe_load((EX/'config.yaml').read_text());c.addstrategy(CTPOptionsMidFrequencyStrategy,config=cfg,timing_provider=provider)
 main_thread=threading.get_ident();st=c.run(runonce=False,preload=False)[0];report=st.build_report()
 trace={'name':name,'report':report,'none_returns':feed.none_returns,'input':sequence,'reads':provider.reads,'main_thread':main_thread,'orders':len(c.broker.orders)};TRACES.append(trace)
 return report['timing']['results'],trace

def test_root08_actual_engine_hold():
 s,m=env();f=complete(s)
 seq=[dict(type='bar',n=n,facts=f,minute=minute(s,n)) for n in (120*NS,180*NS)]
 seq.append(dict(type='idle',n=961*NS,facts=f))
 out,tr=engine('root08',s,m,seq)
 ck('ROOT-MFT1-08',['C05','C06','C10'],{'min':124*NS,'ordinary':[False,True],'max':961*NS,'due':True,'next':2,'idle':1,'orders':0,'same_thread':True},{'min':out[0]['minimum_hold_deadline_ns'],'ordinary':[r['normal_exit_allowed'] for r in out[:2]],'max':out[2]['maximum_hold_deadline_ns'],'due':out[2]['max_hold_due'],'next':sum(r['origin']=='next' for r in out),'idle':tr['none_returns'],'orders':tr['orders'],'same_thread':all(t==tr['main_thread'] for _,t in tr['reads'])})
def test_root09_hold_boundary():
 s,m=env(999);f=complete(s,100*NS,103*NS)
 out=[exact_project(s,f,n,minute(s,n)) for n in (163*NS-1,163*NS)]
 ck('ROOT-MFT1-09',['C04','C05'],{'allowed':[False,True],'max':[1000*NS]*2},{'allowed':[r.normal_exit_allowed for r in out],'max':[r.maximum_hold_deadline_ns for r in out]})
def test_root10_cadence():
 s,m=env(999);out=[]
 for gap in (249999999,250000000,250000001):
  p=projector(s,m);f=active(s,first_leg_intent_ns=0);p.notify_idle(f,clock(s,m,5*NS));r=p.notify_idle(f,clock(s,m,5*NS+gap));out.append([r.cadence_ok,r.deadlines['leg'].deadline_ns,r.token is None])
 ck('ROOT-MFT1-10',['C06'],[[True,5*NS,True],[True,5*NS,True],[False,5*NS,True]],out)
def test_root11_reject_consumes():
 s,m=env();p=projector(s,m);mi=minute(s,entry_candidate=False);f=facts(s);first=p.consume_minute(mi,f,clock(s,m,120*NS));xs=[p.consume_minute(replace(mi,entry_candidate=True),f,clock(s,m,120*NS)) for _ in range(100)]
 ids=[p.notify_idle(f,clock(s,m,120*NS)) for _ in range(100)];new=p.consume_minute(minute(s,180*NS),f,clock(s,m,180*NS))
 ck('ROOT-MFT1-11',['C01'],[True,0,0,True],[first.minute_consumed,sum(x.token is not None for x in xs),sum(x.token is not None for x in ids),new.token is not None])
def test_root12_actual_invocation_binding():
 s,m=env();f=facts(s);mi=minute(s,invocation_id='foreign-next-invocation-B')
 out,tr=engine('root12-foreign-invocation',s,m,[dict(type='bar',n=120*NS,minute=mi,facts=f),dict(type='idle',n=120*NS,facts=f)])
 ck('ROOT-MFT1-12',['C01','C10'],{'reject_unbound_invocation':True},{'reject_unbound_invocation':out[0]['token'] is None})
def test_root13_scope_unknown_survives():
 s,m=env();p=projector(s,m);pending=active(s,first_leg_intent_ns=100*NS,unknown=True);p.project(pending,clock(s,m,101*NS))
 s2=replace(s,generation=8,mapping_id='mapping8');m2=replace(m,generation=8,mapping_id='mapping8');p.reset_scope(s2,m2)
 # Unknown old basket was never reconciled; a different generation cannot establish idle merely by a flag.
 r=p.consume_minute(minute(s2,120*NS),facts(s2),clock(s2,m2,120*NS))
 ck('ROOT-MFT1-13',['C03','C04','C09'],{'old_unknown_does_not_rearm':True},{'old_unknown_does_not_rearm':r.token is None})
def test_root14_cancel_late_duplicate():
 s,m=env();e=evt('fill-late',n=3*NS,terminal=False);f=active(s,first_leg_intent_ns=0,cancel_intent_ns=NS,unknown=True,confirmed_qty=1,event_ids=('cancel-ack','fill-late','fill-late'),events=(evt('cancel-ack','cancel_ACK',quantity=0,n=2*NS,terminal=False),e,e))
 r=projector(s,m).project(f,clock(s,m,4*NS))
 ck('ROOT-MFT1-14',['C03'],[True,False,1,2,3],[r.possible_exposure_unknown,f.authoritative_flat_verified,f.confirmed_qty,len(f.event_ids),f.possible_exposure_qty])
def test_root15_calendar_cutoffs():
 s,m=env();out=[]
 for n in (1800,600,180):
  c=evaluate_calendar(CalendarEvidence('day','rules','astra-synthetic-calendar',n,5),expected_rules_hash='rules');out.append([c.entry_allowed,c.risk_exit_due,c.handover_due])
 ck('ROOT-MFT1-15',['C07'],[[False,False,False],[False,True,False],[False,True,True]],out)
def test_root16_no_authority():
 s,m=env();r=projector(s,m).consume_minute(minute(s),facts(s),clock(s,m,120*NS))
 ck('ROOT-MFT1-16',['C08'],[True,'NOT_PROVEN','NOT_PROVEN'],[r.token is not None,r.execution_permission,r.token.execution_permission if r.token else None])

@pytest.mark.parametrize('field,value',[('monotonic_ns',True),('monotonic_ns',1.0),('monotonic_ns','1'),('monotonic_ns',float('nan'))])
def test_s01_malformed_ns(field,value):
 s,m=env();ck('S01-ns-'+str(value),['C04'],True,rejection('S01-MALFORMED-MONOTONIC-NS',lambda:projector(s,m).consume_minute(minute(s),facts(s),clock(s,m,120*NS,**{field:value}))))
@pytest.mark.parametrize('kind',['clock_untrusted','facts_untrusted','clock_unknown_source','facts_unknown_source','mapping_unknown_source','expired_facts','missing_facts_expiry','minute_foreign_symbols','minute_illegal_barrier','minute_future_end','minute_before_start','complete_missing_z'])
def test_s01_evidence_rejections(kind):
 s,m=env();f=facts(s);mi=minute(s);now=clock(s,m,120*NS)
 if kind=='clock_untrusted':now=replace(now,trusted=False)
 elif kind=='facts_untrusted':f=replace(f,trusted=False)
 elif kind=='clock_unknown_source':now=replace(now,source='unknown')
 elif kind=='facts_unknown_source':f=replace(f,source='unknown')
 elif kind=='mapping_unknown_source':m=replace(m,source='unknown');now=clock(s,m,120*NS)
 elif kind=='expired_facts':f=replace(f,expiry_ns=120*NS)
 elif kind=='missing_facts_expiry':f=replace(f,expiry_ns=None)
 elif kind=='minute_foreign_symbols':mi=replace(mi,quote_cutoffs=(('X',1),('Y',2),('Z',3)))
 elif kind=='minute_illegal_barrier':mi=replace(mi,legal_barrier=False)
 elif kind=='minute_future_end':mi=replace(mi,bucket_end_ns=150*NS)
 elif kind=='minute_before_start':now=clock(s,m,59*NS)
 elif kind=='complete_missing_z':f=complete(s);mi=replace(mi,bucket_end_ns=180*NS,z_score=None);now=clock(s,m,180*NS)
 contract_id=dict(clock_untrusted='S01-CLOCK-UNTRUSTED',facts_untrusted='S01-FACTS-UNTRUSTED',clock_unknown_source='S01-PROVENANCE-CLOCK-UNKNOWN',facts_unknown_source='S01-PROVENANCE-FACTS-UNKNOWN',mapping_unknown_source='S01-PROVENANCE-MAPPING-UNKNOWN',expired_facts='S01-FACTS-EXPIRED',missing_facts_expiry='S01-FACTS-MISSING-EXPIRY',minute_foreign_symbols='S01-MINUTE-FOREIGN-SYMBOLS',minute_illegal_barrier='S01-MINUTE-BARRIER-REJECTED',minute_future_end='S01-MINUTE-FUTURE-END',minute_before_start='S01-MINUTE-BEFORE-START',complete_missing_z='S01-COMPLETE-MISSING-Z')[kind]
 ck('S01-'+kind,['C01','C04','C09'],True,rejection(contract_id,lambda:projector(s,m).consume_minute(mi,f,now)))

def test_s01_uncertainty_deadline_upper():
 s,m=env(1000);n=105*NS-500;f=active(s,first_leg_intent_ns=100*NS)
 r=projector(s,m).project(f,clock(s,m,n))
 ck('S01-uncertain-now-upper-reaches-deadline',['C04'],True,r.deadlines['leg'].expired or r.reason!='READY')
def test_s01_uncertainty_minhold_lower():
 s,m=env(1000);n=164*NS;f=complete(s,100*NS,104*NS)
 r=projector(s,m).project(f,clock(s,m,n),minute=minute(s,n))
 ck('S01-uncertain-now-lower-before-minhold',['C04','C05'],False,r.normal_exit_allowed)
def test_s01_clock_fault_latches_audit():
 s,m=env();p=projector(s,m);f=facts(s);p.project(f,clock(s,m,120*NS));old=p.audit;r=p.project(f,clock(s,m,119*NS));r2=p.consume_minute(minute(s,180*NS),f,clock(s,m,180*NS))
 ck('S01-regression-latch-audit',['C04'],[True,True,True,True],[p.clock_fault,r.timing_fault=='CLOCK_REGRESSION',r2.token is None,len(old)>0 and old[0]['monotonic_ns']==120*NS])
def test_s01_cross_domain_no_subtraction():
 s,m=env();s2=replace(s,clock_domain='other',mapping_id='other');m2=replace(m,clock_domain='other',mapping_id='other');r=projector(s,m).project(active(s,unknown=True),clock(s2,m2,120*NS))
 ck('S01-cross-domain-no-subtraction',['C04'],['HANDOVER',{}],[r.risk_action,dict(r.deadlines)])

def test_s02_actual_idle_no_ordinary_exit():
 s,m=env();f=complete(s);out,tr=engine('idle-no-ordinary-exit',s,m,[dict(type='bar',n=120*NS,minute=minute(s),facts=f),dict(type='idle',n=180*NS,facts=f)])
 ck('S02-idle-cannot-ordinary-exit',['C05','C06','C10'],False,out[1]['normal_exit_allowed'])
def test_s02_actual_idle_deadlines():
 s,m=env();f=active(s,first_leg_intent_ns=120*NS,first_basket_intent_ns=120*NS)
 seq=[dict(type='bar',n=120*NS,minute=minute(s),facts=f)]+[dict(type='idle',n=n*NS,facts=f) for n in (125,135,185)]
 out,tr=engine('idle-leg-basket-recovery',s,m,seq)
 ck('S02-idle-original-deadlines',['C02','C06','C10'],[3,125*NS,135*NS,185*NS,'HANDOVER',0],[tr['none_returns'],out[1]['deadlines']['leg']['deadline_ns'],out[2]['deadlines']['basket']['deadline_ns'],out[3]['deadlines']['recovery']['deadline_ns'],out[3]['risk_action'],tr['orders']])

@pytest.mark.parametrize('z,cost,expect',[(.5,False,True),(.5001,False,False),(.9,True,True)])
def test_s03_ordinary_exit(z,cost,expect):
 s,m=env();p=projector(s,m);mi=minute(s,180*NS,z_score=z,continuation_cost_failed=cost);r=p.consume_minute(mi,complete(s),clock(s,m,180*NS));again=p.consume_minute(mi,complete(s),clock(s,m,180*NS))
 ck('S03-exit-'+str(z)+'-'+str(cost),['C01','C05'],[expect,True,True],[r.normal_exit_allowed,r.token is None,again.token is None])
def test_s03_terminal_legs_do_not_expire():
 s,m=env();events=tuple(evt(x,leg=x,n=n*NS) for x,n in zip('FCP',(101,102,103)))
 f=complete(s,100*NS,103*NS,first_leg_intent_ns=100*NS,first_basket_intent_ns=100*NS,events=events,event_ids=tuple('FCP'))
 r=projector(s,m).consume_minute(minute(s,180*NS),f,clock(s,m,180*NS))
 ck('S03-complete-terminal-legs-stop-entry-deadlines',['C02','C03','C05'],['NORMAL_EXIT_PROPOSAL',True],[r.reason,r.normal_exit_allowed])
def test_s03_cancel_only_timeout_risk():
 s,m=env();f=active(s,cancel_intent_ns=120*NS);r=projector(s,m).notify_idle(f,clock(s,m,125*NS))
 ck('S03-cancel-only-expiry-requires-risk',['C02','C03'],True,r.risk_action!='NONE')

@pytest.mark.parametrize('delta,expected',[(-1,True),(0,False),(1,False)])
def test_s04_token_deadline(delta,expected):
 s,m=env(999);mi=minute(s);r=projector(s,m).consume_minute(mi,facts(s),clock(s,m,150*NS+delta))
 ck('S04-token-expiry-'+str(delta),['C01'],expected,r.token is not None)
def test_s04_policy_deadline_cannot_override():
 s,m=env();mi=minute(s,decision_deadline_ns=240*NS);r=projector(s,m).consume_minute(mi,facts(s),clock(s,m,155*NS))
 ck('S04-config30-cannot-extend-to60',['C01','C09'],True,r.token is None)
def test_s04_retention_and_positive():
 s,m=env();p=projector(s,m,history_capacity=8);f=facts(s);p.consume_minute(minute(s),f,clock(s,m,120*NS))
 for i in range(1,40):n=(120+i*60)*NS;p.consume_minute(minute(s,n,entry_candidate=False),f,clock(s,m,n))
 old=p.consume_minute(minute(s),f,clock(s,m,n));new=p.consume_minute(minute(s,n+60*NS),f,clock(s,m,n+60*NS))
 ck('S04-retention-old-not-revived-new-works',['C01','C09'],[True,True],[old.token is None,new.token is not None])

@pytest.mark.parametrize('kind',['event_future','event_foreign_leg','event_unknown_source','fill_before_exposure','flat_with_confirmed_fill','same_version_conflict','same_event_conflict_across_snapshots','origin_renewal'])
def test_s05_execution_fact_consistency(kind):
 s,m=env();p=projector(s,m);f=complete(s);mi=minute(s,180*NS)
 def act():
  nonlocal f
  if kind=='event_future':f=replace(f,events=(evt(n=300*NS),))
  elif kind=='event_foreign_leg':f=replace(f,events=(evt(leg='OTHER-CONTRACT'),))
  elif kind=='event_unknown_source':f=replace(f,events=(evt(source='unknown'),))
  elif kind=='fill_before_exposure':f=replace(f,latest_complete_fill_upper_ns=60*NS)
  elif kind=='flat_with_confirmed_fill':f=replace(f,complete_basket=False,authoritative_flat_verified=True,possible_exposure_qty=0)
  elif kind=='same_version_conflict':p.project(active(s,unknown=True),clock(s,m,120*NS));f=facts(s)
  elif kind=='same_event_conflict_across_snapshots':p.project(replace(f,events=(evt(quantity=1),)),clock(s,m,120*NS));f=replace(f,events=(evt(quantity=99),))
  elif kind=='origin_renewal':
   p.project(active(s,first_basket_intent_ns=100*NS),clock(s,m,110*NS));f=active(s,first_basket_intent_ns=179*NS)
  return p.consume_minute(mi,f,clock(s,m,180*NS))
 if kind=='origin_renewal':
  r=act();ok=r.deadlines['basket'].deadline_ns==115*NS or r.risk_action!='NONE'
 else:ok=rejection(dict(event_future='S05-EVENT-FUTURE',event_foreign_leg='S05-EVENT-FOREIGN-LEG',event_unknown_source='S05-EVENT-UNKNOWN-SOURCE',fill_before_exposure='S05-FILL-BEFORE-EXPOSURE',flat_with_confirmed_fill='S05-FLAT-WITH-CONFIRMED-FILL',same_version_conflict='S05-SAME-VERSION-CONFLICT',same_event_conflict_across_snapshots='S05-SAME-EVENT-CONFLICT-ACROSS-SNAPSHOTS')[kind],act)
 ck('S05-'+kind,['C02','C03','C04','C09'],True,ok)
def test_s05_deep_freeze_and_duplicate_pair():
 s,m=env();ids=['e'];e=evt();evs=[e,e];f=facts(s,event_ids=ids,events=evs);ids.append('late');evs.clear()
 rejected=rejection('S05-DUPLICATE-EVENT-FINGERPRINT',lambda:replace(f,events=(e,replace(e,quantity=2))))
 ck('S05-freeze-duplicate-consistency',['C09'],[('e',),2,True],[f.event_ids,len(f.events),rejected])

@pytest.mark.parametrize('field,val,contract_id',[('leg_timeout_seconds',6,'S06-TIMING-LEG-TIMEOUT-CAP'),('basket_timeout_seconds',16,'S06-TIMING-BASKET-TIMEOUT-CAP'),('cancel_timeout_seconds',6,'S06-TIMING-CANCEL-TIMEOUT-CAP'),('recovery_timeout_seconds',61,'S06-TIMING-RECOVERY-TIMEOUT-CAP'),('minimum_hold_seconds',59,'S06-TIMING-MINIMUM-HOLD-FLOOR'),('maximum_hold_seconds',901,'S06-TIMING-MAXIMUM-HOLD-CAP'),('idle_interval_ms',251,'S06-TIMING-IDLE-INTERVAL-CAP'),('leg_timeout_seconds',True,'S06-TIMING-LEG-TIMEOUT-BOOL'),('leg_timeout_seconds','5','S06-TIMING-LEG-TIMEOUT-STRING'),('minimum_hold_seconds',float('nan'),'S06-TIMING-MINIMUM-HOLD-NAN')],ids=['leg_timeout_seconds-6','basket_timeout_seconds-16','cancel_timeout_seconds-6','recovery_timeout_seconds-61','minimum_hold_seconds-59','maximum_hold_seconds-901','idle_interval_ms-251','leg_timeout_seconds-True','leg_timeout_seconds-5','minimum_hold_seconds-nan'])
def test_s06_strict_config(field,val,contract_id):
 raw=yaml.safe_load((EX/'config.yaml').read_text());raw['timing'][field]=val;ok=False
 ok=rejection(contract_id,lambda:validate_config(raw))
 ck('S06-config-'+field+'-'+str(val),['C09'],True,ok)
def test_s06_config_stricter_and_unknown():
 raw=yaml.safe_load((EX/'config.yaml').read_text());raw['timing'].update(leg_timeout_seconds=4,basket_timeout_seconds=14,cancel_timeout_seconds=4,recovery_timeout_seconds=59,minimum_hold_seconds=61,maximum_hold_seconds=899,idle_interval_ms=249)
 good=validate_config(raw)['timing']['leg_timeout_seconds']==4;raw['timing']['extra']=1;bad=rejection('S06-TIMING-UNKNOWN-KEY',lambda:validate_config(raw))
 ck('S06-stricter-and-unknown',['C09'],[True,True],[good,bad])
def test_s06_calendar_positive_negative():
 out=[]
 for e in (None,CalendarEvidence('day','rules','astra-synthetic',1801,5),CalendarEvidence('day','rules','astra-synthetic',1801,4),CalendarEvidence('day','other','astra-synthetic',1801,5)):
  out.append(evaluate_calendar(e,expected_rules_hash='rules').entry_allowed)
 ck('S06-calendar-missing-five-four-rules',['C07'],[False,True,False,False],out)
def test_s06_delivery_restriction_earlier():
 c=evaluate_calendar(CalendarEvidence('day','rules','astra-synthetic',3600,5,exercise_or_delivery_seconds=600),expected_rules_hash='rules')
 ck('S06-delivery-cutoff-earlier-than-session',['C07'],[False,True],[c.entry_allowed,c.risk_exit_due])
def test_s06_actual_calendar_missing_blocks_entry():
 s,m=env();f=facts(s);out,tr=engine('no-calendar-entry',s,m,[dict(type='bar',n=120*NS,minute=minute(s),facts=f),dict(type='idle',n=120*NS,facts=f)])
 ck('S06-actual-callback-has-no-calendar-entry',['C07','C10'],True,out[0]['token'] is None)
def test_s08_projection_basis_label():
 s,m=env();r=projector(s,m).project(active(s),clock(s,m,120*NS));ck('S08-output-explicit-synthetic-basis',['C08','C10'],True,'execution_basis' in r.to_dict())
def test_s10_actual_trace_event_provenance():
 s,m=env();f=active(s,events=(evt(n=100*NS,received_ns=101*NS,terminal=False),),event_ids=('e',),first_leg_intent_ns=100*NS)
 out,tr=engine('trace-provenance',s,m,[dict(type='bar',n=120*NS,minute=minute(s),facts=f),dict(type='idle',n=121*NS,facts=f)])
 txt=json.dumps(out)
 ck('S10-trace-original-occurrence-receipt-processing',['C10'],True,all(w in txt for w in ('occurred','received','collection_version','confirmed_qty')))
