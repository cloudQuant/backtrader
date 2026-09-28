"""Configuration-first runtime contracts for Iteration 41.

Importing this package is safe: it exposes schema, registry, and CLI helpers
without importing a runtime dispatcher or optional trading capabilities.
Dispatch helpers remain available through lazy public attributes so existing
callers retain their import surface while ``bootstrap`` and ``doctor`` start
from the smallest offline-only module graph.
"""

from typing import Any

from .config import CONFIG_FILENAME, CONFIG_SCHEMA_VERSION, RuntimeConfig, load_runtime_config
from .errors import (
    CONFIG_EXISTS,
    CONFIG_REQUIRED,
    CONFIG_SCHEMA_UNSUPPORTED,
    ENVIRONMENT_MISMATCH,
    MIGRATION_REVIEW_REQUIRED,
    MODE_PRESET_MISMATCH,
    PRESET_POLICY_VIOLATION,
    RuntimeConfigError,
)
from .policy import PRESET_REGISTRY, PresetPolicy, preset_names
from .managed_execution import (
    ManagedExecutionBindingError,
    ManagedExecutionBridge,
    bind_managed_execution,
    cancel_observation_from_store_response,
    observation_from_store_response,
    project_cancel_record_to_store_response,
    project_record_to_store_response,
    strict_cancel_intent_from_order,
    strict_limit_intent_from_order,
)
from .inventory import (
    ITERATION41_007_CTP_REGISTRATION,
    ITERATION41_007_CTP_RUNTIME_DIR,
    ITERATION41_007_CTP_STRATEGY_ID,
    ITERATION41_010_LIVE_EXAMPLES_REGISTRATION,
    ITERATION41_010_LIVE_EXAMPLES_RUNTIME_DIR,
    ITERATION41_010_LIVE_EXAMPLES_STRATEGY_ID,
    ITERATION41_012_1_REGISTRATION,
    ITERATION41_012_1_RUNTIME_DIR,
    ITERATION41_012_1_STRATEGY_ID,
    ITERATION41_012_2_REGISTRATION,
    ITERATION41_012_2_RUNTIME_DIR,
    ITERATION41_012_2_STRATEGY_ID,
    ITERATION41_013_1_REGISTRATION,
    ITERATION41_013_1_RUNTIME_DIR,
    ITERATION41_013_1_STRATEGY_ID,
    ITERATION41_013_2_REGISTRATION,
    ITERATION41_013_2_RUNTIME_DIR,
    ITERATION41_013_2_STRATEGY_ID,
    ITERATION41_013_3_REGISTRATION,
    ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION,
    ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_DIR,
    ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
    ITERATION41_013_3_RUNTIME_DIR,
    ITERATION41_013_3_STRATEGY_ID,
    ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
    ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR,
    ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID,
    ITERATION41_014_1_REGISTRATION,
    ITERATION41_014_1_RUNTIME_DIR,
    ITERATION41_014_1_STRATEGY_ID,
    ITERATION41_014_2_REGISTRATION,
    ITERATION41_014_2_RUNTIME_DIR,
    ITERATION41_014_2_STRATEGY_ID,
    ITERATION41_015_REGISTRATION,
    ITERATION41_015_RUNTIME_DIR,
    ITERATION41_015_STRATEGY_ID,
    ITERATION41_REPLAY_RUNTIME_SET,
    ITERATION41_MANAGED_REPLAY_RUNTIME_SET,
    iteration41_runtime_registry,
)
from .registry import (
    BootstrapRuntimeSetItem,
    BootstrapRuntimeSetResult,
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    RuntimeSet,
    bootstrap_runtime_config,
    bootstrap_runtime_set,
    default_runtime_registry,
    resolve_runtime_config,
    select_bootstrap_preset,
    validate_runtime_config,
)
from .provider_preflight import (
    ProviderSessionPreflightBinding,
    ProviderSessionPreflightRegistration,
    validate_provider_session_preflight_binding,
)
from .test_execution_profile import (
    RejectingTestExecutionProfileVerifier,
    TestExecutionPreflightContext,
    TestExecutionProfile,
    TestExecutionProfileError,
    TestExecutionProfileObservation,
    TestExecutionProfileVerifier,
    canonical_test_execution_profile,
    parse_test_execution_profile,
    test_execution_profile_sha256,
    validate_test_execution_profile,
)
from .review_evidence import (
    ITERATION41_EVIDENCE_SCHEMA_VERSION,
    REVIEW_REQUIRED,
    Iteration41ReviewEvidenceBindings,
    Iteration41ReviewEvidenceError,
    Iteration41ReviewEvidenceObservation,
    resolve_iteration41_review_evidence_bindings,
    validate_iteration41_review_evidence,
    validate_registered_iteration41_review_evidence,
)


_LAZY_RUNNER_EXPORTS = frozenset(
    {
        "dispatch_configured_runtime",
        "dispatch_registered_runtime",
        "resolve_runner_effective_config",
    }
)


def __getattr__(name: str) -> Any:
    """Load dispatch code only when a caller explicitly requests it.

    The public functions historically re-exported from this module remain
    compatible with ``from backtrader_runtime import ...``.  Leaving the
    dispatcher out of normal package import keeps configuration inspection and
    rejected startup paths free of runner-loading side effects.
    """

    if name in _LAZY_RUNNER_EXPORTS:
        from . import runner

        value = getattr(runner, name)
        globals()[name] = value
        return value
    raise AttributeError("module {0!r} has no attribute {1!r}".format(__name__, name))


__all__ = [
    "CONFIG_EXISTS",
    "CONFIG_FILENAME",
    "CONFIG_REQUIRED",
    "CONFIG_SCHEMA_UNSUPPORTED",
    "CONFIG_SCHEMA_VERSION",
    "BootstrapRuntimeSetItem",
    "BootstrapRuntimeSetResult",
    "ENVIRONMENT_MISMATCH",
    "EffectiveRuntimeConfig",
    "ITERATION41_007_CTP_REGISTRATION",
    "ITERATION41_007_CTP_RUNTIME_DIR",
    "ITERATION41_007_CTP_STRATEGY_ID",
    "ITERATION41_010_LIVE_EXAMPLES_REGISTRATION",
    "ITERATION41_010_LIVE_EXAMPLES_RUNTIME_DIR",
    "ITERATION41_010_LIVE_EXAMPLES_STRATEGY_ID",
    "ITERATION41_012_1_REGISTRATION",
    "ITERATION41_012_1_RUNTIME_DIR",
    "ITERATION41_012_1_STRATEGY_ID",
    "ITERATION41_012_2_REGISTRATION",
    "ITERATION41_012_2_RUNTIME_DIR",
    "ITERATION41_012_2_STRATEGY_ID",
    "ITERATION41_013_1_REGISTRATION",
    "ITERATION41_013_1_RUNTIME_DIR",
    "ITERATION41_013_1_STRATEGY_ID",
    "ITERATION41_013_2_REGISTRATION",
    "ITERATION41_013_2_RUNTIME_DIR",
    "ITERATION41_013_2_STRATEGY_ID",
    "ITERATION41_013_3_REGISTRATION",
    "ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION",
    "ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_DIR",
    "ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID",
    "ITERATION41_013_3_RUNTIME_DIR",
    "ITERATION41_013_3_STRATEGY_ID",
    "ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION",
    "ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR",
    "ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID",
    "ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID",
    "ITERATION41_014_1_REGISTRATION",
    "ITERATION41_014_1_RUNTIME_DIR",
    "ITERATION41_014_1_STRATEGY_ID",
    "ITERATION41_014_2_REGISTRATION",
    "ITERATION41_014_2_RUNTIME_DIR",
    "ITERATION41_014_2_STRATEGY_ID",
    "ITERATION41_015_REGISTRATION",
    "ITERATION41_015_RUNTIME_DIR",
    "ITERATION41_015_STRATEGY_ID",
    "ITERATION41_EVIDENCE_SCHEMA_VERSION",
    "ITERATION41_REPLAY_RUNTIME_SET",
    "ITERATION41_MANAGED_REPLAY_RUNTIME_SET",
    "MIGRATION_REVIEW_REQUIRED",
    "ManagedExecutionBindingError",
    "ManagedExecutionBridge",
    "MODE_PRESET_MISMATCH",
    "PRESET_POLICY_VIOLATION",
    "PRESET_REGISTRY",
    "PresetPolicy",
    "ProviderSessionPreflightBinding",
    "ProviderSessionPreflightRegistration",
    "RegisteredRuntime",
    "RuntimeConfig",
    "RuntimeConfigError",
    "RuntimeProfile",
    "RuntimeRegistry",
    "RuntimeSet",
    "RejectingTestExecutionProfileVerifier",
    "REVIEW_REQUIRED",
    "Iteration41ReviewEvidenceBindings",
    "Iteration41ReviewEvidenceError",
    "Iteration41ReviewEvidenceObservation",
    "bootstrap_runtime_config",
    "bootstrap_runtime_set",
    "bind_managed_execution",
    "cancel_observation_from_store_response",
    "default_runtime_registry",
    "dispatch_configured_runtime",
    "dispatch_registered_runtime",
    "load_runtime_config",
    "observation_from_store_response",
    "project_cancel_record_to_store_response",
    "project_record_to_store_response",
    "iteration41_runtime_registry",
    "preset_names",
    "resolve_runtime_config",
    "resolve_runner_effective_config",
    "resolve_iteration41_review_evidence_bindings",
    "select_bootstrap_preset",
    "strict_limit_intent_from_order",
    "strict_cancel_intent_from_order",
    "validate_runtime_config",
    "TestExecutionPreflightContext",
    "TestExecutionProfile",
    "TestExecutionProfileError",
    "TestExecutionProfileObservation",
    "TestExecutionProfileVerifier",
    "canonical_test_execution_profile",
    "parse_test_execution_profile",
    "test_execution_profile_sha256",
    "validate_provider_session_preflight_binding",
    "validate_test_execution_profile",
    "validate_iteration41_review_evidence",
    "validate_registered_iteration41_review_evidence",
]
