#!/usr/bin/env python
"""Run sa_dual_ma_gateway through the independently started Gateway."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway_client_runner import main
from sa_dual_ma_strategy import DualMAStrategy

if __name__ == "__main__":
    raise SystemExit(main(DualMAStrategy, "SA dual MA (Gateway)", Path(__file__).resolve().parent))
