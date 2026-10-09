"""Live gateway capability check for the optional16 acceptance record.

Starts one ``GatewayServer`` that owns the provider session and exercises the
gateway-level acceptance items with the real Binance demo account:

1. two independent clients (A embedded, B via connection string) share one
   provider session and report the same server pid/journal;
2. order attribution: an order placed by A is visible to B as the same
   provider order id;
3. a wrong-token client is rejected before any provider command;
4. after the server stops, a write from A raises (never fabricates success)
   and a direct provider read confirms NO order was created;
5. the server command journal (JSONL) records the forwarded commands.

Honest limits recorded in the output: the frame-sent-no-reply
``GatewayCommandUncertain`` branch is covered by the package's offline smoke,
not staged live here; the current snapshot has no request-id dedup/anti-replay
cache; transport is localhost-only with a per-run token.

Run:
    C:/anaconda3/python.exe optional16/gateway_capability_check.py

Writes ``optional16/gateway-capability.json`` and prints a summary line.
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # 000_live_certification
for extra in (str(ROOT), str(ROOT / "binance_penetration")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import yaml  # noqa: E402

import optional16  # noqa: E402

certlib = importlib.import_module("certlib")
envfile = importlib.import_module("certlib.envfile")


def _write(record):
    path = Path(__file__).resolve().parent / "gateway-capability.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": record.get("status"), "reason": record.get("reason", ""),
                      "record": str(path)}, ensure_ascii=False))


def main():
    config = yaml.safe_load(
        (ROOT / "binance_penetration" / "cases" / "T01" / "config.yaml").read_text(encoding="utf-8")
    )
    env, missing = envfile.load_env(["BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET"])
    record = {
        "check": "optional16-gateway-capability",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if missing:
        record.update({"status": "BLOCKED", "reason": "credential_env_missing"})
        _write(record)
        return 2

    journal_dir = Path(__file__).resolve().parent / "gateway-capability-journal"
    journal_dir.mkdir(exist_ok=True)
    server = optional16.GatewayServer(config=config, env=env, journal_dir=str(journal_dir))
    client_a = client_b = None
    live_order_id = None
    try:
        server.start()
        record["server"] = {
            "endpoint": server.endpoint,
            "transport_impl": server.transport_impl,
            "token_present": bool(server.token),
        }
        client_a = optional16.GatewayClient.embedded(server)
        facts_a = client_a.connect()
        record["client_a_connect"] = {k: facts_a.get(k) for k in ("host", "server_time_ms", "time_offset_ms")}

        client_b = optional16.GatewayClient.from_connection_string(server.connection_string())
        facts_b = client_b.connect()

        def _server_pid(describe):
            return describe.get("server_pid") or (describe.get("gateway_server") or {}).get("pid")

        pid_a = _server_pid(client_a.describe())
        pid_b = _server_pid(client_b.describe())
        record["shared_server"] = {
            "b_connect_host": facts_b.get("host"),
            "a_pid": pid_a,
            "b_pid": pid_b,
            "a_pid_equals_b_pid": bool(pid_a) and pid_a == pid_b,
        }

        mark = float(client_a.mark_price("BTCUSDT"))
        filters = client_a.filters("BTCUSDT")
        price = round(round(mark * 0.98 / filters["tick_size"]) * filters["tick_size"], 6)
        placement = client_a.place_order(
            "BTCUSDT", "BUY", quantity="0.001", price=str(price),
            position_side="LONG", time_in_force="GTC",
        )
        live_order_id = placement.get("orderId")
        time.sleep(0.5)
        seen_by_b = [o for o in client_b.open_orders("BTCUSDT") if o.get("orderId") == live_order_id]
        record["attribution"] = {
            "order_id": live_order_id,
            "seen_by_b": bool(seen_by_b),
            "status_observed_by_b": (seen_by_b[0].get("status") if seen_by_b else None),
        }
        canceled = client_a.cancel_order("BTCUSDT", order_id=live_order_id)
        record["cancel_status"] = canceled.get("status")
        if canceled.get("status") == "CANCELED":
            live_order_id = None

        wrong = optional16.GatewayClient.from_connection_string(
            "%s:%s:%s" % (client_a.gateway_host, client_a.port, "wrong-token-" + "0" * 8)
        )
        try:
            wrong.connect()
            record["wrong_token"] = {"rejected": False}
        except Exception as exc:  # noqa: BLE001 - recorded as evidence
            record["wrong_token"] = {"rejected": True, "error": type(exc).__name__, "text": str(exc)[:120]}
        finally:
            try:
                wrong.close()
            except Exception:
                pass

        server.stop()
        time.sleep(0.3)
        write_error = None
        try:
            client_a.place_order(
                "BTCUSDT", "BUY", quantity="0.001", price=str(price),
                position_side="LONG", time_in_force="GTC",
            )
        except Exception as exc:  # noqa: BLE001 - recorded as evidence
            write_error = {"type": type(exc).__name__, "text": str(exc)[:120]}
        record["stopped_server_write"] = write_error or {"error": None}

        direct_client = certlib.make_client(
            config, env, {"transport": "direct", "execution": False, "risk": False, "monitor": False}
        )
        direct_client.connect()
        try:
            still_open = [
                o for o in direct_client.open_orders("BTCUSDT")
                if o.get("status") in ("NEW", "PARTIALLY_FILLED")
            ]
            record["venue_orders_after_stopped_write"] = len(still_open)
            record["no_order_created"] = len(still_open) == 0
        finally:
            direct_client.close()

        entries = 0
        for journal_file in journal_dir.glob("*.jsonl"):
            with journal_file.open("r", encoding="utf-8") as handle:
                entries += sum(1 for _ in handle)
        record["journal"] = {"dir": str(journal_dir), "entries": entries}

        record["status"] = "PASS" if (
            record["attribution"]["seen_by_b"]
            and record.get("cancel_status") == "CANCELED"
            and record["wrong_token"].get("rejected") is True
            and write_error is not None
            and record.get("no_order_created") is True
            and entries > 0
        ) else "FAIL"
        record["limits"] = [
            "uncertain-outcome (frame sent, no reply) staged in the package offline smoke, not live",
            "no request-id dedup/anti-replay cache in this snapshot",
            "localhost-only transport with per-run token; not a remote deployment control",
        ]
        return 0 if record["status"] == "PASS" else 1
    except Exception as exc:  # noqa: BLE001 - recorded as evidence
        record["status"] = "FAIL"
        record["exception"] = f"{type(exc).__name__}: {exc}"[:300]
        return 1
    finally:
        if live_order_id is not None and client_a is not None:
            try:
                client_a.cancel_order("BTCUSDT", order_id=live_order_id)
            except Exception:
                pass
        for client in (client_a, client_b):
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass
        try:
            server.stop()
        except Exception:
            pass
        _write(record)


if __name__ == "__main__":
    raise SystemExit(main())
