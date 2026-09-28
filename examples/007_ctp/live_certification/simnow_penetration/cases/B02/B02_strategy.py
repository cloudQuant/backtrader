"""B02: case-specific real-evidence and action plan."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "B02"
CASE_NAME = "批量撤单：多笔已报未成交委托"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证多笔已被真实前置接受且仍有效的委托可批量撤销。",
    "preconditions": (
        "获准的 SimNow 第一套环境、活跃交易时段和受控账户额度。",
        "有多个已确认处于未成交有效状态的委托。",
    ),
    "actions": (
        "记录订单基线后提交经批准的低数量限价委托。",
        "仅在逐笔收到有效受理状态后发起批量撤单。",
        "等待每笔撤单最终回报，并查询委托和成交状态。",
    ),
    "evidence": (
        "订单受理回报、订单引用和撤单请求关联记录。",
        "逐笔撤单结果及撤单期间发生的成交回报。",
        "撤单后委托、成交和剩余持仓核对记录。",
    ),
    "dependency": "需要真实受理的活动委托；撤单与成交可能竞争，须按最终回报和查询结果对账。",
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed batch cancel observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
