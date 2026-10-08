"""Exact public source loader for the SimNow C01 V18 Root entry.

This module supplies the V18 source-bundle API expected by the pinned V18
Root wrapper. It opens only public issuer, owner, manifest, and helper source
files, verifies their exact pins, and yields an ephemeral bundle. It does not
read config, admission, environment, or provider data and does not enter the
V18 runner.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.machinery
import sys
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Iterator, Mapping, Optional


_V18_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.py"
_V18_SHA256 = "0f0026f1b2c217bf124bc8ba5ebe44a00d7c86eb096975f2cd76c7eb850b44ab"
_V18_MAX_BYTES = 2 * 1024 * 1024
_V18_MODULE_NAME = "backtrader_runtime._c01_front_transport_v12_v18_source"
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
    """Safe, fixed local failure from the V18 source loader."""


class VerifiedC01V18SourceBundle:
    """Ephemeral wrapper for one active, exact-pinned V18 source closure."""

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
            raise ValueError("c01_v18_source_bundle_factory_required")
        if (
            not isinstance(root, Path)
            or type(issuer) is not ModuleType
            or type(owner) is not ModuleType
            or type(helpers) not in (dict, MappingProxyType)
            or set(helpers) != _EXPECTED_BUNDLE_HELPERS
        ):
            raise ValueError("c01_v18_source_bundle_invalid")
        self.root = root
        self.issuer = issuer
        self.owner = owner
        self.helpers = MappingProxyType(dict(helpers))
        self._active = True
        self._factory = _BUNDLE_FACTORY

    def __repr__(self) -> str:
        return "VerifiedC01V18SourceBundle(<active pinned public source closure>)"


def _read_v18_source(root: Path) -> bytes:
    path = root / Path(_V18_RELATIVE)
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            path.is_symlink()
            or attributes & 0x400
            or not path.is_file()
            or not path.is_absolute()
            or info.st_size > _V18_MAX_BYTES
        ):
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        with path.open("rb") as stream:
            raw = stream.read(_V18_MAX_BYTES + 1)
    except C01FrontTransportErrorV7:
        raise
    except Exception:
        raise C01FrontTransportErrorV7("source_bundle_unavailable") from None
    if len(raw) > _V18_MAX_BYTES or hashlib.sha256(raw).hexdigest() != _V18_SHA256:
        raise C01FrontTransportErrorV7("source_bundle_unavailable")
    return raw


@contextmanager
def verified_c01_v18_sources(root: Path) -> Iterator[VerifiedC01V18SourceBundle]:
    """Verify the exact V18 issuer/owner/helper closure for the Root wrapper."""

    if not isinstance(root, Path) or not root.is_absolute():
        raise C01FrontTransportErrorV7("source_bundle_unavailable")
    issuer: Optional[ModuleType] = None
    owner: Optional[ModuleType] = None
    helper_context: Any = None
    helper_entered = False
    bundle: Optional[VerifiedC01V18SourceBundle] = None
    try:
        resolved_root = root.resolve(strict=True)
        expected_root = Path(__file__).resolve(strict=True).parents[1]
        if resolved_root != expected_root or not resolved_root.is_dir():
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        if _V18_MODULE_NAME in sys.modules:
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        raw = _read_v18_source(resolved_root)
        issuer = ModuleType(_V18_MODULE_NAME)
        issuer.__file__ = str(resolved_root / Path(_V18_RELATIVE))
        issuer.__package__ = "backtrader_runtime"
        issuer.__loader__ = None
        issuer.__spec__ = importlib.machinery.ModuleSpec(_V18_MODULE_NAME, loader=None)
        issuer.__c01_source_sha256__ = _V18_SHA256
        sys.modules[_V18_MODULE_NAME] = issuer
        exec(compile(raw, issuer.__file__, "exec", dont_inherit=True), issuer.__dict__)
        if (
            issuer.PROFILE_ID != "C01_NATIVE_TD_READ_V18"
            or issuer.__c01_source_sha256__ != _V18_SHA256
        ):
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        issuer._verify_public_profile_sources(resolved_root)
        owner = issuer._load_frozen_owner(resolved_root)
        issuer._verify_source_manifest(resolved_root, owner)
        helper_context = owner._verified_helper_bundle()
        helpers = helper_context.__enter__()
        helper_entered = True
        if type(helpers) is not MappingProxyType or set(helpers) != _EXPECTED_HELPERS:
            raise C01FrontTransportErrorV7("source_bundle_unavailable")
        transport_helpers = dict(helpers)
        transport_helpers["owner_now_utc"] = owner._now_utc
        bundle = VerifiedC01V18SourceBundle(
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
        if sys.modules.get(_V18_MODULE_NAME) is issuer:
            sys.modules.pop(_V18_MODULE_NAME, None)


__all__ = [
    "C01FrontTransportErrorV7",
    "VerifiedC01V18SourceBundle",
    "verified_c01_v18_sources",
]
