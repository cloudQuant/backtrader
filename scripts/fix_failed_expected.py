#!/usr/bin/env python3
"""Fix expected.json for failed tests by running run.py and extracting metrics."""

import subprocess
import json
from pathlib import Path
import sys
import re

FAILED_TESTS = [
    ("mean_reversion", "0065_0231_ohlc_stochastic"),
    ("mean_reversion", "0112_0352_exp_blautvi_tm"),
    ("mean_reversion", "0071_0242_autotrader_momentum"),
    ("mean_reversion", "0119_0378_exp_atr_normalize_histogram"),
    ("mean_reversion", "0120_0387_exp_average_change_candle"),
    ("mean_reversion", "0121_0388_exp_xrsidemarker_histogram"),
    ("mean_reversion", "0122_0389_exp_2xma_ichimoku_oscillator"),
    ("mean_reversion", "0124_0398_exp_kwan_rdp"),
    ("mean_reversion", "0125_0399_exp_kwan_ccc"),
    ("mean_reversion", "0126_0401_exp_kwan_nrp"),
    ("mean_reversion", "0045_0108_icho_trend_ccidualonma_filter"),
    ("mean_reversion", "0046_0110_ma_trend_2"),
    ("mean_reversion", "0047_0132_exp_spearmanrankcorrelation_histogram"),
    ("mean_reversion", "0048_0154_exp_finetuningmacandle"),
    ("machine_learning", "0011_0384_ais2_trading_robot"),
    ("mean_reversion", "0049_0166_nrtr_revers"),
    ("mean_reversion", "0050_0167_extreme_ea"),
    ("mean_reversion", "0051_0171_rsi_rftl_ea"),
    ("mean_reversion", "0142_0635_ivan"),
    ("mean_reversion", "0078_0256_basic_cci_rsi"),
    ("calendar_effects", "0020_0407_turn_of_month_strategy"),
    ("mean_reversion", "0147_0673_expbuysellside"),
    ("mean_reversion", "0148_0674_exphawaves"),
    ("mean_reversion", "0227_1345_three_crows_soldiers_cci"),
    ("mean_reversion", "0169_0769_doubleup"),
    ("multi_indicator_system", "0021_macdcci"),
    ("multi_indicator_system", "0022_universum_3_0"),
    ("mean_reversion", "0236_0146_rsi_ea_v2"),
    ("mean_reversion", "0237_0328_aocci"),
    ("multi_indicator_system", "0028_perceptron"),
    ("mean_reversion", "0183_0947_colormetro_demarker"),
    ("multi_indicator_system", "0029_binary_wave"),
    ("mean_reversion", "0242_0546_anubis"),
    ("mean_reversion", "0243_0565_icci_ima"),
    ("mean_reversion", "0301_1108_blau_ergodic"),
    ("mean_reversion", "0302_1111_blau_ts_stochastic"),
    ("multi_indicator_system", "0002_silvios_ea_best26"),
    ("mean_reversion", "0303_1112_blau_tstochi"),
    ("mean_reversion", "0247_0714_cashmachine_5min"),
    ("mean_reversion", "0305_1114_blau_csi"),
    ("multi_indicator_system", "0007_day_trading_pamxa"),
    ("mean_reversion", "0254_0783_scalpel_ea"),
    ("mean_reversion", "0257_0809_mfi_slowdown"),
    ("mean_reversion", "0261_0813_delta_mfi"),
    ("multi_indicator_system", "0014_steve_cartwright_trader_camel_cci_macd"),
    ("mean_reversion", "0262_0860_fisher_org_v1_sign"),
    ("mean_reversion", "0263_0861_fisher_org_v1"),
    ("mean_reversion", "0268_0925_cci_histogram"),
    ("others", "0018_zweig_breadth_thrust"),
    ("price_patterns", "0019_1318_morningstar_cci"),
    ("price_patterns", "0022_1321_meetinglines_cci"),
    ("price_patterns", "0027_1337_harami_cci"),
    ("trend_following", "0060_0676_exppriceposition"),
    ("price_patterns", "0029_0002_price_action_intraday_trading"),
    ("trend_following", "0062_0685_rabbit3"),
    ("trend_following", "0063_0686_ma2cci"),
    ("trend_following", "0065_0691_polish_layer"),
    ("trend_following", "0045_0578_rabbitm2"),
    ("trend_following", "0019_0131_cidomo"),
    ("pairs_trading", "0017_0152_lbs"),
    ("trend_following", "0020_0136_ema_lwma_rsi"),
    ("trend_following", "0021_0157_bago_ea"),
    ("trend_following", "0024_0247_flat_trend_ea"),
    ("trend_following", "0026_0252_ravi_ao"),
    ("time_session_system", "0002_night_flat_trade"),
    ("trend_following", "0123_1166_ma2cci"),
    ("trend_following", "0158_1316_darkcloud_cci"),
    ("trend_following", "0178_0134_tdsglobal"),
    ("trend_following", "0161_1325_hammer_cci"),
    ("trend_following", "0179_0135_puria_method"),
    ("trend_following", "0180_0137_bulls_bears_eyes_ea"),
    ("trend_following", "0183_0165_alligator_simple_v1_0"),
    ("trend_following", "0184_0175_probe"),
    ("trend_following", "0204_0528_js_chaos"),
    ("trend_following", "0188_0239_bars_alligator"),
    ("trend_following", "0189_0244_gordago_ea"),
    ("trend_following", "0149_1285_rsi_cci"),
    ("trend_following", "0209_0542_vortex_indicator_system"),
    ("trend_following", "0194_0417_fx_chaos_scalp"),
    ("trend_following", "0152_1308_engulfing_cci"),
    ("trend_following", "0250_0862_bsi"),
    ("trend_following", "0266_1080_bnb"),
    ("trend_following", "0276_1106_t3_trix"),
    ("trend_following", "0285_1171_jolly_roger"),
    ("trend_following", "0280_1142_smatf"),
    ("trend_following", "0312_1260_color3rdgenxma"),
]


def extract_metrics(output):
    """Extract metrics from run.py output."""
    metrics = {}

    patterns = {
        'rows': r'Loaded\s+(\d+)\s+bars',
        'bar_num': r'bar_num\s*[:#]\s*(\d+)',
        'buy_count': r'buy_count\s*[:#]\s*(\d+)',
        'sell_count': r'sell_count\s*[:#]\s*(\d+)',
        'win_count': r'(?:Won Trades|won|win_count)\s*[:#]\s*(\d+)',
        'loss_count': r'(?:Lost Trades|lost|loss_count)\s*[:#]\s*(\d+)',
        'trade_num': r'(?:trade_count|Closed Trades)\s*[:#]\s*(\d+)',
        'total_trades': r'(?:total_trades|Total Closed Trades)\s*[:#]\s*(\d+)',
        'stop_count': r'stop_count\s*[:#]\s*(\d+)',
        'final_value': r'(?:End Value|final_value)\s*[:#]\s*([\d,.]+)',
        'sharpe_ratio': r'(?:Sharpe|sharpe_ratio)\s*[:#]\s*([-\d.]+)',
        'annual_return': r'(?:annual_return|Annual Return)\s*[:#]\s*([-\d.]+)',
        'max_drawdown': r'(?:Max Drawdown|max_drawdown)\s*[:#]\s*([-\d.]+)',
        'return_rate': r'(?:total_return|Total Return)\s*[:#]\s*([-\d.]+)',
        'sum_profit': r'(?:Net PnL|net_pnl|sum_profit)\s*[:#]\s*([-\d.]+)',
    }

    return metrics


def fix_expected_json(category, strategy_name):
    """Run strategy and update expected.json."""
    base_dir = Path("/Users/yunjinqi/Documents/new_projects/backtrader")
    test_dir = (base_dir / f"tests/functional/strategies_regression/{category}/{strategy_name}").resolve()
    run_py = test_dir / "run.py"
    expected_path = test_dir / "expected.json"

    if not run_py.exists():
        return False, "run.py not found"

    if not expected_path.exists():
        return False, "expected.json not found"

    try:
        result = subprocess.run(
            [sys.executable, str(run_py)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(test_dir)
        )

        if result.returncode != 0:
            return False, f"run.py failed with code {result.returncode}"

        metrics = extract_metrics(result.stdout + result.stderr)
        if not metrics:
            return False, "Could not extract metrics from output"

        with open(expected_path, 'w') as f:
            json.dump(metrics, f, indent=2)

        return True, f"Updated with {len(metrics)} metrics"

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def main():
    import os
    base_dir = Path("/Users/yunjinqi/Documents/new_projects/backtrader")
    os.chdir(base_dir)

    print(f"Working directory: {os.getcwd()}")
    print(f"Total failed tests to fix: {len(FAILED_TESTS)}\n")

    fixed = 0
    failed = 0

    for i, (category, strategy_name) in enumerate(FAILED_TESTS, 1):
        print(f"[{i}/{len(FAILED_TESTS)}] {category}/{strategy_name}...", end=" ")
        success, message = fix_expected_json(category, strategy_name)

        if success:
            print(f"OK - {message}")
            fixed += 1
        else:
            print(f"FAIL - {message}")
            failed += 1

    print(f"\n=== Summary ===")
    print(f"Fixed: {fixed}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
