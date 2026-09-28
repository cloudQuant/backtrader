from __future__ import annotations

import ast
import builtins
import importlib.util
import io
import os
import pathlib
import socket
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path(r"D:\source_code\backtrader")
TARGETS = {
    "013_1_midfreq_cross_arbitrage": ROOT / "candidate" / "examples" / "013_1_midfreq_cross_arbitrage" / "ctp_example_support.py",
    "013_2_highfreq_calendar_arbitrage": ROOT / "candidate" / "examples" / "013_2_highfreq_calendar_arbitrage" / "ctp_example_support.py",
}

class Refusal(RuntimeError):
    pass

class Bomb:
    def __getattr__(self, name):
        raise AssertionError(f"helper touched forbidden input/constructor: {name}")

parent = types.ModuleType("backtrader_runtime")
parent.__path__ = []
legacy = types.ModuleType("backtrader_runtime.legacy")
def legacy_direct_execution_error(component):
    return Refusal("legacy_direct_execution_not_supported")
legacy.legacy_direct_execution_error = legacy_direct_execution_error
sys.modules["backtrader_runtime"] = parent
sys.modules["backtrader_runtime.legacy"] = legacy


def _is_env_path(file):
    try:
        return pathlib.Path(os.fsdecode(os.fspath(file))).name.casefold() == ".env"
    except (TypeError, ValueError, OSError):
        return False


class DefaultDenyAndInertImportTests(unittest.TestCase):
    def test_each_legacy_store_and_broker_helper_fails_before_inputs(self):
        for label, path in TARGETS.items():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name in {"create_live_store", "create_live_broker"}]
            self.assertEqual({node.name for node in selected}, {"create_live_store", "create_live_broker"}, label)
            namespace = {"__name__": "isolated_candidate." + label, "BtApiStore": Bomb, "BtApiBroker": Bomb}
            exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
            with self.subTest(module=label, helper="create_live_store"):
                with self.assertRaisesRegex(Refusal, "legacy_direct_execution_not_supported"):
                    namespace["create_live_store"](Bomb())
            with self.subTest(module=label, helper="create_live_broker"):
                with self.assertRaisesRegex(Refusal, "legacy_direct_execution_not_supported"):
                    namespace["create_live_broker"](Bomb(), Bomb())

    def test_import_is_inert_for_dotenv_file_reads_sdk_and_network(self):
        old_modules = {name: sys.modules.get(name) for name in ("dotenv",)}
        dotenv_imports = []
        dotenv_calls = []
        env_reads = []
        sdk_imports = []
        network_calls = []

        fake_dotenv = types.ModuleType("dotenv")
        def trap_load_dotenv(*args, **kwargs):
            dotenv_calls.append((args, kwargs))
            raise AssertionError("dotenv.load_dotenv called during compatibility-module import")
        fake_dotenv.load_dotenv = trap_load_dotenv
        sys.modules["dotenv"] = fake_dotenv

        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "dotenv" or name.startswith("dotenv."):
                dotenv_imports.append(name)
            if name == "bt_api_py" or name.startswith(("bt_api_py.", "bt_api_ctp.", "bt_api_execution.")):
                sdk_imports.append(name)
                raise AssertionError("SDK import attempted during compatibility-module import")
            return original_import(name, *args, **kwargs)

        original_open = builtins.open
        original_io_open = io.open
        original_os_open = os.open
        def guarded_open(original, label):
            def call(file, *args, **kwargs):
                if _is_env_path(file):
                    env_reads.append((label, os.fsdecode(os.fspath(file))))
                    raise AssertionError(".env file read attempted during compatibility-module import")
                return original(file, *args, **kwargs)
            return call

        original_socket_methods = {
            "getaddrinfo": socket.getaddrinfo,
            "create_connection": socket.create_connection,
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "sendto": socket.socket.sendto,
        }
        def deny_network(*args, **kwargs):
            network_calls.append((args, kwargs))
            raise AssertionError("network access attempted during compatibility-module import")

        builtins.__import__ = guarded_import
        builtins.open = guarded_open(original_open, "builtins.open")
        io.open = guarded_open(original_io_open, "io.open")
        os.open = guarded_open(original_os_open, "os.open")
        socket.getaddrinfo = deny_network
        socket.create_connection = deny_network
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        socket.socket.sendto = deny_network
        loaded = []
        try:
            sys.path.insert(0, str(REPO))
            for label, path in TARGETS.items():
                module_name = "isolated_inert_import_" + label
                spec = importlib.util.spec_from_file_location(module_name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                loaded.append(module)
        finally:
            sys.path.remove(str(REPO))
            builtins.__import__ = original_import
            builtins.open = original_open
            io.open = original_io_open
            os.open = original_os_open
            for name, method in original_socket_methods.items():
                if name in ("getaddrinfo", "create_connection"):
                    setattr(socket, name, method)
                else:
                    setattr(socket.socket, name, method)
            for name in ("dotenv",):
                prior = old_modules[name]
                if prior is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = prior
            for module in loaded:
                sys.modules.pop(module.__name__, None)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(dotenv_imports, [])
        self.assertEqual(dotenv_calls, [])
        self.assertEqual(env_reads, [])
        self.assertEqual(sdk_imports, [])
        self.assertEqual(network_calls, [])
        for module in loaded:
            self.assertTrue(callable(module.load_dotenv_if_available))

if __name__ == "__main__":
    unittest.main(verbosity=2)
