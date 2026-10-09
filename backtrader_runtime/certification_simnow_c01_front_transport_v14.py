"""Exact public source loader for the SimNow C01 V20 Root entry.

This module supplies the V20 source-bundle API expected by the pinned V20
Root wrapper. It opens only public issuer, owner, manifest, and helper source
files, verifies their exact pins, and yields an ephemeral bundle. It does not
read config, admission, environment, or provider data and does not enter the
V20 runner.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.machinery
import sys
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Iterator, Mapping, Optional


_V20_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
_V20_SHA256 = "7118ed43cdc012181546f54f7b302ee51d3704860c5746807217c35087257f71"
_V20_MAX_BYTES = 2 * 1024 * 1024
_V20_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_native_td_read_v20"
_BUNDLE_FACTORY = object()
_EXPECTED_HELPERS = frozenset(
    {
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
    }
)
_EXPECTED_BUNDLE_HELPERS = _EXPECTED_HELPERS | {"owner_now_utc"}


class C01FrontTransportErrorV7(ValueError):
    """Safe, fixed local failure from the V20 source loader."""


class VerifiedC01V20SourceBundle:
    """Ephemeral wrapper for one active, exact-pinned V20 source closure."""

    __slots__ = ("root", "issuer", "owner", "helpers", "_active", "_factory")

    def __init__(
        self,
        root: Path,
        issuer: ModuleType,
        owner: ModuleType,
        helpers: Mapping[str, Any],
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _BUNDLE_FACTORY:
            raise ValueError("c01_v20_source_bundle_factory_required")
        if (
            not isinstance(root, Path)
            or type(issuer) is not ModuleType
            or type(owner) is not ModuleType
            or type(helpers) not in (dict, MappingProxyType)
            or set(helpers) != _EXPECTED_BUNDLE_HELPERS
        ):
            raise ValueError("c01_v20_source_bundle_invalid")
        self.root = root
        self.issuer = issuer
        self.owner = owner
        self.helpers = MappingProxyType(dict(helpers))
        self._active = True
        self._factory = _BUNDLE_FACTORY

    def __repr__(self) -> str:
        return "VerifiedC01V20SourceBundle(<active pinned public source closure>)"


def _read_v20_source(root: Path) -> bytes:
    path = root / Path(_V20_RELATIVE)
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            path.is_symlink()
            or attributes & 0x400
            or not path.is_file()
            or not path.is_absolute()
            or info.st_size > _V20_MAX_BYTES
        ):
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        with path.open("rb") as stream:
            raw = stream.read(_V20_MAX_BYTES + 1)
    except C01FrontTransportErrorV7:
        raise
    except Exception:
        raise C01FrontTransportErrorV7("source_bundle_unavailable") from None
    if len(raw) > _V20_MAX_BYTES or hashlib.sha256(raw).hexdigest() != _V20_SHA256:
        raise C01FrontTransportErrorV7("source_bundle_unavailable")
    return raw


@contextmanager
def verified_c01_v20_sources(root: Path) -> Iterator[VerifiedC01V20SourceBundle]:
    """Verify the exact V20 issuer/owner/helper closure for the Root wrapper."""

    if not isinstance(root, Path) or not root.is_absolute():
        raise C01FrontTransportErrorV7("source_bundle_unavailable")
    issuer: Optional[ModuleType] = None
    owner: Optional[ModuleType] = None
    helper_context: Any = None
    helper_entered = False
    bundle: Optional[VerifiedC01V20SourceBundle] = None
    try:
        resolved_root = root.resolve(strict=True)
        expected_root = Path(__file__).resolve(strict=True).parents[1]
        if resolved_root != expected_root or not resolved_root.is_dir():
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        if _V20_MODULE_NAME in sys.modules:
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        raw = _read_v20_source(resolved_root)
        issuer = ModuleType(_V20_MODULE_NAME)
        issuer.__file__ = str(resolved_root / Path(_V20_RELATIVE))
        issuer.__package__ = "backtrader_runtime"
        issuer.__loader__ = None
        issuer.__spec__ = importlib.machinery.ModuleSpec(_V20_MODULE_NAME, loader=None)
        issuer.__c01_source_sha256__ = _V20_SHA256
        sys.modules[_V20_MODULE_NAME] = issuer
        exec(compile(raw, issuer.__file__, "exec", dont_inherit=True), issuer.__dict__)
        if (
            issuer.PROFILE_ID != "C01_NATIVE_TD_READ_V20"
            or issuer.__c01_source_sha256__ != _V20_SHA256
        ):
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        issuer._verify_public_profile_sources(resolved_root)
        owner = issuer._load_frozen_owner(resolved_root)
        owner_source = issuer._read_fixed_source(
            resolved_root,
            "backtrader_runtime/certification_simnow_c01_v7_owner.py",
            issuer._OWNER_SHA256,
        )
        owner_digest = hashlib.sha256(owner_source).hexdigest()
        if owner_digest != issuer._OWNER_SHA256:
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        owner.__c01_source_sha256__ = owner_digest
        issuer._verify_source_manifest(resolved_root, owner)
        helper_context = owner._verified_helper_bundle()
        helpers = helper_context.__enter__()
        helper_entered = True
        if type(helpers) is not MappingProxyType or set(helpers) != _EXPECTED_HELPERS:
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        helper_sources = owner._read_source_bundle(resolved_root)
        for helper_name, relative in {
            "private": "backtrader_runtime/certification_roundtrip_private.py",
            "r3_cli": "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
            "selector": "scripts/ctp_000_paired_front_selector.py",
            "handoff": "scripts/ctp_000_front_handoff.py",
            "probe": "backtrader_runtime/ctp_front_pair_probe.py",
            "renderer": "scripts/ctp_000_render_config.py",
            "protocol": "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
            "contract": "backtrader_runtime/certification_simnow_c01_v3_contract.py",
            "supervisor": "backtrader_runtime/certification_simnow_c01_v4_supervisor.py",
            "job_backend": "scripts/ctp_i13_i15_windows_job_backend.py",
            "watchdog": "scripts/ctp_i13_i15_outer_watchdog.py",
            "interpreter_binding": "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
        }.items():
            helper_module = helpers[helper_name]
            helper_raw = helper_sources.get(relative)
            if (
                type(helper_raw) is not bytes
                or hashlib.sha256(helper_raw).hexdigest()
                != getattr(helper_module, "__c01_source_sha256__", None)
                and getattr(helper_module, "__c01_source_sha256__", None) is not None
            ):
                raise C01FrontTransportErrorV7("source_bundle_unavailable")
            helper_module.__c01_source_sha256__ = hashlib.sha256(helper_raw).hexdigest()
        transport_helpers = dict(helpers)
        transport_helpers["owner_now_utc"] = owner._now_utc
        bundle = VerifiedC01V20SourceBundle(
            resolved_root,
            issuer,
            owner,
            transport_helpers,
            _factory=_BUNDLE_FACTORY,
        )
    except C01FrontTransportErrorV7:
        if helper_entered:
            try:
                helper_context.__exit__(*sys.exc_info())
            except Exception:
                pass
            helper_entered = False
    except Exception:
        if helper_entered:
            try:
                helper_context.__exit__(*sys.exc_info())
            except Exception:
                pass
            helper_entered = False
        _cleanup_source_modules(issuer, owner)
        raise C01FrontTransportErrorV7("source_bundle_unavailable") from None
    if bundle is None or helper_context is None or not helper_entered:
        _cleanup_source_modules(issuer, owner)
        raise C01FrontTransportErrorV7("source_bundle_unavailable")
    try:
        yield bundle
    except BaseException:
        bundle._active = False
        context = helper_context
        helper_context = None
        helper_entered = False
        try:
            context.__exit__(*sys.exc_info())
        except Exception:
            pass
        raise
    else:
        bundle._active = False
        context = helper_context
        helper_context = None
        helper_entered = False
        context.__exit__(None, None, None)
    finally:
        if helper_entered and helper_context is not None:
            try:
                helper_context.__exit__(None, None, None)
            except Exception:
                pass
        _cleanup_source_modules(issuer, owner)


def _cleanup_source_modules(issuer: Optional[ModuleType], owner: Optional[ModuleType]) -> None:
    if issuer is not None:
        owner_module_name = getattr(issuer, "_OWNER_MODULE_NAME", None)
        if (
            owner is not None
            and type(owner_module_name) is str
            and sys.modules.get(owner_module_name) is owner
        ):
            sys.modules.pop(owner_module_name, None)
        if sys.modules.get(_V20_MODULE_NAME) is issuer:
            sys.modules.pop(_V20_MODULE_NAME, None)


__all__ = [
    "C01FrontTransportErrorV7",
    "VerifiedC01V20SourceBundle",
    "verified_c01_v20_sources",
]
