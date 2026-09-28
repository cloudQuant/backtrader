# G6 CLAIMED 有效期 r4a 独立验收

**局部接受：**8 份冻结源码/测试逐字节匹配，进程内来源断言通过，独立 `100 passed / 0 skipped`。边界试验在原始 Store binding 过期前 100 微秒允许一次 fake Req；过期后 100 微秒拒绝调用，持久状态为 UNKNOWN / POISONED，未重复消耗 authority。两次可信时刻到近调用的墙钟间隔均小于 250 毫秒。

该结论只覆盖离线有界时差的 fake 调用。未证明真实 CTP、统一 wheel、外部原子账户排他或受保护部署。早先 r4 受污染日志不作为证据；`NO_WRITE / LIVE_NO_GO` 不变。

[机器记录](ctp-claimed-authority-r4a-expiry-independent-review-2026-09-27.json)与[原始归档](ctp-claimed-authority-r4a-expiry-independent-review-2026-09-27.raw.zip)包含冻结来源和独立 QA；归档 SHA-256 `4fd0d8ef28c1761d3e8609e17be18f6aa7febf4a20d338810fa49478781c6aa6`，共 18 项。
