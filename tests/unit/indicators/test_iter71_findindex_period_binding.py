"""FindLast batch optimization retains per-window period evaluation."""
import array
import math
import pytest
import backtrader as bt
import backtrader.indicators.basicops as basicops
from test_iter71_numeric_acceptance_regressions import _indicator

CASES = (bt.ind.FindFirstIndexHighest, bt.ind.FindFirstIndexLowest,
         bt.ind.FindLastIndexHighest, bt.ind.FindLastIndexLowest)

@pytest.mark.parametrize('indicator_type',CASES)
@pytest.mark.parametrize('behavior',['switch','value_error','type_error','runtime_error','not_number'])
def test_dynamic_period_read_order_and_error_fallback(monkeypatch,indicator_type,behavior):
    ind=_indicator(indicator_type,32,120)
    manager=object.__getattribute__(ind.p,'_param_manager')
    manager_cls=type(manager)
    original=manager_cls.get
    rows=[]
    for fast in (False,True):
        reads=[];fallback=[]
        src=array.array('d',[(i*17%37)/3.0 for i in range(120)])
        dst=array.array('d',[-99.0]*120)
        ind.data.array=src;ind.lines[0].array=dst
        def get(self,name,*args,**kwargs):
            if self is manager and name=='period':
                reads.append(name)
                if len(reads)==1:return 32
                if behavior=='switch':return 99
                if behavior=='value_error':raise ValueError('v')
                if behavior=='type_error':raise TypeError('t')
                if behavior=='runtime_error':raise RuntimeError('r')
                return 'not-number'
            return original(self,name,*args,**kwargs)
        def once_next(self,start,end):
            fallback.append((start,end,tuple(dst[31:36])))
            dst[31]=-123.0
        with monkeypatch.context() as m:
            m.setattr(manager_cls,'get',get)
            m.setattr(bt.Indicator,'once_via_next',once_next)
            m.setattr(basicops,'_MIN_PERIOD_FOR_MONOTONIC_INDEX_ONCE',32 if fast else 100000)
            ind.once(31,36)
        norm=lambda seq:tuple('nan' if math.isnan(x) else x for x in seq)
        rows.append((len(reads),[(a,b,norm(c)) for a,b,c in fallback],norm(dst)))
    assert rows[0]==rows[1]
    if indicator_type in CASES[:2]:
        assert rows[0][0]==1
    else:
        assert rows[0][0]==(2 if behavior=='runtime_error' else 6)

@pytest.mark.parametrize('indicator_type',CASES)
def test_normal_indicator_keeps_deque(monkeypatch,indicator_type):
    ind=_indicator(indicator_type,32,120); calls=[]
    original=basicops._once_monotonic_index
    def observed(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(basicops,'_once_monotonic_index',observed)
    ind.once(31,50)
    assert calls==[1]

@pytest.mark.parametrize('indicator_type',CASES)
def test_period_getter_mutating_source_keeps_window_order(monkeypatch,indicator_type):
    ind=_indicator(indicator_type,32,120)
    manager=object.__getattribute__(ind.p,'_param_manager'); manager_cls=type(manager)
    original=manager_cls.get; rows=[]
    for fast in (False,True):
        reads=[];src=array.array('d',[(i*17%37)/3.0 for i in range(120)])
        dst=array.array('d',[-99.0]*120);ind.data.array=src;ind.lines[0].array=dst
        def get(self,name,*args,**kwargs):
            if self is manager and name=='period':
                reads.append(name)
                if len(reads)==2:src[1]=1000.0
            return original(self,name,*args,**kwargs)
        with monkeypatch.context() as m:
            m.setattr(manager_cls,'get',get)
            m.setattr(basicops,'_MIN_PERIOD_FOR_MONOTONIC_INDEX_ONCE',32 if fast else 100000)
            ind.once(31,40)
        rows.append((len(reads),list(dst[31:40]),src[1]))
    assert rows[0]==rows[1]

@pytest.mark.parametrize('indicator_type',CASES[2:])
@pytest.mark.parametrize('kind',['instance','code','collision'])
def test_rebound_or_side_effecting_native_manager_keeps_generic(monkeypatch,indicator_type,kind):
    ind=_indicator(indicator_type,32,120)
    manager=object.__getattribute__(ind.p,'_param_manager');manager_cls=type(manager)
    state=object.__getattribute__(manager,'__dict__'); original=manager_cls.get; rows=[]
    for fast in (False,True):
        reads=[];src=array.array('d',[(i*17%37)/3.0 for i in range(120)])
        dst=array.array('d',[-99.0]*120);ind.data.array=src;ind.lines[0].array=dst
        def get_instance(name,*args,**kwargs):
            if name=='period':
                reads.append(1)
                if len(reads)==2:src[1]=1000.0
            return original(manager,name,*args,**kwargs)
        class Collision:
            def __hash__(self):return hash('period')
            def __eq__(self,other):
                reads.append(1)
                if len(reads)==2:src[1]=1000.0
                return False
        with monkeypatch.context() as m:
            if kind=='instance':m.setitem(state,'get',get_instance)
            elif kind=='collision':
                prior=state['_values'];values={Collision():0};values.update(prior);reads.clear();src[1]=17/3
                m.setitem(state,'_values',values)
            else:
                # In-place changes keep function identity but replace its code.
                # A distinctive constant result makes any skipped read visible.
                def substitute(self,name,default=None,_MISSING=None):
                    state=self.__dict__
                    state['_probe_count']=state.get('_probe_count',0)+1
                    return 32 if state['_probe_count']==1 else 99
                state.pop('_probe_count',None)
                m.setattr(original,'__code__',substitute.__code__)
            m.setattr(basicops,'_MIN_PERIOD_FOR_MONOTONIC_INDEX_ONCE',32 if fast else 100000)
            ind.once(31,40)
        rows.append((len(reads),list(dst[31:40]),src[1]))
    assert rows[0]==rows[1]

def test_manager_replaced_before_basicops_reload_stays_on_window_path():
    import json,os,subprocess,sys
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    script = "import importlib,sys,json\nsys.path.insert(0,'tests/unit/indicators')\nimport backtrader as bt\nimport backtrader.parameters as params\nimport backtrader.indicators.basicops as b\nfrom test_iter71_numeric_acceptance_regressions import _indicator\noriginal=params.ParameterManager.get; state={'target':None,'reads':0}\ndef replacement(self,name,*args,**kwargs):\n if self is state['target'] and name=='period':\n  state['reads']+=1\n  return 32 if state['reads']==1 else 99\n return original(self,name,*args,**kwargs)\nparams.ParameterManager.get=replacement\nb=importlib.reload(b)\nind=_indicator(b.FindLastIndexHighest,32,120)\nstate['target']=object.__getattribute__(ind.p,'_param_manager')\nind.once(31,36)\nprint(json.dumps({'reads':state['reads'],'values':list(ind.lines[0].array[31:36])}))\n"
    run=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,env=env,check=True)
    assert json.loads(run.stdout)=={'reads':6,'values':[85.0,86.0,87.0,88.0,89.0]}
