"""Paired, function-isolated R71-100 Cerebro comparison on public source."""
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import sys
import time

import pandas as pd
import backtrader as bt
from backtrader import linebuffer
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy

ROOT = Path(__file__).parent
source = (ROOT / 'legacy_linebuffer.py').read_text(encoding='utf-8')
node = next(node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == '_factor_context_for_line')
code = ast.get_source_segment(source, node)
namespace = {}
exec(compile(code, '<historical-factor-context-lookup>', 'exec'), linebuffer.__dict__, namespace)
before = namespace['_factor_context_for_line']
after = linebuffer._factor_context_for_line
N = 5000
index = pd.date_range('2024-01-01', periods=N, freq='min', tz='UTC')
close = [100 + 0.003 * i + 3 * math.sin(i * .07) for i in range(N)]
frame = pd.DataFrame(dict(open=[v-.1 for v in close], high=[v+.6 for v in close],
                          low=[v-.7 for v in close], close=close, volume=[100.] * N), index=index)

def digest(values):
    h=hashlib.sha256()
    for value in values:
        h.update(struct.pack('!d', float(value)))
    return h.hexdigest()

def ordinary(runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.expressions=[(self.data.close * (1.01+i*.001) + self.data.high) / 2.0
                              for i in range(16)]
            self.rows=[]
        def next(self):
            self.rows.extend(float(expression[0]) for expression in self.expressions)
    c=bt.Cerebro(stdstats=False,runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame)); c.addstrategy(Probe)
    start=time.perf_counter(); strategy=c.run(preload=True)[0]; elapsed=time.perf_counter()-start
    return elapsed,len(strategy.rows),digest(strategy.rows)

def factor(runonce):
    class Factor(FactorIndicator):
        lines=('factor',)
        formula_fields=required_fields=('close',)
        lookback_h=0
        def __init__(self):
            super().__init__()
            self.expr=(self.data.close * 1.01 + self.data.close * 1.02) / 2.0
        def next(self):
            self.outputs[self.datas[0]].factor[0]=self.expr[0]
    grid=index.rename('close_time')
    research=ResearchSpec(grid=pd.DataFrame({'open_time':grid-pd.Timedelta(minutes=1)},index=grid),
        start=grid[0],end=grid[-1],targets=('asset',),source_timezone='UTC',
        snapshot_id='r71-100-benchmark',price_basis='synthetic',calendar_id='synthetic',
        frequency='1min',feed_time_kind='close_time',groups={'asset':'market'})
    c=bt.Cerebro(stdstats=False,runonce=runonce)
    c.adddata(align_to_grid(frame,research,'asset').feed,name='asset')
    spec=FactorSpec(name='factor',indicator=Factor,panel_line='factor',
                    field_bindings={'close':'feed:target:close'},mode='native')
    c.addstrategy(FactorStrategy,research=research,factors={'factor':spec})
    start=time.perf_counter(); strategy=c.run(preload=True)[0]; elapsed=time.perf_counter()-start
    data=strategy.get_panel().factors['factor'].to_numpy(dtype='float64').ravel()
    return elapsed,len(data),digest(data)

records=[]
for scenario, fn in [('ordinary',ordinary),('factor',factor)]:
    for runonce in (False,True):
        for repetition in range(5):
            order=[('before',before),('after',after)]
            if repetition % 2: order.reverse()
            for label, impl in order:
                linebuffer._factor_context_for_line=impl
                elapsed,count,hash_=fn(runonce)
                records.append(dict(scenario=scenario,runonce=runonce,repeat=repetition,
                                    version=label,seconds=elapsed,count=count,sha256=hash_))
                print(scenario,runonce,repetition,label,round(elapsed,6),count,hash_[:12],flush=True)
linebuffer._factor_context_for_line=after
groups={}
for r in records:
    key=(r['scenario'],r['runonce'])
    groups.setdefault(key,[]).append(r)
summary=[]
for (scenario, runonce), group in groups.items():
    hashes={r['sha256'] for r in group}; counts={r['count'] for r in group}
    if len(hashes)!=1 or len(counts)!=1:
        raise AssertionError((scenario,runonce,hashes,counts))
    med={k:statistics.median(r['seconds'] for r in group if r['version']==k)
         for k in ('before','after')}
    summary.append(dict(scenario=scenario,runonce=runonce,medians=med,
                        speedup=med['before']/med['after'],count=counts.pop(),sha256=hashes.pop()))
out=dict(scope='only lookup implementation varies, current remaining source fixed',
         current_commit='62d08b47d70d863ddc6853c13cebeb5c3f686a58',
         before_commit='506689943^',linebuffer=str(Path(linebuffer.__file__).resolve()),
         python=sys.version,platform=platform.platform(),N=N,records=records,summary=summary,
         script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         before_source_sha256=hashlib.sha256(code.encode()).hexdigest())
(ROOT/'result_r2.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2),flush=True)
