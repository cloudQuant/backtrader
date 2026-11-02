import timeit, statistics
from bt_api_ctp.containers.ctp.ctp_ticker import CtpTickerData
from bt_api_base.containers.auto_init_mixin import AutoInitMixin
INFO = {"InstrumentID":"SA609","LastPrice":1500.0,"PreSettlementPrice":1490.0,"OpenPrice":1495.0,"HighestPrice":1510.0,
 "LowestPrice":1488.0,"BidPrice1":1499.0,"BidVolume1":10,"AskPrice1":1501.0,"AskVolume1":12,"Volume":12345,
 "Turnover":1.0e8,"OpenInterest":5000.0,"UpperLimitPrice":1600.0,"LowerLimitPrice":1400.0,"UpdateTime":"10:00:00",
 "UpdateMillisec":500,"TradingDay":"20261102","ActionDay":"20261102","ExchangeID":"CZCE"}
def build(cls):
    t = cls(INFO, symbol_name="SA609", recv_time_utc=1.0e9, recv_monotonic_ns=1); t.init_data(); return t
class Guarded(CtpTickerData):
    def __setattr__(self, name, value):
        if self.__dict__.get("_frozen", False):
            raise AttributeError(name)
        object.__setattr__(self, name, value)
def run(cls):
    xs = [min(timeit.repeat(lambda: build(cls), number=20000, repeat=1))/20000*1e9 for _ in range(7)]
    return statistics.median(xs)
a, b = run(CtpTickerData), run(Guarded)
print(f"ctp build+init plain={a:.0f}ns guarded={b:.0f}ns overhead={(b-a)/a*100:.1f}%")
t = build(CtpTickerData)
g = min(timeit.repeat(t.get_last_price, number=500000, repeat=7))/500000*1e9
import copy
d = min(timeit.repeat(lambda: copy.deepcopy(t), number=5000, repeat=5))/5000*1e9
print(f"ctp get_last_price={g:.0f}ns deepcopy(ctp ticker)={d:.0f}ns")
