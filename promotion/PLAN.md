# Awesome 列表 PR 推广计划(第二批)

> 目标:向 2000+ star 的 curated 列表提交 PR,收录 6 个 cloudQuant 仓库。
> 调研日期:2026-08-16;2026-09-20 复核第一梯队(渠道已变,见下)。筛选标准:star ≥ 2000、活跃维护(2026 年内有 push)、未收录 cloudQuant、适配度真实。

## 第一梯队(PR 可直接执行,2026-09-20 复核通过)

| # | 列表 | Star | 提交仓库 | 分类/位置 | 条目格式 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [thuquant/awesome-quant](https://github.com/thuquant/awesome-quant) | 5.6k | backtrader、backtrader_web、fincore | 回测 / 量化交易平台 / 编程→Python | 以 raw README 为准(渲染页为 `- [Name](url) - 中文描述`) | 中文受众,活跃。无 CONTRIBUTING、无 CI validator(仓库仅 README/papers/LICENSE)。**每仓库 1 个 PR,共 3 个**(沿用第一批单条目教训)。当前 8 个 open PR,合并节奏可能偏慢 |
| 2 | [yzfly/Awesome-MCP-ZH](https://github.com/yzfly/Awesome-MCP-ZH) | 7.7k | backtrader-mcp | 💰 金融与加密货币 | 表格行三列(名称/中文介绍/备注) | 有 CONTRIBUTING,提交前先读;README 超长且网页渲染会截断,需对全文检索 `backtrader` 确认未收录(以 raw/clone 为准) |

## 非 PR 渠道(2026-09-20 复核发现渠道变更,需人工操作)

| # | 列表 | Star | 提交仓库 | 渠道与注意事项 |
| --- | --- | --- | --- | --- |
| 3 | [wong2/awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers) | 4.3k | backtrader-mcp | ❌ README 顶部声明 "We do not accept PRs",改为网站提交 https://mcpservers.org/submit(需人工填表;可与 promotion/README.md 待办 3 的 MCP 目录站 mcp.so/smithery/glama 一并处理) |
| 4 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | 54.3k | backtrader-skills | ❌ CONTRIBUTING 明确 "Do not open a PR",必须**人工**在 Web UI 用 issue 表单提交(明令禁止 gh CLI,有机器人校验)。门槛:项目 ≥14 天且持续提交,或 ≥100★;一次只能推荐 1 个资源;描述须客观陈述功能、一行、无 emoji、无营销语气。维护者对推广行为敏感,需备好被拒预案 |

## 第二梯队(需先确认格式/分类再提交;skills 类列表 #5/#9 可能同样只收 issue 表单,动手前先读 CONTRIBUTING 和 README 顶部声明)

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
5. 第一波 4 个 PR:thuquant ×3(每仓库一条)+ yzfly ×1,分 1-2 天错峰提交;#3/#4 走人工渠道另行安排;第二梯队逐个核实后排期
6. 提交渠道每批都要重新核实:动手前重读目标仓库 README 顶部声明与 CONTRIBUTING(本批 #3/#4 即因 8 月调研后渠道变更被纠偏)。本机无 gh CLI:PR 用 fork+git push+网页开 PR 完成,issue 表单类(如 #4)必须人工操作,AI 无法代提

## 覆盖矩阵(本批完成后)

| 仓库 | 新曝光列表 |
| --- | --- |
| backtrader | thuquant(#1)、botcrypto(#10) |
| backtrader-mcp | yzfly(#2)、wong2(#3,人工网站提交) |
| backtrader-skills | hesreallyhim(#4,人工 issue 表单)、ComposioHQ(#5)、BehiSecc(#9) |
| backtrader-agent | VoltAgent(#6)、awesome-opencode(#7)、e2b-dev(#8) |
| backtrader_web | thuquant(#1) |
| fincore | thuquant(#1) |
