# 拆分后的子模块 — 提供按功能分类的导入路径
# 例如: from bt_api_py.ctp.ctp_trader_api import CThostFtdcTraderApi
# 例如: from bt_api_py.ctp.ctp_structs_order import CThostFtdcInputOrderField
from __future__ import annotations

import contextlib

from . import (
    _ctp_base as _ctp_base,
)
from . import (
    ctp_constants as ctp_constants,
)
from . import (
    ctp_md_api,
    ctp_structs_account,
    ctp_structs_common,
    ctp_structs_market,
    ctp_structs_order,
    ctp_structs_position,
    ctp_structs_query,
    ctp_structs_risk,
    ctp_structs_trade,
    ctp_structs_transfer,
    ctp_trader_api,
)

with contextlib.suppress(Exception):
    from ._ctp import *

from .ctp import *
