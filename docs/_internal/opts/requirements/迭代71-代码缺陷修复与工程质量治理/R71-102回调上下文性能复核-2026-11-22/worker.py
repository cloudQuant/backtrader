import hashlib
import json
import pathlib
import platform
import sys
import time

root = pathlib.Path(sys.argv[1]).resolve()
label = sys.argv[2]
manifest = json.loads((root.parent / 'manifest.json').read_text(encoding='utf8'))
expected = manifest['paths'][label]
sys.path.insert(0, str(root))
import backtrader as bt
import backtrader.lineiterator as iterator
import backtrader.linebuffer as buffer
from backtrader.utils.load_data import load_mt5_csv

assert pathlib.Path(bt.__file__).resolve() == (root / 'backtrader/__init__.py').resolve()
assert pathlib.Path(iterator.__file__).resolve() == (root / 'backtrader/lineiterator.py').resolve()
assert pathlib.Path(buffer.__file__).resolve() == (root / 'backtrader/linebuffer.py').resolve()

def pinned():
    got = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in expected}
    assert got == expected, (got, expected)
    return got

pre = pinned()
data = load_mt5_csv(str(root / 'tests/datas/XAUUSD_M15.csv')).iloc[:30000]
assert len(data) == 30000
periods = list(range(10, 26))

class Strategy(bt.Strategy):
    def __init__(self):
        self.smas = [bt.ind.SMA(self.data.close, period=p) for p in periods]
        self.callbacks = 0

    def next(self):
        self.callbacks += 1

def make_engine(frame):
    engine = bt.Cerebro(stdstats=False, runonce=False)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Strategy)
    return engine

# Warm the same code path in this interpreter before the measured run.
make_engine(data.iloc[:1000]).run(runonce=False, preload=True)
engine = make_engine(data)
start = time.perf_counter()
strategy = engine.run(runonce=False, preload=True)[0]
elapsed = time.perf_counter() - start
digest = hashlib.sha256()
for sma in strategy.smas:
    assert len(sma.array) == len(data)
    digest.update(sma.array.tobytes())
post = pinned()
assert pre == post
print(json.dumps({'label': label, 'seconds': elapsed, 'rows': len(data), 'periods': periods,
                  'strategy_next_callbacks': strategy.callbacks, 'line_output_sha256': digest.hexdigest(),
                  'lineiterator_sha256': post['backtrader/lineiterator.py'],
                  'linebuffer_sha256': post['backtrader/linebuffer.py'],
                  'data_sha256': post['tests/datas/XAUUSD_M15.csv'],
                  'python': sys.version, 'executable': sys.executable,
                  'platform': platform.platform(), 'runonce': False}))
