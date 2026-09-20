# 人工渠道提交文案(第二批 #3/#4)

> 这两个列表 2026-09-20 复核后确认**不接受 PR**,必须人工在网页操作。文案已按各渠道规则准备,直接复制使用。

## #3 wong2/awesome-mcp-servers → mcpservers.org(网站表单)

该列表 README 顶部声明 "We do not accept PRs. Please submit your MCP on the website"。

**操作步骤**:

1. 打开 https://mcpservers.org/submit ,用 GitHub 账号(cloudQuant)登录
2. 按下方文案填写表单
3. 建议与 promotion/README.md 待办 3 的 MCP 目录站(mcp.so / smithery.ai / glama.ai)同一天批量提交

**表单参考文案**:

| 字段 | 内容 |
| --- | --- |
| Name | backtrader-mcp |
| Repository | https://github.com/cloudQuant/backtrader-mcp |
| Category | Finance |
| Description(EN) | Local-first (stdio) Python MCP server for backtrader strategy development: 30 typed tools with readOnly/destructive/idempotent hints, immutable CAS datasets, typed strategy drafts, human-gated change/run approvals, and bounded subprocess backtests. Ships host configs for Claude Desktop/Claude Code, Codex, and OpenCode. Bilingual (EN/中文) docs. |

> 表述与 punkpeye/awesome-mcp-servers PR #12257 保持一致(同一事实来源),避免两个目录描述互相矛盾。

## #4 hesreallyhim/awesome-claude-code → Web UI issue 表单

**硬性要求**(来自其 CONTRIBUTING,2026-09-20 核实):

- 必须**人工**在 Web UI 用表单提交:https://github.com/hesreallyhim/awesome-claude-code/issues/new?template=recommend-resource.yml
- 明令禁止 gh CLI/API 提交,机器人会校验,AI 无法代提
- 门槛:项目 ≥14 天且 first commit 后有持续提交,**或** ≥100★(backtrader-skills 走"14 天+持续开发"通道)
- 一次只能推荐 **1 个**资源
- 描述要求:客观陈述功能、**一行**、无 emoji、无营销语气("description, not a sales pitch")

**提交前检查清单**:

- [ ] 确认 backtrader-skills 仓库有规范 LICENSE 文件且能被 GitHub license 自动识别(bot 探测失败会被追问)
- [ ] 确认仓库 ≥14 天且有持续提交记录
- [ ] 描述保持一行、事实性陈述

**推荐文案**(表单 Resource description 字段,EN):

```
Offline skills for authoring, reviewing, and testing backtrader trading strategies with AI coding agents (Claude Code, Codex, OpenCode), with validation and regression gates.
```

**备注**(如表单有 "why useful / context" 类字段):

```
I'm the maintainer (@cloudQuant) of the backtrader ecosystem (actively maintained fork + MCP server). These skills let coding agents write and test trading strategies offline against the framework's real validation suite.
```

**心理预期**:维护者明言列表高度选择性、收录不是推广渠道的一部分;若被 close 属正常,待项目积累社区信号(star/使用反馈)后可再次提交,或按其建议"专注项目本身,等被发现"。
