import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_light_import_exposes_live_runner_api_without_heavy_modules():
    repo_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import sys
        import backtrader as bt

        assert bt.Cerebro
        assert bt.Strategy
        assert bt.TimeFrame.Seconds
        assert bt.observers.TradeLogger
        assert bt.indicators.SimpleMovingAverage
        assert bt.indicators.CrossOver
        assert bt.indicators.BollingerBands
        assert bt.indicators.RelativeStrengthIndex
        assert bt.indicators.OBV is bt.indicators.OnBalanceVolume
        assert bt.indicators.AverageDirectionalMovementIndex
        assert bt.indicators.PlusDirectionalIndicator
        assert bt.indicators.MinusDirectionalIndicator
        assert bt.indicators.Highest
        assert bt.indicators.Lowest
        assert "backtrader.analyzers" not in sys.modules
        assert "backtrader.talib" not in sys.modules
        assert "backtrader.profiles" not in sys.modules
        """
    )
    env = os.environ.copy()
    env["BACKTRADER_LIGHT_IMPORT"] = "1"
    env["PYTHONPATH"] = str(repo_root)

    subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
