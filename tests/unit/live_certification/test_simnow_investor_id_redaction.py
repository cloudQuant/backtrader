import contextlib
import importlib
import io
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SIMNOW_SUITE_DIR = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
_MISSING = object()


def _load_runtime_without_reading_dotenv():
    """Import the runtime while replacing dotenv with a no-op module."""
    previous_path = sys.path[:]
    previous_common_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "common" or name.startswith("common.")
    }
    previous_dotenv = sys.modules.get("dotenv", _MISSING)

    for name in previous_common_modules:
        sys.modules.pop(name, None)

    dotenv_stub = types.ModuleType("dotenv")

    def no_op_load_dotenv(*args, **kwargs):
        return None

    dotenv_stub.load_dotenv = no_op_load_dotenv
    sys.modules["dotenv"] = dotenv_stub
    sys.path.insert(0, str(SIMNOW_SUITE_DIR))
    try:
        return importlib.import_module("common.runtime")
    finally:
        sys.path[:] = previous_path
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_common_modules)
        if previous_dotenv is _MISSING:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = previous_dotenv


@pytest.fixture(scope="module")
def simnow_runtime():
    return _load_runtime_without_reading_dotenv()


@pytest.mark.parametrize(
    ("investor_id", "expected_mask"),
    [
        ("123456789", "12***89"),
        ("1234", "****"),
        ("7", "****"),
        ("****", "••••"),
        ("12***34", "***"),
    ],
)
def test_started_store_never_displays_complete_investor_id(
    simnow_runtime, monkeypatch, investor_id, expected_mask
):
    runtime = simnow_runtime
    config = {
        "investor_id": investor_id,
        "td_address": "tcp://trading.invalid:1",
        "md_address": "tcp://market.invalid:2",
    }

    class FakeStore:
        def __init__(self, provider, **kwargs):
            assert provider == "ctp"
            assert kwargs == config

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "BtApiStore", FakeStore)
    monkeypatch.setattr(runtime.cfg, "create_config", lambda _env_key: config)
    monkeypatch.setitem(
        runtime.cfg.SIMNOW_ENVIRONMENTS,
        "new_7x24",
        {"name": "单测环境", "td_address": "", "md_address": ""},
    )
    monkeypatch.delenv("CERTIFICATION_REPORT_DIR", raising=False)
    monkeypatch.delenv("CERTIFICATION_CASE_ID", raising=False)

    output = io.StringIO()
    with contextlib.redirect_stdout(output), runtime.started_store(
        env_key="new_7x24", case_id="unit", report_dir=""
    ):
        pass

    display_text = output.getvalue()
    assert investor_id not in display_text
    assert f"InvestorID: {expected_mask}" in display_text
