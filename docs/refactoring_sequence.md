# Backtrader 重构序列 - 从子类到父类

## 重构原则
- **从子类到父类**: 每次只重构一个文件
- **测试驱动**: 每次重构后运行 `sh install_unix.sh` 确保所有测试通过
- **保持功能**: 重构后功能必须保持不变

## 完整重构序列（139个文件）

### 阶段1：指标实现类（49个文件）
测试命令：`pytest tests/original_tests/test_ind_*.py -v`

1. `indicators/zlind.py`
2. `indicators/zlema.py`
3. `indicators/wma.py`
4. `indicators/williams.py`
5. `indicators/vortex.py`
6. `indicators/ultimateoscillator.py`
7. `indicators/tsi.py`
8. `indicators/trix.py`
9. `indicators/stochastic.py`
10. `indicators/smma.py`
11. `indicators/sma.py`
12. `indicators/rsi.py`
13. `indicators/rmi.py`
14. `indicators/psar.py`
15. `indicators/priceoscillator.py`
16. `indicators/prettygoodoscillator.py`
17. `indicators/pivotpoint.py`
18. `indicators/percentrank.py`
19. `indicators/percentchange.py`
20. `indicators/oscillator.py`
21. `indicators/ols.py`
22. `indicators/myind.py`
23. `indicators/momentum.py`
24. `indicators/macd.py`
25. `indicators/lrsi.py`
26. `indicators/kst.py`
27. `indicators/kama.py`
28. `indicators/ichimoku.py`
29. `indicators/hurst.py`
30. `indicators/hma.py`
31. `indicators/heikinashi.py`
32. `indicators/hadelta.py`
33. `indicators/envelope.py`
34. `indicators/ema.py`
35. `indicators/dv2.py`
36. `indicators/dpo.py`
37. `indicators/dma.py`
38. `indicators/directionalmove.py`
39. `indicators/deviation.py`
40. `indicators/dema.py`
41. `indicators/crossover.py`
42. `indicators/cci.py`
43. `indicators/bollinger.py`
44. `indicators/basicops.py`
45. `indicators/awesomeoscillator.py`
46. `indicators/atr.py`
47. `indicators/aroon.py`
48. `indicators/accdecoscillator.py`
49. `indicators/contrib/vortex.py`

### 阶段2：分析器实现类（17个文件）
测试命令：`pytest tests/original_tests/test_analyzer*.py -v`

50. `analyzers/vwr.py`
51. `analyzers/transactions.py`
52. `analyzers/tradeanalyzer.py`
53. `analyzers/total_value.py`
54. `analyzers/timereturn.py`
55. `analyzers/sqn.py`
56. `analyzers/sharpe_ratio_stats.py`
57. `analyzers/sharpe.py`
58. `analyzers/returns.py`
59. `analyzers/pyfolio.py`
60. `analyzers/positions.py`
61. `analyzers/periodstats.py`
62. `analyzers/logreturnsrolling.py`
63. `analyzers/leverage.py`
64. `analyzers/drawdown.py`
65. `analyzers/calmar.py`
66. `analyzers/annualreturn.py`

### 阶段3：数据源实现类（19个文件）
测试命令：`pytest tests/original_tests/test_data*.py -v`

67. `feeds/yahoo.py`
68. `feeds/vchartfile.py`
69. `feeds/vchartcsv.py`
70. `feeds/vchart.py`
71. `feeds/vcdata.py`
72. `feeds/sierrachart.py`
73. `feeds/rollover.py`
74. `feeds/quandl.py`
75. `feeds/pandafeed.py`
76. `feeds/oanda.py`
77. `feeds/mt4csv.py`
78. `feeds/influxfeed.py`
79. `feeds/ibdata.py`
80. `feeds/ctpdata.py`
81. `feeds/csvgeneric.py`
82. `feeds/chainer.py`
83. `feeds/ccxtfeed.py`
84. `feeds/btcsv.py`
85. `feeds/blaze.py`

### 阶段4：经纪商实现类（6个文件）
测试命令：`pytest tests -k "broker" -v`

86. `brokers/vcbroker.py`
87. `brokers/oandabroker.py`
88. `brokers/ibbroker.py`
89. `brokers/ctpbroker.py`
90. `brokers/ccxtbroker.py`
91. `brokers/bbroker.py`

### 阶段5：观察者实现类（7个文件）
测试命令：`pytest tests -k "observer" -v`

92. `observers/trades.py`
93. `observers/timereturn.py`
94. `observers/logreturns.py`
95. `observers/drawdown.py`
96. `observers/buysell.py`
97. `observers/broker.py`
98. `observers/benchmark.py`

### 阶段6：其他实现类（16个文件）
测试命令：`pytest tests -v --timeout=30`

99. `sizers/percents_sizer.py`
100. `sizers/fixedsize.py`
101. `stores/vcstore.py`
102. `stores/oandastore.py`
103. `stores/ibstore.py`
104. `stores/ctpstore.py`
105. `stores/ccxtstore.py`
106. `filters/session.py`
107. `filters/renko.py`
108. `filters/heikinashi.py`
109. `filters/daysteps.py`
110. `filters/datafilter.py`
111. `filters/datafiller.py`
112. `filters/calendardays.py`
113. `filters/bsplitter.py`
114. `commissions/dc_commission.py`

### 阶段7：中间层基类（13个文件）
测试命令：`pytest tests -v --timeout=30`

115. `sizer.py`
116. `store.py`
117. `resamplerfilter.py`
118. `position.py`
119. `order.py`
120. `trade.py`
121. `comminfo.py`
122. `fillers.py`
123. `timer.py`
124. `signal.py`
125. `dataseries.py`
126. `writer.py`
127. `talib.py`

### 阶段8：核心基类（6个文件）
测试命令：`pytest tests -v --timeout=30`

128. `observer.py`
129. `analyzer.py`
130. `feed.py`
131. `broker.py`
132. `strategy.py`
133. `indicator.py`

### 阶段9：核心框架（6个文件）
测试命令：`pytest tests -v --timeout=30`

134. `cerebro.py`
135. `lineiterator.py`
136. `lineseries.py`
137. `linebuffer.py`
138. `lineroot.py`
139. `metabase.py` ← 最后重构

## 重构策略

### 每个文件的重构步骤：
1. **备份原文件**
2. **分析元类使用**
3. **设计替代方案**
4. **实施重构**
5. **运行测试**
6. **修复问题**
7. **确认通过**

### 测试验证：
- 阶段1-6：针对性测试
- 阶段7-9：完整测试套件
- 每个文件：`sh install_unix.sh` 最终验证

### 风险控制：
- 每次只修改一个文件
- 保持代码备份
- 测试失败立即回滚
- 记录所有更改
- 不能修改测试用例

这个序列确保了最安全的重构路径，从最外层的实现类开始，逐步向核心框架推进。