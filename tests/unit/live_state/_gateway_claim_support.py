"""Synthetic decision-B claim port for BT tests that host a synthetic Gateway.

Test-only copy of the SDK Gateway test helper (bt_api_gateway tests
``iter63_claim_support``); BT tests cannot import the SDK's test tree. Real
claim semantics are covered by the SDK; these tests only need the dispatcher
to run its final validation and the native call to follow the claim fence.
"""

from __future__ import annotations


class SyntheticClaimPort:
    def __init__(self) -> None:
        self.claims = 0
        self.retired = 0

    def ready(self) -> bool:
        return True

    def claim_native(self, record, identity, validate):
        validate(0)
        self.claims += 1
        return ("synthetic-claim", record.reservation_id)

    def native_check(self, claim):
        return lambda: True

    def retire(self, claim) -> None:
        self.retired += 1


def claiming(native):
    """Run a synthetic native's send inside the claim fence after its commit."""

    def wrapped(payload, port, scope):
        fences = []

        class Proxy:
            def __getattr__(self, name):
                return getattr(port, name)

            def commit(self, record):
                marker = port.commit(record)
                if marker is not None:
                    fence = port.native_fence()
                    check = fence.__enter__()
                    fences.append(fence)
                    check()
                return marker

        try:
            return native(payload, Proxy(), scope)
        finally:
            for fence in fences:
                fence.__exit__(None, None, None)

    return wrapped
