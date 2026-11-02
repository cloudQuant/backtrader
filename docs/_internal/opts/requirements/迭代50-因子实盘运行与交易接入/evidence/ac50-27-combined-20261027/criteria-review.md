# I50 AC50-27 独立 criteria review

**结论：GO — AC50-27 指定的功能长流可在用户的纯性能豁免下通过。** 四份原始 `result.json` 和对应 `completion.json` 仍原样为 `status=FAIL`、exit code 3；其 `gate_failures` 只有被豁免的100/500 ms p99/max延迟项。本结论是 AC50-27 的合成 COMPOSITION 长流判定，不表示 AC50-01..27 全部完成、50-B/迭代50完成或真实账户/服务验收。

## 原条款与边界

[验收方案.md](../docs/_internal/opts/requirements/迭代50-因子实盘运行与交易接入/验收方案.md) 的 AC50-27 行规定：27a为20资产、单Alpha003、native/build各至少100,000格；27b为20资产、六个代表因子、native/build各至少100,000格，并完成至少2小时本机墙钟及故障/idle覆盖；两者均检查正确性、数据完整、有界内存和正常资源关闭。四份报告的synthetic-source-utc bar-close→available freshness各采样100,000次，最大0 ms、p99上界0.1 ms；这只支持合成源合同，不是实际provider freshness证据。[迭代计划.md](../docs/_internal/opts/requirements/迭代50-因子实盘运行与交易接入/迭代计划.md) 第183、185行与验收方案第5节明确，纯p99/max超标不阻塞AC50-27功能判定；27b两小时、数值/缺格/数据安全、正常关闭、有界内存及新鲜度/安全deadline仍是要求。

原AC50-27 profile没有要求全101长时流、全组重建或磁盘写失败注入。50-B整体交付另要求全101和多因子长稳；group rebuild在AC50-09/11，disk/persistent-write failure在AC50-25。未测这些场景不阻塞本AC50-27子项，但也不能据此宣称相应AC或整个50-B完成。运行报告中的`backbroker_order_lifecycle_journaled_by_noop_decision=false`不是原AC50-27门槛；原条款要求的是bounded order event，27b实际覆盖了idle撤单。两模式逐格输出dump未直接互比，下面的结论基于每个mode分别通过同类独立scalar oracle，并不声称bitwise逐格相等。

## 四份原始结果

- **27a native**：20目标、factor id 3、100,000评估格+64预热；2,000,000次oracle比较，有限输出2,000,000，无unavailable、rank/correlation或reason错误；source gap为0，返回2,001,280条成员事件；RSS窗口增长1,036,288 B，界限33,554,432 B；Store close、journal关闭、checkpoint、reopen及readback通过。唯一原始失败为`durable_decision_max_latency_exceeded_500ms`（p99 93.1 ms，max 1,985 ms）。`result.json` SHA-256 `e93946e48a46e3d5b961a2ac68a2acabbb86b0457917d66ccb1c7aeca55a8916`。
- **27a build**：同为20目标、Alpha003、100,000格+64预热；同一2,000,000次oracle和零输出/reason/gap错误；RSS增长1,206,272 B/33,554,432 B；Store/journal关闭及重开回读通过。唯一原始失败同为max latency（p99 94.1 ms，max 1,766 ms）。SHA-256 `ef915ad4c77c4c39d5fffb105006b956a9637718b2ef87f4ee59ddf79fd23c5e`。
- **27b native**：20目标、因子1/3/6/48/56/101各100,000格，12,000,000次oracle比较；有限输出12,000,000，无unavailable/reason/source-gap错误；elapsed 11,818.141 s，`duration_seconds_met=true`，超过7,200 s下限。same-generation断线/恢复在grid 50,316原位续接，断线时无feed/strategy/factor推进，barrier观察成功且未超时。BackBroker完成一次submit及一次idle期间cancel，状态Submitted/Accepted/Canceled，无成交/持仓。RSS窗口增长-32,829,440 B/33,554,432 B；Store/journal关闭、checkpoint、reopen/readback通过。唯一原始失败为p99/max（281.1/1,828 ms）。SHA-256 `e5e7d78adc75b71213568b94ee2507d0d0c100bb6d63c201bfe4a1b1142e1c4c`。
- **27b build**：同为20目标、六因子及12,000,000次oracle；零unavailable/reason/source-gap错误；elapsed 9,150.843 s，`duration_seconds_met=true`。same-generation断线/恢复原位续接且无断线推进；BackBroker一次submit、一次idle cancel，未成交；RSS增长2,134,016 B/33,554,432 B；Store/journal关闭、checkpoint、reopen/readback通过。唯一原始失败为p99/max（156.1/2,156 ms）。SHA-256 `93cd29640a6169a830eea6ea45bc71655ec7828d92096987eb0ce79b6a0d0cbd`。

两次27b结果均报告`failure_recovery_path_exercised=true`、`idle_order_event_path_exercised=true`、`ordinary_broker_lifecycle_exercised=true`，source gap为0、cohort未冻结；共返回2,006,320条成员事件，20路feed均到最终slot 100315、cohort next slot为100316且无未决gap。两模式均有100,000条journal记录、WAL/FULL durability、正常关闭及重开回读。其 `profile.soak_fault_idle_order_coverage_complete=false`、`ac50_27b_ready=false`、`formal_acceptance_claimed=false` 等聚合/运行器自报字段保持不变；逐项实测coverage字段为真，原AC未要求运行器自行宣告正式通过，故这些字段不替代审查者的双mode裁定。物理磁盘配额未强制、磁盘写失败未注入；不作磁盘故障覆盖声明。

## 来源一致性与裁定依据

四次运行的benchmark脚本SHA-256均为`75ca8866f6adb7fb8fc2dd361107d7749170d2cb453ba4cff4754a334567c2db`。27a两模式input-generation SHA-256相同（`e5825a532fbcc32191b64a6bfd4c68cdbb4fff1cf494a0ff6ecc155770badbd8`），31个实际加载Backtrader模块的pre-run pin逐项完全相同且各自pre/post相同。27a native的revision标签为`718ca1dc644321b316c761d361a04497fc2719af`、build为`a69a494e7b26251703c130c2b9083f9ce196ef2c`；标签不同，但实测模块pin集合一致。27b两模式input-generation SHA-256均为`c066ca821f2ecd79616fa3b649f392b2f7050c9cfd6ead3fa6524e8ef54a4b0c`，36个模块pin逐项相同且pre/post一致；build的record亦核对`same_runner=true`、`same_input_generator=true`、`same_36_module_pre_pins=true`。

先前native/build单mode的`acceptance`/`adjudication`是各自范围内的冻结裁定，不是双mode跨报告AC50-27最终裁定。本文件依据原AC50-27行对四份结果作跨报告判定；不修改或覆写单mode记录、raw status、gate failures或exit code。证据级别均为`COMPOSITION_SYNTHETIC_SOURCE_STREAM_ONLY`；RSS是基准进程采样，不代表进程树峰值，也可能漏过采样间瞬态峰值。

规范文件SHA-256：`验收方案.md` `16848ee8771a95ab16d627c794c8b29196ea50b330f605ad675332e7a43d95cb`；`迭代计划.md` `5acf19c83d9a9741165a49b7fb1a7e667ea97de5df42cad23c290b4720b272cf`。相关现有裁定pins：27b native `adjudication.json` `34dd87f51f3db84410250ae5200bea438af1b1dff28168b468c63d425774558a`；27b build `adjudication.json` `fc11d6ade4aaa8758b55686987267e9bd1e34f9c3794ba8088375c435cf85d8d`，`record.json` `3174c263a2dac2524bce92c31921fb4ef5adb7b5fb6d1c9629cf1196ed7ef361`。四份`completion.json`均为`result_exists=true`/exit 3；其SHA-256依次为`43f96001a6d433615514a12a52a011a9da51a912ad540537c281a2a05f62bb15`、`bf1761131f8fdc7aaee7ad170c40842e9fbbeea915853dd81bc72140b1a57f3a`、`8c085a9dc768e28da51bb0ec38612d8e05601516e576179e6915175b48486597`、`5b9a446baf8f2c3664e6ccee6a4e1233da2a70b6ed607b0cb90d0458500a94c7`。