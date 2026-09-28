"""Cross-module regression isolated from the pytest collection process."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


_CHILD_SCRIPT = textwrap.dedent(
    r"""
    import hashlib
    import importlib
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[2])

    import backtrader_runtime.config as runtime_config
    import backtrader_runtime.ctp_production_managed_composition as production_composition
    import backtrader_runtime.ctp_production_credentials as production_credentials
    from backtrader_runtime.ctp_f14_external_admission import (
        CtpF14ActionRequest,
        CtpF14AdmissionError,
        CtpF14SessionBinding,
        claim_f14_action,
    )
    from backtrader_runtime.ctp_f14_signed_receipt_contract import (
        CtpF14LocalReceiptObservationCache,
        CtpF14PinnedEd25519Verifier,
        CtpF14ReceiptContractObservation,
        CtpF14ReceiptTrustPolicy,
        verify_f14_receipt_contract,
    )
    from backtrader_runtime.inventory import (
        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
        iteration41_runtime_registry,
    )
    from backtrader_runtime.registry import validate_runtime_config
    from backtrader_runtime.ctp_shared_managed_runtime import (
        CtpProductionManagedSessionAdapter,
        CtpSharedManagedRuntimeError,
        CtpSimNowManagedSessionAdapter,
        open_shared_ctp_managed_runtime,
    )
    from test_ctp_f14_signed_receipt_contract import (
        _NOW,
        _ed25519_wire,
        _payload,
        _real_test_keypair,
    )
    from test_ctp_shared_managed_runner import (
        _production_registration,
        _runtime,
        _session_dependencies,
        _simnow_policy,
    )

    def expect_rejection(exception_type, reason, operation):
        try:
            operation()
        except exception_type as exc:
            assert exc.reason == reason, (exc.reason, reason)
        else:
            raise AssertionError("expected rejection: " + reason)

    runtime_config._require_private_config_security = lambda *args, **kwargs: None
    registry, registration = _runtime(Path(sys.argv[1]), mode="live")
    effective = validate_runtime_config(registration.runtime_dir, registry)
    request = CtpF14ActionRequest(
        runtime_id=registration.runtime_id,
        environment="production",
        mode=effective.mode,
        preset=effective.preset,
        account_fingerprint_sha256=hashlib.sha256(b"synthetic-user-only").hexdigest(),
        config_digest=effective.config_digest,
        effective_digest=effective.effective_digest,
        registration_digest=registration.digest,
        artifact_set_digest="e" * 64,
        session=CtpF14SessionBinding(
            session_id="synthetic-session",
            trading_day="20260925",
            connection_generation=7,
            identity_digest="f" * 64,
        ),
        action_kind="SUBMIT",
        action_id="synthetic-action",
        action_digest=hashlib.sha256(b"synthetic-action").hexdigest(),
        approval_digest=registration.profile_for("live", "managed_live_direct")
        .approval_receipt_digest,
    )

    private_key, public_key, pin = _real_test_keypair()
    observation = verify_f14_receipt_contract(
        request,
        _ed25519_wire(_payload(request), private_key),
        trust_policy=CtpF14ReceiptTrustPolicy((pin,)),
        signature_verifier=CtpF14PinnedEd25519Verifier(lambda _pin: public_key),
        observation_cache=CtpF14LocalReceiptObservationCache(),
        now_utc=_NOW,
    )
    assert type(observation) is CtpF14ReceiptContractObservation
    assert observation.request_digest == request.request_digest

    side_effects = []

    def forbidden(name):
        def record(*args, **kwargs):
            side_effects.append(name)

        return record

    production_composition.select_ctp_front_pair = forbidden("front_probe")
    production_credentials.resolve_ctp_production_credentials = forbidden(
        "credential_resolver"
    )
    real_import_module = importlib.import_module

    def watch_sdk_import(name, package=None):
        if name == "bt_api_ctp.ctp.client":
            side_effects.append("sdk_import")
        return real_import_module(name, package)

    importlib.import_module = watch_sdk_import
    simnow_adapter = CtpSimNowManagedSessionAdapter(
        policy=_simnow_policy(registration),
        dependencies=_session_dependencies(side_effects),
    )

    def claim_then_dispatch():
        admission = claim_f14_action(observation, request)
        admission.assert_active()
        side_effects.append("native_dispatch")

    expect_rejection(
        CtpF14AdmissionError,
        "external_admission_authority_required",
        claim_then_dispatch,
    )
    expect_rejection(
        CtpSharedManagedRuntimeError,
        "production_session_adapter_required",
        lambda: open_shared_ctp_managed_runtime(
            effective,
            registry,
            simnow_adapter=simnow_adapter,
            production_adapter=observation,
        ),
    )

    production_adapter = CtpProductionManagedSessionAdapter(
        registration=_production_registration(registration)
    )
    expect_rejection(
        CtpSharedManagedRuntimeError,
        "production_native_session_authority_unavailable",
        lambda: open_shared_ctp_managed_runtime(
            effective,
            registry,
            simnow_adapter=simnow_adapter,
            production_adapter=production_adapter,
        ),
    )
    assert side_effects == [], side_effects

    default_registration = next(
        item
        for item in iteration41_runtime_registry().registrations
        if item.runtime_id == ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    )
    unavailable = tuple(
        (item.mode, item.preset, item.reason)
        for item in default_registration.unavailable_mode_profiles
    )
    assert (
        "live",
        "managed_live_direct",
        "managed_live_direct_profile_unavailable",
    ) in unavailable
    print("isolated signed-receipt/shared-live guard passed")
    """
)


def test_signed_f14_observation_cannot_enter_same_file_live_session(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    runtime_dir = tmp_path / "runtime"
    test_support_dir = Path(__file__).resolve().parent
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    for name in tuple(child_env):
        if name.startswith(("CTP_", "BT_API_")):
            child_env.pop(name, None)

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            _CHILD_SCRIPT,
            str(runtime_dir),
            str(test_support_dir),
        ],
        cwd=repository_root,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        "isolated integration subprocess failed\n"
        "stdout:\n"
        + result.stdout
        + "\nstderr:\n"
        + result.stderr
    )
    assert "isolated signed-receipt/shared-live guard passed" in result.stdout
