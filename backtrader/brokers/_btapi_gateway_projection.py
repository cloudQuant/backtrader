"""Explicit snapshots of existing BT objects; no provider proof or automatic ACK.

Callers must supply every history-referenced notification clone under its own
stable order key and every associated live Feed. Position datetimes support
naive/fixed-offset tzinfo or a timezone object anchored by an injected Feed.
No snapshot installs objects into a Strategy or Broker.
"""

from __future__ import annotations

import datetime as dt
import json
import inspect
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backtrader.broker import BrokerBase
from backtrader.comminfo import (
    CommInfoBase,
    CommissionInfo,
    ComminfoDC,
    ComminfoFuturesPercent,
    ComminfoFuturesMixed,
    ComminfoFuturesInverse,
    ComminfoFuturesFixed,
    ComminfoFundingRate,
)
from backtrader.commissions import (
    CommInfo,
    CommInfoFutures,
    CommInfoFuturesPerc,
    CommInfoFuturesFixed,
    CommInfoStocks,
    CommInfoStocksPerc,
    CommInfoStocksFixed,
)
from backtrader.feed import DataBase
from backtrader.order import BuyOrder, OrderData, OrderExecutionBit, SellOrder
from backtrader.position import Position
from backtrader.trade import Trade, TradeHistory
from backtrader.utils.autodict import AutoDict, AutoOrderedDict
from backtrader.live_state._common import ensure_no_secret_keys

_MAX_OBJECTS = 10_000
_MAX_BYTES = 16 * 1024 * 1024
_DATA_FIELDS = (
    "dt",
    "size",
    "remsize",
    "price",
    "pricelimit",
    "trailamount",
    "trailpercent",
    "pclose",
    "plimit",
    "value",
    "comm",
    "margin",
    "pnl",
    "psize",
    "pprice",
)
_BIT_FIELDS = (
    "dt",
    "size",
    "price",
    "closed",
    "closedvalue",
    "closedcomm",
    "opened",
    "openedvalue",
    "openedcomm",
    "value",
    "comm",
    "pnl",
    "psize",
    "pprice",
)
_TRADE_NUMBERS = (
    "size",
    "price",
    "value",
    "commission",
    "pnl",
    "pnlcomm",
    "baropen",
    "dtopen",
    "barclose",
    "dtclose",
    "barlen",
)
_HIST_STATUS = ("status", "dt", "barlen", "size", "price", "value", "pnl", "pnlcomm")
_POSITION_NUMBERS = ("size", "price", "adjbase", "upopened", "upclosed")
_PARAM_NUMBERS = ("size", "price", "pricelimit", "exectype", "trailamount", "trailpercent")


_COMMISSION_TYPES = {
    cls.__module__ + "." + cls.__name__: cls
    for cls in (
        CommInfoBase,
        CommissionInfo,
        ComminfoDC,
        ComminfoFuturesPercent,
        ComminfoFuturesMixed,
        ComminfoFuturesInverse,
        ComminfoFuturesFixed,
        ComminfoFundingRate,
        CommInfo,
        CommInfoFutures,
        CommInfoFuturesPerc,
        CommInfoFuturesFixed,
        CommInfoStocks,
        CommInfoStocksPerc,
        CommInfoStocksFixed,
    )
}
_COMMISSION_CACHES = (
    "_stocklike",
    "_commtype",
    "_mult",
    "_margin",
    "_automargin",
    "_leverage_param",
    "_interest_long",
    "_creditrate",
)


@dataclass(frozen=True)
class GatewayFrameworkObjects:
    orders: Mapping[str, BuyOrder | SellOrder]
    positions: Mapping[str, Position]
    trades: Mapping[str, Trade]
    order_refs: Mapping[int, int]
    trade_refs: Mapping[int, int]


def _fail():
    raise ValueError("GATEWAY_FRAMEWORK_SNAPSHOT_INVALID")


def _number(value, *, nullable=True):
    if value is None and nullable:
        return value
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        _fail()
    return value


def _integer(value, *, minimum=0):
    if type(value) is not int or value < minimum or value >= 2**63:
        _fail()
    return value


def _key(value):
    if type(value) is not str or not value or value != value.strip() or len(value) > 1024:
        _fail()
    return value


def _plain(value, depth=0, seen=None):
    if seen is None:
        seen = set()
    if depth > 16:
        _fail()
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return _number(value)
    if type(value) in (dict, list):
        if id(value) in seen:
            _fail()
        seen.add(id(value))
        if type(value) is list:
            if len(value) > _MAX_OBJECTS:
                _fail()
            return [_plain(v, depth + 1, seen) for v in value]
        if len(value) > _MAX_OBJECTS or any(type(k) is not str or not k for k in value):
            _fail()
        return {k: _plain(v, depth + 1, seen) for k, v in value.items()}
    _fail()


def _info_height(node, heights):
    items = node["items"].values() if type(node["items"]) is dict else node["items"]
    maximum = 0
    for child in items:
        height = heights[child["ref"]] if type(child) is dict and set(child) == {"ref"} else 0
        maximum = max(maximum, 1 + height)
    return maximum


def _info_encode(value, budget, table, nodes, order_keys, heights):
    visiting = set()

    def convert(item, depth):
        budget[0] += 3
        if budget[0] > 100_000 or depth > 10:
            _fail()
        if type(item) in (BuyOrder, SellOrder):
            if id(item) not in order_keys:
                _fail()
            return {"order": order_keys[id(item)]}
        if type(item) in (dict, AutoDict, AutoOrderedDict, list, tuple):
            identity = id(item)
            if identity in visiting:
                _fail()
            if identity in table:
                ref = table[identity]
                if depth + heights[ref] > 10:
                    _fail()
                return {"ref": ref}
            if len(item) > _MAX_OBJECTS:
                _fail()
            ref = str(len(table))
            table[identity] = ref
            visiting.add(identity)
            if type(item) in (list, tuple):
                node = {
                    "kind": "list" if type(item) is list else "tuple",
                    "closed": False,
                    "items": [convert(v, depth + 1) for v in item],
                }
            else:
                if any(type(k) is not str or not k for k in item):
                    _fail()
                kind = {dict: "dict", AutoDict: "auto", AutoOrderedDict: "ordered"}[type(item)]
                if kind != "dict" and (
                    type(item._closed) is not bool or set(vars(item)) - {"_closed"}
                ):
                    _fail()
                node = {
                    "kind": kind,
                    "closed": item._closed if kind != "dict" else False,
                    "items": {k: convert(v, depth + 1) for k, v in item.items()},
                }
            visiting.remove(identity)
            nodes[ref] = node
            heights[ref] = _info_height(node, heights)
            if depth + heights[ref] > 10:
                _fail()
            return {"ref": ref}
        return _plain(item)

    return {"root": convert(value, 0)}


def _info_decode_all(roots, nodes, orders):
    cache = {}
    heights = {}
    visiting = set()

    def resolve(edge, depth):
        if depth > 10:
            _fail()
        if type(edge) is not dict:
            if type(edge) is list:
                _fail()
            return _plain(edge)
        if set(edge) == {"order"}:
            if type(edge["order"]) is not str or edge["order"] not in orders:
                _fail()
            return orders[edge["order"]]
        if set(edge) != {"ref"} or type(edge["ref"]) is not str or edge["ref"] not in nodes:
            _fail()
        ref = edge["ref"]
        if ref in visiting:
            _fail()
        if ref in cache:
            if depth + heights[ref] > 10:
                _fail()
            return cache[ref]
        node = _exact(nodes[ref], ("kind", "closed", "items"))
        kind = node["kind"]
        if type(node["closed"]) is not bool:
            _fail()
        if kind in ("list", "tuple"):
            if node["closed"] or type(node["items"]) is not list:
                _fail()
            result = []
        elif kind in ("dict", "auto", "ordered"):
            if type(node["items"]) is not dict or (kind == "dict" and node["closed"]):
                _fail()
            result = {"dict": dict, "auto": AutoDict, "ordered": AutoOrderedDict}[kind]()
        else:
            _fail()
        visiting.add(ref)
        cache[ref] = result
        if kind in ("list", "tuple"):
            result.extend(resolve(child, depth + 1) for child in node["items"])
            if kind == "tuple":
                result = tuple(result)
                cache[ref] = result
        else:
            for key, child in node["items"].items():
                _key(key)
                result[key] = resolve(child, depth + 1)
            if kind != "dict":
                result._closed = node["closed"]
        visiting.remove(ref)
        heights[ref] = _info_height(node, heights)
        if depth + heights[ref] > 10:
            _fail()
        return result

    output = {}
    for key, value in roots.items():
        _exact(value, ("root",))
        output[key] = resolve(value["root"], 0)
        if type(output[key]) is not AutoOrderedDict:
            _fail()
    if set(cache) != set(nodes):
        _fail()
    return output


def _tradeid_encode(value, depth=0, budget=None):
    if budget is not None:
        budget[0] += 3
        if budget[0] > 100_000:
            _fail()
    if depth > 8:
        _fail()
    if type(value) is tuple:
        if len(value) > 16:
            _fail()
        return {"kind": "tuple", "items": [_tradeid_encode(v, depth + 1, budget) for v in value]}
    if value is None or type(value) in (str, int, bool, float):
        if type(value) is float:
            _number(value, nullable=False)
        return {"kind": "scalar", "value": value}
    _fail()


def _tradeid_decode(value, depth=0):
    if depth > 8 or type(value) is not dict:
        _fail()
    if set(value) == {"kind", "value"} and value["kind"] == "scalar":
        if value["value"] is None or type(value["value"]) in (str, int, bool, float):
            if type(value["value"]) is float:
                _number(value["value"], nullable=False)
            return value["value"]
    if (
        set(value) == {"kind", "items"}
        and value["kind"] == "tuple"
        and type(value["items"]) is list
        and len(value["items"]) <= 16
    ):
        return tuple(_tradeid_decode(x, depth + 1) for x in value["items"])
    _fail()


def _tz_descriptor(tz):
    if tz is None:
        return {"kind": "none"}
    zone = getattr(tz, "zone", None) or getattr(tz, "key", None)
    if type(zone) is str and zone:
        return {"kind": "zone", "name": zone}
    if type(tz) is dt.timezone:
        return {
            "kind": "fixed",
            "name": tz.tzname(None),
            "seconds": tz.utcoffset(None).total_seconds(),
        }
    _fail()


def _date_encode(value, data_by_ref):
    if value is None:
        return None
    if type(value) is not dt.datetime:
        _fail()
    if value.tzinfo is None:
        return {"iso": value.isoformat(), "fold": value.fold, "tz": None}
    for ref, data in data_by_ref.items():
        if value.tzinfo is getattr(data, "_tz", None):
            return {"iso": value.isoformat(), "fold": value.fold, "tz": {"feed": ref}}
    if type(value.tzinfo) is dt.timezone:
        return {
            "iso": value.isoformat(),
            "fold": value.fold,
            "tz": {"fixed": value.tzinfo.tzname(None)},
        }
    _fail()


def _date_decode(value, data_by_ref):
    if value is None:
        return None
    if (
        type(value) is not dict
        or set(value) != {"iso", "fold", "tz"}
        or type(value["iso"]) is not str
        or value["fold"] not in (0, 1)
        or type(value["fold"]) is not int
    ):
        _fail()
    try:
        parsed = dt.datetime.fromisoformat(value["iso"]).replace(fold=value["fold"])
        tz = value["tz"]
        if tz is None:
            if parsed.tzinfo is not None:
                _fail()
        elif type(tz) is dict and set(tz) == {"feed"}:
            feed = data_by_ref[_key(tz["feed"])]
            trusted = getattr(feed, "_tz", None)
            if trusted is None:
                _fail()
            parsed = parsed.replace(tzinfo=trusted)
        elif (
            type(tz) is dict
            and set(tz) == {"fixed"}
            and parsed.tzinfo is not None
            and type(tz["fixed"]) is str
        ):
            offset = parsed.utcoffset()
            parsed = parsed.replace(tzinfo=dt.timezone(offset, tz["fixed"]))
        else:
            _fail()
        if parsed.isoformat() != value["iso"]:
            _fail()
        return parsed
    except (ValueError, TypeError, KeyError, OverflowError):
        _fail()


def _sources(data_by_ref):
    if not isinstance(data_by_ref, Mapping) or len(data_by_ref) > _MAX_OBJECTS:
        _fail()
    result = {}
    identities = set()
    for key, data in data_by_ref.items():
        _key(key)
        if not isinstance(data, DataBase) or id(data) in identities or len(data) < 1:
            _fail()
        identities.add(id(data))
        result[key] = data
    return result


def _feed_desc(data):
    name = getattr(data, "_name", "")
    if type(name) is not str:
        _fail()
    return {"name": name, "tz": _tz_descriptor(getattr(data, "_tz", None))}


def _check_maps(*maps):
    for value in maps:
        if not isinstance(value, Mapping) or len(value) > _MAX_OBJECTS:
            _fail()
        if any(type(k) is not str or not k or k != k.strip() for k in value):
            _fail()
        if len({id(v) for v in value.values()}) != len(value):
            _fail()


def _group(table, groups, obj, render):
    identity = id(obj)
    if identity not in table:
        key = str(len(table))
        table[identity] = key
        groups[key] = render(obj)
    return table[identity]


def _commission_descriptor(value, broker):
    cls = type(value)
    name = cls.__module__ + "." + cls.__name__
    if _COMMISSION_TYPES.get(name) is not cls:
        _fail()
    allowed = {"_param_manager", "p", "params", "_getcommission_accepts_role", *_COMMISSION_CACHES}
    if cls is ComminfoDC:
        allowed.add("broker")
    if set(vars(value)) - allowed:
        _fail()
    if value.p is not value.params or value.p._param_manager is not value._param_manager:
        _fail()
    expected = cls._compute_parameter_descriptors()
    manager = value._param_manager
    if set(manager._descriptors) != set(expected) or any(
        manager._descriptors[k] is not expected[k] for k in expected
    ):
        _fail()
    if (
        manager._global_callbacks
        or manager._change_callbacks
        or manager._dependencies
        or manager._dependents
        or manager._lazy_defaults
        or manager._in_transaction
    ):
        _fail()
    params = {
        key: manager._values[key]
        if key in manager._values
        else manager._value_cache[key]
        if key in manager._value_cache
        else expected[key].default
        for key in expected
    }
    caches = {key: getattr(value, key) for key in _COMMISSION_CACHES}
    for item in (*params.values(), *caches.values()):
        if item is not None and type(item) not in (bool, int, float, str):
            _fail()
        if type(item) is float and not math.isfinite(item):
            _fail()
    try:
        parameters = inspect.signature(value._getcommission).parameters
        accepts_role = "role" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        accepts_role = True
    if "_getcommission_accepts_role" in vars(value) and (
        type(value._getcommission_accepts_role) is not bool
        or value._getcommission_accepts_role != accepts_role
    ):
        _fail()
    attached = "broker" in vars(value)
    if attached and (cls is not ComminfoDC or value.broker is not broker):
        _fail()
    return {
        "type": name,
        "params": params,
        "caches": caches,
        "accepts_role": accepts_role,
        "broker_attached": attached,
    }


def _validate_commission_descriptor(value):
    _exact(value, ("type", "params", "caches", "accepts_role", "broker_attached"))
    cls = _COMMISSION_TYPES.get(value["type"])
    if cls is None or type(value["params"]) is not dict or type(value["caches"]) is not dict:
        _fail()
    if set(value["params"]) != set(cls._compute_parameter_descriptors()) or set(
        value["caches"]
    ) != set(_COMMISSION_CACHES):
        _fail()
    if type(value["accepts_role"]) is not bool or type(value["broker_attached"]) is not bool:
        _fail()
    if value["broker_attached"] and cls is not ComminfoDC:
        _fail()
    for item in (*value["params"].values(), *value["caches"].values()):
        if item is not None and type(item) not in (bool, int, float, str):
            _fail()
        if type(item) is float and not math.isfinite(item):
            _fail()


def _data_state(value, tables, groups):
    if type(value) is not OrderData:
        _fail()
    expected = set(_DATA_FIELDS) - {"plimit"} | {"_plimit", "exbits", "p1", "p2"}
    if set(vars(value)) != expected:
        _fail()

    def bits(seq):
        if type(seq) is not deque or len(seq) > _MAX_OBJECTS:
            _fail()
        tables["budget"][0] += len(seq)
        if tables["budget"][0] > 100_000:
            _fail()
        output = []
        for bit in seq:
            if type(bit) is not OrderExecutionBit or set(vars(bit)) != set(_BIT_FIELDS):
                _fail()

            def encode_bit(current):
                tables["budget"][0] += 20
                if tables["budget"][0] > 100_000:
                    _fail()
                return {key: _number(getattr(current, key)) for key in _BIT_FIELDS}

            output.append(_group(tables["bit_values"], groups["bit_values"], bit, encode_bit))
        return output

    bit_id = _group(tables["bits"], groups["bits"], value.exbits, bits)
    if not (
        type(value.p1) is int
        and type(value.p2) is int
        and 0 <= value.p1 <= value.p2 <= len(value.exbits)
    ):
        _fail()
    return {
        "fields": {name: _number(getattr(value, name)) for name in _DATA_FIELDS},
        "p1": value.p1,
        "p2": value.p2,
        "bits": bit_id,
    }


def capture_framework_state(*, orders, positions, trades, data_by_ref, owner, broker):
    """Capture exact supported BT graphs; unknown extensions and aliases are rejected."""
    _check_maps(orders, positions, trades)
    feeds = _sources(data_by_ref)
    if not isinstance(broker, BrokerBase):
        _fail()
    order_keys = {id(value): key for key, value in orders.items()}
    position_keys = {id(value): key for key, value in positions.items()}
    feed_keys = {id(value): key for key, value in feeds.items()}
    groups = {
        name: {}
        for name in (
            "params",
            "info",
            "info_nodes",
            "data",
            "bits",
            "bit_values",
            "history",
            "history_entries",
            "commissions",
        )
    }
    tables = {name: {} for name in groups}
    tables["info_heights"] = {}
    tables["history_parts"] = set()
    tables["budget"] = [20 * (len(orders) + len(positions) + len(trades)) + 4 * len(feeds)]
    if tables["budget"][0] > 100_000:
        _fail()

    def order_ref(value):
        if value is None:
            return None
        key = order_keys.get(id(value))
        if key is None or orders[key] is not value:
            _fail()
        return key

    def feed_ref(value):
        key = feed_keys.get(id(value))
        if key is None or feeds[key] is not value:
            _fail()
        return key

    def params(value):
        if set(vars(value)) != {
            "owner",
            "data",
            "size",
            "price",
            "pricelimit",
            "exectype",
            "valid",
            "tradeid",
            "oco",
            "trailamount",
            "trailpercent",
            "parent",
            "transmit",
            "simulated",
            "histnotify",
        }:
            _fail()
        if value.owner is not owner or any(
            type(getattr(value, n)) is not bool for n in ("transmit", "simulated", "histnotify")
        ):
            _fail()
        valid = value.valid
        if valid is not None:
            _number(valid, nullable=False)
        return {
            "data": feed_ref(value.data),
            "numbers": {k: _number(getattr(value, k)) for k in _PARAM_NUMBERS},
            "valid": valid,
            "tradeid": _tradeid_encode(value.tradeid, budget=tables["budget"]),
            "parent": order_ref(value.parent),
            "oco": order_ref(value.oco),
            "transmit": value.transmit,
            "simulated": value.simulated,
            "histnotify": value.histnotify,
        }

    def history(value):
        if type(value) is not list or len(value) > _MAX_OBJECTS:
            _fail()
        tables["budget"][0] += len(value)
        if tables["budget"][0] > 100_000:
            _fail()

        def encode_entry(item):
            if type(item) is not TradeHistory:
                _fail()
            tables["budget"][0] += 25
            if tables["budget"][0] > 100_000:
                _fail()
            if set(item) not in ({"status"}, {"status", "event"}) or set(item["status"]) != set(
                _HIST_STATUS
            ) | {"tz"}:
                _fail()
            event = None
            if "event" in item:
                if set(item["event"]) != {"order", "size", "price", "commission"}:
                    _fail()
                event = {
                    "order": order_ref(item["event"]["order"]),
                    **{k: _number(item["event"][k]) for k in ("size", "price", "commission")},
                }
                if event["order"] is None:
                    _fail()
            expected_closed = event is not None
            nodes = [item, item["status"]] + ([item["event"]] if event is not None else [])
            for node in nodes[1:]:
                if id(node) in tables["history_parts"]:
                    _fail()
                tables["history_parts"].add(id(node))
            if any(type(node) is not AutoOrderedDict and node is not item for node in nodes):
                _fail()
            if any(
                type(node._closed) is not bool or node._closed is not expected_closed
                for node in nodes
            ):
                _fail()
            return {
                "status": {k: _number(item["status"][k]) for k in _HIST_STATUS},
                "tz": _tz_descriptor(item["status"]["tz"]),
                "event": event,
            }

        return [
            _group(tables["history_entries"], groups["history_entries"], item, encode_entry)
            for item in value
        ]

    order_out = {}
    for key, order in sorted(orders.items()):
        if (
            type(order) not in (BuyOrder, SellOrder)
            or order.owner is not owner
            or (order.broker is not None and order.broker is not broker)
        ):
            _fail()
        expected = {
            "p",
            "params",
            "plen",
            "ref",
            "broker",
            "info",
            "comminfo",
            "triggered",
            "_active",
            "status",
            "_plimit",
            "created",
            "_limitoffset",
            "executed",
            "position",
            "dteos",
        }
        if set(vars(order)) - expected - {"notification_id", "replayed", "fee_correction_ids"}:
            _fail()
        if order.comminfo is not None and not isinstance(order.comminfo, CommInfoBase):
            _fail()
        if (
            order.params is not order.p
            or type(order.triggered) is not bool
            or type(order._active) is not bool
            or type(order.replayed) is not bool
        ):
            _fail()
        _integer(order.ref, minimum=1)
        if type(order.status) is not int or not 0 <= order.status <= 8:
            _fail()
        if order.notification_id is not None:
            _key(order.notification_id)
        fee_present = "fee_correction_ids" in vars(order)
        fee_ids = vars(order).get("fee_correction_ids")
        if fee_present and (
            type(fee_ids) is not tuple
            or len(fee_ids) > _MAX_OBJECTS
            or any(type(x) is not str or not x for x in fee_ids)
        ):
            _fail()
        pos = order.position
        if type(pos) is Position:
            if id(pos) not in position_keys:
                _fail()
            position = {"kind": "ref", "value": position_keys[id(pos)]}
        else:
            position = {"kind": "scalar", "value": _number(pos)}
        if order.comminfo is None:
            commission = None
        else:
            if broker.getcommissioninfo(order.data) is not order.comminfo:
                _fail()
            commission = _group(
                tables["commissions"],
                groups["commissions"],
                order.comminfo,
                lambda value: _commission_descriptor(value, broker),
            )
        order_out[key] = {
            "ref": order.ref,
            "side": "buy" if type(order) is BuyOrder else "sell",
            "params": _group(tables["params"], groups["params"], order.p, params),
            "info": _group(
                tables["info"],
                groups["info"],
                order.info,
                lambda info: _info_encode(
                    info,
                    tables["budget"],
                    tables["info_nodes"],
                    groups["info_nodes"],
                    order_keys,
                    tables["info_heights"],
                ),
            ),
            "created": _group(
                tables["data"],
                groups["data"],
                order.created,
                lambda d: _data_state(d, tables, groups),
            ),
            "executed": _group(
                tables["data"],
                groups["data"],
                order.executed,
                lambda d: _data_state(d, tables, groups),
            ),
            "plen": _number(order.plen),
            "status": order.status,
            "triggered": order.triggered,
            "active": order._active,
            "plimit": _number(order.plimit),
            "limitoffset": _number(order._limitoffset),
            "dteos": _number(order.dteos),
            "position": position,
            "comminfo": commission,
            "notification_id": order.notification_id,
            "replayed": order.replayed,
            "fee_correction_ids": None if fee_ids is None else list(fee_ids),
            "has_broker": order.broker is not None,
        }
    position_out = {}
    for key, position in sorted(positions.items()):
        if type(position) is not Position or set(vars(position)) - set(_POSITION_NUMBERS) - {
            "price_orig",
            "datetime",
            "updt",
        }:
            _fail()
        position_out[key] = {
            "numbers": {k: _number(getattr(position, k)) for k in _POSITION_NUMBERS},
            "price_orig_present": hasattr(position, "price_orig"),
            "price_orig": _number(getattr(position, "price_orig", None)),
            "datetime": _date_encode(position.datetime, feeds),
            "updt": _date_encode(position.updt, feeds),
        }
    trade_out = {}
    for key, trade in sorted(trades.items()):
        if type(trade) is not Trade:
            _fail()
        known = set(_TRADE_NUMBERS) | {
            "ref",
            "data",
            "tradeid",
            "status",
            "justopened",
            "isopen",
            "isclosed",
            "long",
            "historyon",
            "history",
            "notification_id",
            "replayed",
        }
        if set(vars(trade)) - known or any(
            type(getattr(trade, n)) is not bool
            for n in ("justopened", "isopen", "isclosed", "historyon", "replayed")
        ):
            _fail()
        if trade.long is not None and type(trade.long) is not bool:
            _fail()
        _integer(trade.ref, minimum=1)
        if type(trade.status) is not int or not 0 <= trade.status <= 2:
            _fail()
        if trade.notification_id is not None:
            _key(trade.notification_id)
        ref = feed_ref(trade.data)
        trusted_tz = getattr(trade.data, "_tz", None)
        if any(entry["status"]["tz"] is not trusted_tz for entry in trade.history):
            _fail()
        h = _group(tables["history"], groups["history"], trade.history, history)
        if any(
            groups["history_entries"][row]["tz"] != _tz_descriptor(getattr(trade.data, "_tz", None))
            for row in groups["history"][h]
        ):
            _fail()
        trade_out[key] = {
            "ref": trade.ref,
            "data": ref,
            "tradeid": _tradeid_encode(trade.tradeid, budget=tables["budget"]),
            "numbers": {k: _number(getattr(trade, k)) for k in _TRADE_NUMBERS},
            "status": trade.status,
            "justopened": trade.justopened,
            "isopen": trade.isopen,
            "isclosed": trade.isclosed,
            "long": trade.long,
            "historyon": trade.historyon,
            "history": h,
            "notification_id": trade.notification_id,
            "replayed": trade.replayed,
        }
    snapshot = {
        "schema_version": 1,
        "state": {
            "codec": 1,
            "feeds": {k: _feed_desc(v) for k, v in feeds.items()},
            "orders": order_out,
            "positions": position_out,
            "trades": trade_out,
            "groups": groups,
        },
    }
    _validate(snapshot, feeds)
    return snapshot


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _fail()
    return value


def _numbers(value, names):
    _exact(value, names)
    for item in value.values():
        _number(item)


def _bounded(snapshot):
    count = 0
    seen = set()
    stack = [(snapshot, 0)]
    while stack:
        obj, depth = stack.pop()
        count += 1
        if count > 100_000 or depth > 16:
            _fail()
        if type(obj) in (dict, list):
            if len(obj) > 100_000 - count:
                _fail()
            if id(obj) in seen:
                _fail()
            seen.add(id(obj))
        if type(obj) is dict:
            for key, value in obj.items():
                if type(key) is not str or not key:
                    _fail()
                stack.append((value, depth + 1))
        elif type(obj) is list:
            stack.extend((item, depth + 1) for item in obj)
        elif obj is not None and type(obj) not in (str, int, bool, float):
            _fail()
        elif type(obj) is float and not math.isfinite(obj):
            _fail()
    ensure_no_secret_keys(snapshot, "gateway_framework_projection")
    size = 0
    try:
        for fragment in json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).iterencode(snapshot):
            size += len(fragment.encode("utf-8", errors="strict"))
            if size > _MAX_BYTES:
                _fail()
    except (UnicodeError, TypeError, OverflowError):
        _fail()


def _validate_impl(snapshot, feeds):
    _bounded(snapshot)
    _exact(snapshot, ("schema_version", "state"))
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
        _fail()
    state = _exact(snapshot["state"], ("codec", "feeds", "orders", "positions", "trades", "groups"))
    if type(state["codec"]) is not int or state["codec"] != 1:
        _fail()
    for name in ("feeds", "orders", "positions", "trades", "groups"):
        if type(state[name]) is not dict or len(state[name]) > _MAX_OBJECTS:
            _fail()
    if set(state["feeds"]) != set(feeds):
        _fail()
    for key, data in feeds.items():
        if json.dumps(state["feeds"][key], sort_keys=True) != json.dumps(
            _feed_desc(data), sort_keys=True
        ):
            _fail()
    groups = _exact(
        state["groups"],
        (
            "params",
            "info",
            "info_nodes",
            "data",
            "bits",
            "bit_values",
            "history",
            "history_entries",
            "commissions",
        ),
    )
    for group in groups.values():
        if type(group) is not dict or len(group) > _MAX_OBJECTS:
            _fail()
        for key in group:
            _key(key)
    orders, positions, trades = state["orders"], state["positions"], state["trades"]
    for mapping in (orders, positions, trades):
        for key in mapping:
            _key(key)
    for item in groups["bit_values"].values():
        _numbers(item, _BIT_FIELDS)
        for name in _BIT_FIELDS:
            if name != "dt":
                _number(item[name], nullable=False)
    used_bit_values = set()
    for item in groups["bits"].values():
        if type(item) is not list or len(item) > _MAX_OBJECTS:
            _fail()
        for ref in item:
            if ref not in groups["bit_values"]:
                _fail()
            used_bit_values.add(ref)
    if used_bit_values != set(groups["bit_values"]):
        _fail()
    used_bits = set()
    for item in groups["data"].values():
        _exact(item, ("fields", "p1", "p2", "bits"))
        _numbers(item["fields"], _DATA_FIELDS)
        if item["bits"] not in groups["bits"]:
            _fail()
        if (
            type(item["p1"]) is not int
            or type(item["p2"]) is not int
            or not 0 <= item["p1"] <= item["p2"] <= len(groups["bits"][item["bits"]])
        ):
            _fail()
        used_bits.add(item["bits"])
    if used_bits != set(groups["bits"]):
        _fail()
    _info_decode_all(groups["info"], groups["info_nodes"], {key: object() for key in orders})
    for descriptor in groups["commissions"].values():
        _validate_commission_descriptor(descriptor)
    for item in groups["params"].values():
        _exact(
            item,
            (
                "data",
                "numbers",
                "valid",
                "tradeid",
                "parent",
                "oco",
                "transmit",
                "simulated",
                "histnotify",
            ),
        )
        if item["data"] not in feeds:
            _fail()
        _numbers(item["numbers"], _PARAM_NUMBERS)
        _number(item["numbers"]["size"], nullable=False)
        if (
            type(item["numbers"]["exectype"]) is not int
            or not 0 <= item["numbers"]["exectype"] <= 7
        ):
            _fail()
        _number(item["valid"])
        _tradeid_decode(item["tradeid"])
        for name in ("parent", "oco"):
            if item[name] is not None and item[name] not in orders:
                _fail()
        if any(type(item[name]) is not bool for name in ("transmit", "simulated", "histnotify")):
            _fail()
    for item in positions.values():
        _exact(item, ("numbers", "price_orig_present", "price_orig", "datetime", "updt"))
        _numbers(item["numbers"], _POSITION_NUMBERS)
        for name in ("size", "price", "upopened", "upclosed"):
            _number(item["numbers"][name], nullable=False)
        if type(item["price_orig_present"]) is not bool:
            _fail()
        _number(item["price_orig"])
        if not item["price_orig_present"] and item["price_orig"] is not None:
            _fail()
        _date_decode(item["datetime"], feeds)
        _date_decode(item["updt"], feeds)
    order_groups = {}
    used = {"params": set(), "info": set(), "data": set(), "history": set(), "commissions": set()}
    for item in orders.values():
        _exact(
            item,
            (
                "ref",
                "side",
                "params",
                "info",
                "created",
                "executed",
                "plen",
                "status",
                "triggered",
                "active",
                "plimit",
                "limitoffset",
                "dteos",
                "position",
                "comminfo",
                "notification_id",
                "replayed",
                "fee_correction_ids",
                "has_broker",
            ),
        )
        ref = _integer(item["ref"], minimum=1)
        if (
            item["side"] not in ("buy", "sell")
            or type(item["status"]) is not int
            or not 0 <= item["status"] <= 8
        ):
            _fail()
        for name in ("params", "info"):
            if item[name] not in groups[name]:
                _fail()
            used[name].add(item[name])
        for name in ("created", "executed"):
            if item[name] not in groups["data"]:
                _fail()
            used["data"].add(item[name])
        if any(
            type(item[name]) is not bool
            for name in ("triggered", "active", "replayed", "has_broker")
        ):
            _fail()
        if item["comminfo"] is not None:
            if item["comminfo"] not in groups["commissions"]:
                _fail()
            used["commissions"].add(item["comminfo"])
        for name in ("plen", "plimit", "limitoffset", "dteos"):
            _number(item[name])
        if item["notification_id"] is not None:
            _key(item["notification_id"])
        if item["fee_correction_ids"] is not None and (
            type(item["fee_correction_ids"]) is not list
            or any(type(x) is not str or not x for x in item["fee_correction_ids"])
        ):
            _fail()
        pos = _exact(item["position"], ("kind", "value"))
        if pos["kind"] == "ref":
            if pos["value"] not in positions:
                _fail()
        elif pos["kind"] == "scalar":
            _number(pos["value"])
        else:
            _fail()
        param = groups["params"][item["params"]]
        signature = (item["side"], param["data"], json.dumps(param["tradeid"], sort_keys=True))
        if ref in order_groups and order_groups[ref] != signature:
            _fail()
        order_groups[ref] = signature
    used_history_entries = set()
    for item in groups["history"].values():
        if type(item) is not list or len(item) > _MAX_OBJECTS:
            _fail()
        for ref in item:
            if ref not in groups["history_entries"]:
                _fail()
            used_history_entries.add(ref)
    if used_history_entries != set(groups["history_entries"]):
        _fail()
    for row in groups["history_entries"].values():
        _exact(row, ("status", "tz", "event"))
        _numbers(row["status"], _HIST_STATUS)
        if type(row["status"]["status"]) is not int or not 0 <= row["status"]["status"] <= 2:
            _fail()
        if row["event"] is not None:
            event = _exact(row["event"], ("order", "size", "price", "commission"))
            if event["order"] not in orders:
                _fail()
            for name in ("size", "price", "commission"):
                _number(event[name])
    trade_groups = {}
    trade_longs = {}
    history_timezones = {}
    for item in trades.values():
        _exact(
            item,
            (
                "ref",
                "data",
                "tradeid",
                "numbers",
                "status",
                "justopened",
                "isopen",
                "isclosed",
                "long",
                "historyon",
                "history",
                "notification_id",
                "replayed",
            ),
        )
        ref = _integer(item["ref"], minimum=1)
        if item["data"] not in feeds or item["history"] not in groups["history"]:
            _fail()
        used["history"].add(item["history"])
        _tradeid_decode(item["tradeid"])
        _numbers(item["numbers"], _TRADE_NUMBERS)
        for number in item["numbers"].values():
            _number(number, nullable=False)
        if type(item["status"]) is not int or not 0 <= item["status"] <= 2:
            _fail()
        if any(
            type(item[name]) is not bool
            for name in ("justopened", "isopen", "isclosed", "historyon", "replayed")
        ):
            _fail()
        if item["long"] is not None and type(item["long"]) is not bool:
            _fail()
        if item["notification_id"] is not None:
            _key(item["notification_id"])
        signature = (item["data"], json.dumps(item["tradeid"], sort_keys=True))
        if ref in trade_groups and trade_groups[ref] != signature:
            _fail()
        trade_groups[ref] = signature
        if item["long"] is not None:
            if ref in trade_longs and trade_longs[ref] is not item["long"]:
                _fail()
            trade_longs[ref] = item["long"]
        for entry_id in groups["history"][item["history"]]:
            actual_tz = getattr(feeds[item["data"]], "_tz", None)
            if entry_id in history_timezones and history_timezones[entry_id] is not actual_tz:
                _fail()
            history_timezones[entry_id] = actual_tz
            row = groups["history_entries"][entry_id]
            if row["tz"] != _tz_descriptor(getattr(feeds[item["data"]], "_tz", None)):
                _fail()
            if row["event"] is not None:
                order = orders[row["event"]["order"]]
                if groups["params"][order["params"]]["data"] != item["data"]:
                    _fail()
    for name in used:
        if used[name] != set(groups[name]):
            _fail()
    return state


def _validate(snapshot, feeds):
    try:
        return _validate_impl(snapshot, feeds)
    except Exception:
        _fail()


def restore_framework_state(snapshot, *, data_by_ref, owner, broker, commission_for_data):
    """Validate the whole graph, then construct detached BT objects with injected bindings."""
    feeds = _sources(data_by_ref)
    if not isinstance(broker, BrokerBase) or not callable(commission_for_data):
        _fail()
    state = _validate(snapshot, feeds)
    groups = state["groups"]
    comminfos = {}
    comm_group_objects = {}
    comm_object_groups = {}
    for item in state["orders"].values():
        if item["comminfo"] is not None:
            key = groups["params"][item["params"]]["data"]
            if key not in comminfos:
                chosen = commission_for_data(feeds[key])
                if chosen is not broker.getcommissioninfo(feeds[key]):
                    _fail()
                comminfos[key] = chosen
            chosen = comminfos[key]
            group = item["comminfo"]
            if (
                group in comm_group_objects
                and comm_group_objects[group] is not chosen
                or id(chosen) in comm_object_groups
                and comm_object_groups[id(chosen)] != group
            ):
                _fail()
            descriptor = _commission_descriptor(chosen, broker)
            if json.dumps(descriptor, sort_keys=True, allow_nan=False) != json.dumps(
                groups["commissions"][group], sort_keys=True, allow_nan=False
            ):
                _fail()
            comm_group_objects[group] = chosen
            comm_object_groups[id(chosen)] = group
    positions = {}
    for key, item in state["positions"].items():
        obj = Position()
        for name in _POSITION_NUMBERS:
            setattr(obj, name, item["numbers"][name])
        if item["price_orig_present"]:
            obj.price_orig = item["price_orig"]
        elif hasattr(obj, "price_orig"):
            del obj.price_orig
        obj.datetime = _date_decode(item["datetime"], feeds)
        obj.updt = _date_decode(item["updt"], feeds)
        positions[key] = obj
    bit_values = {}
    for key, row in groups["bit_values"].items():
        bit = OrderExecutionBit(
            row["dt"],
            row["size"],
            row["price"],
            row["closed"],
            row["closedvalue"],
            row["closedcomm"],
            row["opened"],
            row["openedvalue"],
            row["openedcomm"],
            row["pnl"],
            row["psize"],
            row["pprice"],
        )
        bit.value, bit.comm = row["value"], row["comm"]
        bit_values[key] = bit
    bit_groups = {
        key: deque(bit_values[ref] for ref in rows) for key, rows in groups["bits"].items()
    }
    data_groups = {}
    for key, item in groups["data"].items():
        obj = OrderData()
        for name in _DATA_FIELDS:
            setattr(obj, name, item["fields"][name])
        obj.p1, obj.p2, obj.exbits = item["p1"], item["p2"], bit_groups[item["bits"]]
        data_groups[key] = obj
    orders = {}
    order_refs = {}
    params_groups = {}
    for key, item in state["orders"].items():
        p = groups["params"][item["params"]]
        cls = BuyOrder if item["side"] == "buy" else SellOrder
        obj = cls(owner=owner, data=feeds[p["data"]], size=1, price=0.0, simulated=True)
        oldref = item["ref"]
        if oldref in order_refs:
            obj.ref = order_refs[oldref]
        else:
            order_refs[oldref] = obj.ref
        if item["params"] in params_groups:
            obj.p = params_groups[item["params"]]
            obj.params = obj.p
        else:
            params_groups[item["params"]] = obj.p
            for name in _PARAM_NUMBERS:
                setattr(obj.p, name, p["numbers"][name])
            obj.p.valid, obj.p.tradeid = p["valid"], _tradeid_decode(p["tradeid"])
            obj.p.transmit, obj.p.simulated, obj.p.histnotify = (
                p["transmit"],
                p["simulated"],
                p["histnotify"],
            )
        obj.created, obj.executed = data_groups[item["created"]], data_groups[item["executed"]]
        obj.plen, obj.status, obj.triggered, obj._active = (
            item["plen"],
            item["status"],
            item["triggered"],
            item["active"],
        )
        obj.plimit, obj._limitoffset, obj.dteos = item["plimit"], item["limitoffset"], item["dteos"]
        obj.position = (
            positions[item["position"]["value"]]
            if item["position"]["kind"] == "ref"
            else item["position"]["value"]
        )
        obj.broker = broker if item["has_broker"] else None
        obj.comminfo = comminfos[p["data"]] if item["comminfo"] is not None else None
        obj.notification_id, obj.replayed = item["notification_id"], item["replayed"]
        if item["fee_correction_ids"] is not None:
            obj.fee_correction_ids = tuple(item["fee_correction_ids"])
        orders[key] = obj
    info_groups = _info_decode_all(groups["info"], groups["info_nodes"], orders)
    for key, item in state["orders"].items():
        orders[key].info = info_groups[item["info"]]
    for key, param in groups["params"].items():
        obj = params_groups[key]
        obj.parent = None if param["parent"] is None else orders[param["parent"]]
        obj.oco = None if param["oco"] is None else orders[param["oco"]]
    history_entries = {}
    history_groups = {}
    for key, rows in groups["history"].items():
        data_ref = next(item["data"] for item in state["trades"].values() if item["history"] == key)
        tz = getattr(feeds[data_ref], "_tz", None)
        history = []
        for entry_id in rows:
            if entry_id not in history_entries:
                row = groups["history_entries"][entry_id]
                st = row["status"]
                entry = TradeHistory(*(st[name] for name in _HIST_STATUS), tz)
                event = row["event"]
                if event is not None:
                    entry.doupdate(
                        orders[event["order"]], event["size"], event["price"], event["commission"]
                    )
                history_entries[entry_id] = entry
            history.append(history_entries[entry_id])
        history_groups[key] = history
    trades = {}
    trade_refs = {}
    for key, item in state["trades"].items():
        obj = Trade(
            data=feeds[item["data"]],
            tradeid=_tradeid_decode(item["tradeid"]),
            historyon=item["historyon"],
        )
        oldref = item["ref"]
        if oldref in trade_refs:
            obj.ref = trade_refs[oldref]
        else:
            trade_refs[oldref] = obj.ref
        for name in _TRADE_NUMBERS:
            setattr(obj, name, item["numbers"][name])
        for name in (
            "status",
            "justopened",
            "isopen",
            "isclosed",
            "long",
            "historyon",
            "notification_id",
            "replayed",
        ):
            setattr(obj, name, item[name])
        obj.history = history_groups[item["history"]]
        trades[key] = obj
    return GatewayFrameworkObjects(
        MappingProxyType(orders),
        MappingProxyType(positions),
        MappingProxyType(trades),
        MappingProxyType(order_refs),
        MappingProxyType(trade_refs),
    )
