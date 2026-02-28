"""CTP sample trading script for backtrader using ctp-python.

This module demonstrates backtrader CTP integration for live Chinese
futures market trading with real-time tick data via ctp-python.

Usage:
    python test_ctp_sample.py

Credentials are loaded from .env file (simnow_user_id / simnow_password).
Uses SimNow 7x24 environment by default for testing outside trading hours.
"""

import logging
import os
import sys
from datetime import datetime, time
from pathlib import Path

import backtrader as bt
from backtrader.stores.ctpstore import CTPStore

# Enable CTP debug logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    stream=sys.stdout,
)


# Load .env file
def load_env(env_path=None):
    """Load environment variables from .env file.

    Parses KEY=VALUE pairs and sets them in os.environ. Skips comments
    and empty lines.

    Args:
        env_path: Path to .env file. Defaults to ../.env relative to
            this script's location.

    Returns:
        None. Environment variables are set directly in os.environ.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / '.env'
    if not env_path.exists():
        print(f"WARNING: .env file not found at {env_path}")
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

# ---- Server address presets ----
# SimNow 7x24:  TD 180.168.146.187:10130  MD 180.168.146.187:10131
# SimNow Trade: TD 180.168.146.187:10201  MD 180.168.146.187:10211
# OpenCTP 7x24: TD 121.37.80.177:20002   MD 121.37.80.177:20004  (free, no auth needed)
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

DAY_START = time(8, 45)
DAY_END = time(15, 15)
NIGHT_START = time(20, 45)
NIGHT_END = time(2, 45)


def is_trading_period():
    """Check if current time is within SimNow trading hours.

    Returns:
        bool: True if current time is within day or night trading
            sessions, False otherwise.
    """
    t = datetime.now().time()
    return (DAY_START <= t <= DAY_END) or (t >= NIGHT_START) or (t <= NIGHT_END)


class GoldQuoteStrategy(bt.Strategy):
    """Strategy that prints gold futures quotes and account balance each bar.

    Attributes:
        live_data: Flag indicating when live data is being received.
        bar_count: Counter for the number of bars processed.
    """

    params = dict(smaperiod=5)

    def __init__(self):
        """Initialize strategy state variables."""
        self.live_data = False
        self.bar_count = 0

    def prenext(self):
        """Called before minimum period is reached.

        Prints initial data bars as they arrive during warmup period.

        Args:
            None. Uses self.datas to access all data feeds.
        """
        for d in self.datas:
            print(f"[prenext] {d._name} dt={d.datetime.datetime(0)} close={d.close[0]:.2f}")

    def next(self):
        """Called for each bar after minimum period is reached.

        Prints OHLCV data and account information for each data feed.

        Args:
            None. Uses self.datas to access all data feeds.
        """
        self.bar_count += 1
        for d in self.datas:
            print(
                f"[next] bar#{self.bar_count} {d._name} "
                f"dt={d.datetime.datetime(0)} "
                f"O={d.open[0]:.2f} H={d.high[0]:.2f} "
                f"L={d.low[0]:.2f} C={d.close[0]:.2f} V={d.volume[0]}"
            )

        # Query and print account balance each bar
        cash = self.broker.getcash()
        value = self.broker.getvalue()
        print(f"  >> Account: cash={cash:.2f}, value={value:.2f}")

        if self.live_data:
            print("  >> [LIVE bar received]")

    def notify_order(self, order):
        """Called when order status changes.

        Args:
            order: Order object with updated status information.
        """
        print(f"[Order] ref={order.ref} status={order.getstatusname()}")

    def notify_data(self, data, status, *args, **kwargs):
        """Called when data feed status changes.

        Args:
            data: Data feed object whose status changed.
            status: New status code.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        status_name = data._getstatusname(status)
        print(f"[notify_data] {data._name}: {status_name}")
        self.live_data = (status_name == 'LIVE')


def check_tcp_connectivity(host, port, timeout=3):
    """Perform a quick TCP connectivity check.

    Args:
        host: Target hostname or IP address.
        port: Target port number.
        timeout: Connection timeout in seconds. Defaults to 3.

    Returns:
        bool: True if connection succeeds, False otherwise.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        s.close()
        return False


def find_reachable_server(presets):
    """Try each server preset and return the first reachable one.

    Tests TCP connectivity to each server's trading front endpoint
    and returns the first one that responds.

    Args:
        presets: Dictionary mapping server names to their address
            configurations containing 'td_front' key.

    Returns:
        tuple: (server_name, server_addrs) if reachable server found,
            (None, None) if no server is reachable.
    """
    for name, addrs in presets.items():
        td = addrs['td_front']
        # Extract host:port from tcp://host:port
        hp = td.replace('tcp://', '')
        host, port = hp.rsplit(':', 1)
        print(f"  Probing {name} ({host}:{port})... ", end='', flush=True)
        if check_tcp_connectivity(host, int(port)):
            print("OK")
            return name, addrs
        else:
            print("unreachable")
    return None, None


if __name__ == "__main__":
    user_id = os.environ.get('simnow_user_id', '')
    password = os.environ.get('simnow_password', '')
    if not user_id or not password:
        print("ERROR: simnow_user_id and simnow_password must be set in .env")
        sys.exit(1)

    # --- Select server ---
    # Override: set CTP_SERVER env var to force a preset (simnow_24h / simnow_trade / openctp)
    forced = os.environ.get('CTP_SERVER', '').strip()
    if forced and forced in SERVER_PRESETS:
        server_name = forced
        server_addrs = SERVER_PRESETS[forced]
        print(f"Using forced server preset: {server_name}")
    else:
        print("Auto-detecting reachable CTP server...")
        server_name, server_addrs = find_reachable_server(SERVER_PRESETS)
        if server_addrs is None:
            print("ERROR: No CTP server is reachable. Check network/VPN.")
            sys.exit(1)
        print(f"Using server: {server_name}")

    td_front = server_addrs['td_front']
    md_front = server_addrs['md_front']

    print(f"SimNow user_id={user_id}")
    print(f"TD front: {td_front}")
    print(f"MD front: {md_front}")

    ctp_setting = {
        'td_front': td_front,
        'md_front': md_front,
        'broker_id': '9999',
        'user_id': user_id,
        'password': password,
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }

    # Gold futures main contract on SHFE
    gold_instrument = 'au2506'

    print(f"Subscribing to: {gold_instrument}")
    print("Waiting for CTP connection...")

    store = CTPStore(ctp_setting)

    if not store.is_connected:
        print("ERROR: CTP connection/login failed. Check credentials and network.")
        store.stop()
        sys.exit(1)

    print("CTP connected and logged in successfully!")

    cerebro = bt.Cerebro(live=True)
    cerebro.setbroker(store.getbroker())
    cerebro.addstrategy(GoldQuoteStrategy)

    data1 = store.getdata(
        dataname=f'{gold_instrument}.SHFE',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        num_init_backfill=0,
    )
    cerebro.adddata(data1)

    print("Starting cerebro... (Ctrl+C to stop)")
    try:
        cerebro.run()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        store.stop()
