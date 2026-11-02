"""Framework service integrations for managed execution and read bridges.

Public names are resolved lazily so importing this namespace does not eagerly
initialize Store, Broker, or provider modules.
"""

from importlib import import_module as _import_module


_EXPORTS = {
    "ManagedOrderRefreshLoop": "service_refresh_loop",
    "ServiceReadProxy": "service_read_proxy",
    "ServiceReadProxyError": "service_read_proxy",
    "ServiceObservationSession": "service_observation",
    "open_service_read_session": "service_observation",
    "ServiceExecutionAdapter": "service_execution_adapter",
    "ServiceExecutionAdapterError": "service_execution_adapter",
    "ServiceExecutionReadError": "service_execution_adapter",
    "ServiceExecutionGroupAdapter": "service_execution_group",
    "require_service_execution_group_adapter": "service_execution_group",
    "AttestedServiceRecoveryEventContext": "service_recovery_attestation",
    "AttestedServiceRecoveryExecutionContext": "service_recovery_attestation",
    "BacktraderServiceRecoveryAttestor": "service_recovery_attestation",
    "SERVICE_RECOVERY_ATTESTOR": "service_recovery_attestation",
    "ServiceRecoveryAttestationError": "service_recovery_attestation",
    "ServiceExecutionSession": "service_execution_session",
    "ServiceExecutionSessionCleanupError": "service_execution_session",
    "ServiceExecutionSessionConfigError": "service_execution_session",
    "ServiceExecutionSessionError": "service_execution_session",
    "run_configured_cerebro": "service_execution_session",
    "ServiceStrategyAccountBookError": "service_strategy_account_book",
    "ServiceStrategyAccountBookView": "service_strategy_account_book",
    "ManagedRuntimeCerebroCleanupError": "managed_runtime_host",
    "ManagedRuntimeCerebroCleanupReport": "managed_runtime_host",
    "ManagedRuntimeCerebroError": "managed_runtime_host",
    "ManagedRuntimeCerebroSession": "managed_runtime_host",
}

__all__ = tuple(_EXPORTS)


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module = _import_module(".{}".format(module_name), __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
