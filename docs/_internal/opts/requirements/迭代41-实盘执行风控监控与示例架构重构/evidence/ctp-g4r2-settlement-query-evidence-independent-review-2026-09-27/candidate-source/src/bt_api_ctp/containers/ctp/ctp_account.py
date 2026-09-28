from __future__ import annotations

from bt_api_base.containers.accounts.account import AccountData
from bt_api_base.functions.utils import from_dict_get_float, from_dict_get_string


class CtpAccountData(AccountData):
    def __init__(
        self,
        account_info,
        symbol_name=None,
        asset_type="FUTURE",
        has_been_json_encoded=False,
    ):
        super().__init__(account_info, has_been_json_encoded)
        self.symbol_name = symbol_name
        self.asset_type = asset_type
        self.exchange_name = "CTP"
        self._initialized = False
        # AutoInitMixin sets _initialized before calling init_data() to avoid
        # re-entrancy. Keep a separate flag for completed payload parsing.
        self._data_initialized = False
        self.broker_id = None
        self.account_id = None
        self.pre_balance = None
        self.balance = None
        self.available = None
        self.commission = None
        self.frozen_margin = None
        self.curr_margin = None
        self.close_profit = None
        self.position_profit = None
        self.withdraw = None
        self.deposit = None
        self.risk_degree = None

    def init_data(self):
        if self._data_initialized:
            return self
        info = self.account_info
        if isinstance(info, dict):
            self.broker_id = from_dict_get_string(info, "BrokerID")
            self.account_id = from_dict_get_string(info, "AccountID")
            self.pre_balance = from_dict_get_float(info, "PreBalance", 0.0)
            self.balance = from_dict_get_float(info, "Balance", 0.0)
            self.available = from_dict_get_float(info, "Available", 0.0)
            self.commission = from_dict_get_float(info, "Commission", 0.0)
            self.frozen_margin = from_dict_get_float(info, "FrozenMargin", 0.0)
            self.curr_margin = from_dict_get_float(info, "CurrMargin", 0.0)
            self.close_profit = from_dict_get_float(info, "CloseProfit", 0.0)
            self.position_profit = from_dict_get_float(info, "PositionProfit", 0.0)
            self.withdraw = from_dict_get_float(info, "Withdraw", 0.0)
            self.deposit = from_dict_get_float(info, "Deposit", 0.0)
            balance = float(self.balance or 0.0)
            margin = float(self.curr_margin or 0.0)
            self.risk_degree = margin / balance if balance > 0 else 0.0
        self._data_initialized = True
        self._initialized = True
        return self

    def get_exchange_name(self):
        self._ensure_init()
        return self.exchange_name or ""

    def get_asset_type(self):
        self._ensure_init()
        return self.asset_type or ""

    def get_account_type(self):
        self._ensure_init()
        return self.account_id or "CNY"

    def get_server_time(self):
        return None

    def get_total_wallet_balance(self):
        return self.balance

    def get_margin(self):
        self._ensure_init()
        balance = float(self.balance or 0.0)
        position_profit = float(self.position_profit or 0.0)
        return balance - position_profit

    def get_available_margin(self):
        self._ensure_init()
        return self.available or 0.0

    def get_unrealized_profit(self):
        self._ensure_init()
        return self.position_profit or 0.0

    def get_balances(self):
        return [self]

    def get_positions(self):
        return []

    def get_all_data(self):
        return {
            "exchange_name": self.exchange_name,
            "asset_type": self.asset_type,
            "account_id": self.account_id,
            "pre_balance": self.pre_balance,
            "balance": self.balance,
            "available": self.available,
            "commission": self.commission,
            "frozen_margin": self.frozen_margin,
            "curr_margin": self.curr_margin,
            "close_profit": self.close_profit,
            "position_profit": self.position_profit,
            "risk_degree": self.risk_degree,
        }
