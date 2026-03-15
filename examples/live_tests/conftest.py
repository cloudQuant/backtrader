"""Serial execution controls for live CTP pytest modules.

These tests require real network access (SimNow CTP credentials) and are
excluded from the normal ``pytest tests`` run.  Execute manually via::

    pytest examples/live_tests -v
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure the project root is on sys.path so ``tests.fixtures`` resolves.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_SIMNOW_SERIAL_GROUP = "simnow_ctp_serial"
_SIMNOW_SERIAL_ORDER = (
    ("test_simnow_ctp.py", "test_simnow_connection"),
    ("test_simnow_ctp.py", "test_simnow_market_data"),
    ("test_simnow_ctp.py", "test_simnow_account_balance"),
    ("test_simnow_ctp.py", "test_simnow_order_placement"),
    ("test_simnow_ctp.py", "test_simnow_real_tick_subscription"),
    ("test_simnow_ctp.py", "test_simnow_positions"),
    ("test_simnow_ctp.py", "test_simnow_full_trading_cycle"),
    ("test_simnow_ctp.py", "test_all_simnow_environments"),
    ("test_simnow_trade_logger_certification.py", "test_simnow_trade_logger_runtime_audit"),
    ("test_simnow_trade_logger_certification.py", "test_simnow_trade_logger_local_error_audit"),
)
_SIMNOW_SERIAL_MODULES = {module_name for module_name, _test_name in _SIMNOW_SERIAL_ORDER}
_SIMNOW_ORDER_LOOKUP = {
    (module_name, test_name): index
    for index, (module_name, test_name) in enumerate(_SIMNOW_SERIAL_ORDER)
}
_SERIAL_WAIT_SECONDS = 0.2
_SERIAL_TIMEOUT_SECONDS = 60 * 60


def _item_module_name(item) -> str:
    """Return the collected test module filename."""
    item_path = getattr(item, "path", None)
    if item_path is not None:
        return Path(item_path).name

    return Path(str(item.fspath)).name


def _is_simnow_serial_item(item) -> bool:
    """Return whether a collected item belongs to the serialized SimNow suite."""
    return _item_module_name(item) in _SIMNOW_SERIAL_MODULES


def pytest_collection_modifyitems(config, items):
    """Assign a stable serial order to SimNow live cases across xdist workers."""
    simnow_items = [item for item in items if _is_simnow_serial_item(item)]
    if not simnow_items:
        return

    ordered_simnow_items = sorted(
        simnow_items,
        key=lambda item: (
            _SIMNOW_ORDER_LOOKUP.get(
                (_item_module_name(item), item.name),
                len(_SIMNOW_SERIAL_ORDER),
            ),
            item.nodeid,
        ),
    )

    original_positions = [index for index, item in enumerate(items) if _is_simnow_serial_item(item)]
    for position, item in zip(original_positions, ordered_simnow_items):
        items[position] = item

    total = len(ordered_simnow_items)
    for index, item in enumerate(ordered_simnow_items):
        item.add_marker(pytest.mark.simnow_serial(index=index, total=total, group=_SIMNOW_SERIAL_GROUP))
        item.add_marker(pytest.mark.xdist_group(name=_SIMNOW_SERIAL_GROUP))


def _lock_file(fileobj):
    """Acquire an exclusive inter-process lock."""
    if os.name == "nt":
        fileobj.seek(0)
        fileobj.write("0")
        fileobj.flush()
        msvcrt.locking(fileobj.fileno(), msvcrt.LK_LOCK, 1)
        return

    fcntl.flock(fileobj.fileno(), fcntl.LOCK_EX)


def _unlock_file(fileobj):
    """Release an exclusive inter-process lock."""
    if os.name == "nt":
        fileobj.seek(0)
        msvcrt.locking(fileobj.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl.flock(fileobj.fileno(), fcntl.LOCK_UN)


def _serial_state_paths(config, run_id: str, group_name: str) -> tuple[Path, Path]:
    """Build unique lock/state file paths for the current pytest session."""
    root = str(config.rootpath)
    digest = hashlib.sha1(f"{root}:{run_id}:{group_name}".encode("utf-8")).hexdigest()[:16]
    base = Path(tempfile.gettempdir()) / f"backtrader-simnow-serial-{digest}"
    return base.with_suffix(".lock"), base.with_suffix(".json")


def _load_serial_state(state_path: Path) -> dict[str, int]:
    """Load the shared serial-execution state from disk."""
    if not state_path.exists():
        return {"next_index": 0}

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"next_index": 0}


def _save_serial_state(state_path: Path, state: dict[str, int]) -> None:
    """Persist the shared serial-execution state to disk."""
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _get_testrun_uid(request) -> str:
    """Get the xdist test-run uid when available, with a local fallback."""
    try:
        return str(request.getfixturevalue("testrun_uid"))
    except pytest.FixtureLookupError:
        return f"local-{os.getpid()}"


@pytest.fixture(autouse=True)
def _serialize_simnow_ctp_cases(request):
    """Run SimNow live tests one-by-one and in a deterministic order."""
    marker = request.node.get_closest_marker("simnow_serial")
    if marker is None:
        yield
        return

    order_index = int(marker.kwargs["index"])
    total = int(marker.kwargs["total"])
    group_name = str(marker.kwargs.get("group") or _SIMNOW_SERIAL_GROUP)
    lock_path, state_path = _serial_state_paths(request.config, _get_testrun_uid(request), group_name)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + max(_SERIAL_TIMEOUT_SECONDS, total * 600)
    lock_file = lock_path.open("a+", encoding="utf-8")

    while True:
        _lock_file(lock_file)
        state = _load_serial_state(state_path)
        if int(state.get("next_index", 0)) == order_index:
            break

        _unlock_file(lock_file)
        if time.monotonic() >= deadline:
            pytest.fail(
                f"Timed out waiting for ordered SimNow slot {order_index + 1}/{total} "
                f"for {request.node.nodeid}"
            )
        time.sleep(_SERIAL_WAIT_SECONDS)

    try:
        yield
    finally:
        state = _load_serial_state(state_path)
        state["next_index"] = max(int(state.get("next_index", 0)), order_index + 1)
        _save_serial_state(state_path, state)
        _unlock_file(lock_file)
        lock_file.close()


@pytest.fixture
def btapi_client():
    """Provide a fake bt_api_py client for non-CTP live-surface tests."""
    return FakeBtApiClient(
        balance={"cash": 2000.0, "value": 2150.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
        live={DEFAULT_SYMBOL: [make_bar(1, 100.5, 102.0, 100.0, 101.0)]},
    )


@pytest.fixture
def btapi_store(btapi_client):
    """Provide a started BtApiStore fixture for placeholder live tests."""
    store = make_store(api=btapi_client)
    store.start()
    yield store
    store.stop()
