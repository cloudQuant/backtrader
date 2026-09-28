"""EM02: case-specific real-evidence and action plan."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = "EM02"
CASE_NAME = "暂停交易：策略执行暂停"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证运行中的策略在收到暂停指令后停止后续策略回调和新委托请求。",
    "preconditions": (
        "已获准运行的真实交易会话和可审计的策略暂停控制。",
        "暂停前盘点未完成委托，并明确由谁负责后续撤单或对账。",
    ),
    "actions": (
        "记录运行进程、会话状态和暂停前的委托基线。",
        "通过实际运维控制触发策略暂停，记录操作人和时间。",
        "在约定观察窗口检查回调停止及新委托请求计数。",
    ),
    "evidence": (
        "暂停指令审计记录、运行日志和带时间戳的进程状态。",
        "暂停前后委托请求及回报的关联记录。",
        "观察窗口内无新增委托请求的监控记录。",
    ),
    "dependency": "本场景验证应用暂停控制；未完成委托仍需单独核对，暂停本身不代表撤单。",
}


class EM02ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind EM02 to an authorized pause and completed empty-order query."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("EM02 strategy requires the EM02 static plan")
        super().__init__(plan, scope, authenticator)
