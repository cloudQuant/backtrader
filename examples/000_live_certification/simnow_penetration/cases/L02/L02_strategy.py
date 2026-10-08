"""Typed read-only evidence contracts with a lazy offline smoke strategy."""
from __future__ import annotations

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


def _load_smoke_strategy():
    """Correlate system connection and readiness log events for case L02."""

    import backtrader as bt

    class L02Strategy(bt.Strategy):
        params = (("case_config", None), ("allow_orders", False))

        def __init__(self):
            self.case_config = self.p.case_config
            self.case_events = []
            self.case_observed = False
            self.case_reason = "awaiting correlated system lifecycle logs"
            self.bars_seen = 0
            self._connected = None
            self._ready = None

        @staticmethod
        def _capture(event):
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            row = {"event_type": event.get("event_type")}
            for key in ("timestamp", "session_id", "gateway_key", "trace_id", "status"):
                value = event.get(key)
                if value is None:
                    value = details.get(key)
                if isinstance(value, (str, int, float, bool)):
                    row[key] = value
            return row

        def notify_store(self, msg, *args, **kwargs):
            event = kwargs.get("event")
            if msg != "runtime_event" or not isinstance(event, dict):
                return
            kind = event.get("event_type")
            if kind not in ("store_connected", "store_ready"):
                return
            row = self._capture(event)
            self.case_events.append(row)
            if kind == "store_connected":
                self._connected = row
            else:
                self._ready = row
            session = (self._connected or {}).get("session_id")
            if (
                self._connected
                and self._ready
                and session
                and session == self._ready.get("session_id")
                and self._connected.get("timestamp")
                and self._ready.get("timestamp")
            ):
                self.case_observed = True
                self.case_reason = "correlated system lifecycle events observed; runner retains certification decision"

        def next(self):
            self.bars_seen += 1

    return L02Strategy


def __getattr__(name):
    if name == "L02Strategy":
        strategy = _load_smoke_strategy()
        globals()[name] = strategy
        return strategy
    raise AttributeError(name)
