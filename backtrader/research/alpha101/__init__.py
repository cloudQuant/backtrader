"""Native Alpha101 formula registry."""

from types import MappingProxyType
from typing import Mapping, Tuple, Type

from ..factor_indicator import FactorIndicator
from ._metadata import (
    DEFAULT_FORMULA_UNIVERSE_POLICY,
    DEFAULT_PIT_POLICY,
    FormulaIdentity,
    ImplementationIdentity,
    native_alpha,
)
from .alpha001 import Alpha001Native
from .alpha002 import Alpha002Native
from .alpha003 import Alpha003Native
from .alpha004 import Alpha004Native
from .alpha005 import Alpha005Native
from .alpha006 import Alpha006Native
from .alpha007 import Alpha007Native
from .alpha008 import Alpha008Native
from .alpha009 import Alpha009Native
from .alpha010 import Alpha010Native
from .alpha011 import Alpha011Native
from .alpha012 import Alpha012Native
from .alpha013 import Alpha013Native
from .alpha014 import Alpha014Native
from .alpha015 import Alpha015Native
from .alpha016 import Alpha016Native
from .alpha017 import Alpha017Native
from .alpha018 import Alpha018Native
from .alpha019 import Alpha019Native
from .alpha020 import Alpha020Native
from .alpha021 import Alpha021Native
from .alpha022 import Alpha022Native
from .alpha023 import Alpha023Native
from .alpha024 import Alpha024Native
from .alpha025 import Alpha025Native
from .alpha026 import Alpha026Native
from .alpha027 import Alpha027Native
from .alpha028 import Alpha028Native
from .alpha029 import Alpha029Native
from .alpha030 import Alpha030Native
from .alpha031 import Alpha031Native
from .alpha032 import Alpha032Native
from .alpha033 import Alpha033Native
from .alpha034 import Alpha034Native
from .alpha035 import Alpha035Native
from .alpha036 import Alpha036Native
from .alpha037 import Alpha037Native
from .alpha038 import Alpha038Native
from .alpha039 import Alpha039Native
from .alpha040 import Alpha040Native
from .alpha041 import Alpha041Native
from .alpha042 import Alpha042Native
from .alpha043 import Alpha043Native
from .alpha044 import Alpha044Native
from .alpha045 import Alpha045Native
from .alpha046 import Alpha046Native
from .alpha047 import Alpha047Native
from .alpha048 import Alpha048Native
from .alpha049 import Alpha049Native
from .alpha050 import Alpha050Native
from .alpha051 import Alpha051Native
from .alpha052 import Alpha052Native
from .alpha053 import Alpha053Native
from .alpha054 import Alpha054Native
from .alpha055 import Alpha055Native
from .alpha056 import Alpha056Native
from .alpha057 import Alpha057Native
from .alpha058 import Alpha058Native
from .alpha059 import Alpha059Native
from .alpha060 import Alpha060Native
from .alpha061 import Alpha061Native
from .alpha062 import Alpha062Native
from .alpha063 import Alpha063Native
from .alpha064 import Alpha064Native
from .alpha065 import Alpha065Native
from .alpha066 import Alpha066Native
from .alpha067 import Alpha067Native
from .alpha068 import Alpha068Native
from .alpha069 import Alpha069Native
from .alpha070 import Alpha070Native
from .alpha071 import Alpha071Native
from .alpha072 import Alpha072Native
from .alpha073 import Alpha073Native
from .alpha074 import Alpha074Native
from .alpha075 import Alpha075Native
from .alpha076 import Alpha076Native
from .alpha077 import Alpha077Native
from .alpha078 import Alpha078Native
from .alpha079 import Alpha079Native
from .alpha080 import Alpha080Native
from .alpha081 import Alpha081Native
from .alpha082 import Alpha082Native
from .alpha083 import Alpha083Native
from .alpha084 import Alpha084Native
from .alpha085 import Alpha085Native
from .alpha086 import Alpha086Native
from .alpha087 import Alpha087Native
from .alpha088 import Alpha088Native
from .alpha089 import Alpha089Native
from .alpha090 import Alpha090Native
from .alpha091 import Alpha091Native
from .alpha092 import Alpha092Native
from .alpha093 import Alpha093Native
from .alpha094 import Alpha094Native
from .alpha095 import Alpha095Native
from .alpha096 import Alpha096Native
from .alpha097 import Alpha097Native
from .alpha098 import Alpha098Native
from .alpha099 import Alpha099Native
from .alpha100 import Alpha100Native
from .alpha101 import Alpha101Native

ALPHA_REGISTRY: Mapping[int, Type[FactorIndicator]] = MappingProxyType(
    {
        1: Alpha001Native,
        2: Alpha002Native,
        3: Alpha003Native,
        4: Alpha004Native,
        5: Alpha005Native,
        6: Alpha006Native,
        7: Alpha007Native,
        8: Alpha008Native,
        9: Alpha009Native,
        10: Alpha010Native,
        11: Alpha011Native,
        12: Alpha012Native,
        13: Alpha013Native,
        14: Alpha014Native,
        15: Alpha015Native,
        16: Alpha016Native,
        17: Alpha017Native,
        18: Alpha018Native,
        19: Alpha019Native,
        20: Alpha020Native,
        21: Alpha021Native,
        22: Alpha022Native,
        23: Alpha023Native,
        24: Alpha024Native,
        25: Alpha025Native,
        26: Alpha026Native,
        27: Alpha027Native,
        28: Alpha028Native,
        29: Alpha029Native,
        30: Alpha030Native,
        31: Alpha031Native,
        32: Alpha032Native,
        33: Alpha033Native,
        34: Alpha034Native,
        35: Alpha035Native,
        36: Alpha036Native,
        37: Alpha037Native,
        38: Alpha038Native,
        39: Alpha039Native,
        40: Alpha040Native,
        41: Alpha041Native,
        42: Alpha042Native,
        43: Alpha043Native,
        44: Alpha044Native,
        45: Alpha045Native,
        46: Alpha046Native,
        47: Alpha047Native,
        48: Alpha048Native,
        49: Alpha049Native,
        50: Alpha050Native,
        51: Alpha051Native,
        52: Alpha052Native,
        53: Alpha053Native,
        54: Alpha054Native,
        55: Alpha055Native,
        56: Alpha056Native,
        57: Alpha057Native,
        58: Alpha058Native,
        59: Alpha059Native,
        60: Alpha060Native,
        61: Alpha061Native,
        62: Alpha062Native,
        63: Alpha063Native,
        64: Alpha064Native,
        65: Alpha065Native,
        66: Alpha066Native,
        67: Alpha067Native,
        68: Alpha068Native,
        69: Alpha069Native,
        70: Alpha070Native,
        71: Alpha071Native,
        72: Alpha072Native,
        73: Alpha073Native,
        74: Alpha074Native,
        75: Alpha075Native,
        76: Alpha076Native,
        77: Alpha077Native,
        78: Alpha078Native,
        79: Alpha079Native,
        80: Alpha080Native,
        81: Alpha081Native,
        82: Alpha082Native,
        83: Alpha083Native,
        84: Alpha084Native,
        85: Alpha085Native,
        86: Alpha086Native,
        87: Alpha087Native,
        88: Alpha088Native,
        89: Alpha089Native,
        90: Alpha090Native,
        91: Alpha091Native,
        92: Alpha092Native,
        93: Alpha093Native,
        94: Alpha094Native,
        95: Alpha095Native,
        96: Alpha096Native,
        97: Alpha097Native,
        98: Alpha098Native,
        99: Alpha099Native,
        100: Alpha100Native,
        101: Alpha101Native,
    }
)


def get_alpha(alpha_id: int) -> Type[FactorIndicator]:
    """Return the promoted native class for an exact, non-bool Alpha ID."""

    if type(alpha_id) is not int:
        raise TypeError("alpha_id must be an integer Alpha101 ID; bool is not accepted")
    try:
        return ALPHA_REGISTRY[alpha_id]
    except KeyError:
        raise KeyError("Alpha%d is not registered as a native formula" % alpha_id) from None


def list_alphas() -> Tuple[int, ...]:
    """Return the registered native formula IDs in ascending order."""

    return tuple(ALPHA_REGISTRY)


__all__ = (
    "ALPHA_REGISTRY",
    "Alpha001Native",
    "Alpha002Native",
    "Alpha003Native",
    "Alpha004Native",
    "Alpha005Native",
    "Alpha006Native",
    "Alpha007Native",
    "Alpha008Native",
    "Alpha009Native",
    "Alpha010Native",
    "Alpha011Native",
    "Alpha012Native",
    "Alpha013Native",
    "Alpha014Native",
    "Alpha015Native",
    "Alpha016Native",
    "Alpha017Native",
    "Alpha018Native",
    "Alpha019Native",
    "Alpha020Native",
    "Alpha021Native",
    "Alpha022Native",
    "Alpha023Native",
    "Alpha024Native",
    "Alpha025Native",
    "Alpha026Native",
    "Alpha027Native",
    "Alpha028Native",
    "Alpha029Native",
    "Alpha030Native",
    "Alpha031Native",
    "Alpha032Native",
    "Alpha033Native",
    "Alpha034Native",
    "Alpha035Native",
    "Alpha036Native",
    "Alpha037Native",
    "Alpha038Native",
    "Alpha039Native",
    "Alpha040Native",
    "Alpha041Native",
    "Alpha042Native",
    "Alpha043Native",
    "Alpha044Native",
    "Alpha045Native",
    "Alpha046Native",
    "Alpha047Native",
    "Alpha048Native",
    "Alpha049Native",
    "Alpha050Native",
    "Alpha051Native",
    "Alpha052Native",
    "Alpha053Native",
    "Alpha054Native",
    "Alpha055Native",
    "Alpha056Native",
    "Alpha057Native",
    "Alpha058Native",
    "Alpha059Native",
    "Alpha060Native",
    "Alpha061Native",
    "Alpha062Native",
    "Alpha063Native",
    "Alpha064Native",
    "Alpha065Native",
    "Alpha066Native",
    "Alpha067Native",
    "Alpha068Native",
    "Alpha069Native",
    "Alpha070Native",
    "Alpha071Native",
    "Alpha072Native",
    "Alpha073Native",
    "Alpha074Native",
    "Alpha075Native",
    "Alpha076Native",
    "Alpha077Native",
    "Alpha078Native",
    "Alpha079Native",
    "Alpha080Native",
    "Alpha081Native",
    "Alpha082Native",
    "Alpha083Native",
    "Alpha084Native",
    "Alpha085Native",
    "Alpha086Native",
    "Alpha087Native",
    "Alpha088Native",
    "Alpha089Native",
    "Alpha090Native",
    "Alpha091Native",
    "Alpha092Native",
    "Alpha093Native",
    "Alpha094Native",
    "Alpha095Native",
    "Alpha096Native",
    "Alpha097Native",
    "Alpha098Native",
    "Alpha099Native",
    "Alpha100Native",
    "Alpha101Native",
    "DEFAULT_FORMULA_UNIVERSE_POLICY",
    "DEFAULT_PIT_POLICY",
    "FormulaIdentity",
    "ImplementationIdentity",
    "get_alpha",
    "list_alphas",
    "native_alpha",
)
