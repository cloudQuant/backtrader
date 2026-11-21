import hashlib
import json
import pathlib
import platform
import sys
import time

root = pathlib.Path(sys.argv[1])
count = int(sys.argv[2])
assert count in (1, 8)
sys.path.insert(0, str(root))
import backtrader as bt
import backtrader.indicators.sma as sma
from backtrader.utils.load_data import load_mt5_csv

data = root / "tests/datas/XAUUSD_M15.csv"
source = root / "backtrader/indicators/sma.py"
data_sha = hashlib.sha256(data.read_bytes()).hexdigest()
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
assert pathlib.Path(sma.__file__).resolve() == source.resolve()
assert data_sha == "d364dea806a6ef634277184d1edc71fb90216fadacf673f70ea9706c55a1f51f"
frame = load_mt5_csv(str(data)).iloc[:30000]
assert len(frame) == 30000
class Strategy(bt.Strategy):
    def __init__(self):
        self.lines_sma = [bt.ind.SMA(self.data.close, period=512 + i * 8) for i in range(count)]
cerebro = bt.Cerebro(stdstats=False, runonce=True)
cerebro.adddata(bt.feeds.PandasData(dataname=frame))
cerebro.addstrategy(Strategy)
start = time.perf_counter()
strategy = cerebro.run(runonce=True)[0]
elapsed = time.perf_counter() - start
digest = hashlib.sha256()
for line in strategy.lines_sma:
    digest.update(line.array.tobytes())
print(json.dumps({"rows": len(frame), "periods": [512 + i * 8 for i in range(count)],
                  "seconds": elapsed, "output_sha256": digest.hexdigest(),
                  "source_sha256": source_sha, "data_sha256": data_sha,
                  "python": sys.version, "platform": platform.platform(),
                  "executable": sys.executable, "runonce": True}))
