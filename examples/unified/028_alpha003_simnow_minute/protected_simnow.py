"""Root-owned, in-process handoff from the registered protected SimNow config.

This helper loads no provider session and grants no trading permission. Keep
the context open until the caller has normally stopped every Store using it.
Private mappings must never be serialized, logged, or passed to a subprocess.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from backtrader_runtime.capability_imports import trusted_installed_capability_import_context
from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.credential_resolver import (
    CTP_AUTHENTICATION_CREDENTIAL_KEYS,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from backtrader_runtime.ctp_artifact_provenance import (
    CtpSdkArtifactPin,
    _validate_exact_tcp_front_pair,
    _verify_pinned_sdk_distributions,
)
from backtrader_runtime.ctp_front_pair_probe import CtpConfiguredFrontPair
from backtrader_runtime.ctp_sandbox_readonly_admission import (
    require_ctp_sandbox_readonly_runtime_contract,
)
from backtrader_runtime.ctp_simnow_readonly_runtime import (
    _SealedCtpCredentialSource,
    _require_matching_ctp_scope,
)
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
    ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
)
from backtrader_runtime.registry import RuntimeRegistry, resolve_runtime_config


# Local consumer identity accepted on 2026-10-29 from
# i51-next-installed-consumer-46aecc87-6c7d9b77-20261029-r2:
# Backtrader 46aecc87a315ba5c7433df3e2b1af2dd9b5dc68f and CTP
# 6c7d9b77d97d5ec19cb9c535f4d1ad16f941fae9. The older I41 tables remain
# untouched. These pins identify artifacts; they do not authorize API writes.
_SDK_PINS = MappingProxyType(
    {
        "bt_api_base": CtpSdkArtifactPin(
            distribution="bt_api_base",
            module="bt_api_base",
            version="0.15.8",
            wheel_filename="bt_api_base-0.15.8-py3-none-any.whl",
            wheel_sha256="b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39",
            record_sha256="dd08e35cabe6e5bb1be98ffb14d5a57c3b2918e9b570e7953b6b8a8d827b7c14",
        ),
        "bt_api_ctp": CtpSdkArtifactPin(
            distribution="bt_api_ctp",
            module="bt_api_ctp",
            version="2.0.4+iteration41.i9",
            wheel_filename="bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl",
            wheel_sha256="c48593e592cecd3721d01102d191f09c196edfd40ef02add09919b668815b7fc",
            record_sha256="362ad9dacdae1a09f416fc400dcf2fa270c78d990c5453d6d80c6461ebc54d1a",
        ),
    }
)


class ProtectedSimNowConfigError(ValueError):
    """A fixed, value-free phase reason; never include a nested exception."""


def _registered_runtime():
    # Runtime packages are installed, whereas examples remain in the checkout.
    # Rebind only the directory of the existing zero-write policy, not its
    # identity, profile, secrets route, capabilities, or binding. No user path.
    runtime_dir = (
        Path(__file__).resolve().parent.parent / "013_3_sa_midfreq_simnow/runtime-ctp-private"
    )
    registration = replace(
        ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION, runtime_dir=runtime_dir
    )
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,),
        registry_id="backtrader.iteration51.protected-simnow",
    )
    return registration, registry


def _official_profile(td_front, md_front):
    from bt_api_ctp.ctp_env_selector import (
        official_simnow_profile_for_td_front,
        verify_official_simnow_profile,
    )

    profile = official_simnow_profile_for_td_front(td_front)
    if not profile or not verify_official_simnow_profile(td_front, md_front, profile):
        raise ProtectedSimNowConfigError("OFFICIAL_SIMNOW_PAIR_REQUIRED")
    return profile


class _PrivateMapping(Mapping):
    """Read-only live view with a value-free representation."""

    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return "PrivateSimNowMapping(<redacted>)"


class _Handoff:
    """Redacted handle that becomes unusable when its owning context closes."""

    def __init__(self, options, profile, source):
        self._options = options
        self.profile = profile
        self._source = source
        self._active = True

    def __repr__(self):
        return "ProtectedSimNowConfig(<redacted>)"

    def for_runner(self):
        if not self._active:
            raise ProtectedSimNowConfigError("CONFIG_CONTEXT_CLOSED")
        # Check every field through the original sealed source again before a
        # later epoch receives the mapping. No external credential dictionary.
        for key in CTP_AUTHENTICATION_CREDENTIAL_KEYS:
            if self._source.require_credential(key) != self._options[key]:
                raise ProtectedSimNowConfigError("CREDENTIAL_BINDING_CHANGED")
        return _PrivateMapping(
            {"config": _PrivateMapping(self._options), "api_kwargs": MappingProxyType({})}
        )

    def _close(self):
        self._active = False
        self._options.clear()
        self._source = None


@contextmanager
def protected_simnow_store_config(*, selected_config_index):
    """Resolve one configured pair through protected readers and pinned SDKs.

    Index is zero-based and selects only a member of sealed config. No TCP
    probe, Store, Broker, Feed, Cerebro, SDK client, or provider call is made.
    The caller must separately enforce shadow mode and normal native cleanup.
    """
    if type(selected_config_index) is not int or not 0 <= selected_config_index < 8:
        raise ProtectedSimNowConfigError("CONFIG_INDEX_INVALID")
    phase = "PROTECTED_CONFIG_REJECTED"
    handoff = None
    try:
        registration, registry = _registered_runtime()
        config = load_runtime_config(registration.runtime_dir, registry=registry)
        effective = resolve_runtime_config(config, registry)
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        _, _, pairs = binding._sealed_private_config(effective, registry)
        if selected_config_index >= len(pairs):
            raise ProtectedSimNowConfigError("CONFIG_INDEX_INVALID")
        row = pairs[selected_config_index]
        pair = CtpConfiguredFrontPair(md_front=row["md_front"], td_front=row["td_front"])
        admission, scope = binding._route(
            effective,
            registry,
            selected_front_pair=pair,
            selected_config_index=selected_config_index,
        )
        require_ctp_sandbox_readonly_runtime_contract(effective, registry, admission)
        scope = _require_matching_ctp_scope(admission, effective, scope)
        phase = "SDK_ARTIFACT_REJECTED"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            _validate_exact_tcp_front_pair(td_front=pair.td_front, md_front=pair.md_front)
            _verify_pinned_sdk_distributions(("bt_api_base", "bt_api_ctp"), pins=_SDK_PINS)
            phase = "OFFICIAL_SIMNOW_PAIR_REQUIRED"
            profile = _official_profile(pair.td_front, pair.md_front)
            phase = "CREDENTIAL_RESOLUTION_REJECTED"
            credentials = resolve_runtime_credentials(effective, registry, scope)
            require_resolved_runtime_credentials_seal(credentials, effective, registry, scope)
            source = _SealedCtpCredentialSource(credentials, effective, registry, scope)
            options = {
                key: source.require_credential(key) for key in CTP_AUTHENTICATION_CREDENTIAL_KEYS
            }
            options.update(
                td_address=pair.td_front,
                md_address=pair.md_front,
                ctp_env_profile=profile,
                environment="simnow",
            )
            handoff = _Handoff(options, profile, source)
            # Exceptions thrown by the consumer must retain their original
            # semantics; only setup failures above are translated below.
            phase = None
            yield handoff
    except ProtectedSimNowConfigError:
        raise
    except Exception:
        if phase is None:
            raise
        raise ProtectedSimNowConfigError(phase) from None
    finally:
        if handoff is not None:
            handoff._close()
