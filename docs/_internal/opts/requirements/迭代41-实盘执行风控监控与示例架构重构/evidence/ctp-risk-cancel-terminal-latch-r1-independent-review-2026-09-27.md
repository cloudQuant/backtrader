# 撤单风险 latch 终态解除：局部独立验收

冻结风险包的四份改动源码/测试哈希匹配。根代理在精确源码路径复跑 `72 passed / 0 failed`（一条现有 pytest 配置警告）；作者全包 `222 passed`。typed cancel-specific proof 仅在 CANCELLED 且目标终态、或 REJECTED 且目标仍有确定敞口时解除对应撤单 latch，并保留独立订单敞口；通用订单 `CANCELED_NO_FILL` proof 不能解除 CANCEL permit。

本证据只接受 fake authority 的风险账本合同。parent 专用 issuer、Execution 原子 terminal event 读回、主仓接线及真实 provider 仍未完成，不能据此释放生产风险占用或开放写路由。

[机器记录](ctp-risk-cancel-terminal-latch-r1-independent-review-2026-09-27.json)与[原始归档](ctp-risk-cancel-terminal-latch-r1-independent-review-2026-09-27.raw.zip) SHA-256 `03b0127bbd32c6c6605d10382756679ce73f8742f9fc60ef0915aeee8d0dcc74`，8 项。
