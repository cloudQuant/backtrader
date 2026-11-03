"""Iteration 60.08 (G5): the Backtrader service read session defaults to typed.

``open_service_read_session`` passes the account ``snapshot_format`` to the SDK
observation assembly. Without a selection it must request the typed Base
account contract; ``generic`` stays an explicit legacy choice; anything else
is refused before any SDK client starts.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.service_observation_clients")

import bt_api_py.service_observation_clients as sdk_clients  # noqa: E402

from backtrader.service.service_observation import open_service_read_session  # noqa: E402


class _Stop(Exception):
    pass


def _service(snapshot_format=None):
    account = {
        "mount": "store.account",
        "account_ref": "account-a",
        "key": {},
        "required_coverage": [],
    }
    if snapshot_format is not None:
        account["snapshot_format"] = snapshot_format
    return {"account": account}


@pytest.fixture
def captured(monkeypatch):
    seen = []

    def fake_open(sdk_config, **_kwargs):
        seen.append(sdk_config["account"])
        raise _Stop

    monkeypatch.setattr(sdk_clients, "open_service_observation_clients", fake_open)
    return seen


@pytest.mark.parametrize("selection, expected", [(None, "typed"), ("typed", "typed"),
                                                 ("generic", "generic")])
def test_typed_is_the_default_and_generic_is_explicit(captured, selection, expected):
    with pytest.raises(_Stop):
        open_service_read_session(_service(selection), instruments=())
    assert captured[-1]["snapshot_format"] == expected


@pytest.mark.parametrize("bad", ["TYPED", "json", 1, None])
def test_unknown_formats_are_refused_before_the_sdk(captured, bad):
    service = _service()
    service["account"]["snapshot_format"] = bad
    with pytest.raises(Exception) as raised:
        open_service_read_session(service, instruments=())
    assert getattr(raised.value, "code", None) == "SERVICE_ACCOUNT_SNAPSHOT_FORMAT_INVALID"
    assert captured == []
