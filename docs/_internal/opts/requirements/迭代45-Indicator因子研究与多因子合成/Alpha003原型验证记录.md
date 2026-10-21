# Alpha003横截面示例原型验证记录

日期：2026-10-21。仓库：`D:/source_code/backtrader`，现有`dev`。父提交：`9e078e28398bd68be51b125a618447ed4a29e145`。本记录与原型同批提交；准确提交可用`git log -1 -- examples/backtest/027_alpha003_panel_acceptance`定位，最终回复也提供SHA。

## 范围与使用方式

用户在v0.4文档交付后明确要求：先在examples实现Alpha101 #3的验收例子，查看使用横截面数据的因子如何实现。新增[027_alpha003_panel_acceptance](../../../../../examples/backtest/027_alpha003_panel_acceptance/README.md)，不占用预留的025/026正式示例编号。

- `alpha003_strategy.py`：唯一的因子定义，只实现PanelFactorIndicator类方法build。
- `factor_strategy.py`：示例内公共FactorStrategy和最小共享表达式引擎；支持字段、截面平均秩、整数窗口Pearson相关、负号。
- `run.py`、`config.yaml`：确定性三资产数据、Cerebro接入、验收与CSV/JSON导出。
- `acceptance.py`：独立Fraction参考及对照，不调用候选算子生成expected。
- 示例README、仓库示例索引、既有复制契约登记，以及本记录和文档入口同步。

Backtrader库代码、fincore和账户路径没有修改。模板和引擎仍局限在本例目录；不把该原型当成已稳定的公共研究API。

## 验收结果

| 检查 | 结果与证据范围 |
|---|---|
| 仓库内默认运行 | PASS；13组检查，17次成功实验、5个非法输入拒绝，共22次尝试；另一次默认实验用于导出展示结果 |
| 独立已知答案 | 第10格A/C=17/23，B=1；前9格缺失；更改B当日open为9.5后，A=sqrt(20/23) |
| 真实Cerebro模式 | runonce/runnext均与独立完整网格参考一致；因子声明不生成普通Indicator实例，不下单 |
| 时间和横截面 | 验资产顺序、未来扰动、并列、零方差；两模式验单资产缺bar、全池内部/尾部缺格、主Feed晚开始早结束 |
| 共享计算 | 两个输出使用同一声明时仍为6个节点；每节点每grid恰好一次 |
| 输入拒绝 | 未知ctx字段、必需列缺失、网格外时间、open/volume无穷值均拒绝 |
| 仓外安装/复制 | `BT_I43_COPY_STRICT=1`：5 passed、128 deselected、0 skipped；包含3种复制运行、1个忽略文件检查、1个自包含导入检查 |
| 复制结果读取 | 三份acceptance.json均PASS；实际导入独立venv的site-packages/backtrader；每份CSV非空，自定义输出目录得到正确落点 |
| 静态质量 | 新例4个Python文件ruff通过，black定向检查通过；明确范围Git whitespace检查通过 |

严格复制环境位于`D:/temp/alpha003-prototype-20261021/venv`，使用system-site-packages复用已有测试/分析依赖；Backtrader单独安装在该venv的site-packages，版本1.4.0，未修改全局原有1.3.0。构建wheel SHA-256为`d3d1decb84ce14228aa5d5837e5b6919574c06eef46fc85c2ccb2477af3a5d7e`。这是本原型的安装运行验证，不是完整迭代45打包验收。

本地输出在示例已忽略的`output/`，包括input_bars.csv、node_values.csv、factor_values.csv和acceptance.json；源码内保留可复现输入/参考，不把本机结果当作便携数据依赖。

## 发现与处理

第一轮完整检查发现无穷源输入没有被Feed后的检查可靠拒绝；已在创建Feed前显式验证源OHLCV，并把fixture数值设为float，消除pandas隐式dtype变更警告。修复后完整验收通过。

初次pytest收集被既有pytest/pytest-asyncio版本不兼容阻断（Package没有obj）；这些是同步测试，后续设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`执行，未改测试判据。成功pytest保留一条既有`asyncio_default_fixture_loop_scope`未知配置警告。

额外运行全局入口分类及布局检查得到14 passed、2 failed、1 skipped。两项失败都指向父提交已跟踪的`examples/service_execution_session`：其根目录未纳入布局白名单，run.py未纳入入口分类。与新027目录无关，本轮没有改动它或放宽检查，因此不声称全局布局/入口检查通过。

## 证据边界与交接

证据等级为`LOCAL_ALPHA003_PROTOTYPE_ONLY`。固定资格池内按当期有限字段确定rank的有效子集；缺失格保留，窗口不压缩，网格尾部无行情时只输出缺失。该政策符合DS45-11/12，不能解释为对缺失行情补值或生成有效交易信号。

本轮不实现动态行业/PIT、全量算子、fincore评价、完整数据集合同或101生产因子库。AC45-01–30仍为NOT_RUN；正式迭代需要将公共能力迁入库、扩充验收并验证其余19个代表式以及两个正式示例。原型对用户写法的展示已经完成，不再重复本轮已通过的验收仅用于提交。
