# backtrader-mcp 2 分钟 Demo 脚本

> 用途:录屏素材(发布 B站 / YouTube / X / 知乎视频)
> 前置条件:backtrader-mcp 已安装并完成宿主配置(见仓库 README 的 Host setup 一节)
> 推荐录屏方式:Claude Code(或 Claude Desktop)会话 + 终端并行分屏

## 前置准备(录屏前一次性完成)

```bash
# 1. 专用环境安装(见 backtrader-mcp README)
git clone https://github.com/cloudQuant/backtrader-mcp.git
cd backtrader-mcp
python -m venv .runtime
. .runtime/bin/activate
python -m pip install -c constraints/requirements-v2.txt .

# 2. 注册只读数据根 + 诊断
export BACKTRADER_MCP_STATE_ROOT='/absolute/private/state'
export BACKTRADER_MCP_SOURCE_ROOTS='{"market_data":"/absolute/read-only/csv"}'
export BACKTRADER_MCP_TARGET_ROOTS='{"strategies":"/absolute/generated/strategies"}'
export BACKTRADER_MCP_RUNTIMES='{"default":"/absolute/cloudquant-backtrader"}'
backtrader-mcp doctor | python -m json.tool
# 期望: doctor.status == "passed"
```

## Demo 正文(约 2 分钟,全程读屏)

### 第 1 幕(0:00-0:20)——开场 + 数据检查

在 Claude Code 中输入:

```text
Use only the backtrader MCP server. Call doctor, then inspect my offline CSV
dataset in the market_data root. Show me the header and a few rows.
```

AI 调用 `doctor` + `inspect_dataset`,屏幕上出现结构化结果:数据源已识别、列结构清晰。

**字幕**:任何离线 CSV,先变成"AI 可验证的数据集"。

### 第 2 幕(0:20-0:50)——注册数据集 + 生成策略草稿

```text
Register the CSV as a dataset with explicit column mapping, then search the
strategy catalog for a multi-timeframe momentum archetype and create a draft
strategy from it.
```

AI 依次调用:
- `register_dataset` → 输出 `dataset_id=ds_<64hex>`,CSV 已固化到内容寻址存储
- `search_strategy_catalog` → 展示 1,155 条元数据记录中匹配的 archetype
- `create_strategy_draft` → 渲染出策略草稿(屏幕上滚动展示生成的 `strategy.py`)

**字幕**:数据集不可变,策略有类型化规格——每一步都可追溯。

### 第 3 幕(0:50-1:15)——静态审查 + 人工审批

```text
Validate the draft without running it, prepare the change set, and show me
exactly which files will be created in the target tree.
```

AI 调用 `validate_strategy_draft`(AST 级静态审查,不导入候选代码)→
`prepare_strategy_changes`(列出将创建的每个文件及哈希)→
终端里人工执行审批命令(录屏特写):

```bash
backtrader-mcp approve --change-set CHANGE_ID --change-token 'SIGNED_TOKEN' --yes
```

**字幕**:AI 生成的代码,必须经过人工审批才落地——审批命令没有 MCP 入口。

### 第 4 幕(1:15-1:45)——受控回测 + 报告

```text
Apply the change set, prepare the run plan, and after I approve, start the
backtest and poll for the result.
```

终端再次审批后,AI 调用 `apply_strategy_changes` → `prepare_strategy_run` →
`start_strategy_run` → 轮询 `get_run_status` → `get_run_result`,最终展示:

```text
final_value, sharpe_ratio, max_drawdown, return_rate, buy/sell counts,
runonce/runnext parity: PASS
```

**字幕**:runonce/runnext 双模式对拍一致,报告可复现。

### 第 5 幕(1:45-2:00)——收尾 CTA

屏幕展示生态链接 + Star 号召:

```text
6-repo ecosystem: cloudQuant/backtrader · backtrader-skills · backtrader-mcp
· backtrader-agent · backtrader_web · fincore
Docs: cloudquant.github.io/backtrader-mcp
```

**字幕**:从数据到回测报告,一次对话完成。Star & fork:github.com/cloudQuant

## 发布清单

- [ ] 标题模板:《一条 prompt,从 CSV 到回测报告——backtrader-mcp 实测》
- [ ] 视频平台:B站(中文)/ YouTube Shorts + X(英文,剪 60s 竖版)
- [ ] 描述区放 6 仓库链接 + awesome-mcp-servers 条目链接
- [ ] 发布当天同步发布文章(见 promotion/article-*.md)
