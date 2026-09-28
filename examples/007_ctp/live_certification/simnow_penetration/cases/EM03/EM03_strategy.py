"""EM03: case-specific real-evidence and action plan."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = "EM03"
CASE_NAME = "暂停交易：账户强制退出"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证外部终止交易会话后，系统识别断线并停止后续委托。",
    "preconditions": (
        "经纪商或 SimNow 运维人员确认可用的服务端会话终止流程。",
        "账户管理员批准测试时段，并明确未完成委托的处置责任。",
    ),
    "actions": (
        "建立并记录真实交易会话及未完成委托基线。",
        "由运维人员通过其正式管理流程终止该会话。",
        "记录前置断线回调、会话状态及后续委托门禁行为。",
    ),
    "evidence": (
        "运维会话终止记录和前置断线回调时间戳。",
        "运行日志中连接状态变化及新委托请求计数。",
        "断线期间未完成委托的查询与对账记录。",
    ),
    "dependency": "公开 API 手册记录客户端登出请求，未说明服务端强制踢出接口；须由运维确认机制。",
}


class EM03ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind EM03 to operator-authorized logout, disconnect and blocked-write facts."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("EM03 strategy requires the EM03 static plan")
        super().__init__(plan, scope, authenticator)
