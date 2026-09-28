"""B01: case-specific real-evidence and action plan."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "B01"
CASE_NAME = "批量撤单：多笔部分成交委托"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证多笔真实部分成交委托可按剩余数量批量发起撤单并关联各自回报。",
    "preconditions": (
        "获准的 SimNow 第一套环境、活跃交易时段及低风险测试账户。",
        "经纪商确认批量撤单接口和订单状态同步方式。",
        "可形成多笔部分成交且仍有未成交数量的实际委托。",
    ),
    "actions": (
        "提交经批准的受控委托，并等待真实部分成交回报。",
        "核对每笔委托的已成交量、剩余量和当前状态。",
        "对仍有效的委托执行批量撤单并跟踪逐笔最终状态。",
    ),
    "evidence": (
        "前置委托及成交回报、交易所委托标识和剩余数量快照。",
        "批量撤单请求、逐笔撤单回报及运行日志中的关联标识。",
        "撤单后委托与成交查询的对账记录。",
    ),
    "dependency": "部分成交由撮合状态决定，策略无法保证；需真实市场条件和柜台批量撤单能力。",
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed batch cancel observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
