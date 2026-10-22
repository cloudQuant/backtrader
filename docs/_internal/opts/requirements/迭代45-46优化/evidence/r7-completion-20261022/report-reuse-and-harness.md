# 报告复用与剩余验收工具

fincore `e04bd082b85374d58e304ec15d43dd134b7fe77b` 在每次报告投影内只读取一次模型的公开属性，将返回的副本作为局部变量复用。没有全局缓存，不改变统计核或公开模型的复制隔离。新增测试逐项统计属性访问，并比较完整报告 payload / semantic digest；报告副本的修改不能改变模型或另一次报告。

同一模型分别用中文/英文和不同标题渲染时，prepare/analyze 被替换为会失败的探针；两次渲染通过且完整模型和结果指纹不变。

主线程在 fincore 运行：

```text
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/factor_analysis tests/parity -q
```

结果为 124 项通过，退出码 0，见 `fincore-report-reuse-regression.txt`。之后只修正 TYPE_CHECKING import 和测试 Counter 的 Ruff 提示，重新运行两个报告测试文件，7 项通过，见 `fincore-report-reuse-focused.txt`；三个改动文件 Ruff 通过。

Backtrader 补齐真实 CLI 的 report-only 选项、独立采集计时、浮点核/固定帧报告归因、阶段/RSS/1-3-10 因子诊断、完整结果逐键比较和固定提交 wheel 验证。026 默认配置恢复旧列序 `close_ma, kdj_j, roc`，新 FactorPanel 仍保留调用者显式列序的接口。025/026 帮助文字明确只有 `--save-panel` 才保存可复评面板，报告状态需读取 summary。

主线程运行 7 个工具/示例测试文件，结果 **99 passed / 2.00s**，见 `final-harness-focused-r3.txt`。此前的测试导入路径和两处诊断 fixture 问题已修正，失败日志单独保留。此处只证明工具边界和局部变更，完整性能与安装结果须读取后续实测证据，不在本记录提前宣布通过。
