# tickbroker_5s_pair_arbitrage_gateway

本示例通过独立的账户级 Gateway 接收行情和提交订单。先启动并授权该 Gateway，再启动策略；不会在策略进程中创建 CTP 会话、Gateway 服务或读取 CTP 凭据。Gateway 不可用时不会回退到 direct。

## 配置与启动

1. 复制公开 `config.yaml`，将 `gateway_strategy` 中的身份、作用域、服务地址、合约和订阅配置为与已注册 Gateway 一致；示例身份和 localhost 端口仅是占位符，不能授予权限。多个策略各使用独立的已登记身份与本地状态目录。
2. 默认 `gateway_resource_provider: local_files` 使用内置加载器。`gateway_resource_files` 只配置 Gateway 公钥、策略公钥和策略私钥的文件路径；每个文件为一行 Z85 CURVE 密钥。文件必须属于当前用户；策略私钥权限不得允许组或其他用户访问，公钥文件不得允许组或其他用户写入。路径及父目录不能是符号链接，不接受不可信的可写目录。当前本地文件权限检查仅支持 POSIX；其他平台明确拒绝，需另行配置受信资源工厂。不要把密钥写入 YAML、命令参数或日志。也可选择受信安装的 `bt_api_py.gateway_example_resources` entry point，工厂签名为 `provider(config=parsed_gateway_config, strategy_dir=Path, first_init=bool)`，返回 `(GatewayPendingHost, security_profiles)`；配置引用本身不授予账户权限。
3. 离线检查：`conda run -n base python run.py --config config.yaml --dry-run`；只解析配置，不读取密钥、不连接网络，也不证明 Gateway 或账户可用。新策略先运行 `--first-init`：仅创建本地随机身份并停止，运营从本地 `state/identity.json` 查看 UUID，将它登记到 Gateway，并将公开配置中的 strategy_scope、strategy_ref 与 actor_ref 等身份设为一致；这一步不建立账户或交易授权。之后显式运行 `--upgrade-state`，在独占运行锁下将新的空白本地状态按已有版本逐步升级，然后停止；再正常运行。v1 升级还要求该示例 `--first-init` 创建的同 UUID 本地初始化标记；旧 direct 状态、缺标记或标记不匹配均拒绝。标记只防止误操作，不证明账户空仓、writer fence 或授权；如身份写入后标记创建前崩溃，应停止并由运营审查，不能手工伪造或清空状态。已有直连策略须按已批准的空仓迁移与对账流程处理。
4. `feed.gateway_clock_verification` 默认关闭；未配置可信 SNTP 来源时行情不可取得交易资格。需要按部署的受信时钟方案显式配置，例如 `servers`，并确保 Gateway 端也有有效校时及身份授权。配置本身不建立时钟、资金或交易权限。

`Ctrl+C`/SIGTERM 或 `--run-seconds` 使用原 Cerebro 停止路径；关闭策略不会停止独立 Gateway。Gateway 暂时不可达、恢复证据不足或授权失效时必须等待/拒绝，不能认为委托已经取消或重新提交。手工交易和其他策略持仓不属于本策略；具体对账按 Gateway 账户事实执行。

当前功能仍在开发验收中：策略资金/可平仓账本、真实 CTP 可信基线、部分订单类型和完整恢复尚未完成。示例中的占位配置、手续费参数或离线检查均不证明真实账户可交易。
