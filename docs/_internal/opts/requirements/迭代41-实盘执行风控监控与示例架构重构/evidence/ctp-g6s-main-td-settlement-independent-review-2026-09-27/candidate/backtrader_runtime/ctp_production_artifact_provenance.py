"""Independent, fail-closed SDK artifact gate for CTP production reads.

Production approval never inherits a SimNow artifact pin. A release reviewer
must add an exact base/CTP wheel pair to this code-owned catalog before this
gate can pass. Runtime config, credentials, and caller input cannot add pins.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    CtpSdkArtifactPin,
    _distribution_key,
    _validate_installed_distribution,
)


CTP_PRODUCTION_SDK_ARTIFACT_PINS: Mapping[str, CtpSdkArtifactPin] = MappingProxyType({})


def verify_ctp_production_sdk_artifact_provenance() -> None:
    """Validate the separately reviewed production wheels before secret access.

    The current empty catalog deliberately rejects every installed SDK. The
    installed-file and wheel-origin checks are shared with the SimNow gate;
    its pin catalog and front policy are not.
    """

    for module_name in ("bt_api_base", "bt_api_ctp"):
        pin = CTP_PRODUCTION_SDK_ARTIFACT_PINS.get(module_name)
        if (
            type(pin) is not CtpSdkArtifactPin
            or pin.module != module_name
            or _distribution_key(pin.distribution) != module_name
        ):
            raise CtpArtifactProvenanceError("production_artifact_pin_unavailable")
        _validate_installed_distribution(pin)


__all__ = [
    "CTP_PRODUCTION_SDK_ARTIFACT_PINS",
    "verify_ctp_production_sdk_artifact_provenance",
]
