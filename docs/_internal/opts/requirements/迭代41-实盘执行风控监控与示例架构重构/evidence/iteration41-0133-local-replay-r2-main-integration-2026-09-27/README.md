# 013_3 本地回放 r2 主树集成验收

状态：`LOCAL_REPLAY_ONLY_ACCEPTED / NO_WRITE / LIVE_NO_GO`。这是合成本地回放的结构修复，不是 SimNow 登录、CTP 原生生命周期、报单/撤单或实盘验收。

## 输入与独立复核

- [作者 r2 冻结包](author-r2.zip) SHA-256 `EF6C629784077E016B1B6E8FFA34F3BD23ADB35C6184D68560A672B1F396A186`；[manifest](author-manifest.json) SHA-256 `14F75238DFAB2959DF32642017E52F9AB0E1D54C6B6E02BCC87FF47906A9642D`。87/87 payload、ZIP CRC 与逐文件字节核对通过。
- [独立 QA 收据](independent-qa-receipt.md) SHA-256 `250B2D5F2534659A63E7EBBAE830E9B090295A3340E5BA80219AE5D6639BAB08`；[QA 原始包](independent-qa.zip) SHA-256 `6C9FA09FC04F39848578A15F94744609B7B34FC9BA60E0AB59295111B58BB703`，42 成员 CRC/字节核对通过。独立结论为 `SAFE_TO_APPLY_LOCAL_REPLAY_ONLY`。旧版点分 `find_spec` 可能导入真实 SDK 父包，其未受保护的 2/2 日志保留但不计合格。
- [应用补丁](local-replay.patch) SHA-256 `B8DD2AE3B0BD108B4445E9D7B261515F0062DB678D6792364F4E22EF32034473`。应用前 `run.py` SHA-256 `16D6A184F1A57C0C2843511DD0BD7ADA4825D945402665BE1AAF8B624FC9576C`，测试文件 SHA-256 `146833DF60C0C847E5AC64C1F8239673E525F5C08DDA86453CF81B3B11327CD5`；精确校验后 `git -c core.autocrlf=false apply --check` 与 apply 成功，目标 SHA-256 分别为 `1C3D37A7485C05EC4EBB82BA1A66218B6B739063E04819D7B327BA4D8847B58E` 和 `00F9DB83E22735539920A7F033AB0A888906ECF61109C156513BCFE1D9C64678`。

## 主树结果

`run_replay` 现在显式组合 `ReplayClient`、`LocalReplayStore`、`BtApiFeed(provider="local_replay")` 与拒绝订单/继承撮合的 `LocalReplayBroker`。模块身份通过逐层 `PathFinder` 查找，不执行可选 SDK 父包初始化。`AGENTS.md` 已同步说明此结构。

| 测试 | 结果 | 原始证据 |
| --- | --- | --- |
| `tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py` | 28 passed，1 条既有 pytest 配置 warning | [JUnit](focused-main-junit.xml) · [stdout](focused-main-pytest.txt) |
| `tests/unit/stores tests/unit/runtime` | 2638 passed、43 skipped、2 xfailed、0 failed，1 条既有 warning；106.68 秒 | [JUnit](stores-runtime-main-junit.xml) · [stdout](stores-runtime-main-pytest.txt) |

完整 Store/Runtime 在应用前为 2636 passed、43 skipped、2 xfailed；本次增加两项测试，没有旧 nodeid 失败。独立受保护回放复现 7500 条合格行情、106 根完成 K 线、64 根收盘 K 线及零订单、交易、SDK 写入、provider/网络/继承撮合调用。独立 QA 未重跑历史 18 个输出文件的逐字节比较，因此该比较只保留作者历史记录，不提升为独立证明。

主树 `backtrader/stores/btapistore.py` SHA-256 仍为 `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`；AccountActorPort r2b/r2c 未合入，258 个旧用例阻断及默认 CTP/live 路由关闭状态不变。

## 本次主树原始文件 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `focused-main-junit.xml` | `D453401DE2D706D290B64379569647969AF5692E866CA178E80517CE7A3FFD95` |
| `focused-main-pytest.txt` | `110715AD00EF378EADE62170322EE3352ABDAE7A7162A6AC88B736F11EF402B2` |
| `stores-runtime-main-junit.xml` | `0253B19172A296C12AB9584D2F4DA9D051417B27D8B64E5B527128EDAD5A6B77` |
| `stores-runtime-main-pytest.txt` | `707ED0F6B74360349609635D3330911CA7FD0F8925F47BC7A30914D4E5D29F10` |
