"""Backtrader projections for the public SDK execution-journal facade.

Backtrader owns its strategy position and factor-facts projections. The SDK
owns the local attribution storage and its schema and capacity operations.
Provider facts and authorization are supplied through ``bt_api_py.execution``;
this module neither selects a venue nor imports provider packages.  If the
provider authority is absent, provider-dependent journal operations fail closed.
"""

from __future__ import annotations

from typing import Any, Optional

from bt_api_py.execution import (
    ExecutionJournalError,
    ExecutionJournalPorts,
    ExecutionJournalProviderAuthority,
    bind_execution_journal_ports as _bind_execution_journal_ports,
    build_execution_journal_ports as _build_execution_journal_ports,
    configure_execution_journal_ports as _configure_execution_journal_ports,
    new_execution_journal as _new_execution_journal,
)
from bt_api_py.fee_pair_facts_journal_port import FeePairFactsJournalPort
from bt_api_py.factor_position_attribution import (
    FactorPositionAttributionJournalPort,
)

__all__ = [
    "BacktraderFeePairFactsJournalPort",
    "BacktraderJournalPortError",
    "BacktraderPositionAttributionJournalPort",
    "bind_backtrader_journal_ports",
    "build_backtrader_journal_ports",
    "install_backtrader_journal_ports",
    "new_execution_journal",
]


class BacktraderJournalPortError(RuntimeError):
    """Backtrader could not supply or bind its framework-owned journal ports."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _facts_module() -> Any:
    from ..factor_execution import factor_execution_facts as module

    return module

class BacktraderPositionAttributionJournalPort(FactorPositionAttributionJournalPort):
    """Bind the SDK-owned journal port to Backtrader error types."""

    def __init__(self) -> None:
        super().__init__(error_type=BacktraderJournalPortError)

class BacktraderFeePairFactsJournalPort(FeePairFactsJournalPort):
    """Bind SDK fee-pair checks to the exact Backtrader facts type."""

    def __init__(
        self, provider_authority: Optional[ExecutionJournalProviderAuthority] = None
    ) -> None:
        super().__init__(provider_authority, facts_module_loader=_facts_module)


def build_backtrader_journal_ports(
    *,
    provider_authority: Optional[ExecutionJournalProviderAuthority] = None,
) -> ExecutionJournalPorts:
    """Build an independent port set for one explicit journal composition.

    A provider authority is a supplied capability, not a process default.
    When absent, provider-dependent operations remain unavailable.
    """
    return _build_execution_journal_ports(
        position_attribution=BacktraderPositionAttributionJournalPort(),
        fee_pair_facts=BacktraderFeePairFactsJournalPort(provider_authority),
        provider_authority=provider_authority,
    )


def _select_ports(
    ports: Optional[ExecutionJournalPorts],
    provider_authority: Optional[ExecutionJournalProviderAuthority],
) -> ExecutionJournalPorts:
    if ports is None:
        return build_backtrader_journal_ports(provider_authority=provider_authority)
    if type(ports) is not ExecutionJournalPorts:
        raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORT_SET_INVALID")
    if provider_authority is not None and provider_authority is not ports.provider_authority:
        raise BacktraderJournalPortError("EXECUTION_PROVIDER_AUTHORITY_MISMATCH")
    return ports


def install_backtrader_journal_ports(
    *,
    provider_authority: Optional[ExecutionJournalProviderAuthority] = None,
    ports: Optional[ExecutionJournalPorts] = None,
) -> ExecutionJournalPorts:
    """Explicitly register a port set as the Execution process default.

    Process-default registration remains subject to the Execution package's
    existing refusal to replace a different registered port. Per-journal use
    does not require this registration.
    """
    ports = _select_ports(ports, provider_authority)
    try:
        _configure_execution_journal_ports(ports)
    except ExecutionJournalError as error:
        code = getattr(error, "code", "")
        if code.startswith("JOURNAL_PORT_ALREADY_CONFIGURED"):
            raise
        raise BacktraderJournalPortError("JOURNAL_PORT_REGISTRATION_FAILED") from error
    return ports


def bind_backtrader_journal_ports(
    journal: Any, *, ports: ExecutionJournalPorts
) -> ExecutionJournalPorts:
    """Require one journal to carry this exact Backtrader composition."""

    try:
        return _bind_execution_journal_ports(journal, ports)
    except ExecutionJournalError as error:
        code = getattr(error, "code", "EXECUTION_JOURNAL_PORT_SET_INVALID")
        raise BacktraderJournalPortError(code) from error


def new_execution_journal(
    database_path: Any,
    *,
    provider_authority: Optional[ExecutionJournalProviderAuthority] = None,
    ports: Optional[ExecutionJournalPorts] = None,
    **options: Any,
) -> Any:
    """Construct one journal with framework projections and injected authority."""

    if "journal_ports" in options:
        raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORTS_ALREADY_SUPPLIED")
    ports = _select_ports(ports, provider_authority)
    return _new_execution_journal(database_path, ports=ports, **options)
