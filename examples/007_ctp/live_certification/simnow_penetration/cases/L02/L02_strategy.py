"""L02 plan and typed read-only system-lifecycle evidence strategy."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "L02"
CASE_NAME = "日志记录：系统运行信息"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证真实运行会话的启动、连接、就绪和退出状态均写入系统日志。",
    "preconditions": (
        "已批准的只读连接窗口和可写入受控目录的日志配置。",
        "记录预期连接前置与运行进程身份。",
    ),
    "actions": (
        "启动受管运行入口并保留原始标准输出及系统日志。",
        "核对连接建立、会话就绪和受控退出的时间顺序。",
        "将日志状态与实际进程和连接观测进行关联。",
    ),
    "evidence": (
        "进程标识、启动和退出时间及未修改的系统日志。",
        "真实连接状态回调和运行就绪事件。",
        "日志文件采集路径及完整性摘要。",
    ),
    "dependency": "本场景要求真实连接证据；本地运行或离线报告不能证明 SimNow 连通。",
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
