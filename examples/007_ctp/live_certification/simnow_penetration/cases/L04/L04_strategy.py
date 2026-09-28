"""L04: case-specific real-evidence and action plan."""

from common.decision_engine import CaseIntentDecisionEngine, DecisionError

CASE_ID = "L04"
CASE_NAME = "日志记录：错误提示信息"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证运行系统记录一条可归因的错误提示，并区分本地检查与前置拒绝。",
    "preconditions": (
        "已批准的真实会话、错误日志目录和受控测试条件。",
        "确认本场景采用运行时价格最小变动单位检查，且不会将请求发至前置。",
    ),
    "actions": (
        "记录合约价格最小变动单位及日志基线。",
        "在运行时风控边界提交一笔不符合最小变动单位的受控请求。",
        "确认请求在本地被拒绝，并检查关联错误日志及前置请求计数。",
    ),
    "evidence": (
        "合约元数据、请求参数和本地拒绝事件的原始记录。",
        "错误日志中明确标注为本地检查的原因及请求关联标识。",
        "本地拒绝前后前置请求计数，证明未将该请求作为柜台拒绝。",
    ),
    "dependency": "现有场景语义是本地价格步长校验；它不能证明 SimNow 服务端错误处理。",
}


class L04ReadOnlyStrategy(CaseIntentDecisionEngine):
    """Bind L04 to local validator error provenance and zero-dispatch audit."""

    def __init__(self, plan, scope, authenticator=None):
        if plan.case_id != CASE_ID:
            raise DecisionError("L04 strategy requires the L04 static plan")
        super().__init__(plan, scope, authenticator)
