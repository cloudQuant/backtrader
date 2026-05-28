# MARSI

## Strategy Overview

This example migrates EA `1172_EA_MARSI` into Backtrader.

The original EA uses two `EMA_RSI_VA` curves:

- A slow curve built from `slow_RSIPeriod` and `slow_EMAPeriods`
- A fast curve built from `fast_RSIPeriod` and `fast_EMAPeriods`

## Trading Logic

- Open long when the slow line crosses from above to below the fast line.
- Open short when the slow line crosses from below to above the fast line.
- If a position is already open, close and reverse on the opposite cross.
- Optional dynamic lot sizing is supported through `use_multpl`, following the original formula based on balance and `Max_drawdown`.
- Optional fixed `SL` and `TP` are supported in points.

## Indicator Logic

`EMA_RSI_VA` is reconstructed directly from the bundled indicator source:

- Compute RSI on the selected price.
- Compute volatility term `abs(RSI - 50) + 1`.
- Use that term to derive adaptive smoothing period `pdsx`.
- Apply recursive smoothing to the selected price series.

## Files

- `strategy_marsi.py` - indicator reconstruction, data loader, strategy
- `run.py` - backtest runner
- `config.yaml` - strategy and backtest parameters

## Usage

```bash
python run.py
```

## Backtest Result

- Period: `2025-12-03 01:15:00` to `2026-03-10 09:00:00`
- Bars: `6129`
- Buy entries: `26`
- Sell entries: `27`
- Closed trades: `52`
- Analyzer total trades: `53`
- Wins: `33`
- Losses: `19`
- Win rate: `62.26%`
- Initial cash: `100000.00`
- Final value: `89288.10`
- Net PnL: `-10711.90`
- Total return: `-10.71%`
- Profit factor: `0.53`
- Sharpe ratio: `-8.96`
- Annual return: `-99.88%`
- Max drawdown: `12.62%`
- SQN: `-1.42`
