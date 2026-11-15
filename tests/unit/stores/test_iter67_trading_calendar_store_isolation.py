"""Two Stores sharing one BtApi keep their own calendar query directories.

Iteration 67, handoff item 3: a borrowed shared facade must never have its
calendar configuration rewritten by Store construction, and one Store's
configuration must not change another Store's read-only query.
"""

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="needs the CTP calendar provider")

from bt_api_py.bt_api import BtApi  # noqa: E402
from bt_api_py.trading_calendar_binding import SIMULATION_ONLY  # noqa: E402

from tests.unit.feeds.test_btapifeed_trading_calendar import (  # noqa: E402
    MONDAY,
    publish,
)
from tests.unit.stores.test_iter67_calendar_config_wiring import local_store  # noqa: E402
from tests.unit.stores.test_iter67_trading_calendar_status import ROUTE  # noqa: E402


def query(store):
    return store.trading_calendar_query(
        ROUTE,
        venue="XSH",
        kind="future",
        product="cu",
        contract="cu2601",
        trading_day=MONDAY,
        mode=SIMULATION_ONLY,
    )


def test_store_queries_and_shared_facade_configuration_stay_isolated(monkeypatch, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    publish(first / "calendars/ctp", publication_id="p1", version_id="v1", start="09:00")
    publish(
        second / "calendars/ctp",
        publication_id="p9",
        version_id="v9",
        start="10:00",
        mock=False,
    )
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    reconfigurations = []
    original_configure = api.configure_trading_calendar_status

    def configure(*, route_roots):
        reconfigurations.append(dict(route_roots))
        return original_configure(route_roots=route_roots)

    monkeypatch.setattr(api, "configure_trading_calendar_status", configure)
    store_a, _ = local_store(monkeypatch, first, api=api)
    store_b, _ = local_store(monkeypatch, second, api=api)
    assert reconfigurations == []
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"

    value_a, value_b = query(store_a), query(store_b)
    assert (value_a.status, value_a.calendar_ref) == ("COMPLETE", "v1")
    assert (value_b.status, value_b.calendar_ref) == ("COMPLETE", "v9")
    assert value_a.windows[-1].start_local.hour == 9
    assert value_b.windows[-1].start_local.hour == 10
    assert (value_a.source_classification, value_b.source_classification) == (
        "DECLARED_MOCK",
        "UNVERIFIED",
    )

    # An external facade reconfiguration belongs to facade-backed routes only.
    api.configure_trading_calendar_status(
        route_roots={ROUTE: str(second / "calendars/ctp")}
    )
    assert query(store_a).calendar_ref == "v1"
    assert query(store_b).calendar_ref == "v9"
    assert api.trading_calendar_status(ROUTE).version_id == "v9"
