"""L01: case-specific real-evidence and action plan."""

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "L01"
CASE_NAME = "日志记录：真实交易信息"
CASE_PLAN = {
    "evidence_basis": "real_runtime",
    "scenario": "验证运行日志将真实委托、成交和撤单信息按标识关联记录。",
    "preconditions": (
        "已批准的真实 SimNow 会话和日志留存策略。",
        "取得独立批准的低风险委托与成交验证窗口。",
    ),
    "actions": (
        "记录进程、会话和日志文件基线。",
        "在授权范围内完成一笔可核验委托及成交生命周期。",
        "按交易日、订单引用和成交标识核对运行日志与前置查询。",
    ),
    "evidence": (
        "真实委托、成交回报及订单/成交查询结果。",
        "订单日志和交易日志中的时间戳、订单引用及成交标识。",
        "采集文件的路径、采集时间和完整性摘要。",
    ),
    "dependency": "成交记录需要真实撮合；无成交时只能说明委托日志行为，不能证明成交日志。",
}


def create_strategy(plan, scope, authenticator):
    """Construct the no-I/O typed trade-log observer for an injected adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)
