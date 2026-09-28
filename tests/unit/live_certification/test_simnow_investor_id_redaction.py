import importlib
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
def test_investor_id_display_value_never_contains_complete_investor_id(
    simnow_runtime, investor_id, expected_mask
):
    runtime = simnow_runtime
    display_text = f"InvestorID: {runtime._mask_investor_id(investor_id)}"
    assert investor_id not in display_text
    assert f"InvestorID: {expected_mask}" in display_text
