#!/usr/bin/env python
"""Run mixbroker_5s_pair_arbitrage_gateway through the independently started Gateway.
The shared runner accepts ``--run-id``, writes the run-status heartbeat and final
summary, and returns the run contract's exit code (iteration 66, section 5.2 B6).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway_client_runner import main
from pair_spread_strategy import PairSpreadStrategy

if __name__ == "__main__":
    raise SystemExit(main(PairSpreadStrategy, "mixbroker_5s_pair_arbitrage (Gateway)", Path(__file__).resolve().parent))
