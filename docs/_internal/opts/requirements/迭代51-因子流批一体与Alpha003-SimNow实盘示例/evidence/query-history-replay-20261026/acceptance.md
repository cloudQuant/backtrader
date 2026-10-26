# 默认查询历史续接与回放时钟（2026-10-26）

本轮在既有 dev、父提交 fab06cdbb4539c8b00e253a01834727004a3f9b6 接受 SOURCE/本地合成叶子组合；没有真实账户或 OS 进程重启验收。确切源码、运行命令及结果见[verification.json](verification.json)、[查询用例记录](query-qa.json)与[回放JUnit](replay-junit.xml)。

默认 ctp_query 每次续接都先建立当前 Store、完成登录/目录/深度查询，再校验旧 tape。新旧快照的采集时点、generation、原始顺序摘要可不同；规范化目录、policy、路由/授权、日历/grid语义、账户/策略/journal/风险身份必须相符。每条新决策绑定 header record ID，query历史必须有该绑定，并须匹配原 journal 行锚点；合法价格/风险更改后重算自摘要不能绕过校验。旧bundle无header绑定只保留兼容，未增加其证据强度。CommonMinuteGrid没有旧optional evidence_sha256属性，旧grid_sha256字段为None；当前query使用独立计算的grid_semantics_sha256，不把None相等当作证明。

受控应用停止返回 LIVE_EPOCH_SEQUENCE_STOPPED：本epoch正常清理、post-join及查询线程/Store关闭已证实，随后不创建下一epoch；自动日切仍要求严格STOPPED。历史只作预热，原格和信号不重复派发。

查询焦点在一次实际执行中通过（1 passed/4.87s，tool 9693b3），三epoch共40、48、28条决策，后两轮各20条历史再加28/8条live，持续使用同一journal和累计预算。用例同时覆盖新snapshot/generation、目录回调顺序及风险/header/行篡改反例。该次仅保存工具输出摘要，未保存原stdout或JUnit；记录明确此限制。后续修改限于回放时钟及其独立测试，query实现和fixture未再改，不为归档重跑此已通过用例。

最初四用例为2pass/2fail；控制停止修复后R2为2pass/1fail（测试错用不存在的grid摘要）；R3在第三正向续接180s外层超时。其公开tape已完成最后批次，静态核对发现测试用初始bundle连续分钟表的02:16等待实际query日历02:31的最后批次（跨10:15–10:30休市），因此永不请求停止。修复使用本epoch真实query计划，最后焦点通过；没有放宽生产deadline。历史原件留在记录的仓外目录，指纹保留，未改写成全绿。

另修复HEAD已有回放时钟缺陷：多次monotonic采样原先提前耗尽UTC分钟表，正常信号被SESSION_CLOSED拒绝。现在计时采样不推进UTC，UTC按当前已发布完整批次对齐对应计划时点，wait只在完成之后进入下一槽；不完整/旧批次与重复采样不跳槽，连续预取交付也保留逐槽报价可用时点。真实回放成交只在决策可用之后的后续bar发生，迟到quote拒绝、tape篡改和flat/nonflat winddown共5项Root QA通过（JUnit4.683s，进程5.234s），5份源码前后指纹一致，仅既有pytest配置warning。独立静态复核GO。

本轮不是性能优化；性能阈值按用户最新口径仅记录。仍待：历史预热期间既有挂单的真实prenext风险撤单组合、当前代码安装验证、实际目录/行情/账户与进程重启；AC51-21a等真实层级不升级。
