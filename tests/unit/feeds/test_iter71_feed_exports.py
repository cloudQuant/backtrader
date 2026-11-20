"""Import-surface regressions for optional and lazy feed exports."""

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BLOCKER = r"""
import importlib.abc
import sys

sdk_attempts = []

class _BlockSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_py" or fullname.startswith("bt_api_py."):
            sdk_attempts.append(fullname)
            raise RuntimeError("blocked optional SDK import: " + fullname)
        return None

sys.meta_path.insert(0, _BlockSDK())
"""


def _run_isolated(source, *, light_import=False):
    env = os.environ.copy()
    env.pop("BACKTRADER_LIGHT_IMPORT", None)
    if light_import:
        env["BACKTRADER_LIGHT_IMPORT"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not pythonpath else str(_REPO_ROOT) + os.pathsep + pythonpath
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(source)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.stdout


@pytest.mark.parametrize("light_import", [False, True], ids=["default", "light"])
def test_feed_star_import_preserves_cohort_and_adds_factor_exports(light_import):
    if importlib.util.find_spec("bt_api_py") is None:
        pytest.skip("the legacy wildcard surface requires the optional SDK")
    output = _run_isolated(
        r"""
import backtrader as bt
import importlib
import warnings
feeds = bt.feeds
namespace = {}
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", DeprecationWarning)
    exec("from backtrader.feeds import *", namespace, namespace)

factor_exports = {
    "MarketFactorSourceBinding",
    "MarketFactorSourceCalendar",
    "MarketFactorSourceError",
    "MarketFactorTickProjection",
    "project_market_factor_tick",
}
assert factor_exports <= set(feeds.__all__)
assert factor_exports <= namespace.keys()
assert feeds._MARKET_COHORT_EXPORTS <= set(feeds.__all__)
assert feeds._MARKET_COHORT_EXPORTS <= namespace.keys()
sdk_cohort = importlib.import_module("bt_api_py.market_cohort")
factor_module = importlib.import_module("backtrader.feeds.market_factor_source")
assert all(namespace[name] is getattr(sdk_cohort, name) for name in feeds._MARKET_COHORT_EXPORTS)
assert all(namespace[name] is getattr(factor_module, name) for name in factor_exports)
assert "MarketCohortLeg" in dir(feeds)
assert "BlazeData" not in namespace
assert "BlazeData" not in feeds.__all__
assert "BlazeData" in dir(feeds)
assert not [item for item in caught if issubclass(item.category, DeprecationWarning)]
assert namespace["BtApiFeed"] is feeds.BtApiFeed
print("legacy cohort and new factor exports imported")
""",
        light_import=light_import,
    )
    assert "legacy cohort and new factor exports imported" in output


@pytest.mark.parametrize("light_import", [False, True], ids=["default", "light"])
def test_feed_star_import_retains_legacy_sdk_requirement(light_import):
    output = _run_isolated(
        _BLOCKER
        + r"""
import backtrader.feeds as feeds
namespace = {}
try:
    exec("from backtrader.feeds import *", namespace, namespace)
except RuntimeError as exc:
    assert "blocked optional SDK import" in str(exc)
else:
    raise AssertionError("legacy cohort star import stopped requesting the SDK")
assert sdk_attempts == ["bt_api_py"]
assert not any(name == "bt_api_py" or name.startswith("bt_api_py.") for name in sys.modules)
assert "MarketCohortLeg" not in feeds.__dict__
assert "MarketFactorSourceError" not in namespace
print("legacy SDK-backed star-import behavior retained")
""",
        light_import=light_import,
    )
    assert "legacy SDK-backed star-import behavior retained" in output


def test_cohort_exports_remain_explicitly_lazy():
    output = _run_isolated(
        _BLOCKER
        + r"""
import backtrader.feeds as feeds
assert "MarketCohortLeg" in dir(feeds)
assert "MarketCohortLeg" not in feeds.__dict__
namespace = {}
try:
    exec("from backtrader.feeds import MarketCohortLeg", namespace, namespace)
except RuntimeError as exc:
    assert "blocked optional SDK import" in str(exc)
else:
    raise AssertionError("explicit cohort import did not request the SDK")
assert sdk_attempts == ["bt_api_py"]
assert "MarketCohortLeg" not in feeds.__dict__
assert "MarketCohortLeg" not in namespace
assert not any(name == "bt_api_py" or name.startswith("bt_api_py.") for name in sys.modules)
print("cohort access stayed explicit")
""",
    )
    assert "cohort access stayed explicit" in output


def test_blaze_data_is_an_explicit_lazy_compatibility_export():
    output = _run_isolated(
        _BLOCKER
        + r"""
import warnings
import backtrader.feeds as feeds
assert "BlazeData" in dir(feeds)
assert "BlazeData" not in feeds.__dict__
assert "BlazeData" not in feeds.__all__

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", DeprecationWarning)
    namespace = {}
    exec("from backtrader.feeds import BlazeData", namespace, namespace)

assert namespace["BlazeData"].__name__ == "BlazeData"
assert namespace["BlazeData"].__module__ == "backtrader.feeds.blaze"
assert sum(issubclass(item.category, DeprecationWarning) for item in caught) == 1
assert not any(name == "blaze" or name.startswith("blaze.") for name in sys.modules)
assert not any(name == "bt_api_py" or name.startswith("bt_api_py.") for name in sys.modules)
assert sdk_attempts == []
print("BlazeData loaded lazily without Blaze or SDK")
""",
    )
    assert "BlazeData loaded lazily without Blaze or SDK" in output
