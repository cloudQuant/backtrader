# backtrader 本轮许可调整审阅包

状态：本地修改，未暂存、未提交、未推送、未发布、未开 PR。

前一阶段交付：新增两份审阅文件；setup.py 的一行 MIT classifier 已纠正为 GNU GPLv3；根 GPL 与业务文件保持。本文件包含完整待审条件和写入前的来源核查快照；下文核查快照中的“只读/未应用/干净”只描述准备阶段，不代表最终工作树状态。最终差异仅包含本文所列新增文件与 backtrader 一行纠错，用户既有改动不在交付补丁中。

本仓不适用其他三仓的非商用许可。历史 GPLv3-or-later 选择权以及第三方独立许可继续保留。

本次增量：基础商业政策已获用户确认；其他例外、正式文本和生效范围仍待审。新增 `DISCLAIMER.md` 及 README 入口，更新三仓许可正文和各仓范围说明。下文历史快照中尚未确认基础政策的表述仅记录前一阶段状态，不覆盖当前确认。免责声明未生效且不是许可条件；根许可和原有免责不变。

# 本地许可调整审阅说明

日期：2026-10-10。状态：本地审阅文件；未提交、未推送、未发布、未创建 PR。

本轮独立许可正文为 `LICENSE-SOURCE-AVAILABLE-DRAFT.md`，逐仓库范围为 `LICENSE-SCOPE-DRAFT.md`。草案均未生效；仓库现行根 LICENSE 保留。源码可见与禁止未经授权商业使用的方向明确；基础商业政策现已确认，具体正式文本和适用范围尚未获批准。个人使用本人自有资金回测和实盘明确拟免费，不以本人投资收益本身认定收费商用。无自动转开源期限。

## 提交前最小决策

1. **剩余例外**：用户已确认个人本人自有资金免费，企业内部使用、为他人管理资金、收费服务或商业产品集成需另行书面授权，无须重复确认这一基础政策。个人免费用途中的常规集成不属于商业产品集成。家庭共同账户、借款/全资公司账户、无偿亲友代管、公益学术机构、培训咨询/捐赠/报销成本等例外应逐项选定，或明确继续暂缓。不得因收益金额、交易频率等让个人自有资金使用变成收费商用。
2. **许可人及范围**：确认有权签发许可的主体，并以来源/授权证据确定首次生效的新版本、完整提交 SHA 和逐文件/版权部分白名单。当前三仓非商用许可白名单为空；所有来源不明、未获足够授权或不可分离的已有内容继续保留原许可。Git 作者名与根版权声明不足以证明完整权属。
3. **采用文本与贡献机制**：审阅完整独立草案、再分发规则与长期源码存档安排；决定下游原创新增部分是否必须采用同一许可、是否须公开，以及未来外部贡献能否另行取得商业授权。贡献者须主动确认具体许可，不能通过修改 CONTRIBUTING 追溯取得版权或宽泛重许可权。正式法律条款建议律师审阅。

仓库特有的硬阻塞另见各自适用清单：Fincept 签署与 GPL 组合分发；opendata 现行 BSL 冲突、既有转换与第三方资源；bt_api_py 的 19 子仓及厂商 SDK；backtrader 的 GPL 来源与版权声明保全。

## README、贡献说明及元数据的未来修改草案

本轮不把 ai-for-investor、opendata、bt_api_py 的现行许可元数据改成新许可，也不覆盖现有 README/CONTRIBUTING 中仍然正确描述当前版本的段落。权属与版本边界通过后，才按经批准清单同步修改：

- README：仅对批准的新版本及许可作品称“源码可见”，说明个人本人自有资金使用免费、商用另行授权、无自动转换；链接许可全文、版本适用清单及第三方例外。
- Python/前端包元数据：核实发行包的实际文件范围；只为已覆盖的包采用自定义许可标记及许可文本，不能冒用 MIT、BUSL-1.1、OSI classifier 或已注册标准许可标识。混合发行物须准确记录各部分许可；不能只改一个包标识就覆盖依赖、子模块或旧版代码。
- 贡献说明：新贡献者确认对明确文件及许可版本有权授权，保留来源和例外；既有 MIT 入站条款不改写成历史贡献者已同意版权转让或限制商业用途的证据。商业授权外部贡献须额外明确获得。
- 第三方声明：记录实际文件路径、上游版本/提交、版权、原许可证及待核实项；无需删除或降低现有 MIT/GPL/厂商声明。数据接口条款与数据再分发权不由代码许可代替。

建议未来贡献确认语句（尚未采用）：

> 我确认对本次贡献列明的原创部分有权授权，并同意这些具体部分按项目指定的正式许可版本接收和发布。我保留版权；第三方材料及其原许可已单列说明。本确认不适用于过去贡献，不是版权转让，也不自动授权项目所有者商业许可或任意重许可。

## 一手参考与设计来源

本轮只比较原则，不复制、翻译改写或换名使用标准 BSL 正文。MariaDB BSL 1.1 的自动转换与正文使用限制，不能满足无自动转换目标；opendata 既有冲突须律师审阅：[MariaDB BSL 1.1](https://mariadb.com/bsl11/)。

禁止商业使用的许可应描述为源码可见；开源定义允许商业领域使用：[OSI 开源定义](https://opensource.org/osd)。MIT 原授权包括相应商业利用权，不能以新根文件追溯取消：[OSI MIT 正文](https://opensource.org/license/mit)。

GPLv3 对适用作品再分发的限制不能由非商用条款覆盖：[GPLv3 官方文本](https://www.gnu.org/licenses/gpl-3.0.en.html)、[SPDX GPL-3.0-or-later 文本](https://spdx.org/licenses/GPL-3.0-or-later.html)。组合分发需要检查实际通信和结合关系：[GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation)。GNU 页直接抓取超时，已以一手搜索摘要、SPDX 转载正文和本地 GPL 文件交叉核对；未据此作出具体产品的法律豁免结论。

## 本轮已确认政策与免责声明审阅

用户已确认：个人本人自有资金免费；企业内部使用、为他人管理资金、收费服务或商业产品集成需另行书面授权。政策确认不代表正式许可、生效版本或任何权属白名单已经批准；前三仓白名单仍为空，Backtrader 仍保留 GPL，不适用上述新增商业限制。

新增 `DISCLAIMER.md` 是独立免责及风险提示草案，未生效，不构成许可证或商业限制。保证和责任限制须按适用法律、现行许可证、实际功能、展示和纳入方式审阅；正式发布用语及适用主体/版本仍须确认。通用声明不能消除实际个性化投资建议的义务，商业软件授权不等于金融监管许可或数据再分发权。

MIT 原有免责保留；GPL 第 15–17 条及第 7/10 条的既有保证、责任和权利边界保留。参考 [MIT 正式文本](https://opensource.org/license/mit) 与 [GPLv3 正式文本](https://opensource.org/license/gpl-3.0)。本轮不新增用户赔偿义务、任意责任上限、仲裁/法院选择或点击即接受约定。

正式发布前建议律师审阅免责声明与许可文本的配合，并核对适用主体、实际服务承诺及法律不得排除的责任；本轮不保证免责效力。完整业务测试和版权调查不在本轮增量范围。

---

## 写入前的逐仓来源核查快照

# Backtrader 本地许可核查

核查日期：2026-10-10（UTC）。本任务只读取目标仓库，在独立工作区准备审阅文件和补丁。
不执行仓库 Python 代码、安装、交易、提交、推送、发布、PR、reset、clean、stash 或历史改写。

## 仓库快照

| 项目 | 核实结果 |
| --- | --- |
| 实际路径 | `/Users/yunjinqi/Documents/new_projects/backtrader` |
| 当前分支 | `dev` |
| HEAD | `ad2c142b9a8b42cede85886528c681abdfcb8096` |
| 获取远程 | `https://github.com/cloudQuant/backtrader.git` |
| 推送远程 | GitHub 上述仓库；另有 `https://gitee.com/yunjinqi/backtrader.git` |
| 现行根许可 | GNU GPLv3，根 `LICENSE` 第 1–6 行 |
| 本轮非商用许可适用 | 不适用于本仓库；保留 GPL 及第三方例外 |

初始工作树已有以下改动。本任务没有读取其内容或覆盖这些文件：

- 已修改：`examples/007_ctp/live_certification/hongyuan_penetration/common/config.py`
- 已修改：`examples/017_fnn_embedding/reports/train_report.jsonl`
- 未跟踪：`docs/_internal/opts/requirements/迭代22_CTP中频模拟交易/evidence/first_set_g3_shadow_observation_20260922_incomplete_summary.json`
- 未跟踪：`docs/_internal/opts/requirements/迭代22_CTP中频模拟交易/evidence/first_set_g3_shadow_observation_20261008_incomplete_summary.json`

## 已读本地指导与范围

- 已完整读取根 `AGENTS.md`（486 行）、`CONTRIBUTING.md`，以及必要的 `README.md`、
  `setup.py`、`pyproject.toml` 和分支治理说明。
- `AGENTS.md` 第 17 行明确 GPLv3；第 24–39 行规定 `dev` 等分支用途与双远程推送。
  本轮无任何推送行为。
- 检查 `.agents/skills` 中相关 review 技能，读取
  `bmad-review-verification-gap/SKILL.md` 和 `bmad-review/SKILL.md`。
  后者是通用审阅工作流，未发现其提供许可证/权属审查专用规则；本轮采用本任务明确限定的
  证据核查与最小补丁范围，不运行其代码或外部动作。
- `AGENTS.md` 第 485–486 行引用的 `.joyincode/rules/backend.md`、
  `.joyincode/rules/frontend.md` 在本地不存在，已记录；本轮没有业务或前端开发改动。
- 未读取环境变量、凭证文件或交易配置内容，也未修改 Codex 记忆。

## 许可与元数据证据

| 位置 | 核实内容 | 处理 |
| --- | --- | --- |
| `LICENSE:1` | GNU GPL 第 3 版完整许可正文；原文件使用 CRLF | 原样保留 |
| `README.md:9`、`:963` | GPLv3 徽章、GPLv3 根许可说明 | 原样保留 |
| `AGENTS.md:17` | GPLv3 | 原样保留 |
| `setup.py:101` | `License :: OSI Approved :: MIT License`，与根许可和 README 冲突 | 准备仅一行纠错补丁，改为 GNU GPLv3 classifier |
| `pyproject.toml:1` 起 | 仅工具设置，未定义 `[project]` 或其他包许可字段 | 不改 |
| `CONTRIBUTING.md:1` 起 | 贡献流程、测试和分支规则；未发现版权转让或可重新许可上游的承诺 | 原样保留；不推定取得上游权属 |
| `docs/source/index.rst:13`、`index_zh.rst:13` | GPLv3 徽章 | 原样保留 |
| `backtrader/plot/multicursor.py:37` 起 | Matplotlib 1.2.0 独立许可；`:40` John D. Hunter；`:50` 起保留版权条件；`:55` 起修改摘要要求 | 保留全文，不转换为拟议非商用许可 |

`setup.py` 没有独立 `license=` 关键字。本轮不新增 `GPL-3.0-or-later` 整包字段，
也不凭这个 classifier 的修正声称已经完成整个分发包中每个文件的许可版本核验。
拟采用的 GNU GPLv3 classifier 可在 [PyPI 官方列表](https://pypi.org/classifiers/) 中核对。

## 新发现：当前文件头缺失，但本地历史明确保留上游权利

当前 `dev` 的 `backtrader/cerebro.py`、`strategy.py`、`__init__.py` 已没有原来的
Daniel Rodriguez 版权及 GPLv3-or-later 授权头；本地 `master` 的对应核心文件头也不能
作为“当前仍完整保留”的证据。本轮没有把当前文件头缺失解释为不存在上游版权。

限定到三个核心文件的本地 Git 历史检查得到：

- 本地历史提交 `cbb370311cac368db6157ce80abf5b0f72f681a3`（2024-12-19）：
  `backtrader/cerebro.py`、`backtrader/strategy.py` 第 5 行是
  `Copyright (C) 2015-2020 Daniel Rodriguez`，第 9–10 行明确 GPL 第 3 版或后续版本。
- 本地提交 `2dd089bf4d6da0af5395b6b0e1db44620b6e255d`（2025-05-30）的标题说明
  删除大部分 Python 文件版权声明；该提交对 `__init__.py`、`cerebro.py`、`strategy.py`
  各删除 18 行。该事实说明应检查通知合规，不能作为整库改许可以及撤销上游权利的依据。
- 作为补充来源，上游 [mementum/backtrader 的 cerebro.py](https://raw.githubusercontent.com/mementum/backtrader/master/backtrader/cerebro.py)
  仍标 Daniel Rodriguez 和 GPLv3-or-later；本报告的历史结论以已核实的本地提交为基准。

恢复准确的版权/GPL 通知及变更声明，是下一次正式分发前需要单独处理的阻塞。
本轮不恢复整个仓库的版权头，避免批量修改业务文件或误写逐文件贡献权属。

## 为什么不把本仓库改为非商用许可

本地 `LICENSE:156` 起说明在遵守条件时授予的权利不可撤销；`:197` 起要求保留通知；
`:208` 起规定修改版本分发；`:463` 起禁止增加限制。历史已证实 GPLv3-or-later 的
上游代码，且本轮未取得上游权利人允许另外许可的文件。维护者自己的修改不能据此
把整个派生库改成“禁止商业使用”。[GNU 官方 FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#NoMilitary)
同样说明不能在 GPL 中另加禁止商业用途的限制。

个人以自己的资金回测及实盘交易、以及相应投资收益，不在本轮被改成需付费的用途。
GPL 已允许的商业使用也不被本轮缩减。第三方资源条件及实际分发义务仍需按内容和行为判断。

`ai-for-investor` 等项目与 GPL 引擎组合分发的具体义务没有在本核查中被解决。
不能因目录、进程或接口分离就断言享有豁免，需向律师提供实际交互与分发方案审查。

## 本轮交付与适用边界

1. `backtrader-metadata.patch`：只把 `setup.py:101` 的 MIT classifier 改为
   `License :: OSI Approved :: GNU General Public License v3 (GPLv3)`。
2. `LICENSE-SCOPE-DRAFT.md`：明确本仓库不纳入拟议非商用许可；GPL、历史权利、
   Matplotlib 例外及组合分发审查均保留，并预留链接到仓库的 `LICENSE-REVIEW.md`。
3. 本文件 `AUDIT.md` 与 `VALIDATION.json`：可审查证据与静态验证结果。

以上只是审阅材料和补丁，尚未应用到目标仓库。根 `LICENSE`、README、贡献说明、
业务文件及用户既有改动均保持原状。本任务没有 commit、push、发布或开 PR。

该元数据更正不创设新授权，不设置新非商用版本边界，也不追溯撤销旧版本授权。
历史 MIT classifier 可能被如何解释，不由本轮文本纠错自动决定；如出现相关权利主张，
需要律师结合实际发布内容处理。

## 验证与未运行项

验证结果由 `VALIDATION.json` 记录：Python AST 可解析、更正前后除唯一许可分类字符串
外 AST 完全一致；补丁仅改 `setup.py` 一行；`git apply --check --whitespace=error` 可应用；
对许可/文档/元数据路径的 `git diff --check` 通过；原仓库 `HEAD` 和初始状态保持一致。

没有运行 `setup.py`、包导入、构建、安装、交易、联网测试或业务回归测试。
本轮没有运行时逻辑变化；直接执行 `setup.py` 还会执行 `version.py`，因此采用 AST/文本
核查与补丁适用性检查。正式发行前仍需补上版权恢复审查和实际分发包检查。

正式法律文本与 GPL 组合分发判断建议由律师审阅；本报告不保证法律效力。
