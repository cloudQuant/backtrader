"""Immutable, source-only identity facts from an MD login callback.

The observation is not an authorization or readiness proof. A client must
bind it to the exact current request and connection generation, clear it when
the native session lifecycle changes, and independently validate its fixed
constructor front and configured broker/user identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MdIdentityObservation:
    """One terminal MD login callback snapshot with no synthesized identity.

    ``request_id`` identifies the login request/response pair. It is distinct
    from ``connection_generation``, which identifies the front connection
    lifecycle. Broker, user, and trading day are copied only from the native
    login response; missing values remain ``None``. ``front`` is copied from
    the client's immutable constructor binding, never from mutable public
    client state.
    """

    front: str | None
    broker_id: str | None
    user_id: str | None
    connection_generation: int
    request_id: int
    trading_day: str | None
    authenticated: bool

    def __post_init__(self) -> None:
        for name in ("front", "broker_id", "user_id", "trading_day"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise ValueError(f"{name} must be a source string or None")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            raise ValueError("connection_generation must be a positive exact integer")
        if type(self.request_id) is not int or self.request_id <= 0:
            raise ValueError("request_id must be a positive exact integer")
        if type(self.authenticated) is not bool:
            raise ValueError("authenticated must be an exact bool")


def md_identity_matches(
    observation: MdIdentityObservation,
    *,
    expected_front: str,
    expected_broker_id: str,
    expected_user_id: str,
    expected_connection_generation: int,
    expected_request_id: int,
) -> bool:
    """Return whether a source observation matches one exact current login.

    This is only a value comparison. The caller remains responsible for
    creating observations from terminal successful callbacks and revoking its
    cached observation on disconnect, restart, or API replacement.
    """

    expected_text = (expected_front, expected_broker_id, expected_user_id)
    if any(
        type(value) is not str or not value or value != value.strip() for value in expected_text
    ):
        raise ValueError("expected MD identity strings must be nonempty and trimmed")
    for name, value in (
        ("expected_connection_generation", expected_connection_generation),
        ("expected_request_id", expected_request_id),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive exact integer")
    if type(observation) is not MdIdentityObservation:
        raise ValueError("observation must be MdIdentityObservation")

    return (
        observation.authenticated is True
        and observation.front == expected_front
        and observation.broker_id == expected_broker_id
        and observation.user_id == expected_user_id
        and observation.connection_generation == expected_connection_generation
        and observation.request_id == expected_request_id
        and _valid_trading_day(observation.trading_day)
    )


def _valid_trading_day(value: str | None) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


__all__ = ["MdIdentityObservation", "md_identity_matches"]
