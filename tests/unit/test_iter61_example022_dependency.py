"""Offline dependency-boundary checks for the CryptoHFTData example."""

import importlib.util
import builtins
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples/backtest/022_cryptohftdata_sma/run.py"
CONDA = "/Users/yunjinqi/opt/anaconda3/bin/conda"
KEY_NAME = "ITER61_EXAMPLE022_FAKE_KEY"


def load_example(monkeypatch):
    spec = importlib.util.spec_from_file_location("iter61_example022", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_absent_package_is_blocked_before_feed(monkeypatch, capsys):
    example = load_example(monkeypatch)
    monkeypatch.setattr(example.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(example.bt, "Cerebro", lambda: pytest.fail("feed should not be created"))
    monkeypatch.setenv(KEY_NAME, "fake-key")

    assert example.main(["--run", "--api-key-env", KEY_NAME]) == 2
    assert "blocked" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("problem", ["missing-class", "noncallable", "missing-transitive"])
def test_incomplete_sdk_is_blocked_before_feed(problem, monkeypatch, capsys):
    example = load_example(monkeypatch)
    monkeypatch.setattr(example.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv(KEY_NAME, "fake-key")
    monkeypatch.setattr(example.bt, "Cerebro", lambda: pytest.fail("feed should not be created"))
    if problem == "missing-transitive":
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cryptohftdata":
                raise ModuleNotFoundError("synthetic missing transitive dependency")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
    else:
        sdk = types.ModuleType("cryptohftdata")
        if problem == "noncallable":
            sdk.CryptoHFTDataClient = None
        monkeypatch.setitem(sys.modules, "cryptohftdata", sdk)

    assert example.main(["--run", "--api-key-env", KEY_NAME]) == 2
    assert "blocked" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    ("package_source", "expected_code", "blocked"),
    [
        ("VALUE = 1\n", 2, True),
        ("CryptoHFTDataClient = None\n", 2, True),
        ("import iter61_nonexistent_sdk_dependency\n", 2, True),
        ("raise RuntimeError('synthetic-sdk-bug')\n", 1, False),
    ],
    ids=[
        "missing-client-class",
        "noncallable-client",
        "missing-transitive-dependency",
        "unrelated-runtime-error",
    ],
)
def test_fake_package_import_boundary(tmp_path, package_source, expected_code, blocked):
    package = tmp_path / "cryptohftdata"
    package.mkdir()
    (package / "__init__.py").write_text(package_source, encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(tmp_path), str(ROOT))),
        KEY_NAME: "iter61-fake-key-never-print",
    }
    result = subprocess.run(
        [
            CONDA,
            "run",
            "--no-capture-output",
            "-n",
            "base",
            "python",
            str(SCRIPT),
            "--run",
            "--api-key-env",
            KEY_NAME,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == expected_code, (result.stdout, result.stderr)
    assert ("blocked" in result.stdout.lower()) is blocked
    assert "iter61-fake-key-never-print" not in result.stdout + result.stderr
    if blocked:
        assert "traceback" not in result.stderr.lower()
    else:
        assert "synthetic-sdk-bug" in result.stderr


def test_available_sdk_uses_existing_feed_flow(tmp_path, monkeypatch, capsys):
    package = tmp_path / "cryptohftdata"
    package.mkdir()
    (package / "__init__.py").write_text("class CryptoHFTDataClient: pass\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sdk_spec = importlib.util.spec_from_file_location("cryptohftdata", package / "__init__.py")
    sdk = importlib.util.module_from_spec(sdk_spec)
    sdk_spec.loader.exec_module(sdk)
    monkeypatch.setitem(sys.modules, "cryptohftdata", sdk)
    monkeypatch.setenv(KEY_NAME, "fake-key")
    example = load_example(monkeypatch)
    calls = []

    class FakeCerebro:
        broker = type("Broker", (), {"getvalue": lambda self: 100.0})()

        def adddata(self, data):
            calls.append(("adddata", data))

        def addstrategy(self, strategy):
            calls.append(("addstrategy", strategy))

        def run(self):
            calls.append(("run",))

    def feed(**kwargs):
        calls.append(("feed", kwargs))
        return "fake-feed"

    monkeypatch.setattr(example.bt, "Cerebro", FakeCerebro)
    monkeypatch.setattr(example.bt.feeds, "CryptoHFTData", feed)
    assert example.main(["--run", "--api-key-env", KEY_NAME]) is None
    assert [item[0] for item in calls] == ["feed", "adddata", "addstrategy", "run"]
    assert calls[0][1]["api_key"] == "fake-key"
    assert "final portfolio value: 100.00" in capsys.readouterr().out
