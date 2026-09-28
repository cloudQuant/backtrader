# G1 R9 预启动服务与 reaper 拓扑（只读设计）

**状态：DESIGN ONLY；未实施；G1 仍关闭。** 本回执仅基于冻结 R8 证据和下面列出的主仓源码快照；未改仓库、默认 preflight、SCM 服务、私有配置、ACL、CTP/native/provider。

## 结论

R9 应将请求 caller 从进程创建和管道 I/O 中移出：固定 SCM guardian 必须先启动、完成信任检查、准备好 one-shot request slot，并发布 READY。caller 只向一个已存在的 client I/O broker 发布小型共享内存 mailbox 消息并获得 ticket；broker 持有预连接的 overlapped client pipe 及其 OVERLAPPED/event/buffer。服务侧 persistent reaper 持有 server pipe I/O、Job/PROCESS 控制句柄和创建时间。请求期间不启动 SCM、不开新 pipe、不调用同步 WriteFile、也不在 caller 栈调用 CreateProcess/Popen。

单个请求遵守一次性绝对 monotonic deadline D。D 到期时，ticket 永久转为 UNKNOWN；稍后到达的 frame/receipt 不能把它升级为成功。reaper 只有在自己观察到匹配的进程已 signaled、对应 Job 活跃数为零、I/O 最终完成/EOF、receipt 精确 readback 且这些都在 D 前时才可发布 observed。

R9 解决的是 R8 暴露的 caller-stack gaps 的拓扑设计，不是 G1 接受。若 reaper 自己卡在 TerminateJobObject、QueryInformationJobObject、CloseHandle 等同步调用，caller 可返回 UNKNOWN，但当前设计不能证明清理或允许复用该 slot；该缺口仍必须明确失败关闭。OS 不调度 caller/reaper 或内核调用永不返回也不被 Python deadline 变成硬实时保证。

## 证据与现状

R8 manifest SHA-256 为 f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb。R8 的正常 child-tree probe 证明在拿到控制句柄后，外部 supervisor 能终止树并观察 Job active=0 和已保留进程句柄 signaled；这不是 whole-command 证明。冻结 trial 的最终 P05 admission-sync 记录为 **1218 ms，D=1200 ms，caller_api_returned=false**。归档 R8_FINDINGS.md 中的 1234 ms 是较早一次；不要把它当最终值。R8 的 overlapped probe在 1016 ms 返回 UNKNOWN，但 OVERLAPPED、event、buffer 仍由 caller-process thread 持有至 CancelIoEx 后读取最终 995 completion；它不是 caller 死亡后仍存活的独立 reaper。

当前主仓服务代码仍是候选单请求路径：
- windows_guardian_service.py::_serve_one_readonly_os_request 在请求 deadline/inner watchdog 之前同步做 anchor/service 检查、创建请求 pipe，随后认证请求并调用两阶段执行；函数 docstring 明确说明这些同步调用不在独立 host watchdog 内。
- _run_readonly_two_stage_request 中 Job1 coordinator+worker 与 Job2 receipt writer 的顺序是正确方向：Job2 必须等 Job1 exit、empty、控制句柄释放后才启动；但该函数当前仍由 service request 路径直接调用。
- request_fixed_readonly_preflight 的 daemon exchange thread、worker-output channel 和现有 outer watchdog 不等价于跨 caller lifetime 的独立 I/O/control owner。
- WindowsJobBackend.create_suspended_in_job 是同步进程创建入口；它必须留在受 reaper 控制的进程中，不能放到 request caller 栈上。

主仓当前只读源码 SHA-256、长度与时间戳见 r9_manifest.json。它们是本设计读取时的来源标识，不是受保护部署证明。

## R9 进程拓扑

固定 SCM guardian/reaper 是常驻控制面，完全位于各请求 Job 之外。它持有 server-side IOCP/overlapped contexts、每个 slot 的 process/job handles、PID+创建时间以及状态机。client I/O broker 是调用应用生命周期内已预启动的独立进程；它持有已验证 server binding 和预连接 client pipe，调用者不持管道 I/O。broker 和 SCM service 都不能由一次请求自动启动或替换。

服务一次只准备一个 slot：
1. 在 READY 之前验证固定 source/runtime/dependency seals、SCM service 身份和 pipe peer；缺失 pin/身份/权限即拒绝。
2. 创建配置 Job1/Job2 与固定 internal channel；保留 reaper 自己的 Job 查询/终止句柄。
3. 以固定 command 创建 coordinator/admission slot，使用 atomic JOB_LIST 将它置于 Job1 后才 resume；保留准确的 process handle、PID、创建时间并验证 typed READY。
4. 建立 coordinator 与 reaper 的有界 internal channel；预先创建 writer-launch slot。writer-launch slot可等待请求，但实际 receipt-writer 只可在 reaper独立确认 Job1 已 empty 后创建/运行于 Job2。
5. 完成所有 listener、overlapped operation、句柄绑定和单次 slot 状态验证后才发布 READY。

任一步失败、返回不确定、deadline 已过或 cleanup handle 关闭失败都不能发布 READY。处理完一个请求后服务保持 NOT_READY，直到新的一次性 slot 重新完成上述准备。等待中的请求不排队；无 READY、pipe busy、slot poisoned 时快速拒绝。

请求 caller API 对外建议是异步 ticket：
- prepare 阶段（命令尚未接受）创建/认证 long-lived client broker，并预连接服务 endpoint。若它卡住或失败，没有 accepted request。
- submit 固定 operation 只做有界 mailbox slot reservation、受限 canonical frame copy、返回 ticket；不打开 pipe、不启动进程、不写管道。
- broker 使用 overlapped WriteFile/ReadFile，在 broker进程持有 client-side OVERLAPPED/event/buffer 至最终 completion。
- poll(ticket) 检查同一 D；D 到期即返回 UNKNOWN。不要用 WaitNamedPipe 无限等候，也不要让同步 request() wrapper 把 deadline描述成跨系统调度的硬实时返回。

Windows named-pipe client 在所有实例忙时，CreateFile 返回 ERROR_PIPE_BUSY，通常例程随后 WaitNamedPipe；R9 的 request submit 不得采用此循环。client broker 只在准备阶段连接；服务未 READY 时不接受操作。CreateFile/WriteFile 的内核调用本身永远不被假定有严格的墙钟上界。

## 句柄归属与请求流程

| 资源 | D 前 READY 状态的 owner | 请求中 owner | 释放规则 |
|---|---|---|---|
| client pipe + client OVERLAPPED/event/buffer | 预启动 client broker | 同一 broker | 只有最终 completion 被消费后可关闭/复用；CancelIoEx 只是请求 |
| server pipe + server OVERLAPPED/event/buffer | persistent reaper | 同一 reaper/IOCP | EOF/最终 completion后释放；否则 poison slot |
| Job1、Job2 handles | persistent reaper，Job query/terminate 权限 | reaper保留原句柄；child只获必要的restricted duplicate | 必须独立读取同一 Job、active=0；CloseHandle失败保留 custody |
| coordinator/launcher PROCESS handles | persistent reaper | reaper | signaled + 创建时PID/FILETIME一致后才可轮换 |
| owner token handle | 认证客户端 pipe 后的短命 admission/coordinator | 仅固定 coordinator | DuplicateHandle目标由精确 retained coordinator process handle绑定；不继承、不放 wire；transfer/close不明则杀 Job1并 poison |
| 各阶段 nonce/pipe | fixed source service/reaper | 对应单次 stage | 固定 schema、request_id、deadline、peer PID/创建时间均匹配；不接受迟到 frame |

请求流程：
1. caller在 monotonic clock上创建 request_id 和 D；broker mailbox 发布完全相同的 request_id/D。服务拒绝过期或超代码上限的 D，不给阶段重新计时。
2. coordinator 在 Job1 收到唯一固定 operation；捕获并验证 owner token，完成受审固定 session 策略，随后执行其固定 sealed bootstrap/worker。所有 worker 子进程必须在创建时原子入 Job1，禁止 create-then-assign。
3. coordinator frame 只给业务 observation，不证明 Job1 cleanup。reaper independently等待 coordinator process signaled，并从自己持有的 Job1 句柄等待/读取 active=0；要在 D 内完成。frame和Job状态跨 request_id/slot generation绑定。
4. 只有 reaper实测 Job1 empty后才给预启动 writer-launch slot发送一次 writer命令。它将 receipt writer 原子加入 Job2；writer执行固定 close/readback/CREATE_NEW/精确字节 readback，再发送固定 receipt frame。
5. reaper验证 writer process signaled、Job2 active=0、writer frame/EOF最终完成、receipt bytes 精确相同。只有 exit code 0 且所有证明在 D 前才可 observed。否则 UNKNOWN。
6. 若 D 到期，reaper请求终止并继续异步回收；caller ticket立即/到期返回 UNKNOWN。晚到的成功 frame/receipt仅供审计，不能提升原 ticket。无法确定是否 empty、handle释放、IO completion时slot保持 poisoned，服务不READY、不复用。

跨进程 DuplicateHandle handshake 至少含：one-shot nonce、request_id、target PID、进程创建时间、remote handle numeric value、期望 token facts。服务/子进程从真实 handle查询 SID、AuthenticationId/session 等；wire的数值/事实只能作为相关性检查，不能成为身份授权。任何 API调用或传输有歧义时关闭/终止整个 request Job，保持UNKNOWN。Windows Job要求成员进程同一 session，不能将 Session-0 coordinator 与交互 session worker塞进同一 Job；缺固定 session转换所需身份/权限时 fail closed。

## P02 / P03 / P07 / P14 负测清单

| 编号 | 故障注入位置 | 必须保留/由谁观察 | 断言 |
|---|---|---|---|
| P02 | 已在 Job1 的 sacrificial coordinator 中，CreateProcessAsUser调用前阻塞（无 child side effect） | reaper仍在Job外；它保留 coordinator PROCESS 和 Job1 handles | deadline后发 terminate；coordinator signaled、Job1 active=0才算cleanup；没有结果帧/Job2。若CreateProcess发生在唯一 reaper进程里，此测直接失败设计 |
| P03 | 同一 API先原子建出 suspended child并加入 Job1，然后在返回 PROCESS_INFORMATION 前卡住 | reaper保留 Job1；child永不在 Job外运行 | terminate Job1后active=0；coordinator signaled；迟到PID/frame不可接收。若子进程可能先运行再 AssignJob，直接拒绝 |
| P07 | broker/reaper对最大允许frame做OVERLAPPED操作；跨 D 保持pending，CancelIoEx返回成功但延迟最终完成；再杀普通caller但保留broker | 发起I/O的 broker/reaper进程自己持管道HANDLE、OVERLAPPED、event/IOCP key、buffer；对端只持自己的contexts | caller ticket在 D 为UNKNOWN；未消费最终completion前不得free、close或复用；broker存活时继续drain；broker死亡时服务看到disconnect后仍保留自身状态直到服务侧completion和Job清理证据 |
| P14 | TerminateJobObject挂起/false；或它成功但QueryInformationJobObject一直失败/active>0；或CloseHandle false | persistent reaper以外的client broker仍能到 D返回UNKNOWN；reaper保留所有 handles与poison状态 | 没有 Job-empty证明就不写成功receipt、不发观察成功、不再READY。若reaper自身不能运行，kill-on-close只是清理机制，不是观察证明；G1 remains closed |
| Late frame | coordinator或writer在 D 以后送一个格式正确的成功帧 | broker/reaper记录同一绝对 D和request id | 原ticket永久UNKNOWN，迟到frame不能upgrade |
| Not ready/restart | 阻塞服务anchor/source验证、slot prewarm或broker preconnect | 请求尚未accepted；固定服务仍无READY token | 快速拒绝/not-ready；不启动普通CLI、native或provider；无accepted command期限声称 |
| Poison/replay | 两次请求复用相同slot，或上一次completion/close未确认 | reaper保留slot generation、nonce、I/O context与Job handles | 第二个请求拒绝；旧事件/句柄不能交给新request_id；成功重启还需新process handles/create-time/nonce |

必须对真实 Windows overlapped pipe、PID/creation-time绑定、Job accounting、句柄继承、CreateProcess atomic JOB_LIST 做独立宿主验收。Fake API返回“job empty”或只从frame读“cleanup complete”不能通过这些测试。

## 最小实现边界与未解限制

1. 在 windows_guardian_service.py 增加独立 startup/READY 生命周期；原 one-shot函数保持关闭，不允许 caller触发 service start。其request callsite只做ticket/mailbox提交和poll。
2. 新增 windows_guardian_reaper.py：单服务实例、序列化 request slot、server IOCP/OVERLAPPED所有权、保留Job/process控制句柄、one absolute D状态机、final-completion/eof处理和poison状态。没有任意PID/path参数。
3. 新增 guardian_client_broker.py：应用生命周期预启动的 client-side channel owner。固定client binding/SCM PID验证、预连接pipe和OVERLAPPED custody、有限mailbox、token/request frame传输；不是每命令启动的subprocess。
4. 在 windows_job_backend.py 增加 startup-only slot prewarm API；所有请求子进程创建都必须由已包含在reaper控制Job的 sacrificial coordinator/launcher执行，并通过原子JOB_LIST在resume前进入正确Job。
5. 复用并只扩展 worker_output_channel.py 的固定通道/帧功能；source manifest/bootstrap只加精确路径和版本化slot/request binding schema，不增加动态导入或宽泛scripts白名单。生成bootstrap仍必须小于256KiB，否则拒绝构建。
6. 新增测试 test_ctp_i13_i15_windows_guardian_reaper.py 和 test_ctp_i13_i15_guardian_client_broker.py，扩展当前 service/backend tests。用fakes注入P02/P03/P07/P14，但另外对Windows真overlapped/Job/PID handle运行。默认CLI/preflight gate不改。

以下仍不由该方案自动解决，必须作为明确的拒绝条件：
- 进程外API（SCM启动/重启、服务部署、依赖runtime pin、protected ProgramData）未验收时没有READY。
- 如果 reaper 的TerminateJobObject、QueryInformationJobObject、Wait/GetOverlappedResult、DuplicateHandle、CloseHandle等在服务端无限不返回，caller仍只能UNKNOWN；必须有higher-level custodian能独立 kill/observe，或接受本功能始终closed。不得用一次终止请求、服务退出、kill-on-close配置冒充Job-empty。
- API线程不被操作系统调度时无法承诺按墙钟时间执行poll返回；票据deadline是可判定的application deadline。
- session 0 token变更、SeTcb、CreateProcessAsUser权限/真实服务SID、基础CPython启动闭包、程序路径ACL/签名、真实生产配置/CTP均是外部部署与安全验收前置条件。本设计和inert tests不证明这些条件成立。

## Microsoft API依据

- Named pipe client开启 overlapped需要FILE_FLAG_OVERLAPPED；所有实例忙时CreateFile返回ERROR_PIPE_BUSY，示例会调用WaitNamedPipe；R9将连接准备移到D之前，request submit不等待busy实例：[Named Pipe Client](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-client).
- AssignProcessToJobObject明确同一Job中的进程必须同session；R9以固定Session0策略保证Job1/Job2内成员一致并拒绝未满足身份/权限：[AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject).
- QueryInformationJobObject返回Job当前状态；证据必须来自reaper retained Job handle，而不是角色frame：[QueryInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject).
- CreateProcessW仅在成功返回后提供PROCESS_INFORMATION，且返回不表示子进程已完成初始化；该调用不能留在request caller stack：[CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).
- 异步I/O仍需由发起方保留OVERLAPPED关联资源，直到最终completion处理；CancelIoEx不等于completion：[Synchronous and Asynchronous I/O](https://learn.microsoft.com/en-us/windows/win32/fileio/synchronous-and-asynchronous-i-o).

## 源快照与决策

主仓只读文件、SHA-256、字节数和读取时间见 r9_manifest.json。R8事实源为该目录下 r8_manifest.json、r8_receipt.json、r8_trials.json、R8_FINDINGS.md。当前状态建议：**可按该拓扑建立隔离R9 candidate；当前default/SCM/真实CTP route仍NOT READY；本设计不构成G1接受。**
