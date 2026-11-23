#!/usr/bin/env python
"""Run mixbroker_5s_single_symbol_gateway through the independently started Gateway.
The shared runner accepts ``--run-id``, writes the run-status heartbeat and final
summary, and returns the run contract's exit code (iteration 66, section 5.2 B6).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway_client_runner import main
from single_symbol_ma_strategy import SingleSymbolMaStrategy

if __name__ == "__main__":
    raise SystemExit(main(SingleSymbolMaStrategy, "mixbroker_5s_single_symbol (Gateway)", Path(__file__).resolve().parent))
