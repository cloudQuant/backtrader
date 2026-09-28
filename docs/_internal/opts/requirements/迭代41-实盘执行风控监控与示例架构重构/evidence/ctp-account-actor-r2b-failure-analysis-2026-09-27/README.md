# r2b 主树失败分组：只读审计

输入为 [主树补丁版 JUnit](../ctp-account-actor-r2b-main-integration-2026-09-27/patched-main-junit.xml)（SHA-256 `6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE`）。本目录是两份独立只读分析的逐字节副本；没有复跑测试、改变生产代码、读取私有配置或触发 provider。

- [Iteration22 的 200 项报告](iteration22-200-report.md)：200/200 都在 CTP Store 构造门失败；65 项显式 `ctp_gateway`，135 项 `btapi` 加 CTP selector；158 项查询/预检/结算等证据、38 项授权/恢复/生命周期、4 项 typed 报撤单。没有普通非 CTP 失败。[逐例 JSON](iteration22-200-analysis-summary.json)和[JUnit 摘录](iteration22-200-summary.txt)保留原始分组。
- [其余 58 项报告](remaining-58-root-cause-report.md)：49 项 CTP 构造门、6 项模糊 route、3 项 unsupported provider 提前拒绝。6 项中 5 项通用 route 测试缺明示选择，1 项注入的 SDK 对象内藏 CTP 配置。013_3 离线回放仍用 `BtApiStore(provider="ctp")` 包装本地 ReplayClient，需本地专用组合，不能豁免真实 CTP 门。
- [Store 可达入口审计](STORE-ENTRY-PATH-AUDIT.md)：除报撤单，还检查 `autostart/start`、首个 getter、`_ensure_api_ready`、结算/恢复控制、SDK 原对象属性、gateway wrapper 与队列派发；只在 submit/cancel 拒绝不能证明零 CTP 会话或零派发。该报告是源码静态审查，未执行对抗探针。

两份报告只解释失败根因，不授权 Actor、CTP 直达写入或生产运行。下次候选须用主树完整 Store/Runtime、受影响 integration 与独立负测重新裁决，不得 skip/xfail 或删除旧用例。

| 文件 | SHA-256 |
| --- | --- |
| `iteration22-200-report.md` | `90581DC8D9965FC529B6898459C6B8DA36A8A9091C6BAD3CE6C6CB1D978AF9B0` |
| `iteration22-200-analysis-summary.json` | `EE60B8A12C5C76035EF7A4A649F50261D17A7B68FF60A3668C28C49528EEB9D0` |
| `iteration22-200-summary.txt` | `7EDDEAEB6B989C92B56526EF59E1DA6C328A6D99FD39D2C0F50D769ED2B60933` |
| `remaining-58-root-cause-report.md` | `AF9542FF96C5FE95012A3F10C5AD345666333D36D5B17D5806A578A236ED1A99` |
| `STORE-ENTRY-PATH-AUDIT.md` | `87A36D1A0D3F06DB4B2D8C3C0DBFA95B4338C3F02D8F3D62A1CF8C3006591F99` |
