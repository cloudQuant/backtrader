# Backtrader Metaclass Migration Report
==================================================

**Summary:**
- Files needing migration: 122
- Classes using metaclasses: 3

## Metaclass Usage Breakdown
### MetaParams -> ModernParamsBase
Used in 1 classes:
  - ParamsBase in ./backtrader/metabase.py

### MetaLineIterator -> ModernLineIterator
Used in 1 classes:
  - LineIterator in ./backtrader/lineiterator.py

### MetaLineRoot -> ModernLineRoot
Used in 1 classes:
  - LineRoot in ./backtrader/lineroot.py

## File-by-File Analysis
### ./backtrader/linebuffer.py
**Lifecycle methods:** dopreinit, dopostinit
**Migration suggestions:**
  - Migrate lifecycle methods ['dopreinit', 'dopostinit'] to use regular __init__ and method patterns

### ./backtrader/store.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/metabase.py
**Metaclass classes:**
  - ParamsBase (uses MetaParams)
**Lifecycle methods:** doprenew, donew, dopreinit, doinit, dopostinit
**Migration suggestions:**
  - Replace 'class ParamsBase(metaclass=MetaParams)' with 'class ParamsBase(ModernParamsBase)'
  - Migrate lifecycle methods ['doprenew', 'donew', 'dopreinit', 'doinit', 'dopostinit'] to use regular __init__ and method patterns

### ./backtrader/lineiterator.py
**Metaclass classes:**
  - LineIterator (uses MetaLineIterator)
**Lifecycle methods:** donew, dopreinit, dopostinit
**Migration suggestions:**
  - Replace 'class LineIterator(metaclass=MetaLineIterator)' with 'class LineIterator(ModernLineIterator)'
  - Migrate lifecycle methods ['donew', 'dopreinit', 'dopostinit'] to use regular __init__ and method patterns

### ./backtrader/indicator.py
**Lifecycle methods:** donew
**Migration suggestions:**
  - Migrate lifecycle methods ['donew'] to use regular __init__ and method patterns

### ./backtrader/resamplerfilter.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzer.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/strategy.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/tradingcal.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/fillers.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/writer.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/lineseries.py
**Lifecycle methods:** donew
**Migration suggestions:**
  - Migrate lifecycle methods ['donew'] to use regular __init__ and method patterns

### ./backtrader/lineroot.py
**Metaclass classes:**
  - LineRoot (uses MetaLineRoot)
**Lifecycle methods:** donew
**Migration suggestions:**
  - Replace 'class LineRoot(metaclass=MetaLineRoot)' with 'class LineRoot(ModernLineRoot)'
  - Migrate lifecycle methods ['donew'] to use regular __init__ and method patterns

### ./backtrader/filters/renko.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/filters/bsplitter.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/filters/datafilter.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/filters/calendardays.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/filters/datafiller.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/commissions/__init__.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/commissions/dc_commission.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/calmar.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/periodstats.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/logreturnsrolling.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/total_value.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/transactions.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/positions.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/returns.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/timereturn.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/vwr.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/pyfolio.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/drawdown.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/sharpe.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/analyzers/leverage.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/directionalmove.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/rmi.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/zlind.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/awesomeoscillator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/zlema.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/percentrank.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/mabase.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/vortex.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/accdecoscillator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/priceoscillator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/ultimateoscillator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/psar.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/macd.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/basicops.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/myind.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/ols.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/stochastic.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/atr.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/prettygoodoscillator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/dma.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/percentchange.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/hadelta.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/cci.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/hma.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/deviation.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/dema.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/williams.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/dv2.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/tsi.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/ichimoku.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/kama.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/pivotpoint.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/rsi.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/trix.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/lrsi.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/hurst.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/aroon.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/bollinger.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/momentum.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/dpo.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/envelope.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/kst.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/indicators/contrib/vortex.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/tests/test_backtrader.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/tests/test_vector_cs_strategy/test_backtrader_cs.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/tests/test_backtrader_ts_strategy/test_backtrader_ts.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/tests/test_vector_ts_strategy/test_backtrader_vector_ts_equal.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/stores/oandastore.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/stores/vchartfile.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/stores/ibstore.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/stores/ctpstore.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/utils/fractal.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/cryptofeed.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/sierrachart.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/ctpdata.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/rollover.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/pandafeed.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/quandl.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/yahoo.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/influxfeed.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/ibdata.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/ccxtfeed.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/csvgeneric.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/vcdata.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/mt4csv.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/blaze.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/oanda.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/feeds/vchart.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/benchmark.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/timereturn.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/drawdown.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/trades.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/broker.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/logreturns.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./backtrader/observers/buysell.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tools/performance_benchmark.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tools/benchmark_suite.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tools/metaclass_migrator.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./studies/contrib/fractal.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/debug_setcommission.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/test_parameterized_base_day34_35.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/original_tests/test_strategy_unoptimized.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/original_tests/test_analyzer-sqn.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/original_tests/test_analyzer-timereturn.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/original_tests/test_strategy_optimized.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/crypto_tests/test_base_funding_rate.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./tests/crypto_tests/test_buy_sell_order_strategy.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./examples/sma_crossover.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')

### ./examples/parameterized_base_day34_35_demo.py
**Has params tuples** - need to convert to descriptors
**Migration suggestions:**
  - Convert params tuples to ParameterDescriptor declarations:
  params = (('param1', 10), ('param2', 'value'))
  becomes:
  param1 = ParameterDescriptor(default=10, name='param1')
  param2 = ParameterDescriptor(default='value', name='param2')
