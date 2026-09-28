import ast
import builtins
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(os.environ.get("BT_GATEWAY_WRAPPER_TEST_SOURCE", Path(__file__).resolve().parents[1] / "candidate" / "backtrader" / "stores" / "btapistore.py"))


class BtApiStoreError(RuntimeError):
    pass


class BtApiMissingDependencyError(RuntimeError):
    pass


class CtpGatewayWrapperGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        factory = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_create_ctp_gateway_wrapper_class"
        )
        namespace = {
            "BtApiMissingDependencyError": BtApiMissingDependencyError,
            "BtApiStoreError": BtApiStoreError,
            "_safe_log": lambda *args, **kwargs: None,
        }
        exec(compile(ast.Module(body=[factory], type_ignores=[]), str(SOURCE), "exec"), namespace)
        cls.factory = staticmethod(namespace["_create_ctp_gateway_wrapper_class"])
        cls.tree = tree

    def install_fake_gateway(self, gateway_client):
        package = types.ModuleType("bt_api_py")
        package.__path__ = []
        gateway = types.ModuleType("bt_api_py.gateway")
        gateway.__path__ = []
        client = types.ModuleType("bt_api_py.gateway.client")
        client.GatewayClient = gateway_client
        old = {
            name: sys.modules.get(name)
            for name in ("bt_api_py", "bt_api_py.gateway", "bt_api_py.gateway.client")
        }
        sys.modules["bt_api_py"] = package
        sys.modules["bt_api_py.gateway"] = gateway
        sys.modules["bt_api_py.gateway.client"] = client
        return old

    @staticmethod
    def restore_modules(old):
        for name, module in old.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def run_ctp_denials_without_gateway_import(self, wrapper_kwargs):
        touched = []
        constructed = []

        class FakeGatewayClient:
            submit_order = _DescriptorTrap("submit_order", touched)
            cancel_order = _DescriptorTrap("cancel_order", touched)

            def __init__(self, **kwargs):
                constructed.append(dict(kwargs))

        old = self.install_fake_gateway(FakeGatewayClient)
        import_attempts = []
        original_import = builtins.__import__

        def recording_import(name, *args, **kwargs):
            if name == "bt_api_py.gateway.client":
                import_attempts.append(name)
            return original_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", recording_import):
                wrapper = self.factory()(**wrapper_kwargs)
                for action in (
                    lambda: wrapper.submit_order({"symbol": "X"}),
                    lambda: wrapper.create_order(symbol="X"),
                    lambda: wrapper.cancel_order("ref"),
                ):
                    with self.assertRaises(BtApiStoreError):
                        action()
                delegated = []
                wrapper.submit_order = lambda payload: delegated.append(payload)
                with self.assertRaises(BtApiStoreError):
                    wrapper.create_order(symbol="still blocked")
                self.assertEqual(delegated, [])
            self.assertEqual(import_attempts, [])
            self.assertEqual(constructed, [])
            self.assertEqual(touched, [])
        finally:
            self.restore_modules(old)

    def test_default_ctp_denies_before_gateway_import_or_construction(self):
        self.run_ctp_denials_without_gateway_import({})

    def test_ctp_triple_underscore_aliases_deny_before_construction(self):
        for exchange in ("CTP___FUTURE", " cTp ___ fUtUrE "):
            with self.subTest(exchange=exchange):
                self.run_ctp_denials_without_gateway_import({"exchange_type": exchange})

    def test_store_ctp_marker_overrides_non_ctp_exchange_label(self):
        self.run_ctp_denials_without_gateway_import(
            {"exchange_type": "BINANCE", "_btapistore_ctp_session_provider": True}
        )

    def test_uncertain_exchange_denies_before_gateway_construction(self):
        self.run_ctp_denials_without_gateway_import({"exchange_type": "NOT_A_GATEWAY"})

    def test_explicit_binance_gateway_still_constructs_and_delegates(self):
        calls = []

        class FakeGatewayClient:
            def __init__(self, **kwargs):
                calls.append(("init", dict(kwargs)))

            def submit_order(self, payload):
                calls.append(("submit", dict(payload)))
                return {"ok": True}

            def cancel_order(self, order_ref, dataname=None):
                calls.append(("cancel", order_ref, dataname))
                return {"cancelled": order_ref}

        old = self.install_fake_gateway(FakeGatewayClient)
        try:
            wrapper = self.factory()(exchange_type="BINANCE")
            self.assertEqual(calls[0], ("init", {"exchange_type": "BINANCE", "asset_type": "FUTURE"}))
            response = wrapper.submit_order({"symbol": "BTC/USDT", "data_name": "btc"})
            self.assertEqual(response, {"ok": True, "data_name": "btc"})
            created = wrapper.create_order(symbol="ETH/USDT", data_name="eth")
            self.assertEqual(created, {"ok": True, "data_name": "eth"})
            cancelled = wrapper.cancel_order("r-1", dataname="BTC/USDT")
            self.assertEqual(cancelled, {"cancelled": "r-1"})
            self.assertEqual([call[0] for call in calls], ["init", "submit", "submit", "cancel"])
        finally:
            self.restore_modules(old)

    def test_store_passes_its_ctp_session_classification_to_builtin_wrapper(self):
        btapistore = next(
            node for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "BtApiStore"
        )
        ensure = next(
            node for node in btapistore.body
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_api_ready"
        )
        assignments = [node for node in ast.walk(ensure) if isinstance(node, ast.Assign)]
        self.assertTrue(
            any(
                any(
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "kwargs"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "_btapistore_ctp_session_provider"
                    for target in node.targets
                )
                and "_is_ctp_session_provider" in ast.unparse(node.value)
                for node in assignments
            )
        )


class _DescriptorTrap:
    def __init__(self, name, touched):
        self.name = name
        self.touched = touched

    def __get__(self, instance, owner):
        self.touched.append(self.name)
        raise AssertionError(f"client method descriptor accessed: {self.name}")


if __name__ == "__main__":
    unittest.main()
