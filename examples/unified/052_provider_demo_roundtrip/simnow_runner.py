"""SimNow registered-sim paper runner for the iteration-52 demo round trip.

Only ``run.py``'s live SIMNOW branch imports this module, so the dry/offline and
crypto paths never load it, the private ``ctp:`` block or the credential file.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paper_common

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_SDK_ROOT = Path(os.environ.get("BT_API_PY_ROOT", "D:/bt_api_py"))
if str(HERE) not in sys.path:
    # simnow_paper is a folder-local module next to this file.
    sys.path.insert(0, str(HERE))

# SimNow credential env-name overrides; the values themselves never enter config.
_SIMNOW_OVERRIDE_FIELDS = {
    "broker_id": "broker_id",
    "user_id": "investor_id",
    "password": "password",
    "app_id": "app_id",
    "auth_code": "auth_code",
}


def _prepend_simnow_sdk_sources() -> None:
    """Prefer the reviewed dev bt_api_py base/CTP sources for the CTP wrapper.

    ``simnow_direct`` builds its wrapper class at import time, so the dev
    sources must precede any installed ``bt_api_ctp`` copy.  Only the two
    source trees are added; the facade directory also ships a ``backtrader``
    shim and must never shadow the framework package.
    """
    for extra in reversed(
        (
            DEFAULT_SDK_ROOT / "bt_api" / "bt_api_base" / "src",
            DEFAULT_SDK_ROOT / "bt_api" / "bt_api_ctp" / "src",
        )
    ):
        if not extra.is_dir():
            continue
        text = str(extra)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)


def _load_optional_credentials(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Read only the named variables from ``path`` (or the process environment)."""
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in names:
                values[key] = value.strip().strip("'\"")
    for name in names:
        if not values.get(name):
            values[name] = os.environ.get(name, "")
    return {name: value for name, value in values.items() if value}


def _load_private_ctp_block(path: Path) -> dict:
    """Parse the sealed canonical ``ctp:`` block without emitting any value.

    The file is private operator input: errors carry field names and exception
    types only, never content.  Callers must only invoke this on a live run.
    """
    import yaml

    if not path.is_file():
        raise RuntimeError("private_config_unavailable")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bounded code
        raise RuntimeError("private_config_invalid:" + type(exc).__name__) from None
    if not isinstance(raw, dict):
        raise RuntimeError("private_config_invalid:root")
    block = raw.get("ctp")
    if not isinstance(block, dict):
        raise RuntimeError("private_config_ctp_block_missing")
    return block


def _simnow_strategy_identity(module, strategy_path: Path, instrument: str, exchange: str) -> str:
    """Bind the unchanged strategy source and the resolved SimNow scope."""
    payload = {
        "strategy_id": "iteration52-simnow-paper-roundtrip",
        "instrument": instrument,
        "exchange": exchange,
    }
    builder = getattr(module, "strategy_identity_sha256", None)
    if callable(builder):
        return str(builder(strategy_path, payload))
    source_sha = hashlib.sha256(strategy_path.read_bytes()).hexdigest()
    merged = dict(payload, strategy_source_sha256=source_sha)
    return hashlib.sha256(
        json.dumps(merged, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _store_facts(session) -> dict:
    store = getattr(session, "store", None)
    facts = getattr(store, "simnow_paper_facts", None)
    if not callable(facts):
        return {}
    try:
        return dict(facts())
    except Exception:  # noqa: BLE001 - evidence stays finite
        return {"unavailable": True}


def run_simnow(plan, params: dict, args, tier_evidence: dict) -> int:
    """Run the bounded SimNow registered-sim paper adapter.

    Only this branch reads the private ``ctp:`` block or the credential env
    file.  The dry/offline path returns before it, and crypto venues never
    enter it.
    """
    import simnow_paper

    venue = "SIMNOW"

    def _blocked(reason: str, **extra) -> int:
        payload = {
            "status": "BLOCKED",
            "reason": reason,
            "entry_tier": tier_evidence,
            "venue": venue,
            "credential_env_names": list(extra.pop("credential_env_names", ())),
        }
        payload.update(extra)
        evidence = paper_common.write_evidence(payload)
        payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    if sys.version_info[:2] != (3, 11):
        return _blocked(
            "live_tier_requires_python_3_11",
            current="{}.{}".format(*sys.version_info[:2]),
            hint="run the SimNow paper tier with C:/anaconda3/python.exe (3.11)",
        )
    if args.order_journal:
        return _blocked("order_journal_unsupported_for_simnow")

    try:
        ctp_block = _load_private_ctp_block(Path(args.private_config))
    except RuntimeError as exc:
        return _blocked(str(exc))

    raw_pairs = ctp_block.get("front_pairs")
    if raw_pairs is None:
        raw_pairs = [
            {"md_front": ctp_block.get("md_front"), "td_front": ctp_block.get("td_front")}
        ]
    if not isinstance(raw_pairs, list) or not 1 <= len(raw_pairs) <= 8:
        return _blocked("private_config_front_pairs_invalid")
    pairs: list[tuple[str, str]] = []
    for item in raw_pairs:
        if not isinstance(item, dict):
            return _blocked("private_config_front_pair_invalid")
        md_front = item.get("md_front")
        td_front = item.get("td_front")
        if not all(isinstance(value, str) and value.strip() for value in (md_front, td_front)):
            return _blocked("private_config_front_pair_invalid")
        pairs.append((td_front.strip(), md_front.strip()))

    instrument = str(ctp_block.get("instrument_id") or "").strip().upper()
    exchange = str(ctp_block.get("exchange_id") or "").strip().upper()
    if not instrument or not exchange:
        return _blocked("private_config_contract_missing")

    credential_names = dict(simnow_paper.SIMNOW_CREDENTIAL_NAMES)
    overrides = params.get("credential_env_names")
    if isinstance(overrides, dict):
        for key, sdk_field in _SIMNOW_OVERRIDE_FIELDS.items():
            value = overrides.get(key)
            if isinstance(value, str) and value.strip():
                credential_names[sdk_field] = value.strip()
    env_names = tuple(sorted(set(credential_names.values())))
    env_values = _load_optional_credentials(Path(args.env_file), env_names)

    def _credential(sdk_field: str, ctp_key: str) -> str:
        env_name = credential_names[sdk_field]
        return str(env_values.get(env_name) or ctp_block.get(ctp_key) or "")

    broker_id = str(ctp_block.get("broker_id") or env_values.get(credential_names["broker_id"]) or "")
    user_id = str(ctp_block.get("user_id") or env_values.get(credential_names["investor_id"]) or "")
    password = _credential("password", "password")
    app_id = _credential("app_id", "app_id")
    auth_code = _credential("auth_code", "auth_code")
    if not all((broker_id, user_id, password, app_id, auth_code)):
        return _blocked("credentials_unavailable", credential_env_names=env_names)

    # simnow_direct builds its CTP wrapper class at import time, so the dev SDK
    # source trees must precede any installed copy.
    _prepend_simnow_sdk_sources()
    try:
        module = simnow_paper.load_simnow_direct()
    except simnow_paper.SimNowPaperError as exc:
        return _blocked(exc.reason, details=exc.details)
    except Exception as exc:  # noqa: BLE001 - finite code only
        return _blocked("simnow_direct_unavailable:" + type(exc).__name__)
    front_env: dict[str, str] = {}
    selector_pairs: list[dict] = []
    for index, (td_front, md_front) in enumerate(pairs):
        td_name = "ITER52_SIMNOW_TD_{}".format(index)
        md_name = "ITER52_SIMNOW_MD_{}".format(index)
        front_env[td_name] = td_front
        front_env[md_name] = md_front
        selector_pairs.append({"td_env": td_name, "md_env": md_name, "kind": "standard"})
    try:
        selection = module.select_front_pair(
            selector_pairs,
            front_env,
            samples=3,
            connect_timeout=3.0,
        )
    except Exception as exc:  # noqa: BLE001 - bounded reason only
        reason = getattr(exc, "reason", None)
        suffix = ":" + str(reason)[:80] if isinstance(reason, str) and reason else ""
        return _blocked(
            "front_selection_failed" + suffix,
            front_selection_error=type(exc).__name__,
        )
    receipt = dict(selection.get("receipt") or {})
    td_front = str(selection.get("td_front") or "")
    md_front = str(selection.get("md_front") or "")
    if not td_front or not md_front:
        return _blocked("front_selection_failed:missing_selected_pair")

    strategy_path = HERE / "provider_demo_roundtrip_strategy.py"
    try:
        identity_sha = _simnow_strategy_identity(module, strategy_path, instrument, exchange)
    except Exception as exc:  # noqa: BLE001
        return _blocked("strategy_identity_unavailable:" + type(exc).__name__)

    strategy_params = paper_common.strategy_params(params)
    time_in_force = str(strategy_params.get("time_in_force") or "GFD").strip().upper()
    if time_in_force not in {"GFD", "GOOD_FOR_DAY"}:
        return _blocked("simnow_paper_gfd_required")
    strategy_params["time_in_force"] = "GFD"
    try:
        max_orders = int(params.get("max_orders") or 2)
    except (TypeError, ValueError):
        return _blocked("simnow_paper_order_budget_invalid")
    if max_orders < 1 or max_orders > 2:
        return _blocked("simnow_paper_order_budget_invalid", max_orders=max_orders)

    run_id = (
        "i52-simnow-paper-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    try:
        simnow_plan = simnow_paper.build_simnow_plan(
            instrument=instrument,
            exchange=exchange,
            md_front=md_front,
            td_front=td_front,
            broker_id=broker_id,
            user_id=user_id,
            password=password,
            app_id=app_id,
            auth_code=auth_code,
            strategy_identity_sha256=identity_sha,
            execution_cycle_id=run_id,
            price_tick=float(params["tick_size"]),
            volume_multiple=float(params["contract_value"]),
            quantity_step=float(params["step_size"]),
            min_quantity=float(params["min_quantity"]),
            max_quantity=float(params["max_quantity"]),
            quantity_unit=str(params.get("quantity_unit") or "contracts"),
            allow_zero_login_response=bool(params.get("allow_zero_login_response", True)),
            login_timeout=float(params.get("login_seconds") or 30.0),
            query_timeout=float(params.get("query_seconds") or 8.0),
            stop_timeout=float(params.get("stop_seconds") or 12.0),
            credential_names=tuple(sorted(credential_names.items())),
        )
        profile = simnow_paper.build_simnow_profile(
            simnow_plan,
            provider_ref=plan.references.provider,
            endpoint_ref=plan.references.endpoint,
            account_ref=plan.references.account,
            credential_ref=plan.references.credential,
            scope_ref=plan.references.scope,
        )
    except simnow_paper.SimNowPaperError as exc:
        return _blocked(exc.reason, details=exc.details)
    except (KeyError, TypeError, ValueError) as exc:
        return _blocked("simnow_paper_parameter_invalid:" + type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - profile construction stays finite
        return _blocked("simnow_paper_profile_invalid:" + type(exc).__name__)

    from bt_api_runtime.direct_backtrader import (
        DirectBacktraderSession,
        DirectCredentials,
        DirectSessionError,
    )

    try:
        # Preflight (login + typed queries + front probes) runs before the
        # session timer, so the one-shot approval needs headroom over the
        # default two minutes while still being bounded.
        grant_seconds = max(int(args.grant_seconds), 300)
        grant = paper_common.build_grant(plan, profile, params, run_id, grant_seconds)
        credentials = DirectCredentials(simnow_plan.credential_values())
        session = DirectBacktraderSession(
            plan=plan,
            profile=profile,
            run_id=run_id,
            credentials=credentials,
            strategy_id="iteration52-simnow-paper-roundtrip",
            grant=grant,
            store_factory=simnow_paper.make_store_factory(
                simnow_plan, simnow_module=module
            ),
            broker_factory=simnow_paper.make_broker_factory(simnow_plan),
            initialize_risk_baseline=False,
        )
    except DirectSessionError as exc:
        return _blocked(exc.code, credential_env_names=env_names)
    except (KeyError, TypeError, ValueError) as exc:
        return _blocked("simnow_paper_grant_invalid:" + type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - session construction stays finite
        return _blocked("simnow_paper_session_build_failed:" + type(exc).__name__)

    if args.preflight_only:
        payload: dict
        try:
            readiness = session.preflight()
            payload = {
                "status": "COMPLETED",
                "reason": "preflight_ok",
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(env_names),
                "front_selection": receipt,
                "readiness": readiness,
                "config_sha256": session.config_sha256(),
            }
        except simnow_paper.SimNowPaperError as exc:
            payload = {
                "status": "BLOCKED",
                "reason": exc.reason,
                "details": exc.details,
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(env_names),
                "front_selection": receipt,
            }
        except DirectSessionError as exc:
            payload = {
                "status": "BLOCKED",
                "reason": exc.code,
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(env_names),
                "front_selection": receipt,
            }
        except Exception as exc:  # noqa: BLE001 - finite code only
            payload = {
                "status": "BLOCKED",
                "reason": "preflight_failure:" + type(exc).__name__,
                "entry_tier": tier_evidence,
                "venue": venue,
                "credential_env_names": list(env_names),
                "front_selection": receipt,
            }
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - cleanup evidence is separate
                pass
        facts = _store_facts(session)
        payload["simnow_paper"] = facts
        stop = facts.get("stop") if isinstance(facts, dict) else None
        if isinstance(stop, dict) and stop.get("action") in {"freeze", "frozen"}:
            payload["status"] = "BLOCKED"
            payload["reason"] = "preflight_cleanup_uncertain"
        evidence = paper_common.write_evidence(payload)
        payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 0 if payload["status"] == "COMPLETED" else 2

    from provider_demo_roundtrip_strategy import ProviderDemoRoundTripStrategy

    strategy_cls = simnow_paper.adapt_roundtrip_strategy(ProviderDemoRoundTripStrategy)
    try:
        report = session.run(
            strategy_cls,
            strategy_params=strategy_params,
            seconds=args.session_seconds,
            initialize_risk_baseline=False,
        )
    except DirectSessionError as exc:
        return _blocked(exc.code, credential_env_names=env_names, front_selection=receipt)
    except Exception as exc:  # noqa: BLE001 - finite code only
        return _blocked(
            "session_failure:" + type(exc).__name__,
            credential_env_names=env_names,
            front_selection=receipt,
        )

    facts = _store_facts(session)
    phase = str((report.strategy_facts or {}).get("phase") or "")
    stop = facts.get("stop") if isinstance(facts, dict) else None
    stop_action = str((stop or {}).get("action") or "") if isinstance(stop, dict) else ""
    if stop_action in {"freeze", "frozen"}:
        status = "UNKNOWN"
        reason = (
            "simnow_paper_residual_exposure"
            if (stop or {}).get("reason") == "simnow_paper_residual_exposure"
            else "simnow_paper_stop_" + (stop or {}).get("reason", "frozen")
        )
    elif report.status == "COMPLETED" and phase in ("canceled", "closed", "closed_verified"):
        status = "PASS"
        reason = "round_trip_" + phase
    elif report.status == "COMPLETED" and phase in (
        "waiting",
        "submitted",
        "resting",
        "partially_filled",
        "filled",
        "awaiting_close",
        "flattening",
    ):
        status = "UNKNOWN"
        reason = "round_trip_incomplete"
    elif report.status == "COMPLETED":
        status = "FAILED"
        reason = "round_trip_" + phase
    else:
        status = "BLOCKED"
        reason = report.code

    payload = {
        "status": status,
        "reason": reason,
        "entry_tier": tier_evidence,
        "venue": venue,
        "credential_env_names": list(env_names),
        "front_selection": receipt,
        "simnow_paper": facts,
        "report": report.to_json(),
    }
    detail = str((payload["report"] or {}).get("failure_detail") or "")
    for secret in (simnow_plan.password, simnow_plan.app_id, simnow_plan.auth_code):
        if secret and secret in detail:
            payload["report"]["failure_detail"] = "<redacted>"
            payload["redaction_applied"] = True
            break
    evidence = paper_common.write_evidence(payload)
    payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
    print(json.dumps(paper_common.summarize(payload), sort_keys=True))
    return {"PASS": 0, "FAILED": 1, "BLOCKED": 2, "UNKNOWN": 3}[status]
