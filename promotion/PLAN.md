# Awesome 列表 PR 推广计划(第二批)

> 目标:向 2000+ star 的 curated 列表提交 PR,收录 6 个 cloudQuant 仓库。
> 调研日期:2026-08-16。筛选标准:star ≥ 2000、活跃维护(2026 年内有 push)、未收录 cloudQuant、适配度真实。

## 第一梯队(格式已确认,可直接执行)

| # | 列表 | Star | 提交仓库 | 分类/位置 | 条目格式 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [thuquant/awesome-quant](https://github.com/thuquant/awesome-quant) | 5.6k | backtrader、backtrader_web、fincore | 回测 / 量化交易平台 / 编程→Python | `* [Name](url) - 中文描述` | 中文受众,活跃(08-10)。无 CONTRIBUTING,可一个 PR 多条,但建议 2 个 PR 降低风险 |
| 2 | [yzfly/Awesome-MCP-ZH](https://github.com/yzfly/Awesome-MCP-ZH) | 7.6k | backtrader-mcp | 💰 金融与加密货币 | 表格行,按字母/拼音就近插入 | 有贡献指南;中文受众;活跃(07-03) |
| 3 | [wong2/awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers) | 4.3k | backtrader-mcp | Community Servers | `- **[Name](url)** - 描述.` | 活跃(07-13);无 CONTRIBUTING |
| 4 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | 52.4k | backtrader-skills | ## Skills | `- [Name](url) by [cloudQuant](https://github.com/cloudQuant) - 描述` | 非常活跃(08-16);描述要强调真实用例 |

## 第二梯队(需先确认格式/分类再提交)

| # | 列表 | Star | 提交仓库 | 需确认事项 |
| --- | --- | --- | --- | --- |
| 5 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 72.6k | backtrader-skills | 是否有量化/金融类目;条目格式 `- [Name](url) - desc. *By [@cloudQuant](...)*`;需"真实用例"叙事 |
| 6 | [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | 24.4k | backtrader-agent | 分类在 `categories/07-specialized-domains/` 下找金融/量化子类;需按分类文件夹格式提交 |
| 7 | [awesome-opencode/awesome-opencode](https://github.com/awesome-opencode/awesome-opencode) | 9.6k | backtrader-agent | 确认 agents 分类与条目格式(README 抓取失败,需 clone 查看) |
| 8 | [e2b-dev/awesome-ai-agents](https://github.com/e2b-dev/awesome-ai-agents) | 29.5k | backtrader-agent | 确认 Coding Agents / Agent Frameworks 分类与表格格式 |
| 9 | [BehiSecc/awesome-claude-skills](https://github.com/BehiSecc/awesome-claude-skills) | 10.0k | backtrader-skills | 确认条目格式(活跃 08-02) |
| 10 | [botcrypto-io/awesome-crypto-trading-bots](https://github.com/botcrypto-io/awesome-crypto-trading-bots) | 2.5k | backtrader | 确认是否有 Framework 分类(backtrader 支持 CCXT 加密货币) |

## 已排除(停更/归档/不适配)

| 列表 | 原因 |
| --- | --- |
| vinta/awesome-python(314k) | 金融相关只有"Financial Data"数据下载分类,无回测/分析分类,不适配 |
| appcypher/awesome-mcp-servers | 已 archive |
| chatmcp/mcpso、grananqvist/Awesome-Quant-ML-Trading、travisvn/awesome-claude-skills、vijaythecoder、rohitg00、RKiding/Awesome-finance-skills、slavakurilyak、ai-for-developers | 2025 年或 2026 年初后停更,PR 大概率无人合并 |
| punkpeye/awesome-mcp-clients | 服务器不适用(clients 列表) |

## 执行规则(第一批的教训)

1. **先读 CONTRIBUTING + CI 校验器**——awesome-quant 教训:一个 PR 只能新增一条 README 条目,有 CI validator
2. **一次只对同一个列表开必要数量的 PR**,错峰提交,避免被维护者视为批量营销
3. **描述用事实**:性能数据(1.86x / 128x)、测试数量(3,200+/1,271)、工具数(30)、指标数(150+)——不写空洞形容词
4. **每 PR 提交后记录链接到 promotion/README.md**,跟踪合并状态
5. 预计每个列表 1 个 PR(共 10 个候选);若某列表有 validator 且只允许单条目,再拆分

## 覆盖矩阵(本批完成后)

| 仓库 | 新曝光列表 |
| --- | --- |
| backtrader | thuquant(#1)、botcrypto(#10) |
| backtrader-mcp | yzfly(#2)、wong2(#3) |
| backtrader-skills | hesreallyhim(#4)、ComposioHQ(#5)、BehiSecc(#9) |
| backtrader-agent | VoltAgent(#6)、awesome-opencode(#7)、e2b-dev(#8) |
| backtrader_web | thuquant(#1) |
| fincore | thuquant(#1) |
