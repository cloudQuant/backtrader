# 迭代 71 B11-03 contrib 直接子类测试定位索引（公开提交 c5fc2e7e）

范围：公开提交的 `backtrader/indicators/contrib/*.py` 中顶层直接继承 `Indicator` 的 258 个具名类。与 2026-11-21 清单逐模块/类名一致；未纳入别名、间接继承类、函数内类或用户自定义子类，不推断其覆盖情况；例如 `tests/unit/indicators/test_iter71_go_tpo_reference.py` 中的自定义 GO 子类不在本次 258 类内。扫描该提交 `tests/unit/indicators` 与 `tests/functional/strategies`；自动扫描只识别字面类名调用，动态 `getattr`、别名与其他测试目录需人工补审。未扫描账户、网络或私密输入。

“旧盘点称全序列设计”只是历史工作区人工盘点的定位线索，本次仅检查所引测试文件存在和可识别节点名存在，未逐节点核验断言、未运行、未证明通过；这不是本次覆盖数或通过数。minperiod 列仅转录旧盘点有明确独立期望的线索，**待核当前测试**；未确认不代表没有。自动扫描中的调用发生于 helper/构造器，不能推断测试收集、到达、通过；字符串和 import 更不能推断执行。

“历史实测”表示工作区旧 M–R 报告称对 8 类各执行过 350 根固定合成样本，报告声称比较两模式全线及源码推算 minperiod；本次未核原始运行日志，未证明结果绑定当前 HEAD。本次未重复旧 QA。近期提交及计划/交接仅作定位线索，祖先关系不证明本次实际执行。

统计：258 类；旧人工盘点称有全序列设计且引用的文件在本提交存在的线索 23 类，其中旧文另称有独立周期线索 22 类；旧文称局部设计的线索 24 类；其余 211 类本次未认定该等级。工作区旧报告称有单样本记录 8 类（与前述分类可重叠）。这些是定位下界，不是 258 类通过率。

## 逐类矩阵

| 类 | 定义 | 旧盘点线索 / 独立周期 | 历史报告或近期提交线索（非本次执行） | 本提交单元测试直接构造语法 |
|---|---|---|---|---|
| AbsolutelyNoLagLwma | `backtrader/indicators/contrib/absolutely_no_lag_lwma.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AbsolutelyNoLagLwmaColor | `backtrader/indicators/contrib/absolutely_no_lag_lwma_color.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AbsolutelyNoLagLwmaIndicator | `backtrader/indicators/contrib/brain_trend2_indicator.py:87` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AcceleratorOscillator | `backtrader/indicators/contrib/shared_strategy_indicators.py:799` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AccumulationDistributionLine | `backtrader/indicators/contrib/accumulation_distribution_line.py:24` | 未静态认定；未确认 | 5d9dbe5d5/ef113e266：缺失及历史局部 | `tests/unit/indicators/test_iter71_accumulation_distribution_integrity.py:104` (test_replay_each_revision_recomputes_adl_from_completed_bar.Probe.__init__) |
| AdaptiveMarketLevel | `backtrader/indicators/contrib/shared_strategy_indicators.py:880` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_adaptive_market_level_bounded_history.py:90` (_AdaptiveMarketLevelProbe.__init__) 等2处 |
| ADXCrossHullStyleIndicator | `backtrader/indicators/contrib/adx_cross_hull_style_indicator.py:91` | 历史静态线索，所引测试未提交；未确认 | 未核实 | 无直接调用语法 |
| ADXDMI | `backtrader/indicators/contrib/adxdmi.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AIAccelerationDecelerationOscillator | `backtrader/indicators/contrib/ai_acceleration_deceleration_oscillator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AIAcceleratorOscillator | `backtrader/indicators/contrib/shared_strategy_indicators.py:812` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AIAwesomeOscillator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1147` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AltrTrendSignalV22 | `backtrader/indicators/contrib/altr_trend_signal_v22.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AmlIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1047` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_aml_seed.py:51` (_run_aml.AmlProbe.__init__) |
| AnchoredMomentumCandleIndicator | `backtrader/indicators/contrib/anchored_momentum_line.py:61` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_anchored_momentum_integrity.py:43` (run.Probe.__init__) |
| AnchoredMomentumLine | `backtrader/indicators/contrib/anchored_momentum_line.py:22` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_anchored_momentum_integrity.py:42` (run.Probe.__init__) 等4处 |
| AnyRangeCldTailIndicator | `backtrader/indicators/contrib/any_range_cld_tail_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AppliedPriceCCI | `backtrader/indicators/contrib/shared_strategy_indicators.py:430` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AroonHornSignIndicator | `backtrader/indicators/contrib/aroon_horn_sign_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AroonOscillatorSignAlert | `backtrader/indicators/contrib/aroon_oscillator_sign_alert.py:18` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_aroon_oscillator_sign.py:60` (_run_cerebro.AroonSignProbe.__init__) |
| ArrowsCurvesIndicator | `backtrader/indicators/contrib/arrows_curves_indicator.py:17` | 未静态认定；未确认 | e63d2bb/53844a9：缺失与replay限定范围，原策略及历史对照 | `tests/unit/indicators/test_iter71_arrows_curves_missing.py:87` (run.Probe.__init__) 等4处 |
| ASCtrendIndicator | `backtrader/indicators/contrib/as_ctrend_indicator.py:24` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| AsimmetricStochNRIndicator | `backtrader/indicators/contrib/asimmetric_stoch_nr_indicator.py:15` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_asimmetric_stoch_execution_modes.py:131` (test_replay_recomputes_from_previous_completed_bar.Probe.__init__) |
| AtrNormalizeHistogram | `backtrader/indicators/contrib/atr_normalize_histogram.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| AverageChangeCandle | `backtrader/indicators/contrib/average_change_candle.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BBSqueezeIndicator | `backtrader/indicators/contrib/bb_squeeze_indicator.py:25` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_bbsqueeze_missing.py:40` (run.Probe.__init__) 等3处 |
| BearsPower | `backtrader/indicators/contrib/bulls_power.py:39` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BezierStDevIndicator | `backtrader/indicators/contrib/bezier_st_dev_indicator.py:64` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_bezier_stdev_integrity.py:32` (run.Probe.__init__) 等2处 |
| BinaryWaveIndicator | `backtrader/indicators/contrib/binary_wave_indicator.py:24` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| BlauCMIIndicator | `backtrader/indicators/contrib/blau_cmi_indicator.py:87` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauCMomentumIndicator | `backtrader/indicators/contrib/blau_c_momentum_indicator.py:91` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauCSI | `backtrader/indicators/contrib/blau_csi.py:45` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauErgodic | `backtrader/indicators/contrib/blau_ergodic.py:20` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_blau_ergodic_runonce.py:35` (_run.Probe.__init__) |
| BlauErgodicMDI | `backtrader/indicators/contrib/shared_strategy_indicators.py:1164` | 旧盘点称局部设计（本次仅核文件存在）；未确认 | 未核实 | `tests/unit/indicators/test_iter71_blau_ergodic_mdi_color.py:51` (_run_indicator.ColorProbe.__init__) |
| BlauErgodicMDIClassic | `backtrader/indicators/contrib/shared_strategy_indicators.py:1214` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauTSStochastic | `backtrader/indicators/contrib/blau_ts_stochastic.py:45` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauTStochI | `backtrader/indicators/contrib/blau_t_stoch_i.py:45` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BlauTVI | `backtrader/indicators/contrib/blau_tvi.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BrainTrend2Indicator | `backtrader/indicators/contrib/brain_trend2_indicator.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BrainTrendSignalProxy | `backtrader/indicators/contrib/brain_trend_signal_proxy.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BrakeExpIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1239` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BrakeParbIndicator | `backtrader/indicators/contrib/brake_parb_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BreakoutBarsTrendV2 | `backtrader/indicators/contrib/breakout_bars_trend_v2.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BSIIndicator | `backtrader/indicators/contrib/bsi_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BullsBearsEyes | `backtrader/indicators/contrib/bulls_bears_eyes.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BullsPower | `backtrader/indicators/contrib/bulls_power.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BWWiseMan1Signal | `backtrader/indicators/contrib/bw_wise_man1_signal.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| BykovTrendIndicator | `backtrader/indicators/contrib/bykov_trend_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CandlesticksBW | `backtrader/indicators/contrib/candlesticks_bw.py:21` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_candlesticks_bw_integrity.py:54` (_run.Probe.__init__) 等2处 |
| CandleStopColor | `backtrader/indicators/contrib/candle_stop_color.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CandlesXSmoothedIndicator | `backtrader/indicators/contrib/candles_x_smoothed_indicator.py:40` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CaudateXPeriodCandleColor | `backtrader/indicators/contrib/caudate_x_period_candle_color.py:21` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_caudate_candle_missing.py:58` (_run.Probe.__init__) 等3处 |
| CCIDualOnMA | `backtrader/indicators/contrib/accumulation_distribution_line.py:88` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_linecci_minperiod.py:23` (_CCIDualProbe.__init__) |
| CCIHistogramIndicator | `backtrader/indicators/contrib/cci_histogram_indicator.py:20` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_cci_histogram_nonfinite.py:35` (_run.Probe.__init__) 等2处 |
| CCIWoodiesIndicator | `backtrader/indicators/contrib/cci_woodies_indicator.py:38` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CenterOfGravityCandleIndicator | `backtrader/indicators/contrib/center_of_gravity_candle_indicator.py:21` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CenterOfGravityIndicator | `backtrader/indicators/contrib/center_of_gravity_indicator.py:22` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_center_of_gravity_signal_integrity.py:12` (run.Probe.__init__) 等2处 |
| CGOscillator | `backtrader/indicators/contrib/cg_oscillator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ChaikinOscillator | `backtrader/indicators/contrib/accumulation_distribution_line.py:46` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_accumulation_distribution_integrity.py:50` (_run.Probe.__init__) 等2处 |
| ChangeOfVolatilityIndicator | `backtrader/indicators/contrib/lrma_indicator.py:154` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CloseCloseEmaStochastic | `backtrader/indicators/contrib/raw_close_close_stochastic.py:62` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_close_close_stochastic_runonce.py:35` (_run.Probe.__init__) 等2处 |
| CloseLineCCI | `backtrader/indicators/contrib/close_line_cci.py:20` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_close_line_cci_zero.py:48` (_run.Probe.__init__) 等2处 |
| ClosePriceFractals | `backtrader/indicators/contrib/close_price_fractals.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| Color3rdGenXMAIndicator | `backtrader/indicators/contrib/color3rd_gen_xma_indicator.py:92` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_color3rdgenxma_minperiod.py:92` (_run_consumer.StandaloneProbe.__init__) |
| ColorAMLIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:456` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorAMLMeanReversionIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:538` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorBBCandlesIndicator | `backtrader/indicators/contrib/color_bb_candles_indicator.py:20` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_color_bb_candles_minperiod.py:74` (_run_color_bb.ColorBBCandlesProbe.__init__) |
| ColorCoppockIndicator | `backtrader/indicators/contrib/color_coppock_indicator.py:85` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorHMA | `backtrader/indicators/contrib/color_hma.py:23` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorJVariationIndicator | `backtrader/indicators/contrib/color_j_variation_indicator.py:33` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorMetroDeMarkerIndicator | `backtrader/indicators/contrib/color_metro_de_marker_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorMetroStochasticIndicator | `backtrader/indicators/contrib/color_metro_stochastic_indicator.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorMetroWprIndicator | `backtrader/indicators/contrib/color_metro_wpr_indicator.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorMomentumAMAIndicator | `backtrader/indicators/contrib/kama_indicator.py:129` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorRMACDIndicator | `backtrader/indicators/contrib/trvi_indicator.py:170` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_color_rmacd_ema_signal.py:33` (_run.Probe.__init__) |
| ColorSchaffDeMarkerTrendCycle | `backtrader/indicators/contrib/color_schaff_de_marker_trend_cycle.py:21` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorSchaffTrendCycleIndicator | `backtrader/indicators/contrib/color_schaff_trend_cycle_indicator.py:85` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_color_schaff_runonce.py:40` (_run_stc.STCProbeStrategy.__init__) |
| ColorStepXCCXIndicator | `backtrader/indicators/contrib/color_step_xccx_indicator.py:129` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| ColorX2MA | `backtrader/indicators/contrib/color_x2_ma.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ColorXDerivative | `backtrader/indicators/contrib/color_x_derivative.py:15` | 历史静态线索，所引测试未提交；未确认 | 未核实 | 无直接调用语法 |
| ColorZerolagDeMarker | `backtrader/indicators/contrib/color_zerolag_de_marker.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| CorrectedAverageIndicator | `backtrader/indicators/contrib/corrected_average_indicator.py:68` | 旧盘点称局部设计（本次仅核文件存在）；未确认 | 未核实 | 无直接调用语法 |
| DarvasBoxesSystem | `backtrader/indicators/contrib/darvas_boxes_system.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| DemaRangeChannelColor | `backtrader/indicators/contrib/dema_range_channel_color.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| DerivativeIndicator | `backtrader/indicators/contrib/derivative_indicator.py:30` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_derivative_missing.py:27` (_run.Probe.__init__) 等2处 |
| DigitalFT01Indicator | `backtrader/indicators/contrib/digital_ft01_indicator.py:45` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| DigitalMacd | `backtrader/indicators/contrib/digital_macd.py:125` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_digital_macd_convolution.py:40` (_DigitalMacdProbe.__init__) 等14处 |
| DonchianChannelsSystem | `backtrader/indicators/contrib/donchian_channels_system.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_donchian_channels_integrity.py:268` (test_real_factor_strict_context_overflow_and_missing.Factor.__init__) |
| DotsIndicator | `backtrader/indicators/contrib/dots_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| EFDistanceIndicator | `backtrader/indicators/contrib/ef_distance_indicator.py:46` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| EmaRsiVa | `backtrader/indicators/contrib/ema_rsi_va.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| EnvelopesJpAlonso | `backtrader/indicators/contrib/envelopes_jp_alonso.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| F2aAOIndicator | `backtrader/indicators/contrib/f2a_ao_indicator.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FatlFilter | `backtrader/indicators/contrib/fatl_filter.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FiboCandlesIndicator | `backtrader/indicators/contrib/fibo_candles_indicator.py:32` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_fibo_candles_missing.py:66` (run.Probe.__init__) 等3处 |
| FineTuningMA | `backtrader/indicators/contrib/fine_tuning_ma.py:56` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FisherOrgV1 | `backtrader/indicators/contrib/fisher_org_v1.py:58` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FisherOrgV1Sign | `backtrader/indicators/contrib/fisher_org_v1_sign.py:61` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FlatTrendDistanceIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1357` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FlatTrendIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1312` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ForceDiverSign | `backtrader/indicators/contrib/force_index_ema.py:34` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ForceIndexEMA | `backtrader/indicators/contrib/force_index_ema.py:22` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ForceIndexEma | `backtrader/indicators/contrib/force_index_ema_2.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ForecastOscilator | `backtrader/indicators/contrib/forecast_oscilator.py:54` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FractalAMAMBK | `backtrader/indicators/contrib/fractal_amambk.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FramaLinesIndicator | `backtrader/indicators/contrib/frama_series.py:57` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| FramaSeries | `backtrader/indicators/contrib/frama_series.py:18` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| FRASMAv2Indicator | `backtrader/indicators/contrib/frasm_av2_indicator.py:39` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| FunctionalAwesomeOscillator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1127` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| GOIndicator | `backtrader/indicators/contrib/go_indicator.py:24` | 未静态认定；未确认 | 666397c78：子类与strict局部；完整预热矩阵待核 | `tests/unit/indicators/test_iter71_go_tpo_reference.py:83` (run.Probe.__init__) 等6处 |
| HLRIndicator | `backtrader/indicators/contrib/hlr_indicator.py:22` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| HMA | `backtrader/indicators/contrib/hma.py:35` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| I4DRFV2 | `backtrader/indicators/contrib/i4_drfv2.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| I4DRFV3 | `backtrader/indicators/contrib/i4_drfv3.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IAMMAIndicator | `backtrader/indicators/contrib/iamma_indicator.py:15` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_iamma_seed.py:45` (_run_iamma.IAMMAProbe.__init__) |
| IAnchMomIndicator | `backtrader/indicators/contrib/i_anch_mom_indicator.py:51` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IDeMarkerSignIndicator | `backtrader/indicators/contrib/i_de_marker_sign_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IGapIndicator | `backtrader/indicators/contrib/i_gap_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IinMASignalIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1406` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IndexedMovingAverage | `backtrader/indicators/contrib/indexed_moving_average.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| InstantaneousTrendFilterIndicator | `backtrader/indicators/contrib/instantaneous_trend_filter_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| InverseReactionIndicator | `backtrader/indicators/contrib/inverse_reaction_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IRSISignIndicator | `backtrader/indicators/contrib/irsi_sign_indicator.py:41` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IStochKomposterIndicator | `backtrader/indicators/contrib/i_stoch_komposter_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ITrendIndicator | `backtrader/indicators/contrib/i_trend_indicator.py:85` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| IWPRSignIndicator | `backtrader/indicators/contrib/iwpr_sign_indicator.py:20` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_iwpr_missing.py:43` (_run.Probe.__init__) 等2处 |
| JBrainTrend1SigIndicator | `backtrader/indicators/contrib/j_brain_trend1_sig_indicator.py:96` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| JFatlApprox | `backtrader/indicators/contrib/fatl_filter.py:77` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| JFatlCandleApprox | `backtrader/indicators/contrib/fatl_filter.py:112` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| JMASlopeIndicator | `backtrader/indicators/contrib/jma_slope_indicator.py:51` | 旧盘点称全序列设计（本次仅核文件存在）；未确认 | 未核实 | 无直接调用语法 |
| JTpoProxy | `backtrader/indicators/contrib/j_tpo_proxy.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_go_tpo_reference.py:85` (run.Probe.__init__) 等2处 |
| KalmanFilterCandleIndicator | `backtrader/indicators/contrib/kalman_filter_line.py:82` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KalmanFilterIndicator | `backtrader/indicators/contrib/kalman_filter_indicator.py:38` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_kalman_filter_warmup.py:54` (_run.Probe.__init__) 等5处 |
| KalmanFilterLine | `backtrader/indicators/contrib/kalman_filter_line.py:47` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KAMAIndicator | `backtrader/indicators/contrib/kama_indicator.py:52` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KaracaticaIndicator | `backtrader/indicators/contrib/karacatica_indicator.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_karacatica_integrity.py:102` (run.Probe.__init__) 等4处 |
| KDJ | `backtrader/indicators/contrib/shared_strategy_indicators.py:1455` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KDJIndicator | `backtrader/indicators/contrib/kdj_indicator.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_kdj_missing.py:72` (run_indicator.Probe.__init__) 等8处 |
| KwanCccIndicator | `backtrader/indicators/contrib/kwan_ccc_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KwanNrpIndicator | `backtrader/indicators/contrib/kwan_nrp_indicator.py:22` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| KwanRdpIndicator | `backtrader/indicators/contrib/kwan_rdp_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LaguerreAdxIndicator | `backtrader/indicators/contrib/laguerre_adx_indicator.py:21` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LaguerreColorIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1569` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LaguerreFilterIndicator | `backtrader/indicators/contrib/laguerre_filter_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LaguerreIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:1513` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LaguerrePlusDiProxy | `backtrader/indicators/contrib/laguerre_plus_di_proxy.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_laguerre_plus_di_missing.py:72` (run.Probe.__init__) 等5处 |
| LaguerreRocIndicator | `backtrader/indicators/contrib/laguerre_roc_indicator.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_laguerre_roc_replay.py:217` (test_factor_strategy_strict_rejects_intermediate_overflow.Factor.__init__) |
| LeManSignalIndicator | `backtrader/indicators/contrib/le_man_signal_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LinearRegSlopeV2Indicator | `backtrader/indicators/contrib/linear_reg_slope_v2_indicator.py:76` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_linear_reg_slope_replay.py:52` (_run.Probe.__init__) |
| LineCCI | `backtrader/indicators/contrib/accumulation_distribution_line.py:63` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_linecci_minperiod.py:42` (_DirectLineCCIProbe.__init__) |
| LocoIndicator | `backtrader/indicators/contrib/loco_indicator.py:40` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| LRMAIndicator | `backtrader/indicators/contrib/lrma_indicator.py:91` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_vinin_lrma_ma_method2.py:435` (test_standalone_lrma_formula_and_missing_recovery.S.__init__) |
| LsmaAngleIndicator | `backtrader/indicators/contrib/lsma_angle_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| Macd2Indicator | `backtrader/indicators/contrib/macd2_indicator.py:18` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| MacdCandleIndicator | `backtrader/indicators/contrib/macd_candle_indicator.py:18` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| MalrIndicator | `backtrader/indicators/contrib/malr_indicator.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| MARoundingChannelIndicator | `backtrader/indicators/contrib/ma_rounding_channel_indicator.py:60` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| MomentumCandleSignIndicator | `backtrader/indicators/contrib/momentum_candle_sign_indicator.py:19` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| MovingAverageFNIndicator | `backtrader/indicators/contrib/moving_average_fn_indicator.py:96` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| Mt5StochasticCloseClose | `backtrader/indicators/contrib/mt5_stochastic_close_close.py:15` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_mt5_stochastic_replay.py:56` (_run.Probe.__init__) |
| MUVNorDiffCloudIndicator | `backtrader/indicators/contrib/muv_nor_diff_cloud_indicator.py:56` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_muv_nordiff_missing.py:75` (_run.Probe.__init__) 等3处 |
| NonLagDotIndicator | `backtrader/indicators/contrib/non_lag_dot_indicator.py:20` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| NRTRExtrIndicator | `backtrader/indicators/contrib/nrtr_extr_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| NRTRIndicator | `backtrader/indicators/contrib/nrtr_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| OsHMAIndicator | `backtrader/indicators/contrib/hma.py:101` | 旧盘点称局部设计（本次仅核文件存在）；未确认 | 未核实 | `tests/unit/indicators/test_iter71_oshma_warmup.py:52` (execute.Probe.__init__) 等3处 |
| PChannelSystem | `backtrader/indicators/contrib/p_channel_system.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| PercentageCrossoverChannel | `backtrader/indicators/contrib/percentage_crossover_channel.py:15` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据；3996c12fa：缺失状态修复局部 | `tests/unit/indicators/test_iter71_percentage_channel_missing.py:64` (run.Probe.__init__) 等3处 |
| PercentEnvelope | `backtrader/indicators/contrib/percent_envelope.py:18` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| PivotZigZagProxy | `backtrader/indicators/contrib/pivot_zig_zag_proxy.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| PriceChannelStopIndicator | `backtrader/indicators/contrib/price_channel_stop_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| PriceExtremeChannel | `backtrader/indicators/contrib/price_extreme_channel.py:19` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| QQECloudIndicator | `backtrader/indicators/contrib/qqe_cloud_indicator.py:49` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| RaviIndicator | `backtrader/indicators/contrib/ravi_indicator.py:18` | 未静态认定；未确认 | 2026-11-21 真实Cerebro双模式全数组单样本，源码推算minperiod；历史证据 | 无直接调用语法 |
| RawCloseCloseStochastic | `backtrader/indicators/contrib/raw_close_close_stochastic.py:19` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_raw_close_close_stochastic_nan_parity.py:44` (_run.Probe.__init__) |
| RDTrendTriggerIndicator | `backtrader/indicators/contrib/rd_trend_trigger_indicator.py:18` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_rd_trend_trigger_seed.py:88` (_run_cerebro.RDTrendTriggerProbe.__init__) |
| RelativeVigorIndex | `backtrader/indicators/contrib/shared_strategy_indicators.py:1657` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| RenkoLevel | `backtrader/indicators/contrib/renko_level.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| RenkoLineBreak | `backtrader/indicators/contrib/renko_line_break.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| RFTLIndicator | `backtrader/indicators/contrib/rftl_indicator.py:30` | 旧盘点称局部设计（本次仅核文件存在）；未确认 | 未核实 | `tests/unit/indicators/test_iter71_rftl_warmup_parity.py:42` (_run.Probe.__init__) 等6处 |
| RKDIndicator | `backtrader/indicators/contrib/rkd_indicator.py:15` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_rkd_warmup_reference.py:59` (_run.Probe.__init__) |
| ROC2VGIndicator | `backtrader/indicators/contrib/roc2_vg_indicator.py:31` | 未静态认定；未确认 | 4ac72051e：MOM零值修复的专项局部 | `tests/unit/indicators/test_iter71_roc2vg_negative_period.py:26` (test_negative_period_is_rejected_before_strategy_callbacks.Probe.__init__) 等4处 |
| RSIHistogramIndicator | `backtrader/indicators/contrib/rsi_histogram_indicator.py:20` | 未静态认定；未确认 | b67636f7f：缺失颜色及历史局部 | `tests/unit/indicators/test_iter71_rsi_histogram_missing.py:35` (test_rsi_histogram_color_matches_value_or_is_missing.Probe.__init__) 等3处 |
| RsiomaV2 | `backtrader/indicators/contrib/rsioma_v2.py:20` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_rsioma_v2_runonce.py:28` (_run.Probe.__init__) |
| RSISlowdown | `backtrader/indicators/contrib/rsi_slowdown.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| RVIHistogramIndicator | `backtrader/indicators/contrib/rvi_histogram_indicator.py:68` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_rvi_histogram_warmup.py:146` (test_next_update_exception_restores_state_and_preserves_exception.Probe.__init__) 等3处 |
| SafeADX | `backtrader/indicators/contrib/safe_adx.py:16` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SafeAMA | `backtrader/indicators/contrib/safe_adx.py:58` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SafeCCI | `backtrader/indicators/contrib/shared_strategy_indicators.py:1747` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SafeCCIWithFactor | `backtrader/indicators/contrib/shared_strategy_indicators.py:1778` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SidusIndicator | `backtrader/indicators/contrib/sidus_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SilverTrendDirectionSignalProxy | `backtrader/indicators/contrib/shared_strategy_indicators.py:1838` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SilverTrendIndicator | `backtrader/indicators/contrib/silver_trend_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SilverTrendSignalProxy | `backtrader/indicators/contrib/shared_strategy_indicators.py:1806` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SkyscraperFixColorAMLIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:328` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SkyscraperFixDuplexIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:225` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SkyscraperFixIndicator | `backtrader/indicators/contrib/shared_strategy_indicators.py:122` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SlidingRangeColor | `backtrader/indicators/contrib/sliding_range_color.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_sliding_range_color.py:31` (_run.Probe.__init__) 等4处 |
| SlowStoch | `backtrader/indicators/contrib/slow_stoch.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SmoothedADXIndicator | `backtrader/indicators/contrib/smoothed_adx_indicator.py:60` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SmoothedRelativeVigorIndex | `backtrader/indicators/contrib/shared_strategy_indicators.py:1716` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 专项真实执行1项，缺失窗口仍映射0；见 R71-112b | `tests/unit/indicators/test_iter71_smoothed_rvi_nan_window.py:30` (_run.Probe.__init__) |
| SmoothedRsi | `backtrader/indicators/contrib/smoothed_rsi.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| SpearmanRankCorrelationHistogram | `backtrader/indicators/contrib/spearman_rank_correlation_histogram.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_spearman_missing.py:30` (run.S.__init__) 等4处 |
| StalinIndicator | `backtrader/indicators/contrib/stalin_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| StarterLaguerreFilter | `backtrader/indicators/contrib/starter_laguerre_filter.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| StepMANRTRIndicator | `backtrader/indicators/contrib/step_manrtr_indicator.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| StochasticHistogramIndicator | `backtrader/indicators/contrib/stochastic_histogram_indicator.py:32` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | d7af1dcb1：模式/多时钟/有界缓冲专项，见对应复核 | `tests/unit/indicators/test_iter71_stochastic_histogram_execution_modes.py:138` (_ReplayCaptureStrategy.__init__) 等12处 |
| T3AlarmIndicator | `backtrader/indicators/contrib/t3_alarm_indicator.py:21` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| T3Average | `backtrader/indicators/contrib/t3_average.py:21` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| T3Indicator | `backtrader/indicators/contrib/t3_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| T3Trix | `backtrader/indicators/contrib/t3_average.py:53` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| The20sV020Signal | `backtrader/indicators/contrib/the20s_v020_signal.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| ThreeCandlesIndicator | `backtrader/indicators/contrib/three_candles_indicator.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_threecandles_missing.py:38` (_run.Probe.__init__) 等4处 |
| ThreeLineBreakIndicator | `backtrader/indicators/contrib/three_line_break_indicator.py:17` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_three_line_break_minperiod.py:70` (_run_indicator.ProbeStrategy.__init__) 等4处 |
| TimeLine | `backtrader/indicators/contrib/time_line.py:17` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_line_operations.py:426` (TimeLineSmaTestStrategy.__init__) |
| TradingChannelIndexProxy | `backtrader/indicators/contrib/trading_channel_index_proxy.py:19` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TrendArrowsIndicator | `backtrader/indicators/contrib/trend_arrows_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TrendContinuationIndicator | `backtrader/indicators/contrib/trend_continuation_indicator.py:80` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_trend_continuation_seed.py:88` (_run_indicator.ProbeStrategy.__init__) 等2处 |
| TrendIntensityIndexProxy | `backtrader/indicators/contrib/trend_intensity_index_proxy.py:22` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| TrendManagerIndicator | `backtrader/indicators/contrib/trend_manager_indicator.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TriggerLine | `backtrader/indicators/contrib/trigger_line.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TripleEmaRate | `backtrader/indicators/contrib/triple_ema_rate.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TriXCandleIndicator | `backtrader/indicators/contrib/tri_x_candle_indicator.py:20` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_trix_candle_integrity.py:27` (run.P.__init__) 等2处 |
| TRVIIndicator | `backtrader/indicators/contrib/trvi_indicator.py:70` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| TwoPbIdealXOSMAIndicator | `backtrader/indicators/contrib/two_pb_ideal_xosma_indicator.py:17` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| TwoXmaIchimokuOscillator | `backtrader/indicators/contrib/xma_ichimoku.py:116` | 历史静态线索，所引测试未提交；未确认 | 未核实 | `tests/unit/indicators/test_iter71_xma_ichimoku_bounded.py:35` (_CaptureXmaStrategy.__init__) |
| UltraAbsolutelyNoLagLwmaColor | `backtrader/indicators/contrib/ultra_absolutely_no_lag_lwma_color.py:22` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| UltraRSIIndicator | `backtrader/indicators/contrib/j_brain_trend1_sig_indicator.py:164` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| UltraWPRIndicator | `backtrader/indicators/contrib/ultra_wpr_indicator.py:71` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_ultra_wpr_runonce.py:62` (_run_cerebro.UltraWPRProbe.__init__) |
| UltraXMAIndicator | `backtrader/indicators/contrib/adx_cross_hull_style_indicator.py:163` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | 无直接调用语法 |
| UpDownCandleStrength | `backtrader/indicators/contrib/up_down_candle_strength.py:17` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_candle_strength_vwma.py:34` (_run.Probe.__init__) |
| VininITrendIndicator | `backtrader/indicators/contrib/vinin_i_trend_indicator.py:66` | 历史静态线索，所引测试未提交；未确认 | 未核实 | 无直接调用语法 |
| VininITrendLRMAIndicator | `backtrader/indicators/contrib/lrma_indicator.py:185` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_vinin_lrma_ma_method2.py:111` (run.S.__init__) 等6处 |
| VolumeWeightedMAIndicator | `backtrader/indicators/contrib/volume_weighted_ma_indicator.py:37` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_vwma_formula.py:22` (_run.Probe.__init__) |
| VolumeWeightedMAStDevIndicator | `backtrader/indicators/contrib/volume_weighted_ma_st_dev_indicator.py:39` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| VWAPCloseIndicator | `backtrader/indicators/contrib/vwap_close_indicator.py:17` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_vwap_close_contract.py:60` (_run_cerebro.Probe.__init__) 等2处 |
| VWMACandle | `backtrader/indicators/contrib/vwma_candle.py:18` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_candle_strength_vwma.py:36` (_run.Probe.__init__) 等3处 |
| VWMADigitSystem | `backtrader/indicators/contrib/vwma_digit_system.py:15` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| Wami | `backtrader/indicators/contrib/wami.py:18` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| WPRSISignalIndicator | `backtrader/indicators/contrib/wprsi_signal_indicator.py:17` | 未静态认定；未确认 | 79a4f7792：缺失与真实策略局部 | `tests/unit/indicators/test_iter71_wprsi_missing.py:70` (_run.Strategy.__init__) |
| X2MACandleApprox | `backtrader/indicators/contrib/shared_strategy_indicators.py:621` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| XCCIHistogramVolDirectIndicator | `backtrader/indicators/contrib/xcci_histogram_vol_direct_indicator.py:15` | 历史静态线索，所引测试未提交；未确认 | 未核实 | 无直接调用语法 |
| XCCIHistogramVolIndicator | `backtrader/indicators/contrib/xcci_histogram_vol_indicator.py:17` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_xcci_histogram_vol_missing.py:16` (_XCCIStateProbe.__init__) |
| XDeMarkerHistogramVolDirectIndicator | `backtrader/indicators/contrib/x_de_marker_histogram_vol_direct_indicator.py:18` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | aa0a7f883/ad851c61a：预热/replay及缺失；需按全线minperiod矩阵核对 | `tests/unit/indicators/test_iter71_xdemarker_missing_standalone.py:50` (run.S.__init__) 等8处 |
| XFisherIndicator | `backtrader/indicators/contrib/x_fisher_indicator.py:17` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_x_fisher_replay_revisions.py:85` (_run_replay.Probe.__init__) |
| XMACDIndicator | `backtrader/indicators/contrib/xmacd_indicator.py:19` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_xmacd_minperiod_runonce.py:71` (_run.Probe.__init__) 等2处 |
| XmaIchimoku | `backtrader/indicators/contrib/xma_ichimoku.py:20` | 历史静态线索，所引测试未提交；未确认 | 未核实 | `tests/unit/indicators/test_iter71_xma_ichimoku_bounded.py:26` (_CaptureXmaStrategy.__init__) 等3处 |
| XMAIshimokuChannelIndicator | `backtrader/indicators/contrib/xma_ishimoku_channel_indicator.py:35` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| XMAIshimokuLine | `backtrader/indicators/contrib/xma_ishimoku_line.py:44` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| XMARangeBandsIndicator | `backtrader/indicators/contrib/xma_range_bands_indicator.py:76` | 未静态认定；未确认 | 未核实 | 无直接调用语法 |
| XPeriodCandleColor | `backtrader/indicators/contrib/shared_strategy_indicators.py:714` | 未静态认定；未确认 | 4433b1535/2d36fd1c5：缺失局部，查具体公开线 | `tests/unit/indicators/test_iter71_xperiod_indicator_graph_boundary.py:38` (test_single_bar_smoothing_in_indicator_graph.Strategy.__init__) 等4处 |
| XPeriodCandleSystemColor | `backtrader/indicators/contrib/shared_strategy_indicators.py:758` | 未静态认定；未确认 | 4433b1535/2d36fd1c5：缺失局部，查具体公开线 | 无直接调用语法 |
| XrsiDeMarkerHistogram | `backtrader/indicators/contrib/xrsi_de_marker_histogram.py:43` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_xrsi_de_marker_histogram_rsi_price.py:78` (_run.Probe.__init__) |
| XRSIHistogramVolDirectIndicator | `backtrader/indicators/contrib/xrsi_histogram_vol_direct_indicator.py:17` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_xrsi_vol_direct_nonfinite.py:35` (_run.Strategy.__init__) 等3处 |
| XRSIHistogramVolIndicator | `backtrader/indicators/contrib/xrsi_histogram_vol_indicator.py:17` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_xrsi_vol_nonfinite_replay.py:69` (_run.Strategy.__init__) 等2处 |
| XRVIIndicator | `backtrader/indicators/contrib/xrvi_indicator.py:15` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_xrvi_runonce.py:55` (_run_xrvi.XRVIProbeStrategy.__init__) |
| ZeroLagHLRIndicator | `backtrader/indicators/contrib/hlr_indicator.py:44` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_zero_lag_hlr_warmup.py:142` (test_replayed_daily_slow_uses_final_fast_and_previous_slow.ReplayStrategy.__init__) |
| ZeroLagMacd | `backtrader/indicators/contrib/zero_lag_macd.py:18` | 旧盘点称全序列设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_zero_lag_macd_runonce.py:32` (_run.Probe.__init__) |
| ZigZagRecentPivotSignal | `backtrader/indicators/contrib/zig_zag_recent_pivot_signal.py:15` | 未静态认定；未确认 | 未核实 | `tests/unit/indicators/test_iter71_zigzag_replay.py:85` (test_multifeed_unchanged_secondary_matches_its_own_history.Probe.__init__) |
| ZPFIndicator | `backtrader/indicators/contrib/zpf_indicator.py:78` | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 | 未核实 | `tests/unit/indicators/test_iter71_wma_once_segments.py:132` (test_zpf_wma_children_match_independent_reference_with_missing_input.Strategy.__init__) 等2处 |

## 优先补测清单

以下类未达到本矩阵中“旧文称全序列设计并有独立周期线索”的定位门槛。对于列有历史运行或局部专项的类，先核对已提交节点与参数，不重复已接受 QA；它们出现在这里只表示本矩阵尚未证明完整 B11-03 条件。

| 类 | 当前线索 |
|---|---|
| AbsolutelyNoLagLwma | 仅策略构造语法；未确认 |
| AbsolutelyNoLagLwmaColor | 仅策略构造语法；未确认 |
| AbsolutelyNoLagLwmaIndicator | 仅策略构造语法；未确认 |
| AcceleratorOscillator | 仅策略构造语法；未确认 |
| AccumulationDistributionLine | 存在单元直接构造语法；未确认 |
| AdaptiveMarketLevel | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| ADXCrossHullStyleIndicator | 历史静态线索，所引测试未提交；未确认 |
| ADXDMI | 仅策略构造语法；未确认 |
| AIAccelerationDecelerationOscillator | 仅策略构造语法；未确认 |
| AIAcceleratorOscillator | 仅策略构造语法；未确认 |
| AIAwesomeOscillator | 未查明；未确认 |
| AltrTrendSignalV22 | 仅策略构造语法；未确认 |
| AmlIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| AnchoredMomentumCandleIndicator | 存在单元直接构造语法；未确认 |
| AnchoredMomentumLine | 存在单元直接构造语法；未确认 |
| AnyRangeCldTailIndicator | 仅策略构造语法；未确认 |
| AppliedPriceCCI | 仅策略构造语法；未确认 |
| AroonHornSignIndicator | 仅策略构造语法；未确认 |
| AroonOscillatorSignAlert | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| ArrowsCurvesIndicator | 存在单元直接构造语法；未确认 |
| ASCtrendIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| AsimmetricStochNRIndicator | 存在单元直接构造语法；未确认 |
| AtrNormalizeHistogram | 仅策略构造语法；未确认 |
| AverageChangeCandle | 仅策略构造语法；未确认 |
| BBSqueezeIndicator | 存在单元直接构造语法；未确认 |
| BearsPower | 仅策略构造语法；未确认 |
| BezierStDevIndicator | 存在单元直接构造语法；未确认 |
| BlauCMIIndicator | 仅策略构造语法；未确认 |
| BlauCMomentumIndicator | 仅策略构造语法；未确认 |
| BlauCSI | 仅策略构造语法；未确认 |
| BlauErgodicMDI | 旧盘点称局部设计（本次仅核文件存在）；未确认 |
| BlauErgodicMDIClassic | 仅策略构造语法；未确认 |
| BlauTSStochastic | 仅策略构造语法；未确认 |
| BlauTStochI | 仅策略构造语法；未确认 |
| BlauTVI | 仅策略构造语法；未确认 |
| BrainTrend2Indicator | 仅策略构造语法；未确认 |
| BrainTrendSignalProxy | 仅策略构造语法；未确认 |
| BrakeExpIndicator | 仅策略构造语法；未确认 |
| BrakeParbIndicator | 仅策略构造语法；未确认 |
| BreakoutBarsTrendV2 | 仅策略构造语法；未确认 |
| BSIIndicator | 仅策略构造语法；未确认 |
| BullsBearsEyes | 仅策略构造语法；未确认 |
| BullsPower | 仅策略构造语法；未确认 |
| BWWiseMan1Signal | 仅策略构造语法；未确认 |
| BykovTrendIndicator | 仅策略构造语法；未确认 |
| CandlesticksBW | 存在单元直接构造语法；未确认 |
| CandleStopColor | 仅策略构造语法；未确认 |
| CandlesXSmoothedIndicator | 仅策略构造语法；未确认 |
| CaudateXPeriodCandleColor | 存在单元直接构造语法；未确认 |
| CCIDualOnMA | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| CCIHistogramIndicator | 存在单元直接构造语法；未确认 |
| CCIWoodiesIndicator | 仅策略构造语法；未确认 |
| CenterOfGravityCandleIndicator | 仅策略构造语法；未确认 |
| CenterOfGravityIndicator | 存在单元直接构造语法；未确认 |
| CGOscillator | 仅策略构造语法；未确认 |
| ChaikinOscillator | 存在单元直接构造语法；未确认 |
| ChangeOfVolatilityIndicator | 仅策略构造语法；未确认 |
| CloseLineCCI | 存在单元直接构造语法；未确认 |
| ClosePriceFractals | 仅策略构造语法；未确认 |
| Color3rdGenXMAIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| ColorAMLIndicator | 仅策略构造语法；未确认 |
| ColorAMLMeanReversionIndicator | 仅策略构造语法；未确认 |
| ColorBBCandlesIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| ColorCoppockIndicator | 仅策略构造语法；未确认 |
| ColorHMA | 仅策略构造语法；未确认 |
| ColorJVariationIndicator | 仅策略构造语法；未确认 |
| ColorMetroDeMarkerIndicator | 仅策略构造语法；未确认 |
| ColorMetroStochasticIndicator | 仅策略构造语法；未确认 |
| ColorMetroWprIndicator | 仅策略构造语法；未确认 |
| ColorMomentumAMAIndicator | 仅策略构造语法；未确认 |
| ColorSchaffDeMarkerTrendCycle | 仅策略构造语法；未确认 |
| ColorStepXCCXIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| ColorX2MA | 仅策略构造语法；未确认 |
| ColorXDerivative | 历史静态线索，所引测试未提交；未确认 |
| ColorZerolagDeMarker | 仅策略构造语法；未确认 |
| CorrectedAverageIndicator | 旧盘点称局部设计（本次仅核文件存在）；未确认 |
| DarvasBoxesSystem | 仅策略构造语法；未确认 |
| DemaRangeChannelColor | 仅策略构造语法；未确认 |
| DerivativeIndicator | 存在单元直接构造语法；未确认 |
| DigitalFT01Indicator | 仅策略构造语法；未确认 |
| DigitalMacd | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| DonchianChannelsSystem | 存在单元直接构造语法；未确认 |
| DotsIndicator | 仅策略构造语法；未确认 |
| EFDistanceIndicator | 仅策略构造语法；未确认 |
| EmaRsiVa | 仅策略构造语法；未确认 |
| EnvelopesJpAlonso | 仅策略构造语法；未确认 |
| F2aAOIndicator | 仅策略构造语法；未确认 |
| FatlFilter | 未查明；未确认 |
| FiboCandlesIndicator | 存在单元直接构造语法；未确认 |
| FineTuningMA | 仅策略构造语法；未确认 |
| FisherOrgV1 | 仅策略构造语法；未确认 |
| FisherOrgV1Sign | 仅策略构造语法；未确认 |
| FlatTrendDistanceIndicator | 仅策略构造语法；未确认 |
| FlatTrendIndicator | 仅策略构造语法；未确认 |
| ForceDiverSign | 仅策略构造语法；未确认 |
| ForceIndexEMA | 未查明；未确认 |
| ForceIndexEma | 仅策略构造语法；未确认 |
| ForecastOscilator | 仅策略构造语法；未确认 |
| FractalAMAMBK | 仅策略构造语法；未确认 |
| FramaLinesIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| FramaSeries | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| FRASMAv2Indicator | 仅策略构造语法；未确认 |
| FunctionalAwesomeOscillator | 未查明；未确认 |
| GOIndicator | 存在单元直接构造语法；未确认 |
| HLRIndicator | 未查明；未确认 |
| HMA | 未查明；未确认 |
| I4DRFV2 | 仅策略构造语法；未确认 |
| I4DRFV3 | 仅策略构造语法；未确认 |
| IAnchMomIndicator | 仅策略构造语法；未确认 |
| IDeMarkerSignIndicator | 仅策略构造语法；未确认 |
| IGapIndicator | 仅策略构造语法；未确认 |
| IinMASignalIndicator | 仅策略构造语法；未确认 |
| IndexedMovingAverage | 仅策略构造语法；未确认 |
| InstantaneousTrendFilterIndicator | 仅策略构造语法；未确认 |
| InverseReactionIndicator | 仅策略构造语法；未确认 |
| IRSISignIndicator | 仅策略构造语法；未确认 |
| IStochKomposterIndicator | 仅策略构造语法；未确认 |
| ITrendIndicator | 仅策略构造语法；未确认 |
| IWPRSignIndicator | 存在单元直接构造语法；未确认 |
| JBrainTrend1SigIndicator | 仅策略构造语法；未确认 |
| JFatlApprox | 未查明；未确认 |
| JFatlCandleApprox | 仅策略构造语法；未确认 |
| JMASlopeIndicator | 旧盘点称全序列设计（本次仅核文件存在）；未确认 |
| JTpoProxy | 存在单元直接构造语法；未确认 |
| KalmanFilterCandleIndicator | 仅策略构造语法；未确认 |
| KalmanFilterIndicator | 存在单元直接构造语法；未确认 |
| KalmanFilterLine | 未查明；未确认 |
| KAMAIndicator | 未查明；未确认 |
| KaracaticaIndicator | 存在单元直接构造语法；未确认 |
| KDJ | 仅策略构造语法；未确认 |
| KDJIndicator | 存在单元直接构造语法；未确认 |
| KwanCccIndicator | 仅策略构造语法；未确认 |
| KwanNrpIndicator | 仅策略构造语法；未确认 |
| KwanRdpIndicator | 仅策略构造语法；未确认 |
| LaguerreAdxIndicator | 仅策略构造语法；未确认 |
| LaguerreColorIndicator | 仅策略构造语法；未确认 |
| LaguerreFilterIndicator | 仅策略构造语法；未确认 |
| LaguerreIndicator | 未查明；未确认 |
| LaguerrePlusDiProxy | 存在单元直接构造语法；未确认 |
| LaguerreRocIndicator | 存在单元直接构造语法；未确认 |
| LeManSignalIndicator | 仅策略构造语法；未确认 |
| LinearRegSlopeV2Indicator | 存在单元直接构造语法；未确认 |
| LocoIndicator | 仅策略构造语法；未确认 |
| LRMAIndicator | 存在单元直接构造语法；未确认 |
| LsmaAngleIndicator | 仅策略构造语法；未确认 |
| Macd2Indicator | 仅策略构造语法；未确认 |
| MacdCandleIndicator | 仅策略构造语法；未确认 |
| MalrIndicator | 仅策略构造语法；未确认 |
| MARoundingChannelIndicator | 仅策略构造语法；未确认 |
| MomentumCandleSignIndicator | 仅策略构造语法；未确认 |
| MovingAverageFNIndicator | 仅策略构造语法；未确认 |
| Mt5StochasticCloseClose | 存在单元直接构造语法；未确认 |
| MUVNorDiffCloudIndicator | 存在单元直接构造语法；未确认 |
| NonLagDotIndicator | 仅策略构造语法；未确认 |
| NRTRExtrIndicator | 仅策略构造语法；未确认 |
| NRTRIndicator | 仅策略构造语法；未确认 |
| OsHMAIndicator | 旧盘点称局部设计（本次仅核文件存在）；未确认 |
| PChannelSystem | 仅策略构造语法；未确认 |
| PercentageCrossoverChannel | 存在单元直接构造语法；未确认 |
| PercentEnvelope | 仅策略构造语法；未确认 |
| PivotZigZagProxy | 仅策略构造语法；未确认 |
| PriceChannelStopIndicator | 仅策略构造语法；未确认 |
| PriceExtremeChannel | 仅策略构造语法；未确认 |
| RaviIndicator | 仅策略构造语法；未确认 |
| RelativeVigorIndex | 仅策略构造语法；未确认 |
| RenkoLevel | 仅策略构造语法；未确认 |
| RenkoLineBreak | 仅策略构造语法；未确认 |
| RFTLIndicator | 旧盘点称局部设计（本次仅核文件存在）；未确认 |
| RKDIndicator | 存在单元直接构造语法；未确认 |
| ROC2VGIndicator | 存在单元直接构造语法；未确认 |
| RSIHistogramIndicator | 存在单元直接构造语法；未确认 |
| RSISlowdown | 仅策略构造语法；未确认 |
| SafeADX | 仅策略构造语法；未确认 |
| SafeAMA | 仅策略构造语法；未确认 |
| SafeCCI | 仅策略构造语法；未确认 |
| SafeCCIWithFactor | 仅策略构造语法；未确认 |
| SidusIndicator | 仅策略构造语法；未确认 |
| SilverTrendDirectionSignalProxy | 仅策略构造语法；未确认 |
| SilverTrendIndicator | 仅策略构造语法；未确认 |
| SilverTrendSignalProxy | 仅策略构造语法；未确认 |
| SkyscraperFixColorAMLIndicator | 仅策略构造语法；未确认 |
| SkyscraperFixDuplexIndicator | 仅策略构造语法；未确认 |
| SkyscraperFixIndicator | 仅策略构造语法；未确认 |
| SlidingRangeColor | 存在单元直接构造语法；未确认 |
| SlowStoch | 仅策略构造语法；未确认 |
| SmoothedADXIndicator | 仅策略构造语法；未确认 |
| SmoothedRelativeVigorIndex | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| SmoothedRsi | 仅策略构造语法；未确认 |
| SpearmanRankCorrelationHistogram | 存在单元直接构造语法；未确认 |
| StalinIndicator | 仅策略构造语法；未确认 |
| StarterLaguerreFilter | 仅策略构造语法；未确认 |
| StepMANRTRIndicator | 仅策略构造语法；未确认 |
| T3Average | 未查明；未确认 |
| T3Indicator | 仅策略构造语法；未确认 |
| T3Trix | 仅策略构造语法；未确认 |
| The20sV020Signal | 仅策略构造语法；未确认 |
| ThreeCandlesIndicator | 存在单元直接构造语法；未确认 |
| TimeLine | 存在单元直接构造语法；未确认 |
| TradingChannelIndexProxy | 仅策略构造语法；未确认 |
| TrendArrowsIndicator | 仅策略构造语法；未确认 |
| TrendContinuationIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| TrendManagerIndicator | 仅策略构造语法；未确认 |
| TriggerLine | 仅策略构造语法；未确认 |
| TripleEmaRate | 仅策略构造语法；未确认 |
| TriXCandleIndicator | 存在单元直接构造语法；未确认 |
| TwoPbIdealXOSMAIndicator | 仅策略构造语法；未确认 |
| TwoXmaIchimokuOscillator | 历史静态线索，所引测试未提交；未确认 |
| UltraAbsolutelyNoLagLwmaColor | 仅策略构造语法；未确认 |
| UltraRSIIndicator | 仅策略构造语法；未确认 |
| UpDownCandleStrength | 存在单元直接构造语法；未确认 |
| VininITrendIndicator | 历史静态线索，所引测试未提交；未确认 |
| VininITrendLRMAIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| VolumeWeightedMAIndicator | 存在单元直接构造语法；未确认 |
| VolumeWeightedMAStDevIndicator | 仅策略构造语法；未确认 |
| VWAPCloseIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| VWMACandle | 存在单元直接构造语法；未确认 |
| VWMADigitSystem | 仅策略构造语法；未确认 |
| Wami | 仅策略构造语法；未确认 |
| WPRSISignalIndicator | 存在单元直接构造语法；未确认 |
| X2MACandleApprox | 仅策略构造语法；未确认 |
| XCCIHistogramVolDirectIndicator | 历史静态线索，所引测试未提交；未确认 |
| XCCIHistogramVolIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| XDeMarkerHistogramVolDirectIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| XFisherIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| XmaIchimoku | 历史静态线索，所引测试未提交；未确认 |
| XMAIshimokuChannelIndicator | 仅策略构造语法；未确认 |
| XMAIshimokuLine | 仅策略构造语法；未确认 |
| XMARangeBandsIndicator | 仅策略构造语法；未确认 |
| XPeriodCandleColor | 存在单元直接构造语法；未确认 |
| XPeriodCandleSystemColor | 仅策略构造语法；未确认 |
| XrsiDeMarkerHistogram | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |
| XRSIHistogramVolDirectIndicator | 存在单元直接构造语法；未确认 |
| XRSIHistogramVolIndicator | 存在单元直接构造语法；未确认 |
| ZeroLagHLRIndicator | 存在单元直接构造语法；未确认 |
| ZigZagRecentPivotSignal | 存在单元直接构造语法；未确认 |
| ZPFIndicator | 旧盘点称局部设计（本次仅核文件存在）；旧盘点称有独立期望，未逐节点核验 |

## 可分组验证方案

1. **滚动窗口和无状态函数**：按 OHLC/close/volume 数据依赖与窗口族分批，以独立公式构造默认、短周期和长周期，核对所有公开线完整数组、首有效值与独立 minperiod、缺失离窗恢复和 short history；避免以全零或全 NaN 样本冒充通过。
2. **递归/颜色/信号状态**：以明确独立状态机测试完整预热序列、趋势反转、flat、NaN 和恢复；逐根/批量及分段 once 分别运行。对状态策略还需验证无效信号不能触发真实本地订单。
3. **组合表达式与子指标**：明确每条线的上游依赖和 minperiod 推导，覆盖 batch/next 初始化顺序、不同平滑方法、依赖中途 NaN；父类通过不代替子类单独输出验证。
4. **时钟和重放**：每个状态族抽取 fast/slow feed、真实小时→日 replay、同 bar 多次修订、缺失末次修订和 bounded buffer；replay 请求 runonce 会回落 next，不计为独立批量证据。
5. **负载与特殊合同**：对 strict 高有限值溢出、零分母、可见 NaN 与原始 Inf 分别建证；动态参数、自定义子类和性能另列，不借普通合成样本推定安全。每轮固定公开 HEAD，仅跑新增节点，提交已独立审阅的窄范围。

## 已有高价值问题

- `SmoothedRelativeVigorIndex` 已记录完整 OHLC 缺失期间子均线为 NaN，最终 `If` 却在两模式投影为0；不能将此有限结果当有效 RVI，真实策略信号影响应单独复现。
- `PriceExtremeChannel` 的旧真实探针显示输出在零基索引5已出现有限值，声明 minperiod 为12；这不是双模式不一致，但表明最小周期、可用输出与预热前缀的合同需逐线界定。
- `XDeMarkerHistogramVolDirectIndicator` 的 strict 计算中间溢出、`ArrowsCurvesIndicator` 的输入长度回退/输出写失败非原子等均在近期复核中明确开放；局部修复或 replay 通过不等于本矩阵完成。
- 旧盘点中有测试文件来自未提交 WIP（例如 contrib_remaining）；本矩阵按已提交快照核对文件是否存在，不把用户草稿或函数名当成通过。

明细 JSON 与全部直接构造/引用位置见同目录 `matrix_r3.json`；它不是运行报告。

## 历史盘点证据位置（仅定位，不是当前通过）

| 类 | 旧文声称类型 | 旧文引用的本提交测试文件或节点 |
|---|---|---|
| AdaptiveMarketLevel | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_adaptive_market_level_minperiod.py:178` |
| ADXCrossHullStyleIndicator | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py:326` |
| AmlIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_aml_seed.py:192` |
| AroonOscillatorSignAlert | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_aroon_oscillator_sign.py:167` |
| ASCtrendIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_as_ctrend_value11.py:124` |
| BinaryWaveIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_binary_wave_runonce.py:125` |
| BlauErgodic | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_blau_ergodic_runonce.py:122` |
| BlauErgodicMDI | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_blau_ergodic_mdi_color.py:104` |
| CCIDualOnMA | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_linecci_minperiod.py:105` |
| CloseCloseEmaStochastic | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_close_close_stochastic_runonce.py:112` |
| Color3rdGenXMAIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color3rdgenxma_minperiod.py:156` |
| ColorBBCandlesIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color_bb_candles_minperiod.py:124` |
| ColorRMACDIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color_rmacd_ema_signal.py:61` |
| ColorSchaffTrendCycleIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color_schaff_runonce.py:171` |
| ColorStepXCCXIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color_step_xccx_state.py:157` |
| ColorXDerivative | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py:443` |
| CorrectedAverageIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_corrected_average_runonce.py:122` |
| DigitalMacd | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_digital_macd_convolution.py:124` |
| FramaLinesIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_frama_seed.py:203` |
| FramaSeries | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_frama_seed.py:122` |
| IAMMAIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_iamma_seed.py:87` |
| JMASlopeIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_contrib_coverage_audit.py:157` |
| LineCCI | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_linecci_minperiod.py:105` |
| OsHMAIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_remaining_contrib_mode_parity.py::test_public_lines_match_from_declared_minperiod` |
| QQECloudIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_qqe_cloud_once_seed.py::test_qqe_cloud_once_carries_trailing_reference_across_segments` |
| RawCloseCloseStochastic | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_raw_close_close_stochastic_nan_parity.py::test_raw_and_smoothed_lines_match_reference_after_nan_window` |
| RDTrendTriggerIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_rd_trend_trigger_seed.py::test_rd_trend_trigger_seeds_from_first_valid_ttf_for_171_real_bars` |
| RFTLIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_remaining_contrib_mode_parity.py::test_public_lines_match_from_declared_minperiod` |
| RsiomaV2 | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_rsioma_v2_runonce.py::test_signal_matches_independent_ema_and_next` |
| RVIHistogramIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_rvi_histogram_warmup.py::test_first_published_value_has_full_prior_input_history` |
| SmoothedRelativeVigorIndex | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_smoothed_rvi_nan_window.py::test_missing_ohlc_keeps_child_windows_and_current_zero_projection_in_both_modes` |
| StochasticHistogramIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_stochastic_histogram_execution_modes.py::test_runnext_matches_full_batch_series_and_independent_formula` |
| T3AlarmIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_t3_alarm_once_segments.py::test_t3_default_once_matches_next_with_warmup_and_missing_values` |
| ThreeLineBreakIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_three_line_break_minperiod.py::test_three_line_break_run_modes_match_with_a_missing_bar` |
| TrendContinuationIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_trend_continuation_seed.py::test_trend_continuation_first_value_seeds_from_current_components` |
| TrendIntensityIndexProxy | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_trend_intensity_index_proxy.py::test_tii_next_once_and_segmented_once_match_missing_reference` |
| TRVIIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_color_rmacd_ema_signal.py::test_trvi_next_once_and_segmented_match_reference` |
| TwoXmaIchimokuOscillator | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py::test_xma_long_period_dynamic_length_and_exactbars` |
| UltraWPRIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_ultra_wpr_runonce.py::test_ultra_wpr_cerebro_modes_match_reference_and_exact_warmup` |
| UltraXMAIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_ultraxma_runonce.py::test_ultraxma_full_runonce_sequence_matches_runnext` |
| VininITrendIndicator | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py::test_vinin_i_trend_runonce_segmented_and_runnext_parity` |
| VininITrendLRMAIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_vinin_trend_seed.py::test_vinin_lrma_trend_matches_raw_seeded_reference_for_171_bars` |
| VWAPCloseIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_vwap_close_contract.py::test_vwap_close_matches_n_bar_formula_and_minperiod` |
| XCCIHistogramVolDirectIndicator | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py::test_xcci_vol_direct_clean_parity_and_exactbars` |
| XCCIHistogramVolIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_xcci_histogram_vol_missing.py::test_missing_inputs_do_not_publish_a_valid_neutral_color_or_signal` |
| XDeMarkerHistogramVolDirectIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_x_demarker_histogram_vol_direct_warmup.py::test_first_values_match_formula_without_losing_prenext_bars` |
| XFisherIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_x_fisher_warmup.py::test_x_fisher_recursive_output_includes_valid_prenext_bars` |
| XMACDIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_xmacd_minperiod_runonce.py::test_missing_values_and_segmented_once_match_streaming` |
| XmaIchimoku | 历史静态线索，所引测试未提交 | `tests/unit/indicators/test_iter71_contrib_remaining.py::test_xma_long_period_rolling_sum_matches_reference_and_dual_modes` |
| XrsiDeMarkerHistogram | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_xrsi_de_marker_histogram_rsi_price.py::test_rsi_price_selects_the_requested_source_and_matches_rsi_reference` |
| XRVIIndicator | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_xrvi_runonce.py::test_xrvi_real_cerebro_matches_independent_reference` |
| ZeroLagMacd | 旧盘点称全序列设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_zero_lag_macd_runonce.py::test_formula_and_signal_seed_match_next_and_once` |
| ZPFIndicator | 旧盘点称局部设计：本次仅核文件存在 | `tests/unit/indicators/test_iter71_zpf_line1_binding.py::test_zpf_and_line1_match_independent_reference_with_missing_inputs` |

## 历史来源及绑定

以下六份为读取时的公开**工作区**材料，SHA-256 固定的是当时工作区原始字节；它们不是 c5fc 提交对象，也不将任何报告中的测试结果自动绑定到该 HEAD。五份盘点及样本报告对分类、历史样本的作用如上，第六份是旧类清单。

| 工作区来源 | SHA-256 |
|---|---|
| `D:/source_code/backtrader/.codex-tmp/iter71_indicators_af.md` | `19f784fb382a67b7c54536b93828c4831c412155582ebe5f6d3cfb1fe1226e91` |
| `D:/source_code/backtrader/.codex-tmp/iter71_indicators_gl.md` | `3062b07f2eb5dc032e3eeadd613b3d34312f5faa491de065af534af98f598320` |
| `D:/source_code/backtrader/.codex-tmp/iter71_indicators_mr.md` | `d1297991478b233ab39a8b95187e9d669420124140d1b6de4797bda456a2ce0f` |
| `D:/source_code/backtrader/.codex-tmp/iter71_indicators_sz.md` | `0e9817512808515a00785c307653958af1f6cb401090d59f3f59c6854d702f04` |
| `D:/source_code/backtrader/.codex-tmp/iter71_indicators_mr_probe.md` | `f6ac1477a959cf2ffa13773ac390bd605c9d968de729fb3172b462c567e8e9e8` |
| `D:/source_code/backtrader/.codex-tmp/iter71_contrib_inventory_20261121.json` | `d329f4eb3d15aabd75e3629aa662a80bdd5c22fac6af3d04ba37c14f52066761` |

## 新的限定试点线索

benchmark102 的探索性结果记录称，在受限轻量包壳、128 根合成数据及第 55 根 high 为 NaN 的 AroonHornSignIndicator 试点中，两模式两线全序列一致，55–63 两箭头均为有限0。结果文件 `D:/temp/i71_parity_harness_c5fc_20261122/pilot_results_20261122.json` 的 SHA-256 为 `be504079fa9de3e65f985b221ea1aac2c4c5b1ec313588e9e2cc499be4ab13e5`。该次执行的脚本随后在原路径修改且未留固定副本，因此无法核验执行脚本字节或按固定脚本重现，本条不计为正式通过或当前 HEAD 的已绑定运行证据。有限0不能单独证明缺失合同错误或存在伪箭头；受限包壳也不能代表完整包导入。

独立审阅者核对公开快照中 536 个源码/测试文件与 c5fc Git blob 在 CRLF→LF 后一致，并核对 258 个 `(module, class, line)`；这不构成运行测试，也不涵盖目录外或用户自定义类。
