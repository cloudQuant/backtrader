"""Same-process Root entry for the SimNow C01 V18 candidate.

The fixed outer Root wrapper loads this module and its companion sources from
held public bytes, then calls :func:`run_c01_root_entry_v18` in the issuer
process. The issuer stages candidate custody inside its original private
``ExitStack``. Root completes physical postverify and ledger validation before
this function returns the one-use opaque case receipt.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import re
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping


_ENTRY_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_entry_v18"
_ENTRY_RELATIVE = "backtrader_runtime/certification_simnow_c01_root_entry_v18.py"
_FRONT_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_front_transport_v12"
_ROOT_BRIDGE_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_v16"
_PROJECTION_MODULE_NAME = "common.c01_root_admission_bridge"
_CERTIFICATION_MODULE_NAME = "common.certification"
_CUSTODY_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXACT_PUBLIC_SOURCE_PINS: dict[str, str] = {
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "backtrader_runtime/certification_simnow_c01_dependencies_v1.json": "7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324",
    "backtrader_runtime/certification_simnow_c01_front_transport_v12.py": "f23d1488c29366f040df3bf98fbdc94fc17dc1a58886f269faaf30650d449091",
    "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494",
    "backtrader_runtime/certification_simnow_c01_native_td_read_v18.admission.schema.json": "02f4891ea2dc18b2125db05706779abf830eef33fd3c264b81104e3154333c54",
    "backtrader_runtime/certification_simnow_c01_native_td_read_v18.py": "0f0026f1b2c217bf124bc8ba5ebe44a00d7c86eb096975f2cd76c7eb850b44ab",
    "backtrader_runtime/certification_simnow_c01_native_td_read_v18.sources.json": "372ee3aefc9d7066fcbeb82253dd4798d7f74c0b9eea9337c3d0af58c702f70d",
    "backtrader_runtime/certification_simnow_c01_native_v4.py": "66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66",
    "backtrader_runtime/certification_simnow_c01_root_custody_v16.py": "571036d79815f7791bc6917f7afbf87ff8acd9806dc0556a80b9b39d34553f26",
    "backtrader_runtime/certification_simnow_c01_root_v16.py": "c703e509a73aeb5e4b1e37fd911a8a3ccd4211fe1ce9cf2cdcf65edffe586cef",
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": "19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0",
    "backtrader_runtime/certification_simnow_c01_v3_protocol.py": "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160",
    "backtrader_runtime/certification_simnow_c01_v4_supervisor.py": "daf2cf99cbc5d977e27f59efb0f27087abdf3493c9d959d5c3d253744f869da1",
    "backtrader_runtime/certification_simnow_c01_v7_owner.py": "ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9",
    "backtrader_runtime/ctp_front_pair_probe.py": "d6f92c7d2f6df13480cebcee2c7f864ac305d34d4cda37d1a22c466932d2905f",
    "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml": "33d60824f780784f0c391a8212816c6167dd7485dec5b9fc0b461b28e6b4adca",
    "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py": "c88501fda1ce83cebb334b58566776bee5154a5cfea1c5cc22d717a2e09d3f17",
    "examples/000_live_certification/simnow_penetration/cases/C01/run_v18.py": "507ca6c373a83fbbf7580a740c06d7ee5417701aba6c79bf02aea30810cc936e",
    "examples/000_live_certification/simnow_penetration/common/c01_root_admission_bridge.py": "ad8cab9db917ebdadc5fbfb28ee26ca485746b7c8e6c4e4e2501d033fdb956f8",
    "examples/000_live_certification/simnow_penetration/common/certification.py": "1604afa4dba946cd1d1fbd327c6d47057f0380d766e42d9a4614c3369851d020",
    "examples/000_live_certification/simnow_penetration/config.private.yaml.template": "debc71d75b4e04c4e64c38750cdfa2101dc69585ef7898a290c721d882f51db2",
    "scripts/ctp_000_front_handoff.py": "b08e70e723a5d31f18809129387455dfee3645e6ad9f2b516d7aa2789ffd19f7",
    "scripts/ctp_000_paired_front_selector.py": "08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb",
    "scripts/ctp_000_render_config.py": "34bf2a99872f43f0d915bafcb0284827a8ac0c4baf70a2ce5f1046888223eac9",
    "scripts/ctp_i13_i15_outer_watchdog.py": "31c945c77c7e147a296e66f4f1ec075e0a23f1a88b94fd339884268e79ca251c",
    "scripts/ctp_i13_i15_windows_job_backend.py": "2566dd55d1a96285473850b1e2c63174696347da56e07d69fb72aa3a6285e381",
}
_EXACT_SOFTWARE_PINS: dict[str, str] = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
}


class C01RootEntryV18Error(ValueError):
    """Fixed, non-sensitive failure from the C01 V18 Root entry."""

    def __init__(self, code: str):
        if type(code) is not str or not code or any(ord(char) < 32 for char in code):
            code = "root_entry_blocked"
        super().__init__(code)


def run_c01_root_entry_v18(
    *,
    root: Path,
    front_module: ModuleType,
    root_bridge_module: ModuleType,
    projection_module: ModuleType,
    certification_module: ModuleType,
    root_custody_module: ModuleType,
    exact_public_pins: dict[str, str],
    exact_software_pins: dict[str, str],
) -> Any:
    """Run one exact V18 issuer under same-process Root custody.

    The caller is the fixed Root wrapper. It supplies source modules that were
    loaded from its held source map. Its own entry-file pin is taken from the
    module metadata set by that wrapper, avoiding a self-hash dependency.
    """

    try:
        root = _validate_root(root)
        entry_module = _validate_entry_module(root)
        complete_public_pins = _complete_public_pins(entry_module, exact_public_pins)
        _validate_software_pins(exact_software_pins)
        _validate_module(
            root,
            front_module,
            _FRONT_MODULE_NAME,
            "backtrader_runtime/certification_simnow_c01_front_transport_v12.py",
            complete_public_pins,
        )
        _validate_module(
            root,
            root_bridge_module,
            _ROOT_BRIDGE_MODULE_NAME,
            "backtrader_runtime/certification_simnow_c01_root_v16.py",
            complete_public_pins,
        )
        _validate_module(
            root,
            projection_module,
            _PROJECTION_MODULE_NAME,
            "examples/000_live_certification/simnow_penetration/common/c01_root_admission_bridge.py",
            complete_public_pins,
        )
        _validate_module(
            root,
            certification_module,
            _CERTIFICATION_MODULE_NAME,
            "examples/000_live_certification/simnow_penetration/common/certification.py",
            complete_public_pins,
        )
        _validate_module(
            root,
            root_custody_module,
            _CUSTODY_MODULE_NAME,
            "backtrader_runtime/certification_simnow_c01_root_custody_v16.py",
            complete_public_pins,
        )
        _require_function(front_module, "verified_c01_v18_sources")
        _require_function(root_bridge_module, "c01_root_invocation_scope")
        _require_function(root_bridge_module, "current_c01_root_invocation_nonce")
        _require_function(root_bridge_module, "pending_root_admission_result")
        _require_function(root_bridge_module, "finalize_c01_root_case_result")
        _require_function(projection_module, "project_c01_root_candidate")
        _require_function(certification_module, "get_certification_scenario")
        _require_function(root_custody_module, "open_source_runtime_leases")
        _require_function(root_custody_module, "verify_and_mint_postverify")
        _require_function(root_custody_module, "prepare_candidate_custody")

        receipt = None
        with front_module.verified_c01_v18_sources(root) as bundle:
            _validate_bundle(front_module, bundle, root, complete_public_pins)
            helpers = bundle.helpers
            private_module = helpers["private"]
            cli_module = helpers["r3_cli"]
            with root_custody_module.open_source_runtime_leases(
                private_module,
                cli_module,
                complete_public_pins,
                exact_software_pins,
                root_entry_module=entry_module,
            ):
                with root_bridge_module.c01_root_invocation_scope(
                    front_module,
                    bundle,
                    projection_module,
                    certification_module,
                    root_custody_module,
                ) as scope:
                    issuer_result = bundle.issuer.run_c01_native_td_read_v18(
                        _root_scope=scope
                    )
                    nonce = root_bridge_module.current_c01_root_invocation_nonce()
                    pending = root_bridge_module.pending_root_admission_result(
                        nonce, issuer_result
                    )
                    proof = root_custody_module.verify_and_mint_postverify(
                        root_bridge_module, scope, pending
                    )
                    receipt = root_bridge_module.finalize_c01_root_case_result(
                        pending,
                        root_custody_module=root_custody_module,
                        postverify_proof=proof,
                    )
                    receipt_type = getattr(root_bridge_module, "C01RootCaseResultReceipt", None)
                    if (
                        type(receipt_type) is not type
                        or type(receipt) is not receipt_type
                        or receipt.exit_code() != 0
                    ):
                        raise C01RootEntryV18Error("root_case_receipt_invalid")
        if receipt is None:
            raise C01RootEntryV18Error("root_case_receipt_unavailable")
        return receipt
    except C01RootEntryV18Error:
        raise
    except Exception:
        raise C01RootEntryV18Error("root_entry_blocked") from None


def _validate_root(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute():
        raise C01RootEntryV18Error("root_path_invalid")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise C01RootEntryV18Error("root_path_invalid")
    return resolved


def _validate_entry_module(root: Path) -> ModuleType:
    module = sys.modules.get(__name__)
    if (
        type(module) is not ModuleType
        or module.__name__ != _ENTRY_MODULE_NAME
        or module.__dict__ is not globals()
        or Path(module.__file__).resolve(strict=True)
        != (root / Path(_ENTRY_RELATIVE)).resolve(strict=True)
        or type(getattr(module, "__c01_source_sha256__", None)) is not str
        or not _SHA256_RE.fullmatch(module.__c01_source_sha256__)
    ):
        raise C01RootEntryV18Error("root_entry_source_invalid")
    function = module.__dict__.get("run_c01_root_entry_v18")
    if (
        type(function) is not FunctionType
        or function.__globals__ is not module.__dict__
        or getattr(module, "_C01_ROOT_ENTRY_CALLABLE", None) is not function
    ):
        raise C01RootEntryV18Error("root_entry_function_invalid")
    return module


def _complete_public_pins(
    entry_module: ModuleType, pins: dict[str, str]
) -> dict[str, str]:
    if type(pins) is not dict:
        raise C01RootEntryV18Error("public_source_map_invalid")
    entry_path = _ENTRY_RELATIVE
    expected = dict(_EXACT_PUBLIC_SOURCE_PINS)
    expected[entry_path] = entry_module.__c01_source_sha256__
    if pins != expected:
        raise C01RootEntryV18Error("public_source_map_mismatch")
    if any(
        type(path) is not str
        or not path
        or "\\" in path
        or type(digest) is not str
        or not _SHA256_RE.fullmatch(digest)
        for path, digest in pins.items()
    ):
        raise C01RootEntryV18Error("public_source_map_invalid")
    return expected


def _validate_software_pins(pins: dict[str, str]) -> None:
    if type(pins) is not dict or pins != _EXACT_SOFTWARE_PINS:
        raise C01RootEntryV18Error("software_source_map_mismatch")
    if any(
        type(path) is not str
        or type(digest) is not str
        or not _SHA256_RE.fullmatch(digest)
        for path, digest in pins.items()
    ):
        raise C01RootEntryV18Error("software_source_map_invalid")


def _validate_module(
    root: Path,
    module: ModuleType,
    expected_name: str,
    relative_path: str,
    pins: Mapping[str, str],
) -> None:
    digest = pins.get(relative_path)
    if (
        type(module) is not ModuleType
        or module.__name__ != expected_name
        or type(getattr(module, "__file__", None)) is not str
    ):
        raise C01RootEntryV18Error("source_module_invalid")
    source_path = Path(module.__file__).resolve(strict=True)
    try:
        actual_relative = source_path.relative_to(root).as_posix()
    except Exception:
        actual_relative = None
    if (
        actual_relative != relative_path
        or type(digest) is not str
        or not _SHA256_RE.fullmatch(digest)
        or getattr(module, "__c01_source_sha256__", None) != digest
    ):
        raise C01RootEntryV18Error("source_module_pin_invalid")


def _require_function(module: ModuleType, name: str) -> FunctionType:
    function = getattr(module, name, None)
    if (
        type(function) is not FunctionType
        or function.__module__ != module.__name__
        or function.__qualname__ != name
    ):
        raise C01RootEntryV18Error("source_function_invalid")
    if function.__globals__ is module.__dict__:
        return function
    wrapped = getattr(function, "__wrapped__", None)
    closure = getattr(function, "__closure__", None)
    if (
        type(wrapped) is not FunctionType
        or wrapped.__module__ != module.__name__
        or wrapped.__qualname__ != name
        or wrapped.__globals__ is not module.__dict__
        or function.__globals__ is not contextlib.contextmanager.__globals__
        or function.__code__.co_name != "helper"
        or function.__code__.co_freevars != ("func",)
        or type(closure) is not tuple
        or len(closure) != 1
        or closure[0].cell_contents is not wrapped
    ):
        raise C01RootEntryV18Error("source_function_invalid")
    return function


def _validate_bundle(
    front_module: ModuleType,
    bundle: Any,
    root: Path,
    pins: Mapping[str, str],
) -> None:
    issuer = getattr(bundle, "issuer", None)
    owner = getattr(bundle, "owner", None)
    helpers = getattr(bundle, "helpers", None)
    if (
        type(bundle) is not getattr(front_module, "VerifiedC01V18SourceBundle", None)
        or getattr(bundle, "_factory", None) is not getattr(front_module, "_BUNDLE_FACTORY", None)
        or getattr(bundle, "_active", False) is not True
        or bundle.root.resolve(strict=True) != root
        or type(issuer) is not ModuleType
        or issuer.__name__ != "backtrader_runtime._c01_front_transport_v12_v18_source"
        or issuer.PROFILE_ID != "C01_NATIVE_TD_READ_V18"
        or issuer.__c01_source_sha256__
        != pins.get("backtrader_runtime/certification_simnow_c01_native_td_read_v18.py")
        or type(owner) is not ModuleType
        or type(helpers) is not MappingProxyType
        or set(helpers) != {
            "private",
            "r3_cli",
            "selector",
            "handoff",
            "probe",
            "renderer",
            "protocol",
            "contract",
            "supervisor",
            "job_backend",
            "watchdog",
            "interpreter_binding",
            "owner_now_utc",
        }
    ):
        raise C01RootEntryV18Error("source_bundle_invalid")
    _require_function(issuer, "run_c01_native_td_read_v18")


_C01_ROOT_ENTRY_CALLABLE = run_c01_root_entry_v18


__all__ = ["C01RootEntryV18Error", "run_c01_root_entry_v18"]
