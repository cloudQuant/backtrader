# 本机 CTP 配置来源核查（2026-09-24；生成前历史快照）

> **历史状态提示：** 本核查记录早于私有 SimNow 配置生成和 shared canonical `ctp:` migration。文中“runtime 配置不存在”、当时的 `.env` 缺字段结论以及独立 `runtime-production/config.yaml` 的说法均是采集时点事实，不能当作当前状态或目标 operator flow。当前唯一目标路径是 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`；SimNow 与未来 production 复用同一文件及 `ctp:` 字段形状。单文件 schema/mode 迁移已实现，但 production runner/write admission 尚未实现或验收。

本记录只列字段名、公开前置地址和准入结论，不包含账户、密码、认证码或其哈希。用户要求由已有 `.env` / `config.yaml` 准备必需的 schema-v4 `config.yaml`，并由其中的 `md_front`、`td_front` 直接决定连接目标；运行时不得按时间、set 名称或连接失败切换地址。

| 显式候选来源 | 已有字段 | 对私有 SimNow runtime 的缺口 |
| --- | --- | --- |
| `examples/013_3_sa_midfreq_simnow/.env` | 五个认证字段名，其中 `CTP_USER_ID`、`CTP_PASSWORD` 的值为空 | 缺少成对前置、具体合约、交易所、HedgeFlag，以及非空用户 ID 和密码。原 Windows ACL 曾继承普通用户读取权限；本次已将该文件改为当前用户、SYSTEM、Administrators 可访问的受保护 ACL，未改动文件内容。 |
| `examples/013_3_sa_midfreq_simnow/config.yaml`（旧迭代 22 策略参数） | 三组成对 SimNow 前置、`exchange=CZCE` | `instrument: null`，且三对地址均在文件中；不能据此确定用户想连接的一对。它不是迭代 41 runtime 配置。 |
| `D:/bt_api_py/ctp_data/collector.yaml` | 一对前置和非空连接/认证字段；BrokerID 与官方 SimNow 默认值一致 | 缺少具体合约、交易所、HedgeFlag；前置为 `182.254.243.31:30001/30011`，不在当前受审 SimNow 地址对中；Windows ACL 也不满足私有来源门禁。BrokerID 相同不足以证明账户和地址归属。 |
| `examples/014_1_ctp_options_lowfreq/.env` 与 `examples/015_ctp_options_highfreq/.env` | 部分认证字段名，密码均为空；015 的用户 ID 也为空 | 均不是独立完整的前置、账户、合约、交易所、HedgeFlag 配置；不能据此推出可运行的实盘策略。 |

[SimNow 官方产品与服务页](https://www.simnow.com.cn/product.action)的可索引内容列出第一组 TD/MD `180.168.146.187:10201/10211`、第二组 `10202/10212`、7×24 环境 `10130/10131`。本次直接打开该页面返回 403，故这些公开地址仍需在实际只读会话中验证可用性；上述 SDK collector 文件中的 `182.254.243.31` 不能仅凭文件名认定为该官方 SimNow 环境，亦不能悄悄加入代码允许清单。

采集时，`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 和 `examples/007_ctp/runtime-production/config.yaml` 均不存在；两处均有精确 `/config.yaml` Git 忽略规则。对受保护的 013_3 `.env` 运行离线准备命令后，工具只报告缺少的字段名并保持目标不存在。现有来源当时既不能无歧义地选出用户要求的单一前置地址对，也没有已确认的当前合约及同源非空账号/密码。将旧 `instrument: null` 或模板占位符写入目标只会制造无效配置。该段关于生产独立字段来源只记录当时资料缺口；目标 workflow 现改为未来在同一 `config.yaml` 替换 mode/preset 与 CTP 参数，不创建第二份生产 operator config。

2026-09-24 补验（仍属生成前历史快照）：`prepare-ctp-simnow-config --source-collector-yaml D:\bt_api_py\ctp_data\collector.yaml` 已能按固定映射识别 collector 格式，但实际文件在读取前因 `private_source_acl_unsafe` 被拒，目标仍不存在；即使 ACL 合格，也仍需第二个显式来源给出合约、交易所、HedgeFlag，并且其原有前置地址与当时受审地址对不符。`prepare-ctp-production-config` 当时已有 production 专用 `.env`/YAML 离线准备入口；该入口现为 legacy/deferred，不是当前 shared-config workflow，也不表示有生产资料或运行/交易准入。本机没有完整生产来源，因此未调用其文件创建路径处理任何真实账号。

该历史快照当时建议下一步由使用者补齐非秘密字段并明确 TD/MD pair；该建议已由后续受保护配置准备和 shared canonical `ctp:` migration supersede。配置生成本身仍不登记运行路由、不证明 SDK 制品或账号验收、不允许报撤单。
