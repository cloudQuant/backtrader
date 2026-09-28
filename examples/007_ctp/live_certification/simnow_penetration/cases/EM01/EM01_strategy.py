"""EM01: case-specific real-evidence and action plan."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = "EM01"
CASE_NAME = "暂停交易：账户交易权限限制"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证账户交易权限受限时，系统记录拒绝结果并阻止新增委托。",
    "preconditions": (
        "经批准的 SimNow 测试账户、可交易品种和交易时段。",
        "账户管理员可临时变更交易权限，并安排权限恢复。",
    ),
    "actions": (
        "记录账户和权限基线，由管理员临时撤销报单权限。",
        "在获准范围内发送一笔受控委托，观察真实交易前置响应。",
        "由管理员恢复权限，并记录恢复后的账户状态。",
    ),
    "evidence": (
        "权限变更与恢复的管理员审计记录及时间戳。",
        "委托请求、前置拒绝回报和运行日志中的关联请求标识。",
        "权限恢复后账户状态的核对记录。",
    ),
    "dependency": "账户权限变更须由 SimNow 或经纪商运维人员执行；策略不能自行制造账户权限状态。",
}


class EM01ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind EM01 to control-plane permission disable/restore and provider facts."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("EM01 strategy requires the EM01 static plan")
        super().__init__(plan, scope, authenticator)
