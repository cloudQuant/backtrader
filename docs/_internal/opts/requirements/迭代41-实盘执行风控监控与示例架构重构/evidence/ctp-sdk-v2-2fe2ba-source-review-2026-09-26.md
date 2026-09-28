# CTP SDK V2 原生字段源码复验（2026-09-26）

## 范围与修改

SDK 已保存为本地干净提交 **`2fe2ba9d78bab6477aa4e232795aad35a14f2313`**，
tree `4d87dc1feb2aa1c38383ddce061c11bd6640f6b1`。相对历史 `f90568c` 仅修改
`client.py` 和对应入口测试；没有 push、wheel 构建、默认 pin 变化或真实会话。

V2 绑定同时核对逻辑请求和原生请求的 canonical JSON/hash。SUBMIT 两者必须相同；
CANCEL 的原生请求只能比逻辑请求多 Store 分配的精确正 int32 `OrderActionRef`，
逻辑请求不得携带该字段。`RequestID` 是独立绑定字段；请求体可省略它，也可携带
与该绑定精确相等的整数。它不能由 ActionRef 推导，也不要求两者相等。

独立 QA 曾复现 caller field 的 ActionRef `444` 被静默覆盖为 Store 的 `91`。
修复后，SDK 先逐字段读取并核对 caller 的完整原生 payload 和所需 RequestID，
再构造独立字段对象，最后复核所有 setter/getter 结果。冲突值、0、字符串、bool、
缺失 getter、RequestID 不符和 setter 改值均拒绝；正例分别传递 ActionRef `91`、
RequestID `53`。精确 int 检查是 SDK 的保守合同，不声称等同于 SWIG 的全部接受类型。

## 验证与来源更正

- 作者与独立 QA 均通过 **44 项 V2 焦点测试**。
- 独立 QA 使用正确的父仓根路径，14 文件并集 **472 passed、2 warnings、62.54s**。
  其结果为直接工具输出，保存了审阅收据，未生成独立 JUnit/原始日志。
- 作者原 472 项运行错误地将父仓的 `bt_api_py` 子目录放入 PYTHONPATH，可能加载
  旧工作区的父包。原 JUnit/日志保留，manifest 已追加来源更正；不得用这份原记录
  证明指定父包的 normalizer 来源。
- 作者随后以正确父仓根路径运行受影响的单个 normalizer 用例：**1 passed**；
  同一进程先断言父包、normalizer、contract models 的实际 `__file__` 均属于指定根。
- Ruff、py_compile、diff-check 通过。两条环境 warning 是 pytest 已有未知配置项，
  以及本机 CPython 3.11 没有匹配 `_ctp` 扩展而使用不可用扩展 fallback。

这些都是 fake/source 验证。父仓还存在三项按 hash 冻结的 V2 修改和其他脏子模块，
不是干净父包或安装 wheel 验收；也没有真实 SWIG/native 行为、原生关闭或 provider 证据。

| 文件 | SHA-256 |
| --- | --- |
| SDK `src/bt_api_ctp/ctp/client.py` | `a80d060577c210c5faafc57e72b5f2435d6e7b25f6b4fad7eb5797827abe6bd6` |
| SDK `tests/test_ctp_callback_ingress_client.py` | `82de7c2539edfa7e7c6f2a84dc821d09fe8f7d2927638ea4ed18507d081313ce` |

## 材料与后续门

[JSON 与逐文件 hash 清单](ctp-sdk-v2-2fe2ba-source-review-2026-09-26.json)的 SHA-256 为
`1f1ae845cdbc494fab8005b83474b51ef09dc44f86049182d580e6670e3b6cbb`。
另存有[独立审阅收据](ctp-sdk-v2-2fe2ba-source-review-2026-09-26-independent.txt)、
[作者来源更正](ctp-sdk-v2-2fe2ba-source-review-2026-09-26-author-manifest.txt)、
[原作者 JUnit](ctp-sdk-v2-2fe2ba-source-review-2026-09-26-author.junit.xml)及
[正确来源的单节点 JUnit](ctp-sdk-v2-2fe2ba-source-review-2026-09-26-parent-node.junit.xml)。

执行 Store 的同对象一次性 binding issuer、事务 readback 和主仓的
`self._adapter.verify_native_call` 是代码实现的本地验证链。上游逐动作
`CtpDispatchAuthorityVerifier` 仍是注入协议，实际 approval/key/source 与账户级外部
writer fence 没有部署；本次字段校验不提供这些权限。V17 迁移、完整两次报单加撤单
组合、统一可复现制品及 G1–G8 仍需分别验收，默认写入与 live 状态未改变。
