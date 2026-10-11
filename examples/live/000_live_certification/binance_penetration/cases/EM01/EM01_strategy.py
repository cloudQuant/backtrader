"""EM01 — operator permission restriction probe (evidence-based outcome).

The certification operator (recorded operator/authorization refs) attempts one
top-level operation the probed demo key is not expected to be allowed to
perform: toggling the account position mode through the signed
``POST /fapi/v1/positionSide/dual`` request with ``dualSidePosition=false``.

The probed key is selected from the config ``credentials`` block:

  * Restricted path (ready for a restricted-permission demo key).  When the
    runner-internal environment stash (``ctx._env_values``; never serialized
    into evidence) holds BOTH names configured as ``restricted_api_key_env`` /
    ``restricted_secret_env``, a second ``BinanceDemoClient`` is built from
    those values (same host/timeout as the primary client), connected, and the
    toggle is attempted with THAT key:
      - If the venue rejects the request (``BinanceApiError``: any code is
        accepted; a code outside the -2015 / -2016 permission family is noted)
        the rejection code/message is recorded as the restriction evidence.
        Nothing is restored (the mode never changed), the mode is re-read
        through the PRIMARY client to confirm ``dualSidePosition is True``
        (mode_unchanged) and the case PASSes with rule
        ``position_mode_restriction`` and ``key_source="restricted_env"``.
      - If the restricted key holds the permission (unexpected), hedge mode is
        restored IMMEDIATELY with the same restricted client, verified back to
        True through the primary client, and the case returns FAIL
        (``no_permission_restriction_observed_with_restricted_key``).
      - If the restricted client cannot be built or connected the case returns
        FAIL (``restricted_key_client_error``): the probe never ran, the mode
        is untouched, and the failure is never silent.
    The second client is always closed.

  * Primary fallback (the current state: the restricted values are absent).
    The probe runs with the primary demo key exactly as before:
      - If the venue rejects the request (``BinanceApiError``: the -2015 /
        permission family or any code) the rejection code/message is recorded
        as the restriction evidence; hedge mode is re-read to confirm
        ``dualSidePosition is True`` (mode_unchanged) and the case PASSes with
        rule ``position_mode_restriction``.  No restore is needed.
      - If the demo key holds the permission (the observed demo behaviour: the
        toggle call succeeds) hedge mode is restored IMMEDIATELY
        (``dualSidePosition=true``), the mode is verified back to True, and
        the case returns BLOCKED
        (``permission_restriction_not_producible_on_demo_key``) with
        ``toggle_succeeded=True, restored=True, dual_side_position_after=True``.
        A restriction that cannot be produced is not a PASS.
      - If restoring hedge mode fails, the mode is still re-verified and the
        case returns FAIL (``mode_restore_failed``) — the account must never be
        silently left in one-way mode.

The case starts only when hedge mode is already active; otherwise it is
BLOCKED.  Facts: operator_ref, authorization_ref, code/msg (160 chars), and
the hedge-mode verification booleans.  No account aliases/UIDs are recorded.
"""

from __future__ import annotations

from certlib.binance_client import (
    DEFAULT_HOST,
    BinanceApiError,
    BinanceDemoClient,
    WriteOutcomeUnknown,
)
from certlib.context import CaseResult

CASE_ID = "EM01"
RISK = "WRITE"

_PROBE_PATH = "/fapi/v1/positionSide/dual"
_PERMISSION_FAMILY = (-2015, -2016)


def _toggle(client, value):
    """Signed position-mode toggle; value is "true" or "false"."""
    return client._request("POST", _PROBE_PATH, {"dualSidePosition": value}, is_write=True)


def _hedge_mode(client):
    """True only when accountConfig reports hedge mode (dualSidePosition is True)."""
    return client.account_config().get("dualSidePosition") is True


def _restore_hedge_mode(client, verify_client=None):
    """Toggle back to hedge mode and re-verify it; never raises.

    ``client`` sends the restore toggle; ``verify_client`` (default: the same
    client) performs the follow-up read.
    """
    verify = client if verify_client is None else verify_client
    out = {"restored": False, "dual_side_position_after": None}
    try:
        _toggle(client, "true")
        out["restored"] = True
    except BinanceApiError as exc:
        out["error"] = {"code": exc.code, "msg": str(exc.msg)[:160]}
    except WriteOutcomeUnknown:
        out["error"] = {"code": None, "msg": "outcome_unknown"}
    try:
        out["dual_side_position_after"] = _hedge_mode(verify)
    except BinanceApiError as exc:
        out["verify_error"] = str(exc.msg)[:160]
    return out


def _restricted_env_credentials(ctx):
    """(api_key, secret) from the runner stash, or (None, None) when absent.

    Absent covers: no ``_env_values`` attribute, a non-dict stash, unset
    config names, or either value missing from the stash.
    """
    section = ctx.config.get("credentials", {}) or {}
    key_name = section.get("restricted_api_key_env")
    secret_name = section.get("restricted_secret_env")
    if not (isinstance(key_name, str) and key_name):
        return None, None
    if not (isinstance(secret_name, str) and secret_name):
        return None, None
    values = getattr(ctx, "_env_values", None)
    if not isinstance(values, dict):
        return None, None
    api_key = values.get(key_name)
    secret = values.get(secret_name)
    if not (api_key and secret):
        return None, None
    return str(api_key), str(secret)


def _restricted_client(ctx, api_key, secret):
    """Second demo client on the same host/timeout as the primary client."""
    environment = ctx.config.get("environment", {}) or {}
    timeouts = ctx.config.get("timeouts", {}) or {}
    return BinanceDemoClient(
        api_key,
        secret,
        host=environment.get("base_url", DEFAULT_HOST),
        timeout=float(timeouts.get("request_seconds", 10.0)),
    )


def _restore_then(toggle_client, verify_client, facts, blocked_reason):
    """Restore + verify hedge mode; FAIL rather than leave one-way mode."""
    restore = _restore_hedge_mode(toggle_client, verify_client)
    facts["restored"] = restore["restored"]
    facts["dual_side_position_after"] = restore["dual_side_position_after"]
    if restore.get("error"):
        facts["restore_error"] = restore["error"]
    if restore.get("verify_error"):
        facts["verify_error"] = restore["verify_error"]
    if not (restore["restored"] and restore["dual_side_position_after"] is True):
        return CaseResult(CASE_ID, "FAIL", "mode_restore_failed", facts)
    return CaseResult(CASE_ID, "BLOCKED", blocked_reason, facts)


class EM01Strategy:
    def run(self, ctx):
        scenario = ctx.scenario()
        client = ctx.client
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em01")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em01")
        facts = {
            "rule": "position_mode_restriction",
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "probe_path": _PROBE_PATH,
            "probe_value": "false",
        }

        if not _hedge_mode(client):
            return CaseResult(CASE_ID, "BLOCKED", "hedge_mode_not_active", facts)

        api_key, secret = _restricted_env_credentials(ctx)
        if api_key and secret:
            return self._probe_with_restricted_key(ctx, client, facts, api_key, secret)

        def recover():
            """Restore + verify hedge mode; FAIL rather than leave one-way mode."""
            restore = _restore_hedge_mode(client)
            facts["restored"] = restore["restored"]
            facts["dual_side_position_after"] = restore["dual_side_position_after"]
            if restore.get("error"):
                facts["restore_error"] = restore["error"]
            if restore.get("verify_error"):
                facts["verify_error"] = restore["verify_error"]
            if not (restore["restored"] and restore["dual_side_position_after"] is True):
                return CaseResult(CASE_ID, "FAIL", "mode_restore_failed", facts)
            return CaseResult(CASE_ID, "BLOCKED",
                              "permission_restriction_not_producible_on_demo_key", facts)

        ctx.log(f"operator {operator_ref} probes the restricted position-mode toggle")
        try:
            _toggle(client, "false")
        except BinanceApiError as exc:
            facts["restriction_source"] = "venue_error"
            facts["code"] = exc.code
            facts["msg"] = str(exc.msg)[:160]
            try:
                facts["mode_unchanged"] = _hedge_mode(client)
            except BinanceApiError:
                facts["mode_unchanged"] = None
            if facts["mode_unchanged"] is True:
                return CaseResult(CASE_ID, "PASS", "", facts)
            if facts["mode_unchanged"] is None:
                return CaseResult(CASE_ID, "UNKNOWN", "mode_verification_unavailable", facts)
            # The rejection did not prevent the state change: restore at once.
            facts["toggle_succeeded"] = True
            return recover()
        except WriteOutcomeUnknown:
            try:
                facts["hedge_mode_after"] = _hedge_mode(client)
            except BinanceApiError:
                facts["hedge_mode_after"] = None
            return CaseResult(CASE_ID, "UNKNOWN", "toggle_outcome_unknown", facts)

        # The demo key performed the restricted toggle: restore hedge mode NOW.
        facts["toggle_succeeded"] = True
        ctx.log("probe accepted; restoring hedge mode (dualSidePosition=true)")
        return recover()

    def _probe_with_restricted_key(self, ctx, primary, facts, api_key, secret):
        """Probe the toggle with the restricted-permission key (second client)."""
        facts["key_source"] = "restricted_env"
        try:
            restricted = _restricted_client(ctx, api_key, secret)
        except Exception as exc:  # never raise: report and fail closed
            facts["restricted_client_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return CaseResult(CASE_ID, "FAIL", "restricted_key_client_error", facts)

        try:
            try:
                restricted.connect()
            except Exception as exc:  # never raise: report and fail closed
                facts["restricted_client_error"] = f"{type(exc).__name__}: {exc}"[:160]
                return CaseResult(CASE_ID, "FAIL", "restricted_key_client_error", facts)

            ctx.log(f"operator {facts['operator_ref']} probes the toggle with the restricted key")
            try:
                _toggle(restricted, "false")
            except BinanceApiError as exc:
                facts["restriction_source"] = "venue_error"
                facts["code"] = exc.code
                facts["msg"] = str(exc.msg)[:160]
                facts["permission_family_match"] = exc.code in _PERMISSION_FAMILY
                try:
                    facts["mode_unchanged"] = _hedge_mode(primary)
                except BinanceApiError:
                    facts["mode_unchanged"] = None
                if facts["mode_unchanged"] is True:
                    return CaseResult(CASE_ID, "PASS", "", facts)
                if facts["mode_unchanged"] is None:
                    return CaseResult(CASE_ID, "UNKNOWN", "mode_verification_unavailable", facts)
                # The rejection did not prevent the state change: restore at once.
                facts["toggle_succeeded"] = True
                return _restore_then(
                    restricted,
                    primary,
                    facts,
                    "permission_restriction_not_producible_on_restricted_key",
                )
            except WriteOutcomeUnknown:
                try:
                    facts["hedge_mode_after"] = _hedge_mode(primary)
                except BinanceApiError:
                    facts["hedge_mode_after"] = None
                return CaseResult(CASE_ID, "UNKNOWN", "toggle_outcome_unknown", facts)

            # The restricted key performed the toggle: not a producible
            # restriction after all.  Restore + verify before reporting FAIL.
            facts["toggle_succeeded"] = True
            ctx.log("restricted-key probe accepted; restoring hedge mode (dualSidePosition=true)")
            outcome = _restore_then(
                restricted,
                primary,
                facts,
                "permission_restriction_not_producible_on_restricted_key",
            )
            if outcome.status == "FAIL":
                return outcome  # mode_restore_failed must never be masked
            return CaseResult(
                CASE_ID, "FAIL", "no_permission_restriction_observed_with_restricted_key", facts
            )
        finally:
            try:
                restricted.close()
            except Exception:
                pass
