"""R71-031 regressions for callbacks created while projecting route snapshots."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from backtrader.stores import _account_position_projection as projection


def _sdk_contract_stubs(monkeypatch):
    package = ModuleType("bt_api_py")
    package.__path__ = []

    aliases = ModuleType("bt_api_py.instrument_metadata_aliases")
    aliases.configured_position_quantity_unit = lambda *_args, **_kwargs: "contracts"

    account_position = ModuleType("bt_api_py.account_position_read")
    account_position.position_read_has_positions = lambda *_args, **_kwargs: True
    account_position.validate_position_read_batch = lambda *_args, **_kwargs: None
    account_position.validate_position_read_row = lambda *_args, **_kwargs: None

    monkeypatch.setitem(sys.modules, "bt_api_py", package)
    monkeypatch.setitem(sys.modules, aliases.__name__, aliases)
    monkeypatch.setitem(sys.modules, account_position.__name__, account_position)


def test_deferred_feed_lookup_callbacks_keep_each_route_and_read(monkeypatch):
    _sdk_contract_stubs(monkeypatch)

    class AlphaInstrument:
        pass

    class BetaInstrument:
        pass

    alpha = AlphaInstrument()
    beta = BetaInstrument()
    reads = [
        SimpleNamespace(
            exchange_name="alpha-route",
            positions=[alpha],
            account_position_type=object,
            market_instrument_key_type=AlphaInstrument,
        ),
        SimpleNamespace(
            exchange_name="beta-route",
            positions=[beta],
            account_position_type=object,
            market_instrument_key_type=BetaInstrument,
        ),
    ]
    store = SimpleNamespace(
        _sdk_position_read_adapter=SimpleNamespace(
            read=lambda *_args, **_kwargs: SimpleNamespace(routes=reads)
        ),
        _sdk_exchanges=("alpha-route", "beta-route"),
        _ensure_api_ready=lambda: None,
        _resolve_sdk_route_name=lambda name: name,
        _sdk_position_query_timeout=lambda: 1.0,
        _api=object(),
        _data_feeds=[
            SimpleNamespace(
                _dataname="alpha-feed",
                p=SimpleNamespace(dataname="alpha-feed"),
            ),
            SimpleNamespace(
                _dataname="beta-feed",
                p=SimpleNamespace(dataname="beta-feed"),
            ),
        ],
        _sdk_exchange=lambda name: {
            "alpha-feed": "alpha-route",
            "beta-feed": "beta-route",
        }[name],
        get_market_instrument_key=lambda name: {
            "alpha-feed": alpha,
            "beta-feed": beta,
        }[name],
        contract_metadata={},
    )
    deferred = []

    def defer_feed_lookup(_rows, **kwargs):
        deferred.append(kwargs["feed_name_for"])
        return []

    monkeypatch.setattr(projection, "project_account_position_rows", defer_feed_lookup)

    class ProjectionError(Exception):
        pass

    assert projection.project_store_account_positions(
        store,
        error_type=ProjectionError,
        missing_dependency_error_type=ProjectionError,
        contract_metadata_aliases=lambda *_args, **_kwargs: (),
    ) == []
    assert len(deferred) == 2

    # Exercise callbacks after both routes have been visited. Each closure must
    # still use the route and key type that were current when it was created.
    assert deferred[0](alpha) == "alpha-feed"
    assert deferred[1](beta) == "beta-feed"
