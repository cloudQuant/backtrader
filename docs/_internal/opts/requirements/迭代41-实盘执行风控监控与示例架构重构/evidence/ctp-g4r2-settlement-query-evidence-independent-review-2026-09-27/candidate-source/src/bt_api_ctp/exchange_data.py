from __future__ import annotations

from bt_api_base.containers.exchanges.exchange_data import ExchangeData


class CtpExchangeData(ExchangeData):
    def __init__(self) -> None:
        super().__init__()
        self.exchange_name = "CTP"
        self.rest_url = ""
        self.wss_url = ""
        self.acct_wss_url = ""
        self.md_front = ""
        self.td_front = ""
        self.kline_periods = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
        }
        self.reverse_kline_periods = {value: key for key, value in self.kline_periods.items()}


class CtpExchangeDataFuture(CtpExchangeData):
    pass


__all__ = ["CtpExchangeData", "CtpExchangeDataFuture"]
