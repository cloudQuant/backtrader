# R8 Windows separate-process custodian/reaper — reviewer checklist

**用途：** R8 候选的只读验收清单；不是实现批准或 G1 通过结论。检查目标是“请求在绝对截止内只能得到有证据的终态；否则 UNKNOWN，同时仍有进程负责保留/回收未完成资源”。R8 需要逐项运行下列负测并保存 OS 事实、时间戳和句柄所有者。R7/R7t 的失败不得由测试结束后的 teardown 覆盖。

## 冻结基线与已知反例

| 输入 | SHA-256 | 用途 |
|---|---|---|
| R7 r7_manifest.json | afdc99be96a1ad4961235e358f9069070a5bafe2d051db9f59e2ff94fc8f9d7d | 原冻结试验清单；独立 QA 归档核对 14 项 0 mismatch |
| R7 r7_scenarios.json | d95f9e73009e9ae7d52f97a572c559b5ee32c65a7d8106dda4913fa5fbff5317 | admission-sync 超过 1.8 秒仍阻塞；overlapped 返回时 cancel_completed=0 |
| R7 独立 QA R7-QA.md | d9e547de5920c4fca3e55f4b3e83da6ad518d6bfd048d030b00fdf07e0718d5e | 独立重放和限制记录 |
| R7t r7t_manifest.json | 8a46c8e16a0fa68f0229dbE995e6f34da60a2ef7ea7441655131a10c7409abde | teardown 延续版冻结清单 |
| R7t r7_scenarios.json | 1d27c9d47f3e56a45a5ec8afba811ebcb58d68d4cd8eb88aed206c7b99f7ada0 | UNKNOWN 快照后才清理；清理结果未升级原结果 |

R7/R7t 都是 rejected / G1 closed。它们证明已建成的惰性 worker Job 能杀死 worker 与两层后代；没有证明 setup 同步调用可中断。R7 的调用者和“外部监督器”仍是同一 native harness；外围 Python watchdog 没有 Job handle。R7t 的 CancelIoEx 后 250ms 等待仍报告 cancel_completed=0，并继续关闭本地 event；该路径不是可复用 I/O reaper 证据。R7t teardown 在记录 UNKNOWN 后可以把 worker 清理掉，但不回写原调用结果。

## 进程与句柄归属（R8 必须在日志中实证）

角色名只用于描述候选：caller 是请求方；reaper 是在 caller 截止期间仍存活、拥有终止能力的独立进程；custodian 是处理这一个请求的子进程；worker/后代属于受监督 Job。候选可用不同名字，但必须给出等价的进程树和句柄归属。

| 对象/状态 | 必须由哪个仍存活进程持有 | 放弃/关闭条件 |
|---|---|---|
| 请求 Job HANDLE（reaper 持 JOB_OBJECT_QUERY、JOB_OBJECT_TERMINATE、SYNCHRONIZE；需要启动子进程的一方另持最小 JOB_OBJECT_ASSIGN_PROCESS 权限） | caller 截止期间的独立 reaper。不能只有 custodian/worker 自己持有；不把唯一 handle 放进可能阻塞/被杀的线程。 | 只在本请求的进程退出、Job ActiveProcesses=0、所有需记录的退出事实和本地 pending I/O 均已收敛后关闭。不能在 TerminateJobObject 成功返回后立即关。若证据缺失，保留 handle/请求槽并隔离下一请求。 |
| custodian PROCESS HANDLE | 独立 reaper；来自已创建并受 Job 约束的该精确进程，不凭 PID 重新打开后替代。 | WaitForSingleObject=WAIT_OBJECT_0 且 GetExitCodeProcess != STILL_ACTIVE 后才能记录退出。WAIT_TIMEOUT/WAIT_FAILED/查询失败都为 UNKNOWN。 |
| worker PROCESS/THREAD HANDLE（若结果需要其 exit code 或控制） | 创造它的一方，或通过受限 DuplicateHandle 明确交给 reaper；日志证明该 handle 对应的 PID/创建身份，不能只传 PID。 | process handle signaled 并抓取 exit code；thread handle 在确认无需 Resume/控制后释放。不能因协调者发来“worker exited”文字而代替独立 handle/job 事实。 |
| 每端的 pipe HANDLE、每个未完成 OVERLAPPED、事件、缓冲区、IOCP completion key/context | 发起该 overlapped 操作的那个进程。OVERLAPPED 不是跨进程句柄；发起端必须保留结构、event、缓冲区和 file/pipe handle，直到 completion 被观察。 | completion 已被对应 event/IOCP/GetOverlappedResult 消费后才能复用/释放。另一进程的超时、进程退出或 CancelIoEx 返回值不能直接释放本端对象。 |
| caller 的 request/reply I/O context | caller 中独立于业务等待栈的持久 request object/reaper；若 caller 退出，则 caller 只能报告 UNKNOWN，不能声称服务端收尾。 | 仅在 caller 端 I/O completion 被消费后释放。调用者超时但取消仍 pending 时，保留 context；不得栈上 OVERLAPPED 返回后继续让内核引用。 |
| Job completion / reaper 队列事件 | reaper；completion key 要绑定本次 request/job generation，不能用旧请求通知推进新请求。 | 只在处理完本 Job 的退出/active-zero 通知且最终 query 核验后撤销关联。 |

**独立 reaper 定义：**在请求 deadline 内，reaper 不执行可能被注入阻塞的 CreateProcess、ResumeThread、pipe connect/read/write 或应用回调；它持有已建立 Job/进程句柄并只做有界观察、取消、TerminateJobObject、等待与再次查询。若 reaper 本身会在这些 Win32 调用上卡住，必须再有存活的更高层 custodian 持有其 Job/PROCESS handles；否则本轮返回 UNKNOWN 且架构不能声称覆盖整个命令。R7/R7t 没有证明最高层 custodian 的启动/建 Job 调用有硬截止。

## Job-empty 允许写入的严格谓词

job_empty_proven=true 只能由 reaper 根据它持有的本次确切 Job handle 独立计算，且全部条件须在同一绝对 request deadline D 前成立：

1. Job creation/init 的事实与本 request ID 绑定；该 Job 启用 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE，不启用 breakaway/silent-breakaway；被控进程的子进程创建路径不绕开该 Job。创建时使用原子 Job-list assignment 或等价可证明“执行前已入 Job”的路径；不能 CreateProcess 后再 AssignProcessToJobObject 作为唯一包含保证。
2. 需要终止时，对正确 Job 的 TerminateJobObject 请求已返回成功。这个成功只表示终止请求已发出，不代表成员退出。
3. 精确 custodian/launcher process handle 已 signaled；退出码已读取且不是 STILL_ACTIVE。若 R8 还要报告 worker 的业务结果，worker 的进程退出码必须来自该 worker 的 retained process handle 或受信、正确关联的 Job exit completion，不得来自子进程自报。
4. 在上述退出事实后，用仍有效的 Job handle 查询 JobObjectBasicAccountingInformation.ActiveProcesses 得到 0；查询错误、非零或截止到达均不通过。若实现依赖 JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO，仍应以本 Job 的 query/关联证据确认，不能接受其他 Job、旧 request 或未排空 completion port 的通知。
5. 没有受监督树外的线程/进程在结果形成后仍有权限把新成员加入同一 Job。reaper 要把终结与 admission fence 线性化；若仍有 assignment-capable coordinator，它必须仍属于同一个受监督 Job，且不能在 query=0 后继续派生/加入成员。避免“查询 0 后仍有代码创建/加入成员”。
6. 结果帧、frame EOF、取消完成（若存在）以及句柄释放失败状态单独核验。某 stage 的 Job-empty 不替代另一 stage 的 Job-empty。不得在 caller deadline 之后补报 SUCCESS/OBSERVED；晚到的清理事实可进入只读审计，但原 request 仍为 UNKNOWN。

缺任一项：job_empty_proven=false, command result=UNKNOWN; Job/process/IO contexts 留在 reaper custody。TerminateJobObject 成功、kill-on-close 已配置、父进程声称已清理、一个瞬时 query false 之后未来变成 0，均不能单独证明。

## 可执行负测清单

每项使用唯一 request ID 与绝对单调截止 D。记录 accepted_at_ns, D, 所有 API enter/return 与 deadline decision 的 monotonic_ns, PID/creation time, Job identity/active count, process wait/exit code, pending I/O state。测试日志不得只保留子进程自报 JSON。每项同时断言 response_written_before_D 和 late_response_suppressed。至少有一个正常正控：clean frame + EOF、custodian exit 0、Job 空，且结果在 D 前写回。

| ID | 注入方式 / 具体步骤 | 必须观测与断言 |
|---|---|---|
| R8-P01 未就绪时请求 | 在 READY barrier 前延迟固定 custodian/Job 建立，deadline 从 caller 发起请求时开始。发请求但不放开 READY，越过 D。 | 不接受 request、不启动 worker、不返回“已验证”；caller 在 D 内得到 UNKNOWN/未就绪。若 server 在 D 后给成功或把 startup 时间排除又称整条硬截止，FAIL。服务可在未 READY 时拒绝 admission，但不能把它记录为已接受命令。 |
| R8-P02 CreateProcessW 卡在调用前 | 在独立 custodian 的进程创建 API wrapper 进入后阻塞，尚未创建子进程/尚无 PROCESS_INFORMATION。由已存活 reaper 在 D 前终止 request Job/custodian。 | reaper 手里必须已有可终止 Job 和 custodian process handle。调用线程退出且 Job query=0 才能说 containment proven；否则 caller UNKNOWN、handles retained。若卡住的进程正是唯一 reaper，case 必须判架构 FAIL（没有独立控制者），不能靠 mock timeout。 |
| R8-P03 CreateProcessW 创建后、返回前卡住 | 用同步 shim 在子进程已创建后阻塞 CreateProcess 调用返回；子进程必须从第一条可执行指令起就在 reaper 持有的 Job 内。 | reaper 可在不等调用返回的情况下终止 Job；在 D 前观察 custodian exit + ActiveProcesses=0。晚返回的 PI/句柄不得开启执行、写成功帧或使已 UNKNOWN 请求变成 OBSERVED。若子进程存在过未纳管窗口，FAIL。 |
| R8-P04 ResumeThread 卡在恢复前/恢复后 | 两次独立注入：调用前阻塞；以及已将 suspend count 减到 0、目标可能已运行但 API 返回前阻塞。 | 目标在 Resume 前已被 reaper Job 包含，reaper 保有 Job + custodian handle。恢复前卡住：可杀 suspended process；恢复后卡住：可杀已运行 process。均须在 D 前得到 process signaled + Job zero；没有证据=UNKNOWN。子进程 READY/frame 不能提前越过未完成的 Resume 结果。 |
| R8-P05 同步 pipe 写满 | 复现 R7 admission-sync：连接端不读、填满 pipe，再由请求端对 admission/命令做同步 WriteFile。 | 调用会阻塞；必须证实 R8 生产请求路径不使用此同步阻塞方式。若测试路径仍是同步 WriteFile，则 caller 未在 D 前返回/UNKNOWN 即 FAIL；杀 caller Job 不是正常 bounded return。 |
| R8-P06 connect/read/write OVERLAPPED pending | 使用 FILE_FLAG_OVERLAPPED pipe；分别让 ConnectNamedPipe、header read、body read、write 永久 pending。让 deadline 到，再请求取消。 | OVERLAPPED、manual-reset event/IOCP context、buffer 和本端 pipe HANDLE 仍由 I/O 发起进程持有；reaper 能独立观察或杀该进程。不得释放/复用任一个 pending 对象。没有成功 completion + 证据时结果 UNKNOWN。 |
| R8-P07 CancelIoEx 成功但 completion 延迟 | 对特定 OVERLAPPED* 调 CancelIoEx 返回 TRUE；测试驱动/peer 暂不让 completion 被消费。 | 仍显示 pending；不关 event/pipe、不复用 buffer/OVERLAPPED、不处理下一个 request。只在 GetOverlappedResult/IOCP 对这一个 op 给出终态 completion 后 release。R7t “cancel 请求已发出”不能算已取消。 |
| R8-P08 CancelIoEx 与正常完成竞态 | 在 ReadFile 正要完成时调用 CancelIoEx，使其返回 ERROR_NOT_FOUND 或读已完成。分别让最终 completion 成功、ERROR_OPERATION_ABORTED。 | ERROR_NOT_FOUND 不等于安全取消。消费同一 op 的 completion/实际 byte count 后分类：完整且截止前的合法帧可继续；被取消、短读/短写、不完整帧只可 UNKNOWN。不得按 CancelIoEx bool 推断。 |
| R8-P09 CancelIoEx 返回其他错误 / completion 不来 | 注入 access/invalid-handle/驱动错误，或不投递 completion。 | UNKNOWN；在仍有 pending 状态时保留 I/O context 和其 owning process/pipe handle。若该 I/O 所在进程要退出，reaper 等进程已 signaled 后再关闭该进程自己的 endpoint；另一端仍须消费断连/完成，不能复用上下文。 |
| R8-P10 pending I/O owner 死亡 | 杀掉发起端进程，令对端仍有未完成读/写；模拟 pipe peer 持有继承/复制句柄导致 EOF 延后。 | 对端自己的 pending OVERLAPPED 仍由对端 owner 持有并被取消/完成；只有它读到确定 broken-pipe/EOF 或自身进程被独立回收，才收尾。owner death 是断连线索，不是另一进程 I/O 已 completion 的证明。 |
| R8-P11 超长、短帧、尾随帧和错误 PID | 发 cap-1、cap、cap+1 字节；截断 header/body；一帧后不关写端；额外写第二帧；复用 stale nonce/request ID 或错 peer PID/创建身份。 | 在分配前拒绝 >cap；短帧、缺 EOF、尾随数据、错误 peer/nonce/request 都拒绝。所有读等待共用 D，不因读 header/body 或重连刷新预算。frame 完整本身仍不能证明 process/Job 清理。 |
| R8-P12 worker + descendant + grandchild | worker 产生 child/grandchild，报告完成后父先退出/挂住；分别终止 Job 与只终止 worker。 | ActiveProcesses 在后代活着时必须非零；只杀父进程不得得到 job-empty。Job 终止后须逐个生成退出证据/Job zero。R7 descendant_join 的 3→0 是正向 basis，但 R8 要独立 reaper 持有 Job handle。测试 CREATE_BREAKAWAY_FROM_JOB/静默 breakaway配置必须拒绝或证明成员仍被纳管；若能脱 Job，FAIL。 |
| R8-P13 假 job-empty / query 故障 | child 帧自称 job_empty=true；把一次查询伪造成 0 但允许仍存活 member；随后 QueryInformationJobObject 返回失败/ERROR_ACCESS_DENIED。 | 结果层只采 reaper 持有的确切 Job handle。查询失败或 process handle 仍 unsignaled 时 UNKNOWN；不得由 frame 字段/单次 stale snapshot 置 OBSERVED。后代退出后在 D 内可以重新 query，但必须先确认没有新的 assignment producer。 |
| R8-P14 终止调用慢/失败，close 失败 | TerminateJobObject 前后阻塞；返回 FALSE；Job Query 阻塞/失败；CloseHandle FALSE/异常。 | TerminateJobObject=TRUE 只是 request。超时/失败时 UNKNOWN，所有仍必要 handles 继续 retained/poisoned；不能“cleanup returned”或开下一 request。若 reaper 自己可被这些调用卡住，测试必须由再上一层的独立 custodian 终止 reaper；无更上一层时该硬期限声明 FAIL。 |
| R8-P15 Job-empty 通知延迟 / 查询假阴性 | 先让 ActiveProcesses 非零，发出终止，再返回一次非零/查询错误，随后在同一 D 内释放 worker。另在 D 后才释放。 | D 内有界重查可得零时方可证明；若 D 到仍非零/不可查询，立即保持 UNKNOWN，即便 teardown 后变 0 也不能改 request result。迟到的零只进后续审计记录。 |
| R8-P16 frame-before-empty 与 empty-before-frame | A: worker/custodian先写完整 frame但仍运行/后代存活；B: process/Job 已清空但 frame 缺失、截断或 writer 没 EOF。 | A 不得响应成功直到独立 process/Job 证据；B 为 UNKNOWN。可接受成功要求合法帧 + 期望正常 exit + Job-empty + 无 pending I/O + 全部在 D 前。 |
| R8-P17 每请求时限单调递减 | 在连接、身份校验、创建、resume、worker、frame、取消、reap 的每阶段各耗时，使阶段和逐步逼近/跨过一个初始 D。 | 只设置一次绝对 D；所有等待取 remaining=max(0,D-now)。禁止各阶段重新给 full timeout。若任一步返回已越 D，即使随后清理成功，原请求结果仍 UNKNOWN；response 不得晚写。 |
| R8-P18 caller disconnect/timeout | caller 在 pending response read 中断连或本地 deadline 到达；server 继续尝试完成 worker。 | caller 返回 UNKNOWN，绝不把自身 IPC timeout写成服务端 terminated/job-empty。server/reaper 继续保留 Job/process/IO handles 并自行收尾；后续 response 只能作为晚到审计，不能复用原 request 为 success。 |
| R8-P19 reaper/custodian 死亡 | 分别杀 reaper、custodian、worker；Job 设置 kill-on-close；保留另一个进程的 Job dup handle。 | custodian death：reaper用 retained Job query/终止剩余树。reaper death：OS kill-on-close可触发清理，但 caller没有独立确认时只能 UNKNOWN；若 caller/另一个 watchdog保有 duplicated Job handle，必须观察该确切 handle 的 exit+zero 后才可报清理完成。 |
| R8-P20 unknown 请求槽复用 | 第一个 request pending cancel 或 Job cleanup 时发第二个同通道请求；或让旧 IOCP/pipe completion 到达新 request。 | 不得复用旧 OVERLAPPED、pipe、Job、request generation；第二请求拒绝/排队且不重置第一 deadline。completion key、nonce、request_id和Job identity不匹配时不得推进第二请求。 |
| R8-P21 正常正控与 late result | 标准短 worker：一帧 canonical 且 capped、写端 EOF、exit code 0、所有成员退出。另在 D+epsilon 才让相同结果完成。 | 正控：caller 在 D 前收到结果且 exit/job/IO completion facts 可追溯。晚控：UNKNOWN、禁止 response/receipt success；晚到的 process exit + Job zero不得升级。 |

## R8 评审必须带上的执行证据

每个测试产出一条来自 reaper 的机器可读事实记录，至少包含：

- request_id、单一 deadline_monotonic_ns、accepted_at_ns、decision_at_ns、response_write_started/finished_ns。
- custodian/reaper/worker 的 PID + 创建时间（适用时）、进程 handle wait 结果、exit code、Job 标识/handle-owning process、Job limit flags、ActiveProcesses 查询序列及时间。
- 每一端 pipe HANDLE 所属进程；OVERLAPPED 标识、发起 API、pending 状态、CancelIoEx 返回码、最终 completion 状态/bytes、event/IOCP dequeue 时间；取消完成前是否有任何 close/reuse（必须为 false）。
- 终止请求、Job-empty 观察、控制句柄释放的时间顺序。release 不得早于所有 required proof。
- R7/R7t 结果快照与测试后的 teardown 清理分别保存。测试后能清场只是 fixture hygiene，不会更新 deadline 内已返回的 UNKNOWN。

不允许用 Sleep/延长 timeout 代替确定性卡点；API wrapper 应能在调用前阻塞、API 副作用已发生但尚未返回时阻塞、和返回前/后进行门控。同步调用挂住的负测必须由另一个真实进程中的 reaper 观察并处置，不可只 mock watchdog。真实 Win32 测试只用 inert executable、临时命名管道和 temp Job，不启动/安装服务，不访问 native/provider/私密配置。

## 当前从 R7/R7t 能下的结论

- **已被 Windows inert 测到：**成功启动后的 worker/Join/后代挂起可由真实 Job 终止；term 后确实观察到 worker exit 和 ActiveProcesses 0；在证据前保留控制句柄。
- **明确失败：**同步 admission 写可以越过 caller deadline；overlapped CancelIoEx 仍 pending 时释放/返回没有完成 reaper；预热/setup 时间不在请求预算内；测试用外围 Python watchdog 不是独立 OS custodian。
- **R8 的最小新增证明：**独立存活进程确实持有本请求 Job 与 custodian process HANDLE；它在调用者路径堵住时仍能按同一 D 终止/观察；所有跨进程 overlapped 各由自己的存活 endpoint owner持有并 drain；未知不能通过晚到 cleanup/child frame升级。
- **仍不能默认声称：**若最顶层 reaper在建立它自己的 containment、同步 CreateProcess、ResumeThread、TerminateJobObject、Job query或内核 pipe 调用内可永久停住，而无再上一层已有句柄 owner，则没有由 R7/R7t证据支持的整体硬截止。候选必须将该边界作为拒绝/UNKNOWN，或提交真实、更外层且早已存在的 custodian 证据。

## Microsoft API 依据

- [CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/fileio/cancelioex-func)：取消是请求；成功后也不能释放/复用对应 OVERLAPPED，直到操作完成；失败会给 ERROR_NOT_FOUND 等状态。
- [同步与异步 I/O](https://learn.microsoft.com/en-us/windows/win32/fileio/synchronous-and-asynchronous-i-o)：异步 I/O 的 buffer/OVERLAPPED 生命周期要等完成；CancelIoEx 作用于当前进程发出的操作。
- [GetOverlappedResultEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresultex)：可带有限等待读取指定 handle + OVERLAPPED 的最终完成结果。
- [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)：Job 对子进程的默认包含和 breakaway规则；TerminateJobObject用于终止当前 Job 成员；QueryInformationJobObject取得 accounting状态。
- [JOBOBJECT_BASIC_ACCOUNTING_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)：ActiveProcesses表示当前 Job 成员数。
- [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) / [ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)：返回的 PROCESS_INFORMATION/线程句柄是进程创建结果；ResumeThread降低 suspend count，降到零时线程恢复运行。它们的同步阻塞不可由发起线程自己的 timeout 变量中断。
- [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)：发起 Job 成员终止；仍须单独等进程对象和查询 Job 状态证明完成。

以上文档用于 API 语义定位，不替代 R8 的实测、句柄 custody、权限与部署验收。
