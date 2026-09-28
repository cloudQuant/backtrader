from __future__ import annotations

from bt_api_base.containers.bars.bar import BarData
from bt_api_base.functions.utils import (
    from_dict_get_float,
    from_dict_get_int,
    from_dict_get_string,
)


class CtpBarData(BarData):
    def __init__(
        self,
        bar_info,
        symbol_name=None,
        asset_type="FUTURE",
        has_been_json_encoded=False,
    ):
        super().__init__(bar_info, has_been_json_encoded)
        self.symbol_name = symbol_name
        self.asset_type = asset_type
        self.exchange_name = "CTP"
        self._initialized = False
        # See CtpAccountData: this must not share AutoInitMixin's re-entrancy
        # guard, otherwise the first getter can skip parsing the payload.
        self._data_initialized = False
        self.open_time = None
        self.close_time = None
        self.open_price = None
        self.high_price = None
        self.low_price = None
        self.close_price = None
        self.volume_val = None
        self.amount_val = None
        self.open_interest = None
        self.settlement_price_val = None

    def init_data(self):
        if self._data_initialized:
            return self
        info = self.bar_info
        if isinstance(info, dict):
            self.open_time = from_dict_get_string(info, "open_time")
            self.close_time = from_dict_get_string(info, "close_time")
            self.open_price = from_dict_get_float(info, "open", 0.0)
            self.high_price = from_dict_get_float(info, "high", 0.0)
            self.low_price = from_dict_get_float(info, "low", 0.0)
            self.close_price = from_dict_get_float(info, "close", 0.0)
            self.volume_val = from_dict_get_int(info, "volume", 0)
            self.amount_val = from_dict_get_float(info, "amount", 0.0)
            self.open_interest = from_dict_get_float(info, "open_interest", 0.0)
            self.settlement_price_val = from_dict_get_float(info, "settlement_price")
        self._data_initialized = True
        self._initialized = True
        return self

    def get_exchange_name(self):
        return self.exchange_name or ""

    def get_symbol_name(self):
        return self.symbol_name or ""

    def get_asset_type(self):
        return self.asset_type or ""

    def get_server_time(self):
        self._ensure_init()
        return self.close_time or ""

    def get_open_time(self):
        self._ensure_init()
        return self.open_time or ""

    def get_open_price(self):
        return float(self.open_price or 0.0)

    def get_high_price(self):
        return float(self.high_price or 0.0)

    def get_low_price(self):
        return float(self.low_price or 0.0)

    def get_close_price(self):
        return float(self.close_price or 0.0)

    def get_volume(self):
        return int(self.volume_val or 0)

    def get_amount(self):
        return float(self.amount_val or 0.0)

    def get_close_time(self):
        self._ensure_init()
        return self.close_time or ""

    def get_bar_status(self):
        return True

    def get_open_interest(self):
        return float(self.open_interest or 0.0)

    def get_settlement_price(self):
        return float(self.settlement_price_val or 0.0)

    def get_all_data(self):
        if not self._initialized:
            self.init_data()
        return {
            "exchange_name": self.exchange_name,
            "symbol_name": self.symbol_name,
            "asset_type": self.asset_type,
            "open_time": self.open_time,
            "close_time": self.close_time,
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
            "volume": self.volume_val,
            "amount": self.amount_val,
            "open_interest": self.open_interest,
            "settlement_price": self.settlement_price_val,
            "bar_status": True,
        }

    def __str__(self):
        return str(self.get_all_data())

    def __repr__(self):
        return self.__str__()
