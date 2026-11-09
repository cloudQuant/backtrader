#!/usr/bin/env python
"""Run tickbroker_5s_single_symbol_gateway through the independently started Gateway."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway_client_runner import main
from single_symbol_ma_strategy import SingleSymbolMaStrategy

if __name__ == "__main__":
    raise SystemExit(main(SingleSymbolMaStrategy, "tickbroker_5s_single_symbol (Gateway)", Path(__file__).resolve().parent))
