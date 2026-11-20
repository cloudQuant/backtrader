"""Cold-process checks for Bokeh's optional dependency boundary."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CHILD = textwrap.dedent(
    """\
    import os
    import sys
    import types

    repository_root, scenario, external_root = sys.argv[1:]
    assert "importlib.util" not in sys.modules

    local_package_root = os.path.join(repository_root, "backtrader", "bokeh")
    shadow_entry = os.path.join(repository_root, "backtrader")
    sys.path.insert(0, shadow_entry)
    if external_root:
        sys.path.append(external_root)
    original_path = sys.path[:]

    log_records = []

    class StubLogger:
        def debug(self, message, *args, **kwargs):
            log_records.append(("DEBUG", message, args))

        def warning(self, message, *args, **kwargs):
            log_records.append(("WARNING", message, args))

    logger = StubLogger()
    backtrader_package = types.ModuleType("backtrader")
    backtrader_package.__path__ = [os.path.join(repository_root, "backtrader")]
    utils_package = types.ModuleType("backtrader.utils")
    utils_package.__path__ = [os.path.join(repository_root, "backtrader", "utils")]
    logging_module = types.ModuleType("backtrader.utils.log_message")
    logging_module.get_logger = lambda name: logger
    sys.modules["backtrader"] = backtrader_package
    sys.modules["backtrader.utils"] = utils_package
    sys.modules["backtrader.utils.log_message"] = logging_module

    class ObserveBokehSearch:
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "bokeh":
                return None
            assert shadow_entry not in sys.path
            if scenario == "finder_error":
                raise ModuleNotFoundError(
                    "api_secret=synthetic-finder-sentinel",
                    name="bokeh",
                )
            return None

    sys.meta_path.insert(0, ObserveBokehSearch())

    local_bokeh = types.ModuleType("bokeh")
    local_bokeh.__file__ = os.path.join(local_package_root, "__init__.py")
    local_bokeh.__path__ = [local_package_root]
    local_bokeh.__spec__ = None
    local_bokeh.__package__ = "bokeh"
    sys.modules["bokeh"] = local_bokeh

    source_path = os.path.join(local_package_root, "__init__.py")
    with open(source_path, "r", encoding="utf-8") as source_file:
        source = source_file.read()

    try:
        exec(compile(source, source_path, "exec"), local_bokeh.__dict__)
    except ImportError as exc:
        assert scenario in (
            "finder_error",
            "nested_missing",
            "external_missing",
            "root_named_internal",
            "broken_import",
        )
        expected_names = {
            "finder_error": "bokeh",
            "nested_missing": "bokeh.internal_dependency",
            "external_missing": "tornado",
            "root_named_internal": "bokeh",
        }
        if scenario in expected_names:
            assert getattr(exc, "name", None) == expected_names[scenario]
        else:
            assert type(exc) is ImportError
    else:
        assert scenario in ("missing", "success")

    assert "importlib.util" in sys.modules
    assert sys.path == original_path
    assert sys.modules.get("bokeh") is not local_bokeh

    if scenario == "missing":
        assert ("DEBUG", "Optional third-party Bokeh package is not installed", ()) in log_records
        assert sys.modules.get("bokeh") is None
    elif scenario == "success":
        assert sys.modules["bokeh"].synthetic_external_bokeh is True
        assert not log_records
    elif scenario == "finder_error":
        assert log_records == [(
            "WARNING",
            "Failed to locate third-party Bokeh: import finder failed",
            (),
        )]
    else:
        assert any(record[0] == "WARNING" for record in log_records)
        assert "synthetic-bokeh-import-sentinel" not in repr(log_records)
        assert "synthetic-finder-sentinel" not in repr(log_records)
    """
)


def _write_fake_external_bokeh(tmp_path, scenario):
    package = tmp_path / "bokeh"
    package.mkdir()
    shadow_entry = repr(str(_REPOSITORY_ROOT / "backtrader"))
    check_shadow = f"import sys\nassert {shadow_entry} not in sys.path\n"

    if scenario == "success":
        body = "synthetic_external_bokeh = True\n"
    elif scenario == "nested_missing":
        body = (
            "raise ModuleNotFoundError("
            "'api_secret=synthetic-bokeh-import-sentinel', "
            "name='bokeh.internal_dependency')\n"
        )
    elif scenario == "external_missing":
        body = (
            "raise ModuleNotFoundError("
            "'api_secret=synthetic-bokeh-import-sentinel', name='tornado')\n"
        )
    elif scenario == "root_named_internal":
        body = (
            "raise ModuleNotFoundError("
            "'api_secret=synthetic-bokeh-import-sentinel', name='bokeh')\n"
        )
    else:
        body = "raise ImportError('api_secret=synthetic-bokeh-import-sentinel')\n"

    (package / "__init__.py").write_text(check_shadow + body, encoding="utf-8")
    return tmp_path


def _run_fresh_python(scenario, external_root=None):
    return subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            _CHILD,
            str(_REPOSITORY_ROOT),
            scenario,
            str(external_root or ""),
        ],
        cwd=str(_REPOSITORY_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cold_missing_bokeh_degrades_only_when_spec_is_none():
    result = _run_fresh_python("missing")
    assert result.returncode == 0, result.stdout + result.stderr


def test_cold_external_bokeh_load_restores_shadow_path(tmp_path):
    external_root = _write_fake_external_bokeh(tmp_path, "success")
    result = _run_fresh_python("success", external_root)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "scenario",
    (
        "finder_error",
        "nested_missing",
        "external_missing",
        "root_named_internal",
        "broken_import",
    ),
)
def test_cold_bokeh_errors_are_logged_propagated_and_restore_shadow_path(
    scenario, tmp_path
):
    external_root = None
    if scenario != "finder_error":
        external_root = _write_fake_external_bokeh(tmp_path, scenario)
    result = _run_fresh_python(scenario, external_root)
    assert result.returncode == 0, result.stdout + result.stderr
