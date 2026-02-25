"""SA futures dual moving average strategy via CTP.

This script implements a classic dual moving average crossover strategy
for SA (soda ash / 纯碱) main contract on CZCE exchange, using live
CTP market data through the ctp-python integration.

Strategy logic:
    - BUY  when fast MA crosses above slow MA (golden cross)
    - SELL when fast MA crosses below slow MA (death cross)
    - Only hold one position direction at a time
    - Account balance is queried and printed each bar

Usage:
    # Use auto-detected server:
    python ctp_sa_dual_ma_strategy.py

    # Force a specific server preset:
    CTP_SERVER=simnow_24h python ctp_sa_dual_ma_strategy.py

    # Custom server via environment:
    CTP_TD_FRONT=tcp://x.x.x.x:port CTP_MD_FRONT=tcp://x.x.x.x:port python ctp_sa_dual_ma_strategy.py

Credentials loaded from .env (simnow_user_id / simnow_password).
"""

import logging
import os
import socket
import sys
from datetime import datetime, time
from pathlib import Path

import backtrader as bt
from backtrader.stores.ctpstore import CTPStore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------
def load_env(env_path=None):
    """Load environment variables from .env file."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / '.env'
    if not env_path.exists():
        logger.warning(f".env not found at {env_path}")
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()


load_env()

# ---------------------------------------------------------------------------
# Server presets
# ---------------------------------------------------------------------------
SERVER_PRESETS = {
    'simnow_24h': {
        'td_front': 'tcp://180.168.146.187:10130',
        'md_front': 'tcp://180.168.146.187:10131',
    },
    'simnow_trade': {
        'td_front': 'tcp://180.168.146.187:10201',
        'md_front': 'tcp://180.168.146.187:10211',
    },
    'openctp': {
        'td_front': 'tcp://121.37.80.177:20002',
        'md_front': 'tcp://121.37.80.177:20004',
    },
}


def check_tcp(host, port, timeout=3):
    """Quick TCP connectivity check."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        s.close()
        return False


def find_reachable_server():
    """Return (name, addrs) for the first reachable preset, or (None, None)."""
    for name, addrs in SERVER_PRESETS.items():
        hp = addrs['td_front'].replace('tcp://', '')
        host, port = hp.rsplit(':', 1)
        print(f"  Probing {name} ({host}:{port})... ", end='', flush=True)
        if check_tcp(host, int(port)):
            print("OK")
            return name, addrs
        else:
            print("unreachable")
    return None, None


def resolve_server():
    """Determine which CTP server to connect to."""
    # Priority 1: explicit env vars
    td = os.environ.get('CTP_TD_FRONT', '').strip()
    md = os.environ.get('CTP_MD_FRONT', '').strip()
    if td and md:
        return 'custom', {'td_front': td, 'md_front': md}

    # Priority 2: forced preset
    forced = os.environ.get('CTP_SERVER', '').strip()
    if forced and forced in SERVER_PRESETS:
        return forced, SERVER_PRESETS[forced]

    # Priority 3: auto-detect
    print("Auto-detecting reachable CTP server...")
    return find_reachable_server()


# ---------------------------------------------------------------------------
# Dual Moving Average Strategy for SA futures
# ---------------------------------------------------------------------------
class DualMAStrategy(bt.Strategy):
    """Dual moving average crossover strategy for SA (soda ash) futures.

    Params:
        fast_period: Period for the fast moving average (default: 5).
        slow_period: Period for the slow moving average (default: 20).
        order_size:  Number of lots per trade (default: 1).
        print_log:   Whether to print detailed logs (default: True).
    """

    params = dict(
        fast_period=5,
        slow_period=20,
        order_size=1,
        print_log=True,
    )

    def __init__(self):
        self.live_data = False
        self.bar_count = 0
        self.order = None  # pending order tracker

        # Moving averages
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.p.slow_period)

        # Crossover signal: +1 when fast crosses above slow, -1 when below
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    def log(self, msg):
        if self.p.print_log:
            dt = self.data.datetime.datetime(0)
            print(f"[{dt}] {msg}")

    def notify_data(self, data, status, *args, **kwargs):
        status_name = data._getstatusname(status)
        self.log(f"DATA STATUS: {data._name} -> {status_name}")
        self.live_data = (status_name == 'LIVE')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return  # wait for further updates

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"BUY EXECUTED: price={order.executed.price:.2f}, "
                    f"size={order.executed.size}, "
                    f"comm={order.executed.comm:.2f}"
                )
            else:
                self.log(
                    f"SELL EXECUTED: price={order.executed.price:.2f}, "
                    f"size={order.executed.size}, "
                    f"comm={order.executed.comm:.2f}"
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER FAILED: {order.getstatusname()}")

        self.order = None  # clear pending order

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(
                f"TRADE CLOSED: pnl={trade.pnl:.2f}, "
                f"net_pnl={trade.pnlcomm:.2f}"
            )

    def prenext(self):
        """Called before enough bars for indicators — just log the bar."""
        self.bar_count += 1
        self.log(
            f"[prenext] bar#{self.bar_count} {self.data._name} "
            f"C={self.data.close[0]:.2f} (waiting for MA warmup: "
            f"{len(self)}/{self.p.slow_period})"
        )

    def next(self):
        self.bar_count += 1

        # Print bar data
        self.log(
            f"bar#{self.bar_count} {self.data._name} "
            f"O={self.data.open[0]:.2f} H={self.data.high[0]:.2f} "
            f"L={self.data.low[0]:.2f} C={self.data.close[0]:.2f} "
            f"V={self.data.volume[0]:.0f}"
        )
        self.log(
            f"  fast_ma={self.fast_ma[0]:.2f} slow_ma={self.slow_ma[0]:.2f} "
            f"cross={self.crossover[0]:.0f}"
        )

        # Account balance
        cash = self.broker.getcash()
        value = self.broker.getvalue()
        pos = self.getposition(self.data)
        self.log(
            f"  Account: cash={cash:.2f} value={value:.2f} "
            f"pos_size={pos.size} pos_price={pos.price:.2f}"
        )

        # Skip trading until live data
        if not self.live_data:
            return

        # Skip if there's a pending order
        if self.order is not None:
            return

        current_pos = pos.size

        # --- Trading logic ---
        if self.crossover[0] > 0:
            # Golden cross: fast MA crossed above slow MA
            if current_pos < 0:
                # Close short first
                self.log(f"SIGNAL: Golden cross -> close short ({abs(current_pos)} lots)")
                self.order = self.buy(
                    data=self.data,
                    size=abs(current_pos),
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] + 2,
                )
            if current_pos <= 0:
                # Open long
                self.log(f"SIGNAL: Golden cross -> open long ({self.p.order_size} lots)")
                self.order = self.buy(
                    data=self.data,
                    size=self.p.order_size,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] + 2,
                )

        elif self.crossover[0] < 0:
            # Death cross: fast MA crossed below slow MA
            if current_pos > 0:
                # Close long first
                self.log(f"SIGNAL: Death cross -> close long ({current_pos} lots)")
                self.order = self.sell(
                    data=self.data,
                    size=current_pos,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] - 2,
                )
            if current_pos >= 0:
                # Open short
                self.log(f"SIGNAL: Death cross -> open short ({self.p.order_size} lots)")
                self.order = self.sell(
                    data=self.data,
                    size=self.p.order_size,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] - 2,
                )

    def stop(self):
        """Called when the strategy is stopped."""
        self.log(
            f"Strategy stopped. Total bars: {self.bar_count}, "
            f"Final value: {self.broker.getvalue():.2f}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = os.environ.get('simnow_user_id', '')
    password = os.environ.get('simnow_password', '')
    if not user_id or not password:
        print("ERROR: simnow_user_id and simnow_password must be set in .env")
        sys.exit(1)

    server_name, server_addrs = resolve_server()
    if server_addrs is None:
        print("ERROR: No CTP server is reachable. Check network/VPN.")
        sys.exit(1)

    td_front = server_addrs['td_front']
    md_front = server_addrs['md_front']

    print(f"Server: {server_name}")
    print(f"  TD: {td_front}")
    print(f"  MD: {md_front}")
    print(f"  User: {user_id}")

    ctp_setting = {
        'td_front': td_front,
        'md_front': md_front,
        'broker_id': '9999',
        'user_id': user_id,
        'password': password,
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }

    # SA (soda ash / 纯碱) main contract on CZCE
    # Common active months: 01, 05, 09
    # Adjust the contract month as needed
    sa_instrument = 'SA509'
    exchange = 'CZCE'

    print(f"Instrument: {sa_instrument}.{exchange}")
    print("Connecting to CTP...")

    store = CTPStore(ctp_setting)

    if not store.is_connected:
        print("ERROR: CTP connection/login failed.")
        store.stop()
        sys.exit(1)

    print("CTP connected!")

    cerebro = bt.Cerebro(live=True)
    cerebro.setbroker(store.getbroker())

    cerebro.addstrategy(
        DualMAStrategy,
        fast_period=5,
        slow_period=20,
        order_size=1,
        print_log=True,
    )

    data = store.getdata(
        dataname=f'{sa_instrument}.{exchange}',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        num_init_backfill=0,
    )
    cerebro.adddata(data)

    print(f"Starting dual-MA strategy on {sa_instrument}... (Ctrl+C to stop)")
    print(f"  Fast MA period: 5")
    print(f"  Slow MA period: 20")
    print(f"  Order size: 1 lot")
    print("=" * 60)

    try:
        cerebro.run()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        store.stop()
        print("Done.")
