"""Static getter coverage matrix: which Base getters each provider overrides."""
import importlib, inspect, pkgutil, sys
from bt_api_base.containers.tickers.ticker import TickerData
from bt_api_base.containers.bars.bar import BarData
from bt_api_base.containers.orders.order import OrderData
from bt_api_base.containers.trades.trade import TradeData
from bt_api_base.containers.positions.position import PositionData
BASES = [TickerData, BarData, OrderData, TradeData, PositionData]
PKGS = ["bt_api_ctp", "bt_api_okx", "bt_api_binance"]

def classes(pkg):
    mod = importlib.import_module(pkg + ".containers")
    out = []
    for info in pkgutil.walk_packages(mod.__path__, pkg + ".containers."):
        try:
            m = importlib.import_module(info.name)
        except Exception as exc:  # noqa
            print("IMPORT-FAIL", info.name, type(exc).__name__, file=sys.stderr); continue
        for _, c in inspect.getmembers(m, inspect.isclass):
            if c.__module__ == m.__name__ and any(issubclass(c, b) and c is not b for b in BASES):
                out.append(c)
    return out

def raises_nie(fn):
    try:
        src = inspect.getsource(fn)
    except Exception:
        return False
    return "raise NotImplementedError" in src

rows = []
for pkg in PKGS:
    for c in classes(pkg):
        base = next(b for b in BASES if issubclass(c, b))
        getters = sorted(n for n, v in vars(base).items() if n.startswith("get_") and callable(v))
        miss_nie, inherited = [], []
        for g in getters:
            owner = next(k for k in c.__mro__ if g in vars(k))
            if owner is base:
                (miss_nie if raises_nie(vars(base)[g]) else inherited).append(g)
        extra = sorted(n for k in c.__mro__ if k not in (base,) and k.__module__.startswith(pkg)
                       for n, v in vars(k).items() if n.startswith("get_") and callable(v) and n not in vars(base))
        rows.append((pkg, base.__name__, c.__name__, len(getters), miss_nie, inherited, sorted(set(extra))))
for pkg, b, c, n, nie, inh, extra in rows:
    print(f"{pkg}|{b}|{c}|{n}|NIE={','.join(nie) or '-'}|INHERITED={','.join(inh) or '-'}|EXTRA={','.join(extra) or '-'}")
