"""Fresh-process checks for the shared lazy dependency guard and example caller."""

import json
import os
from pathlib import Path
import subprocess
import sys

evidence = Path(__file__).resolve().parent
source = Path((evidence / "source-origin.txt").read_text().strip()).resolve().parent.parent
environment = os.environ.copy()
for name in ("PYTHONPATH", "PYTHONHOME", "BACKTRADER_USE_INSTALLED"):
    environment.pop(name, None)
probes = {
    "parent_import_without_pandas": """
import importlib.abc, sys
class BlockPandas(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pandas" or fullname.startswith("pandas."):
            raise ModuleNotFoundError("blocked pandas for dependency probe")
sys.meta_path.insert(0, BlockPandas())
import backtrader.research
""",
    "research_guard_without_pandas": """
import backtrader
import importlib.abc, sys
for name in tuple(sys.modules):
    if name == "pandas" or name.startswith("pandas."):
        del sys.modules[name]
class BlockPandas(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pandas" or fullname.startswith("pandas."):
            raise ModuleNotFoundError("blocked pandas for dependency probe")
sys.meta_path.insert(0, BlockPandas())
import backtrader.research
from backtrader.research import dataset, storage, field_validation, factor_strategy, specs
from backtrader.errors import DependencyError
assert "pandas" not in sys.modules
assert "fincore" not in sys.modules
for module in (dataset, storage, field_validation, factor_strategy):
    assert module.require_research_runtime is specs.require_research_runtime
    try:
        module.require_research_runtime()
    except DependencyError as exc:
        assert exc.code == "DEPENDENCY_UNAVAILABLE"
    else:
        raise AssertionError(module.__name__)
print("PASS: lazy import and all four shared guards reject missing pandas")
""",
    "minimum_python": """
import sys
from backtrader.research import dataset, storage, field_validation, factor_strategy, specs
from backtrader.errors import DependencyError
original = sys.version_info
try:
    sys.version_info = (3, 10, 0)
    for module in (dataset, storage, field_validation, factor_strategy):
        try:
            module.require_research_runtime()
        except DependencyError as exc:
            assert exc.code == "DEPENDENCY_UNAVAILABLE"
        else:
            raise AssertionError(module.__name__)
finally:
    sys.version_info = original
print("PASS: simulated below-minimum version rejected by shared guard")
""",
    "daily_example_metadata": """
import importlib.util
from pathlib import Path
from backtrader.research.alpha101 import get_alpha
path = Path("examples/backtest/027_alpha003_panel_acceptance/run_daily.py")
spec = importlib.util.spec_from_file_location("daily_example_metadata", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
params = module._params(Path.cwd())
assert params["formula"] == get_alpha(3).formula
assert params["alpha_id"] == 3
print("PASS: real daily runner reads canonical class formula without data I/O")
""",
}
results = {}
for name, code in probes.items():
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=source,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    results[name] = {"exit_code": result.returncode, "output": result.stdout}
    if name == "parent_import_without_pandas":
        assert result.returncode != 0 and "analyzers/pyfolio.py" in result.stdout
        results[name]["status"] = "EXPECTED_UNCHANGED_PARENT_IMPORT_LIMITATION"
        continue
    assert result.returncode == 0, result.stdout
    print(result.stdout.strip())
(evidence / "runtime-probes.json").write_text(
    json.dumps(
        {
            "status": "PASS",
            "source_export": str(source),
            "python": sys.version,
            "minimum_version_check": "simulated sys.version_info, not CPython 3.10 execution",
            "lazy_import_scope": "research package after normal parent import; parent analyzers.pyfolio imports pandas eagerly",
            "probes": results,
        },
        indent=2,
    )
    + "\n"
)
