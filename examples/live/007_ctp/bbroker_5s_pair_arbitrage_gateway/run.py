#!/usr/bin/env python
"""Run bbroker_5s_pair_arbitrage_gateway through the independently started Gateway."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway_client_runner import main
from pair_spread_strategy import PairSpreadStrategy

if __name__ == "__main__":
    raise SystemExit(main(PairSpreadStrategy, "bbroker_5s_pair_arbitrage (Gateway)", Path(__file__).resolve().parent))
