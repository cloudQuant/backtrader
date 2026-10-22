# R7b：评价和报告接口修复（2026-10-22）

范围：借用帧及 attrs/index 不变；清理 unused MultiIndex levels 后指纹稳定；拒绝 panel 无法提供的 precomputed 标签；报告逐因子方向；显式 next_open_to_open / close_to_close 价格口径与 025/026 配置透传。

主线程复核差异并独立执行 test_factor_fincore_integration.py、test_factor_report.py、test_factor_research_examples.py：**32 passed in 5.72s**，见 adapter-regression.txt。包含真实 fincore API、多因子正负方向隔离、缺 turnover capability 拒绝、CSV 指纹往返、报告两种价格口径及零订单采集。fincore 使用 dev@9027733 源码，此项不是安装验收。

本轮保留默认 next_open_to_open，无双重价格移位；新增显式 close_to_close 报告用于避免示例评价配置与 HTML 悄然分歧。尚未将上述局部通过用于关闭性能/全101/安装门禁。
